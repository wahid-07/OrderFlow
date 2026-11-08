from uuid import UUID
from app.auth import require_roles
from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue import (
    PRODUCT_PRESENTATION,
    active_price_conditions,
    get_active_schemes,
    get_catalogue_retailer,
    resolve_scheme_for_sku,
    resolve_schemes_for_sku,
)
from app.database import get_db_session
from app.models import Product, RetailerPrice, Salesman, SalesmanRetailerAssignment, User
from app.scheme_engine import calculate_line

router = APIRouter()


class CartItemRequest(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


class CartQuoteRequest(BaseModel):
    items: list[CartItemRequest] = Field(min_length=1)
    retailer_id: UUID | None = Field(default=None, description="Target retailer ID for salesman/order desk orders")
    idempotency_key: str | None = Field(default=None, max_length=100, description="Client idempotency key for offline sync")
    order_source: str | None = Field(default=None, max_length=32, description="Source of order (retailer, salesman, offline_sync)")


class CartQuoteLine(BaseModel):
    sku: str
    name: str
    order_unit: str
    requested_quantity: int
    paid_quantity: int
    free_quantity: int
    delivered_quantity: int
    unit_price: Decimal
    subtotal: Decimal
    discount: Decimal
    free_value: Decimal
    total: Decimal
    scheme_label: str | None = None
    discount_percent: Decimal = Decimal("0.00")
    available_stock: int | None = None
    is_low_stock: bool | None = None


class CartQuoteResponse(BaseModel):
    source: Literal["database"]
    lines: list[CartQuoteLine]
    subtotal: Decimal
    discount_total: Decimal
    free_quantity: int
    free_value: Decimal
    total: Decimal


@router.post("/cart/quote", response_model=CartQuoteResponse)
def quote_cart(
    request: CartQuoteRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "salesman")),
    ],
) -> CartQuoteResponse:
    target_retailer_id = current_user.retailer_id

    if current_user.role == "salesman":
        if not request.retailer_id:
            raise HTTPException(
                status_code=400,
                detail="retailer_id is required when requesting a quote as salesman",
            )
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if salesman is None:
            raise HTTPException(
                status_code=403,
                detail="Active salesman profile not found",
            )
        assignment = session.scalar(
            select(SalesmanRetailerAssignment).where(
                SalesmanRetailerAssignment.salesman_id == salesman.id,
                SalesmanRetailerAssignment.retailer_id == request.retailer_id,
                SalesmanRetailerAssignment.is_active.is_(True),
            )
        )
        if assignment is None:
            raise HTTPException(
                status_code=403,
                detail="Salesman is not assigned to this retailer",
            )
        target_retailer_id = request.retailer_id
    elif current_user.role == "order_desk":
        target_retailer_id = request.retailer_id or current_user.retailer_id

    if target_retailer_id is None:
        raise HTTPException(
            status_code=403,
            detail="User is not linked to a retailer",
        )

    return calculate_cart_quote(
        request,
        session,
        target_retailer_id,
    )


def calculate_cart_quote(
    request: CartQuoteRequest,
    session: Session,
    retailer_id: UUID,
) -> CartQuoteResponse:
    retailer = get_catalogue_retailer(session, retailer_id)
    now = datetime.now(timezone.utc)
    schemes = get_active_schemes(session)
    lines: list[CartQuoteLine] = []

    # Consolidate duplicate SKU lines so tier discounts and order totals reflect total ordered quantity
    consolidated_items: dict[str, int] = {}
    for item in request.items:
        consolidated_items[item.sku] = consolidated_items.get(item.sku, 0) + item.quantity

    for sku, quantity in consolidated_items.items():
        product = session.scalar(
            select(Product).where(
                Product.sku == sku,
                Product.is_active.is_(True),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail=f"Unknown SKU: {sku}")

        retailer_price = session.scalar(
            select(RetailerPrice)
            .where(
                RetailerPrice.product_id == product.id,
                RetailerPrice.retailer_id == retailer.id,
                *active_price_conditions(now),
            )
            .order_by(
                RetailerPrice.valid_from.desc().nullslast(),
                RetailerPrice.created_at.desc(),
            )
            .limit(1)
        )
        if retailer_price is None:
            raise HTTPException(
                status_code=404,
                detail=f"No active price for SKU {sku} and this retailer",
            )

        presentation = PRODUCT_PRESENTATION.get(product.sku, {})
        matching_schemes = resolve_schemes_for_sku(product.sku, schemes)
        rules = [rule for _, rule in matching_schemes]
        calculation = calculate_line(
            quantity,
            retailer_price.unit_price,
            rules if rules else None,
        )

        scheme_label = calculation.scheme_label or (
            matching_schemes[0][0] if matching_schemes else None
        )

        lines.append(
            CartQuoteLine(
                sku=product.sku,
                name=product.name,
                order_unit=presentation.get("order_unit", "case"),
                requested_quantity=calculation.requested_quantity,
                paid_quantity=calculation.paid_quantity,
                free_quantity=calculation.free_quantity,
                delivered_quantity=calculation.delivered_quantity,
                unit_price=calculation.unit_price,
                subtotal=calculation.subtotal,
                discount=calculation.discount,
                free_value=calculation.free_value,
                total=calculation.total,
                scheme_label=scheme_label,
                discount_percent=calculation.discount_percent,
            )
        )

    return CartQuoteResponse(
        source="database",
        lines=lines,
        subtotal=sum((line.subtotal for line in lines), Decimal("0.00")),
        discount_total=sum((line.discount for line in lines), Decimal("0.00")),
        free_quantity=sum(line.free_quantity for line in lines),
        free_value=sum((line.free_value for line in lines), Decimal("0.00")),
        total=sum((line.total for line in lines), Decimal("0.00")),
    )