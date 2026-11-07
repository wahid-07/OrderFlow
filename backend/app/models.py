from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class Retailer(TimestampMixin, Base):
    __tablename__ = "retailers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    auth_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    retailer_id: Mapped[UUID | None] = mapped_column(ForeignKey("retailers.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Salesman(TimestampMixin, Base):
    __tablename__ = "salesmen"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    pack_label: Mapped[str | None] = mapped_column(String(100))
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RetailerPrice(TimestampMixin, Base):
    __tablename__ = "retailer_prices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Scheme(TimestampMixin, Base):
    __tablename__ = "schemes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scheme_type: Mapped[str] = mapped_column(String(50), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    free_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    free_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    note: Mapped[str | None] = mapped_column(String(500))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id"), nullable=False
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    free_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    delivered_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )


class AiCapture(TimestampMixin, Base):
    __tablename__ = "ai_captures"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SkuAlias(TimestampMixin, Base):
    __tablename__ = "sku_aliases"
    __table_args__ = (
        UniqueConstraint("retailer_id", "alias", name="uq_sku_alias_retailer_alias"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))