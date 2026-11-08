import csv
from app.auth import get_current_user, require_roles
from sqlalchemy.engine import Engine
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from app.database import get_engine
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.cart import (
    CartItemRequest,
    CartQuoteLine,
    CartQuoteRequest,
    CartQuoteResponse,
    calculate_cart_quote,
)
from app.catalogue import active_price_conditions
from app.database import get_db_session
from app.inventory import ensure_inventory_record
from app.models import (
    Inventory,
    Order,
    OrderItem,
    Product,
    Retailer,
    RetailerPrice,
    Salesman,
    SalesmanRetailerAssignment,
    StockMovement,
    User,
)

router = APIRouter()

OrderStatus = Literal["pending_review", "credit_hold", "approved", "rejected"]
OrderAction = Literal["approve", "reject", "place_on_hold", "release_hold"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DemoOrder(BaseModel):
    source: Literal["database"] = "database"
    id: str
    order_number: str
    retailer_name: str
    retailer_id: str | None = None
    salesman_id: str | None = None
    order_source: str = "retailer"
    idempotency_key: str | None = None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    subtotal: Decimal
    discount_total: Decimal
    free_quantity: Decimal
    free_value: Decimal
    total: Decimal
    note: str | None = None
    hold_reason: str | None = None
    retailer_credit_limit: Decimal | None = None
    retailer_current_outstanding: Decimal | None = None
    retailer_available_credit: Decimal | None = None
    lines: list[CartQuoteLine]


class UnavailableReorderItem(BaseModel):
    sku: str
    name: str
    requested_quantity: int
    reason: Literal["inactive_or_discontinued", "no_active_price", "out_of_stock"]
    message: str


class RepeatOrderDraftResponse(BaseModel):
    source: Literal["database"] = "database"
    original_order_id: str
    original_order_number: str
    retailer_id: str
    retailer_name: str
    is_reorderable: bool = True
    has_unavailable_items: bool
    unavailable_items: list[UnavailableReorderItem]
    draft_quote: CartQuoteResponse | None = None
    valid_lines_count: int = 0
    total: Decimal = Decimal("0.00")
    message: str


class OrderListResponse(BaseModel):
    source: Literal["database"] = "database"
    orders: list[DemoOrder]


class OrderDecisionRequest(BaseModel):
    action: OrderAction
    note: str | None = Field(default=None, max_length=500)


def _get_retailer(session: Session) -> Retailer:
    retailer = session.execute(
        select(Retailer)
        .where(Retailer.external_ref == "DEMO-RETAILER")
        .where(Retailer.is_active.is_(True))
    ).scalar_one_or_none()

    if retailer is None:
        raise HTTPException(
            status_code=500,
            detail="Demo retailer is not configured",
        )

    return retailer


def _product_map(
    session: Session,
    quote_lines: list[CartQuoteLine],
) -> dict[str, Product]:
    skus = [line.sku for line in quote_lines]

    products = session.execute(
        select(Product).where(Product.sku.in_(skus))
    ).scalars().all()

    return {product.sku: product for product in products}


def _order_to_response(
    session: Session,
    order: Order,
) -> DemoOrder:
    retailer = session.get(Retailer, order.retailer_id)

    if retailer is None:
        raise HTTPException(
            status_code=500,
            detail="Order retailer not found",
        )

    items = session.execute(
        select(OrderItem, Product, Inventory)
        .join(Product, Product.id == OrderItem.product_id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.created_at)
    ).all()

    lines: list[CartQuoteLine] = []

    for item, product, inv in items:
        subtotal = item.unit_price * item.quantity
        total = item.line_total

        scheme_label = None
        discount_percent = Decimal("0.00")
        if subtotal > Decimal("0.00") and item.discount > Decimal("0.00"):
            discount_percent = ((item.discount / subtotal) * Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        if item.free_quantity > 0 and item.discount > Decimal("0.00"):
            pct_str = format(discount_percent.normalize(), "f")
            scheme_label = f"{int(item.free_quantity)} free + {pct_str}% off"
        elif item.free_quantity > 0:
            free_int = int(item.free_quantity)
            scheme_label = f"{free_int} free case{'s' if free_int > 1 else ''}"
        elif item.discount > Decimal("0.00"):
            pct_str = format(discount_percent.normalize(), "f")
            scheme_label = f"{pct_str}% off"

        lines.append(
            CartQuoteLine(
                sku=product.sku,
                name=product.name,
                order_unit="case",
                requested_quantity=int(item.quantity),
                paid_quantity=int(item.quantity),
                free_quantity=int(item.free_quantity),
                delivered_quantity=int(item.delivered_quantity),
                unit_price=item.unit_price,
                subtotal=subtotal,
                discount=item.discount,
                free_value=item.free_quantity * item.unit_price,
                total=total,
                scheme_label=scheme_label,
                discount_percent=discount_percent,
                available_stock=inv.available_stock if inv else 0,
                is_low_stock=inv.is_low_stock if inv else False,
            )
        )

    updated_at = order.updated_at or order.created_at

    return DemoOrder(
        id=str(order.id),
        order_number=order.order_number,
        retailer_name=retailer.name,
        retailer_id=str(retailer.id),
        salesman_id=str(order.salesman_id) if order.salesman_id else None,
        order_source=order.order_source or "retailer",
        idempotency_key=order.idempotency_key,
        status=order.status,
        created_at=order.created_at,
        updated_at=updated_at,
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        free_quantity=order.free_quantity,
        free_value=order.free_value,
        total=order.total_amount,
        note=order.note,
        hold_reason=order.hold_reason,
        retailer_credit_limit=retailer.credit_limit,
        retailer_current_outstanding=retailer.current_outstanding,
        retailer_available_credit=retailer.available_credit,
        lines=lines,
    )


def _validate_idempotent_order(
    session: Session,
    existing_order: Order,
    target_retailer_id: UUID,
    salesman_id: UUID | None,
    current_user: User,
    request: CartQuoteRequest,
) -> DemoOrder:
    # 1. Retailer ownership check: prevent cross-retailer leakage
    if existing_order.retailer_id != target_retailer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key collision across different retailers",
        )

    # 2. Salesman attribution check
    if current_user.role == "salesman":
        if existing_order.salesman_id != salesman_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used by a different salesman",
            )
    elif current_user.role == "retailer":
        if existing_order.salesman_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used by a salesman order",
            )

    # 3. Payload verification: compare requested items & quantities vs existing items
    existing_items = session.execute(
        select(OrderItem, Product)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == existing_order.id)
    ).all()

    existing_item_map: dict[str, int] = {}
    for item, product in existing_items:
        existing_item_map[product.sku] = existing_item_map.get(product.sku, 0) + int(item.quantity)

    request_item_map: dict[str, int] = {}
    for item in request.items:
        request_item_map[item.sku] = request_item_map.get(item.sku, 0) + item.quantity

    if existing_item_map != request_item_map:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key reused with a different order payload",
        )

    return _order_to_response(session, existing_order)


