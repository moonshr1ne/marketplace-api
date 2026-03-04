from typing import Sequence
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.models import Product, ProductStatus, Order, OrderItem


def create_product(db: Session, p: Product) -> Product:
    db.add(p)
    db.flush()
    db.refresh(p)
    return p


def get_product(db: Session, product_id: int) -> Product | None:
    return db.get(Product, product_id)


def list_products(db: Session, page: int, size: int, status: ProductStatus | None, category: str | None) -> tuple[Sequence[Product], int]:
    stmt = select(Product)
    count_stmt = select(func.count()).select_from(Product)

    if status is not None:
        stmt = stmt.where(Product.status == status)
        count_stmt = count_stmt.where(Product.status == status)
    if category is not None:
        stmt = stmt.where(Product.category == category)
        count_stmt = count_stmt.where(Product.category == category)

    total = db.execute(count_stmt).scalar_one()
    items = db.execute(stmt.order_by(Product.id).offset(page * size).limit(size)).scalars().all()
    return items, int(total)


def save_order(db: Session, order: Order) -> Order:
    db.add(order)
    db.flush()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: int) -> Order | None:
    return db.get(Order, order_id)