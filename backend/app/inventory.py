"""Live Inventory and Stock Management API for OrderFlow Phase 5."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.catalogue import PRODUCT_PRESENTATION
from app.database import get_db_session
from app.models import Inventory, Product, StockMovement, User

router = APIRouter()


class InventoryItemResponse(BaseModel):
    sku: str
    name: str
    pack_label: str
    order_unit: str
    available_stock: int
    is_out_of_stock: bool
    is_low_stock: bool
    # Internal stock management fields (included for authorized Order Desk / Admin)
    on_hand_stock: int | None = None
    reserved_stock: int | None = None
    low_stock_threshold: int | None = None
    updated_at: datetime | None = None


class ReceiveStockRequest(BaseModel):
    sku: str
    quantity: int = Field(gt=0, description="Quantity of cases received")
    reason: str | None = Field(default=None, max_length=500)


class AdjustStockRequest(BaseModel):
    sku: str
    new_on_hand: int = Field(ge=0, description="New physical on-hand stock count")
    reason: str = Field(min_length=3, max_length=500, description="Mandatory audit reason")


class UpdateThresholdRequest(BaseModel):
    low_stock_threshold: int = Field(ge=0, description="Configurable low-stock alert threshold")


class StockMovementResponse(BaseModel):
    id: str
    sku: str
    movement_type: str
    quantity: int
    on_hand_before: int
    on_hand_after: int
    reserved_before: int
    reserved_after: int
    reference_id: str | None
    reason: str | None
    created_at: datetime


def ensure_inventory_record(session: Session, product: Product) -> Inventory:
    """Ensure an inventory row exists for the given product, initializing with zero stock baseline."""
    inv = session.execute(
        select(Inventory).where(Inventory.product_id == product.id).with_for_update()
    ).scalar_one_or_none()

    if inv is None:
        inv = Inventory(
            product_id=product.id,
            on_hand_stock=0,
            reserved_stock=0,
            low_stock_threshold=10,
        )
        session.add(inv)
        session.flush()

        session.add(
            StockMovement(
                product_id=product.id,
                movement_type="init",
                quantity=0,
                on_hand_before=0,
                on_hand_after=0,
                reserved_before=0,
                reserved_after=0,
                reference_id="ZERO-STOCK-INIT",
                reason="Initial zero-stock inventory initialization",
                created_by_user_id=None,
            )
        )
        session.flush()

    return inv


@router.get("/inventory", response_model=list[InventoryItemResponse])
def list_inventory(
    current_user: Annotated[
        User,
        Depends(
            require_roles(
                "retailer", "order_desk", "distributor_admin", "super_admin"
            )
        ),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[InventoryItemResponse]:
    """View inventory for all active catalogue products."""
    is_order_desk = current_user.role in (
        "order_desk",
        "distributor_admin",
        "super_admin",
    )

    rows = session.execute(
        select(Product, Inventory)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(Product.is_active.is_(True))
        .order_by(Product.sku)
    ).all()

    results: list[InventoryItemResponse] = []
    for prod, inv in rows:
        presentation = PRODUCT_PRESENTATION.get(prod.sku, {})
        on_hand = inv.on_hand_stock if inv else 0
        reserved = inv.reserved_stock if inv else 0
        avail = max(0, on_hand - reserved)
        threshold = inv.low_stock_threshold if inv else 10
        is_low = avail <= threshold
        is_out = avail <= 0

        results.append(
            InventoryItemResponse(
                sku=prod.sku,
                name=prod.name,
                pack_label=prod.pack_label or "Pack not configured",
                order_unit=presentation.get("order_unit", "case"),
                available_stock=avail,
                is_out_of_stock=is_out,
                is_low_stock=is_low,
                on_hand_stock=on_hand if is_order_desk else None,
                reserved_stock=reserved if is_order_desk else None,
                low_stock_threshold=threshold if is_order_desk else None,
                updated_at=inv.updated_at if (inv and is_order_desk) else None,
            )
        )

    return results


@router.get("/inventory/{sku}", response_model=InventoryItemResponse)
def get_product_inventory(
    sku: str,
    current_user: Annotated[
        User,
        Depends(
            require_roles(
                "retailer", "order_desk", "distributor_admin", "super_admin"
            )
        ),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryItemResponse:
    """View live inventory for an individual product SKU."""
    is_order_desk = current_user.role in (
        "order_desk",
        "distributor_admin",
        "super_admin",
    )

    prod = session.execute(
        select(Product).where(Product.sku == sku.strip(), Product.is_active.is_(True))
    ).scalar_one_or_none()

    if prod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active product with SKU '{sku}' not found",
        )

    inv = ensure_inventory_record(session, prod)
    session.commit()

    presentation = PRODUCT_PRESENTATION.get(prod.sku, {})
    on_hand = inv.on_hand_stock if inv else 0
    reserved = inv.reserved_stock if inv else 0
    avail = max(0, on_hand - reserved)
    threshold = inv.low_stock_threshold if inv else 10

    return InventoryItemResponse(
        sku=prod.sku,
        name=prod.name,
        pack_label=prod.pack_label or "Pack not configured",
        order_unit=presentation.get("order_unit", "case"),
        available_stock=avail,
        is_out_of_stock=avail <= 0,
        is_low_stock=avail <= threshold,
        on_hand_stock=on_hand if is_order_desk else None,
        reserved_stock=reserved if is_order_desk else None,
        low_stock_threshold=threshold if is_order_desk else None,
        updated_at=inv.updated_at if (inv and is_order_desk) else None,
    )


@router.post("/inventory/receive", response_model=InventoryItemResponse)
def receive_inventory(
    payload: ReceiveStockRequest,
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryItemResponse:
    """Increase stock quantity after receiving physical inventory from suppliers."""
    prod = session.execute(
        select(Product).where(
            Product.sku == payload.sku.strip(), Product.is_active.is_(True)
        )
    ).scalar_one_or_none()

    if prod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active product with SKU '{payload.sku}' not found",
        )

    inv = ensure_inventory_record(session, prod)

    on_hand_before = inv.on_hand_stock
    on_hand_after = on_hand_before + payload.quantity
    reserved_current = inv.reserved_stock

    inv.on_hand_stock = on_hand_after

    movement = StockMovement(
        product_id=prod.id,
        movement_type="receive",
        quantity=payload.quantity,
        on_hand_before=on_hand_before,
        on_hand_after=on_hand_after,
        reserved_before=reserved_current,
        reserved_after=reserved_current,
        reference_id=None,
        reason=payload.reason or "Stock received from supplier",
        created_by_user_id=current_user.id,
    )
    session.add(movement)
    session.commit()
    session.refresh(inv)

    presentation = PRODUCT_PRESENTATION.get(prod.sku, {})
    avail = inv.available_stock
    return InventoryItemResponse(
        sku=prod.sku,
        name=prod.name,
        pack_label=prod.pack_label or "Pack not configured",
        order_unit=presentation.get("order_unit", "case"),
        available_stock=avail,
        is_out_of_stock=avail <= 0,
        is_low_stock=inv.is_low_stock,
        on_hand_stock=inv.on_hand_stock,
        reserved_stock=inv.reserved_stock,
        low_stock_threshold=inv.low_stock_threshold,
        updated_at=inv.updated_at,
    )


@router.post("/inventory/adjust", response_model=InventoryItemResponse)
def adjust_inventory(
    payload: AdjustStockRequest,
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryItemResponse:
    """Record an audit adjustment to physical on-hand stock with a mandatory reason."""
    prod = session.execute(
        select(Product).where(
            Product.sku == payload.sku.strip(), Product.is_active.is_(True)
        )
    ).scalar_one_or_none()

    if prod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active product with SKU '{payload.sku}' not found",
        )

    inv = ensure_inventory_record(session, prod)

    if payload.new_on_hand < inv.reserved_stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot adjust on-hand stock to {payload.new_on_hand} cases: "
                f"{inv.reserved_stock} cases are currently reserved for pending orders."
            ),
        )

    on_hand_before = inv.on_hand_stock
    on_hand_after = payload.new_on_hand
    delta = on_hand_after - on_hand_before

    inv.on_hand_stock = on_hand_after

    movement = StockMovement(
        product_id=prod.id,
        movement_type="adjustment",
        quantity=delta,
        on_hand_before=on_hand_before,
        on_hand_after=on_hand_after,
        reserved_before=inv.reserved_stock,
        reserved_after=inv.reserved_stock,
        reference_id=None,
        reason=payload.reason,
        created_by_user_id=current_user.id,
    )
    session.add(movement)
    session.commit()
    session.refresh(inv)

    presentation = PRODUCT_PRESENTATION.get(prod.sku, {})
    avail = inv.available_stock
    return InventoryItemResponse(
        sku=prod.sku,
        name=prod.name,
        pack_label=prod.pack_label or "Pack not configured",
        order_unit=presentation.get("order_unit", "case"),
        available_stock=avail,
        is_out_of_stock=avail <= 0,
        is_low_stock=inv.is_low_stock,
        on_hand_stock=inv.on_hand_stock,
        reserved_stock=inv.reserved_stock,
        low_stock_threshold=inv.low_stock_threshold,
        updated_at=inv.updated_at,
    )


@router.patch("/inventory/{sku}/threshold", response_model=InventoryItemResponse)
def update_low_stock_threshold(
    sku: str,
    payload: UpdateThresholdRequest,
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> InventoryItemResponse:
    """Configure low-stock alert threshold for a product."""
    prod = session.execute(
        select(Product).where(Product.sku == sku.strip(), Product.is_active.is_(True))
    ).scalar_one_or_none()

    if prod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active product with SKU '{sku}' not found",
        )

    inv = ensure_inventory_record(session, prod)
    inv.low_stock_threshold = payload.low_stock_threshold
    session.commit()
    session.refresh(inv)

    presentation = PRODUCT_PRESENTATION.get(prod.sku, {})
    avail = inv.available_stock
    return InventoryItemResponse(
        sku=prod.sku,
        name=prod.name,
        pack_label=prod.pack_label or "Pack not configured",
        order_unit=presentation.get("order_unit", "case"),
        available_stock=avail,
        is_out_of_stock=avail <= 0,
        is_low_stock=inv.is_low_stock,
        on_hand_stock=inv.on_hand_stock,
        reserved_stock=inv.reserved_stock,
        low_stock_threshold=inv.low_stock_threshold,
        updated_at=inv.updated_at,
    )


@router.get("/inventory/{sku}/history", response_model=list[StockMovementResponse])
def get_stock_movement_history(
    sku: str,
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[StockMovementResponse]:
    """View stock movement ledger history for a product (Order Desk and Admin only)."""
    prod = session.execute(
        select(Product).where(Product.sku == sku.strip(), Product.is_active.is_(True))
    ).scalar_one_or_none()

    if prod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active product with SKU '{sku}' not found",
        )

    movements = session.execute(
        select(StockMovement)
        .where(StockMovement.product_id == prod.id)
        .order_by(StockMovement.created_at.desc())
    ).scalars().all()

    return [
        StockMovementResponse(
            id=str(m.id),
            sku=prod.sku,
            movement_type=m.movement_type,
            quantity=m.quantity,
            on_hand_before=m.on_hand_before,
            on_hand_after=m.on_hand_after,
            reserved_before=m.reserved_before,
            reserved_after=m.reserved_after,
            reference_id=m.reference_id,
            reason=m.reason,
            created_at=m.created_at,
        )
        for m in movements
    ]

