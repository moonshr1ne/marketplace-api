from datetime import datetime
from decimal import Decimal
from fastapi import FastAPI, Depends, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, conint, constr
from sqlalchemy.orm import Session
from jose import JWTError
from app.db import SessionLocal
from app.models import Product, ProductStatus, Order, User, UserRole
from app.repositories import create_product, get_product, list_products, get_order
from app.services import create_order_service
from app.errors import ApiError, api_error_handler, validation_error_handler
from fastapi.exceptions import RequestValidationError
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_user_by_email,
    get_user_by_id,
    validate_refresh_and_rotate,
)

security = HTTPBearer(auto_error=False)


class ProductCreate(BaseModel):
    name: constr(min_length=1, max_length=255)
    description: constr(max_length=4000) | None = None
    price: Decimal = Field(..., ge=Decimal("0.01"))
    stock: conint(ge=0)
    category: constr(min_length=1, max_length=100)
    status: ProductStatus


class ProductUpdate(ProductCreate):
    pass


class ProductResponse(BaseModel):
    id: int
    name: str
    description: str | None
    price: Decimal
    stock: int
    category: str
    status: ProductStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductsPageResponse(BaseModel):
    items: list[ProductResponse]
    totalElements: int
    page: int
    size: int


class OrderItemCreate(BaseModel):
    product_id: conint(ge=1)
    quantity: conint(ge=1, le=999)


class OrderCreateRequest(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1, max_length=50)
    promo_code: constr(pattern=r"^[A-Z0-9_]{4,20}$") | None = None


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    price_at_order: Decimal

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    promo_code: str | None
    total_amount: Decimal
    discount_amount: Decimal
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    email: constr(min_length=3, max_length=320)
    password: constr(min_length=6, max_length=200)
    role: UserRole = UserRole.USER


class LoginRequest(BaseModel):
    email: constr(min_length=3, max_length=320)
    password: constr(min_length=6, max_length=200)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


app = FastAPI(title="Marketplace API", version="1.0.0")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if cred is None or cred.scheme.lower() != "bearer":
        raise ApiError("TOKEN_INVALID", "Token is invalid", 401)
    token = cred.credentials
    try:
        payload = decode_token(token)
        if payload.get("typ") != "access":
            raise JWTError()
        user_id = int(payload.get("sub"))
    except Exception as e:
        if "Signature has expired" in str(e):
            raise ApiError("TOKEN_EXPIRED", "Token has expired", 401)
        raise ApiError("TOKEN_INVALID", "Token is invalid", 401)
    user = get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("TOKEN_INVALID", "Token is invalid", 401)
    return user


@app.post("/auth/register", response_model=TokenPairResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = get_user_by_email(db, body.email)
    if existing is not None:
        raise ApiError("VALIDATION_ERROR", "Validation error", 400, {"field_errors": [{"loc": ["body", "email"], "msg": "Email already exists", "type": "value_error"}]})
    u = User(email=body.email, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    db.refresh(u)
    access = create_access_token(u)
    refresh = create_refresh_token(db, u)
    return TokenPairResponse(access_token=access, refresh_token=refresh)


@app.post("/auth/login", response_model=TokenPairResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    u = get_user_by_email(db, body.email)
    if u is None or not verify_password(body.password, u.password_hash):
        raise ApiError("TOKEN_INVALID", "Invalid credentials", 401)
    access = create_access_token(u)
    refresh = create_refresh_token(db, u)
    return TokenPairResponse(access_token=access, refresh_token=refresh)


@app.post("/auth/refresh", response_model=TokenPairResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        _, access, new_refresh = validate_refresh_and_rotate(db, body.refresh_token)
        return TokenPairResponse(access_token=access, refresh_token=new_refresh)
    except:
        raise ApiError("REFRESH_TOKEN_INVALID", "Refresh token is invalid", 401)


@app.post("/products", response_model=ProductResponse, status_code=201)
def create_product_ep(body: ProductCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = Product(
        name=body.name,
        description=body.description,
        price=body.price,
        stock=body.stock,
        category=body.category,
        status=body.status,
    )
    p = create_product(db, p)
    return p


@app.get("/products/{id}", response_model=ProductResponse)
def get_product_ep(id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = get_product(db, id)
    if p is None:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404, {"product_id": id})
    return p


@app.get("/products", response_model=ProductsPageResponse)
def list_products_ep(
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=200),
    status: ProductStatus | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = list_products(db, page, size, status, category)
    return ProductsPageResponse(items=items, totalElements=total, page=page, size=size)


@app.put("/products/{id}", response_model=ProductResponse)
def update_product_ep(id: int, body: ProductUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = get_product(db, id)
    if p is None:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404, {"product_id": id})
    p.name = body.name
    p.description = body.description
    p.price = body.price
    p.stock = body.stock
    p.category = body.category
    p.status = body.status
    db.add(p)
    db.flush()
    db.refresh(p)
    return p


@app.delete("/products/{id}", response_model=ProductResponse)
def delete_product_ep(id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = get_product(db, id)
    if p is None:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404, {"product_id": id})
    p.status = ProductStatus.ARCHIVED
    db.add(p)
    db.flush()
    db.refresh(p)
    return p


@app.post("/orders", response_model=OrderResponse, status_code=201)
def create_order_ep(
    body: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = [{"product_id": i.product_id, "quantity": i.quantity} for i in body.items]
    order = create_order_service(db, user_id=user.id, items=items, promo_code=body.promo_code)
    db.refresh(order)
    return order


@app.get("/orders/{id}", response_model=OrderResponse)
def get_order_ep(id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    o = get_order(db, id)
    if o is None:
        raise ApiError("ORDER_NOT_FOUND", "Order not found", 404, {"order_id": id})
    if user.role != UserRole.ADMIN and o.user_id != user.id:
        raise ApiError("ORDER_OWNERSHIP_VIOLATION", "Order belongs to another user", 403)
    return o