@router.post(
    "/orders",
    response_model=DemoOrder,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    request: CartQuoteRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "salesman")),
    ],
) -> DemoOrder:
    target_retailer_id: UUID | None = None
    salesman_id: UUID | None = None
    order_source: str = request.order_source or "retailer"

    if current_user.role == "retailer":
        if current_user.retailer_id is None:
            raise HTTPException(
                status_code=403,
                detail="User is not linked to a retailer",
            )
        target_retailer_id = current_user.retailer_id
        salesman_id = None
        order_source = request.order_source or "retailer"

    elif current_user.role == "salesman":
        if not request.retailer_id:
            raise HTTPException(
                status_code=400,
                detail="retailer_id is required when creating an order as a salesman",
            )
        target_retailer_id = request.retailer_id
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if not salesman:
            raise HTTPException(
                status_code=403,
                detail="Active salesman profile not found for user",
            )
        assignment = session.scalar(
            select(SalesmanRetailerAssignment).where(
                SalesmanRetailerAssignment.salesman_id == salesman.id,
                SalesmanRetailerAssignment.retailer_id == target_retailer_id,
                SalesmanRetailerAssignment.is_active.is_(True),
            )
        )
        if not assignment:
            raise HTTPException(
                status_code=403,
                detail="Salesman is not assigned to this retailer",
            )
        salesman_id = salesman.id
        order_source = request.order_source or "salesman"

    elif current_user.role == "order_desk":
        if not request.retailer_id:
            raise HTTPException(
                status_code=400,
                detail="retailer_id is required when creating an order as order_desk",
            )
        target_retailer_id = request.retailer_id
        salesman_id = None
        order_source = request.order_source or "order_desk"

    else:
        raise HTTPException(
            status_code=403,
            detail="Role not authorized to create orders",
        )

    # Server-side Idempotency check:
    clean_idempotency_key = (
        request.idempotency_key.strip()
        if request.idempotency_key and request.idempotency_key.strip()
        else None
    )
    if clean_idempotency_key:
        existing_order = session.scalar(
            select(Order).where(Order.idempotency_key == clean_idempotency_key)
        )
        if existing_order is not None:
            return _validate_idempotent_order(
                session=session,
                existing_order=existing_order,
                target_retailer_id=target_retailer_id,
                salesman_id=salesman_id,
                current_user=current_user,
                request=request,
            )

    # 1. Lock retailer row for concurrent credit check safety
    retailer = session.execute(
        select(Retailer)
        .where(Retailer.id == target_retailer_id)
        .with_for_update()
    ).scalar_one_or_none()

    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=403,
            detail="Retailer account is inactive or not found",
        )

    # 2. Calculate cart quote reflecting schemes and discounts
    quote = calculate_cart_quote(
        request,
        session,
        target_retailer_id,
    )
    if not quote.lines:
        raise HTTPException(
            status_code=400,
            detail="Cart cannot be empty",
        )

    products = _product_map(session, quote.lines)

    missing_skus = [
        line.sku for line in quote.lines if line.sku not in products
    ]

    if missing_skus:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown SKU(s): {', '.join(missing_skus)}",
        )

    # 3. Stock Validation & Row-Level Locking (ordered by product_id to prevent deadlocks)
    product_by_id = {p.id: p for p in products.values()}
    inv_map: dict[UUID, Inventory] = {}
    for pid in sorted(product_by_id.keys()):
        prod = product_by_id[pid]
        inv = ensure_inventory_record(session, prod)
        inv_map[pid] = inv

    # Aggregate required delivered quantity by product_id (handles multiple lines for the same SKU)
    total_required_by_product: dict[UUID, int] = {}
    for line in quote.lines:
        prod = products[line.sku]
        total_required_by_product[prod.id] = (
            total_required_by_product.get(prod.id, 0) + line.delivered_quantity
        )

    # Validate aggregated required quantities against live available stock
    for pid, total_req in total_required_by_product.items():
        inv = inv_map[pid]
        prod = product_by_id[pid]
        if inv.available_stock < total_req:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Insufficient stock for {prod.name} ({prod.sku}). "
                    f"Required: {total_req} case{'s' if total_req > 1 else ''}, "
                    f"Available: {inv.available_stock} case{'s' if inv.available_stock != 1 else ''}."
                ),
            )

    # 4. Automatic Credit Check:
    # Pending review orders reserve credit; held orders do NOT reduce available credit twice.
    pending_total = session.scalar(
        select(func.coalesce(func.sum(Order.total_amount), Decimal("0.00")))
        .where(
            Order.retailer_id == retailer.id,
            Order.status == "pending_review",
        )
    ) or Decimal("0.00")

    limit = retailer.credit_limit if retailer.credit_limit is not None else Decimal("0.00")
    outstanding = (
        retailer.current_outstanding
        if retailer.current_outstanding is not None
        else Decimal("0.00")
    )
    available_credit = limit - outstanding
    effective_available_credit = available_credit - pending_total

    if quote.total > effective_available_credit:
        initial_status: OrderStatus = "credit_hold"
        hold_reason = (
            f"Order total ₹{quote.total:.2f} exceeds available credit ₹{max(Decimal('0.00'), effective_available_credit):.2f} "
            f"(Credit limit: ₹{limit:.2f}, Outstanding: ₹{outstanding:.2f})"
        )
    else:
        initial_status: OrderStatus = "pending_review"
        hold_reason = None

    now = _utc_now()
    order_id = UUID(int=0)
    order_number = f"OF-{now:%y%m%d}-{now:%H%M%S%f}"[:22]

    order = Order(
        retailer_id=retailer.id,
        created_by_user_id=current_user.id,
        salesman_id=salesman_id,
        order_source=order_source,
        idempotency_key=clean_idempotency_key,
        order_number=order_number,
        status=initial_status,
        subtotal=quote.subtotal,
        discount_total=quote.discount_total,
        free_quantity=quote.free_quantity,
        free_value=quote.free_value,
        total_amount=quote.total,
        note=None,
        hold_reason=hold_reason,
        updated_at=now,
    )

    session.add(order)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        if clean_idempotency_key:
            existing_order = session.scalar(
                select(Order).where(Order.idempotency_key == clean_idempotency_key)
            )
            if existing_order is not None:
                return _validate_idempotent_order(
                    session=session,
                    existing_order=existing_order,
                    target_retailer_id=target_retailer_id,
                    salesman_id=salesman_id,
                    current_user=current_user,
                    request=request,
                )
        raise

    for line in quote.lines:
        product = products[line.sku]

        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=line.paid_quantity,
                unit_price=line.unit_price,
                free_quantity=line.free_quantity,
                delivered_quantity=line.delivered_quantity,
                discount=line.discount,
                line_total=line.total,
            )
        )

    # 5. Stock Reservation: pending_review orders reserve stock; credit_hold orders do NOT reserve stock.
    if initial_status == "pending_review":
        for pid, total_qty in total_required_by_product.items():
            inv = inv_map[pid]
            res_before = inv.reserved_stock
            inv.reserved_stock += total_qty
            session.add(
                StockMovement(
                    product_id=pid,
                    movement_type="reserve",
                    quantity=total_qty,
                    on_hand_before=inv.on_hand_stock,
                    on_hand_after=inv.on_hand_stock,
                    reserved_before=res_before,
                    reserved_after=inv.reserved_stock,
                    reference_id=order_number,
                    reason=f"Stock reservation for order {order_number} (pending review)",
                    created_by_user_id=current_user.id,
                )
            )

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if clean_idempotency_key:
            existing_order = session.scalar(
                select(Order).where(Order.idempotency_key == clean_idempotency_key)
            )
            if existing_order is not None:
                return _validate_idempotent_order(
                    session=session,
                    existing_order=existing_order,
                    target_retailer_id=target_retailer_id,
                    salesman_id=salesman_id,
                    current_user=current_user,
                    request=request,
                )
        raise
    session.refresh(order)

    return _order_to_response(session, order)


