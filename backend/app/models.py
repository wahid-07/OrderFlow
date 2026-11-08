from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
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
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    current_outstanding: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )

    @property
    def available_credit(self) -> Decimal:
        limit = self.credit_limit if self.credit_limit is not None else Decimal("0.00")
        outstanding = (
            self.current_outstanding
            if self.current_outstanding is not None
            else Decimal("0.00")
        )
        return limit - outstanding


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
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SalesmanRetailerAssignment(TimestampMixin, Base):
    __tablename__ = "salesman_retailer_assignments"
    __table_args__ = (
        UniqueConstraint("salesman_id", "retailer_id", name="uq_salesman_retailer_assignment"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    salesman_id: Mapped[UUID] = mapped_column(
        ForeignKey("salesmen.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class SalesmanVisitNote(TimestampMixin, Base):
    __tablename__ = "salesman_visit_notes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    salesman_id: Mapped[UUID] = mapped_column(
        ForeignKey("salesmen.id", ondelete="CASCADE"), nullable=False, index=True
    )
    retailer_id: Mapped[UUID] = mapped_column(
        ForeignKey("retailers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )


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
    salesman_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("salesmen.id"), nullable=True
    )
    order_source: Mapped[str] = mapped_column(
        String(32), default="retailer", nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, index=True
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
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
    retailer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("retailers.id"), nullable=True
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("reserved_stock >= 0", name="ck_inventory_reserved_non_negative"),
        CheckConstraint("on_hand_stock >= 0", name="ck_inventory_on_hand_non_negative"),
        CheckConstraint("reserved_stock <= on_hand_stock", name="ck_inventory_reserved_le_on_hand"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id"), unique=True, nullable=False, index=True
    )
    on_hand_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    @property
    def available_stock(self) -> int:
        return max(0, self.on_hand_stock - self.reserved_stock)

    @property
    def is_low_stock(self) -> bool:
        return self.available_stock <= self.low_stock_threshold


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movements"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: "receive", "adjustment", "reserve", "release_reservation", "deduct_approved"
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    on_hand_before: Mapped[int] = mapped_column(Integer, nullable=False)
    on_hand_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_before: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
