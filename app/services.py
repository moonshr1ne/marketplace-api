import os
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import Product, ProductStatus, Order, OrderItem, OrderStatus
from app.errors import ApiError


def create_order_service(db: Session, user_id: int, items: list[dict], promo_code: str | None) -> Order:
    if promo_code is not None:
        raise ApiError("PROMO_CODE_INVALID", "Promo code is invalid", 422)

    product_ids = [int(i["product_id"]) for i in items]
    rows = db.execute(select(Product).where(Product.id.in_(product_ids)).with_for_update()).scalars().all()
    by_id = {p.id: p for p in rows}

    for pid in product_ids:
        if pid not in by_id:
            raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404, {"product_id": pid})

    for it in items:
        p = by_id[int(it["product_id"])]
        if p.status != ProductStatus.ACTIVE:
            raise ApiError("PRODUCT_INACTIVE", "Product is inactive", 409, {"product_id": p.id})

    shortages = []
    for it in items:
        pid = int(it["product_id"])
        qty = int(it["quantity"])
        p = by_id[pid]
        if p.stock < qty:
            shortages.append({"product_id": pid, "requested": qty, "available": p.stock})

    if shortages:
        raise ApiError("INSUFFICIENT_STOCK", "Insufficient stock", 409, {"items": shortages})

    order_items = []
    total = Decimal("0.00")

    for it in items:
        pid = int(it["product_id"])
        qty = int(it["quantity"])
        p = by_id[pid]
        p.stock -= qty
        price = Decimal(p.price)
        total += price * qty
        order_items.append(OrderItem(product_id=pid, quantity=qty, price_at_order=price))

    order = Order(
        user_id=user_id,
        status=OrderStatus.CREATED,
        promo_code=None,
        total_amount=total,
        discount_amount=Decimal("0.00"),
        items=order_items,
    )

    db.add(order)
    db.flush()
    db.refresh(order)
    return order