@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "salesman", "order_desk", "distributor_admin", "super_admin")),
    ],
) -> OrderListResponse:
    query = select(Order).order_by(Order.created_at.desc())

    if current_user.role == "retailer":
        if current_user.retailer_id is None:
            raise HTTPException(
                status_code=403,
                detail="User is not linked to a retailer",
            )

        query = query.where(
            Order.retailer_id == current_user.retailer_id
        )

    elif current_user.role == "salesman":
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if not salesman:
            raise HTTPException(
                status_code=403,
                detail="Active salesman profile not found",
            )

        assigned_retailer_ids = session.execute(
            select(SalesmanRetailerAssignment.retailer_id).where(
                SalesmanRetailerAssignment.salesman_id == salesman.id,
                SalesmanRetailerAssignment.is_active.is_(True),
            )
        ).scalars().all()

        query = query.where(
            (Order.salesman_id == salesman.id)
            | (Order.retailer_id.in_(assigned_retailer_ids))
        )

    orders = session.execute(query).scalars().all()

    return OrderListResponse(
        orders=[
            _order_to_response(session, order)
            for order in orders
        ]
    )


@router.get("/orders/{order_id}", response_model=DemoOrder)
def get_order(
    order_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "salesman", "order_desk", "distributor_admin", "super_admin")),
    ],
) -> DemoOrder:
    try:
        order_uuid = UUID(order_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid order ID",
        )

    query = select(Order).where(Order.id == order_uuid)

    if current_user.role == "retailer":
        if current_user.retailer_id is None:
            raise HTTPException(
                status_code=403,
                detail="User is not linked to a retailer",
            )

        query = query.where(
            Order.retailer_id == current_user.retailer_id
        )

    elif current_user.role == "salesman":
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if not salesman:
            raise HTTPException(
                status_code=403,
                detail="Active salesman profile not found",
            )

        assigned_retailer_ids = session.execute(
            select(SalesmanRetailerAssignment.retailer_id).where(
                SalesmanRetailerAssignment.salesman_id == salesman.id,
                SalesmanRetailerAssignment.is_active.is_(True),
            )
        ).scalars().all()

        query = query.where(
            (Order.salesman_id == salesman.id)
            | (Order.retailer_id.in_(assigned_retailer_ids))
        )

    order = session.execute(query).scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return _order_to_response(session, order)


@router.post(
    "/orders/{order_id}/repeat-draft",
    response_model=RepeatOrderDraftResponse,
)
def create_repeat_order_draft(
    order_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "salesman", "order_desk", "distributor_admin", "super_admin")),
    ],
) -> RepeatOrderDraftResponse:
    try:
        order_uuid = UUID(order_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid order ID",
        )

    order = session.get(Order, order_uuid)
    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    retailer = session.get(Retailer, order.retailer_id)
    if retailer is None:
        raise HTTPException(
            status_code=500,
            detail="Retailer for order not found",
        )

    # Permission check:
    if current_user.role == "retailer":
        if current_user.retailer_id != order.retailer_id:
            raise HTTPException(
                status_code=403,
                detail="Retailers can only repeat their own orders",
            )
    elif current_user.role == "salesman":
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if not salesman:
            raise HTTPException(
                status_code=403,
                detail="Active salesman profile not found",
            )
        assignment = session.scalar(
            select(SalesmanRetailerAssignment).where(
                SalesmanRetailerAssignment.salesman_id == salesman.id,
                SalesmanRetailerAssignment.retailer_id == order.retailer_id,
                SalesmanRetailerAssignment.is_active.is_(True),
            )
        )
        if not assignment:
            raise HTTPException(
                status_code=403,
                detail="Salesman is not assigned to this retailer",
            )

    # Fetch original items
    items = session.execute(
        select(OrderItem, Product, Inventory)
        .join(Product, Product.id == OrderItem.product_id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.created_at)
    ).all()

    if not items:
        raise HTTPException(
            status_code=400,
            detail="Original order has no line items",
        )

    # Fetch active retailer prices
    now = _utc_now()
    active_conds = active_price_conditions(now)
    active_prices = session.execute(
        select(RetailerPrice, Product.sku)
        .join(Product, Product.id == RetailerPrice.product_id)
        .where(
            RetailerPrice.retailer_id == order.retailer_id,
            *active_conds,
        )
    ).all()
    price_by_sku = {sku: rp for rp, sku in active_prices}

    unavailable_items: list[UnavailableReorderItem] = []
    valid_items: list[CartItemRequest] = []

    for item, product, inv in items:
        qty = int(item.quantity)
        if not product.is_active:
            unavailable_items.append(
                UnavailableReorderItem(
                    sku=product.sku,
                    name=product.name,
                    requested_quantity=qty,
                    reason="inactive_or_discontinued",
                    message=f"{product.name} ({product.sku}) is discontinued or inactive in the live catalogue.",
                )
            )
        elif product.sku not in price_by_sku:
            unavailable_items.append(
                UnavailableReorderItem(
                    sku=product.sku,
                    name=product.name,
                    requested_quantity=qty,
                    reason="no_active_price",
                    message=f"No active contracted price found for {product.name} ({product.sku}).",
                )
            )
        elif inv is None or inv.available_stock <= 0:
            unavailable_items.append(
                UnavailableReorderItem(
                    sku=product.sku,
                    name=product.name,
                    requested_quantity=qty,
                    reason="out_of_stock",
                    message=f"{product.name} ({product.sku}) is currently out of stock.",
                )
            )
        else:
            valid_items.append(
                CartItemRequest(sku=product.sku, quantity=qty)
            )

    draft_quote: CartQuoteResponse | None = None
    if valid_items:
        quote_req = CartQuoteRequest(
            items=valid_items,
            retailer_id=order.retailer_id,
        )
        draft_quote = calculate_cart_quote(quote_req, session, order.retailer_id)

    valid_count = len(draft_quote.lines) if draft_quote else 0
    total_val = draft_quote.total if draft_quote else Decimal("0.00")

    if unavailable_items and valid_items:
        msg = f"Reorder draft prepared with {valid_count} available item(s). {len(unavailable_items)} item(s) are currently unavailable."
    elif unavailable_items and not valid_items:
        msg = "All items from the original order are currently unavailable or out of stock."
    else:
        msg = f"Reorder draft prepared with all {valid_count} item(s) at current pricing and active schemes."

    return RepeatOrderDraftResponse(
        original_order_id=str(order.id),
        original_order_number=order.order_number,
        retailer_id=str(retailer.id),
        retailer_name=retailer.name,
        is_reorderable=valid_count > 0,
        has_unavailable_items=len(unavailable_items) > 0,
        unavailable_items=unavailable_items,
        draft_quote=draft_quote,
        valid_lines_count=valid_count,
        total=total_val,
        message=msg,
    )


@router.patch(
    "/orders/{order_id}/decision",
    response_model=DemoOrder,
)
def update_order_decision(
    order_id: str,
    request: OrderDecisionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> DemoOrder:
    try:
        order_uuid = UUID(order_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid order ID",
        )

    # 1. Lock the order row first
    order = session.execute(
        select(Order).where(Order.id == order_uuid).with_for_update()
    ).scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    allowed_actions: dict[OrderStatus, set[OrderAction]] = {
        "pending_review": {
            "approve",
            "reject",
            "place_on_hold",
        },
        "credit_hold": {
            "reject",
            "release_hold",
        },
        "approved": set(),
        "rejected": set(),
    }

    action_statuses: dict[OrderAction, OrderStatus] = {
        "approve": "approved",
        "reject": "rejected",
        "place_on_hold": "credit_hold",
        "release_hold": "pending_review",
    }

    if request.action not in allowed_actions[order.status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Action '{request.action}' is not allowed "
                f"from '{order.status}'"
            ),
        )

    # 2. Lock the retailer row next (consistent lock order: Retailer before Inventory)
    retailer = session.execute(
        select(Retailer).where(Retailer.id == order.retailer_id).with_for_update()
    ).scalar_one_or_none()

    if retailer is None:
        raise HTTPException(
            status_code=500,
            detail="Retailer not found for this order",
        )

    # 3. Retrieve order items and aggregate required delivered quantities by product_id
    order_items = session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    ).scalars().all()

    total_qty_by_product: dict[UUID, int] = {}
    for item in order_items:
        total_qty_by_product[item.product_id] = (
            total_qty_by_product.get(item.product_id, 0) + int(item.delivered_quantity)
        )

    # 4. Lock Inventory rows in ascending order of product_id (prevents deadlocks)
    inv_map: dict[UUID, Inventory] = {}
    for pid in sorted(total_qty_by_product.keys()):
        prod = session.get(Product, pid)
        if prod:
            inv = ensure_inventory_record(session, prod)
            inv_map[pid] = inv

    if request.action == "approve":
        limit = retailer.credit_limit if retailer.credit_limit is not None else Decimal("0.00")
        outstanding = (
            retailer.current_outstanding
            if retailer.current_outstanding is not None
            else Decimal("0.00")
        )

        # Approval-time credit calculation:
        # effective_available_credit = credit_limit - current_outstanding - sum(other pending_review orders)
        other_pending_total = session.scalar(
            select(func.coalesce(func.sum(Order.total_amount), Decimal("0.00")))
            .where(
                Order.retailer_id == retailer.id,
                Order.status == "pending_review",
                Order.id != order.id,
            )
        ) or Decimal("0.00")

        effective_available = limit - outstanding - other_pending_total

        if order.total_amount > effective_available:
            # Order fails credit check, transitions to credit_hold: release existing reservation
            for pid, total_qty in total_qty_by_product.items():
                inv = inv_map[pid]
                res_before = inv.reserved_stock
                inv.reserved_stock = max(0, inv.reserved_stock - total_qty)
                session.add(
                    StockMovement(
                        product_id=pid,
                        movement_type="release_reservation",
                        quantity=-total_qty,
                        on_hand_before=inv.on_hand_stock,
                        on_hand_after=inv.on_hand_stock,
                        reserved_before=res_before,
                        reserved_after=inv.reserved_stock,
                        reference_id=order.order_number,
                        reason=f"Reservation released: order {order.order_number} moved to credit hold during approval attempt",
                        created_by_user_id=current_user.id,
                    )
                )

            order.status = "credit_hold"
            order.hold_reason = (
                f"Cannot approve: Order amount ₹{order.total_amount:.2f} exceeds available credit "
                f"(effective available: ₹{max(Decimal('0.00'), effective_available):.2f}, "
                f"Limit: ₹{limit:.2f}, Outstanding: ₹{outstanding:.2f}, Other pending: ₹{other_pending_total:.2f})"
            )
            order.updated_at = _utc_now()
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=order.hold_reason,
            )

        retailer.current_outstanding = outstanding + order.total_amount
        order.hold_reason = None
        order.status = "approved"

        # Deduct physical stock and clear reservation atomically
        for pid, total_qty in total_qty_by_product.items():
            inv = inv_map[pid]
            on_hand_before = inv.on_hand_stock
            res_before = inv.reserved_stock
            inv.on_hand_stock = max(0, inv.on_hand_stock - total_qty)
            inv.reserved_stock = max(0, inv.reserved_stock - total_qty)
            session.add(
                StockMovement(
                    product_id=pid,
                    movement_type="deduct_approved",
                    quantity=-total_qty,
                    on_hand_before=on_hand_before,
                    on_hand_after=inv.on_hand_stock,
                    reserved_before=res_before,
                    reserved_after=inv.reserved_stock,
                    reference_id=order.order_number,
                    reason=f"Physical stock deduction for approved order {order.order_number}",
                    created_by_user_id=current_user.id,
                )
            )

    elif request.action == "release_hold":
        # Check available stock fresh on aggregated quantities before releasing hold back to pending_review
        for pid, total_qty in total_qty_by_product.items():
            inv = inv_map[pid]
            if inv.available_stock < total_qty:
                prod = session.get(Product, pid)
                sku_str = prod.sku if prod else str(pid)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot release hold: Insufficient available stock for SKU '{sku_str}'. "
                        f"Required: {total_qty}, Available: {inv.available_stock}."
                    ),
                )

        # Reserve stock fresh
        for pid, total_qty in total_qty_by_product.items():
            inv = inv_map[pid]
            res_before = inv.reserved_stock
            inv.reserved_stock += total_qty
            session.add(
                StockMovement(
                    product_id=pid,
                    movement_type="reserve",
                    quantity=total_qty,
                    on_hand_before=inv.on_hand_stock,
                    on_hand_after=inv.on_hand_stock,
                    reserved_before=res_before,
                    reserved_after=inv.reserved_stock,
                    reference_id=order.order_number,
                    reason=f"Stock reservation for order {order.order_number} (hold released to pending review)",
                    created_by_user_id=current_user.id,
                )
            )

        order.hold_reason = None
        order.status = "pending_review"

    elif request.action == "place_on_hold":
        # Order transitions pending_review -> credit_hold: release reservation
        for pid, total_qty in total_qty_by_product.items():
            inv = inv_map[pid]
            res_before = inv.reserved_stock
            inv.reserved_stock = max(0, inv.reserved_stock - total_qty)
            session.add(
                StockMovement(
                    product_id=pid,
                    movement_type="release_reservation",
                    quantity=-total_qty,
                    on_hand_before=inv.on_hand_stock,
                    on_hand_after=inv.on_hand_stock,
                    reserved_before=res_before,
                    reserved_after=inv.reserved_stock,
                    reference_id=order.order_number,
                    reason=f"Stock reservation released: order {order.order_number} placed on hold by Order Desk",
                    created_by_user_id=current_user.id,
                )
            )
        order.hold_reason = request.note or "Manual hold placed by Order Desk"
        order.status = "credit_hold"

    elif request.action == "reject":
        if order.status == "pending_review":
            for pid, total_qty in total_qty_by_product.items():
                inv = inv_map[pid]
                res_before = inv.reserved_stock
                inv.reserved_stock = max(0, inv.reserved_stock - total_qty)
                session.add(
                    StockMovement(
                        product_id=pid,
                        movement_type="release_reservation",
                        quantity=-total_qty,
                        on_hand_before=inv.on_hand_stock,
                        on_hand_after=inv.on_hand_stock,
                        reserved_before=res_before,
                        reserved_after=inv.reserved_stock,
                        reference_id=order.order_number,
                        reason=f"Stock reservation released: order {order.order_number} rejected",
                        created_by_user_id=current_user.id,
                    )
                )
        order.status = "rejected"

    order.updated_at = _utc_now()

    if request.note is not None:
        order.note = request.note

    session.commit()
    session.refresh(order)

    return _order_to_response(session, order)


@router.get("/orders/{order_id}/tally.csv")
def export_tally_csv(
    order_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk")),
    ],
) -> Response:
    try:
        order_uuid = UUID(order_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid order ID",
        )

    order = session.get(Order, order_uuid)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    if order.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only approved orders can be exported",
        )

    items = session.execute(
        select(OrderItem, Product)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.created_at)
    ).all()

    output = StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow(
        [
            "Order Number",
            "Order Date",
            "SKU",
            "Product Name",
            "Paid Quantity",
            "Free Quantity",
            "Delivered Quantity",
            "Unit",
            "Unit Price",
            "Line Subtotal",
            "Scheme Discount",
            "Line Total",
        ]
    )

    for item, product in items:
        writer.writerow(
            [
                order.order_number,
                order.created_at.date().isoformat(),
                product.sku,
                product.name,
                format(item.quantity.normalize(), "f"),
                format(item.free_quantity.normalize(), "f"),
                format(item.delivered_quantity.normalize(), "f"),
                "case",
                item.unit_price,
                f"{item.unit_price * item.quantity:.2f}",
                item.discount,
                item.line_total,
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{order.order_number}-tally.csv"'
            )
        },
    )

def clear_demo_orders(engine: Engine) -> None:
    """Clear orders from the supplied test database only."""
    with Session(engine) as session:
        session.execute(delete(StockMovement))
        session.execute(delete(OrderItem))
        session.execute(delete(Order))
        session.execute(update(Retailer).values(current_outstanding=Decimal("0.00")))
        session.execute(update(Inventory).values(reserved_stock=0))
        session.commit()