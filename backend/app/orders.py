import csv
from app.auth import get_current_user, require_roles
from sqlalchemy.engine import Engine
from decimal import Decimal
from io import StringIO
from app.database import get_engine
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID


from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.cart import CartQuoteLine, CartQuoteRequest, calculate_cart_quote
from app.database import get_db_session
from app.models import Order, OrderItem, Product, Retailer, User

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
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    subtotal: Decimal
    discount_total: Decimal
    free_quantity: Decimal
    free_value: Decimal
    total: Decimal
    note: str | None = None
    lines: list[CartQuoteLine]


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
        select(OrderItem, Product)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.created_at)
    ).all()

    lines: list[CartQuoteLine] = []

    for item, product in items:
        subtotal = item.unit_price * item.quantity
        total = item.line_total

        lines.append(
            CartQuoteLine(
                sku=product.sku,
                name=product.name,
                order_unit="case",
                requested_quantity=item.quantity,
                paid_quantity=item.quantity,
                free_quantity=item.free_quantity,
                delivered_quantity=item.delivered_quantity,
                unit_price=item.unit_price,
                subtotal=subtotal,
                discount=item.discount,
                free_value=item.free_quantity * item.unit_price,
                total=total,
                scheme_label="",
            )
        )

    updated_at = order.updated_at or order.created_at

    return DemoOrder(
        id=str(order.id),
        order_number=order.order_number,
        retailer_name=retailer.name,
        status=order.status,
        created_at=order.created_at,
        updated_at=updated_at,
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        free_quantity=order.free_quantity,
        free_value=order.free_value,
        total=order.total_amount,
        note=order.note,
        lines=lines,
    )


@router.post(
    "/orders",
    response_model=DemoOrder,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    request: CartQuoteRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_roles("retailer"))],
) -> DemoOrder:
   

   

    if current_user.retailer_id is None:
        raise HTTPException(
            status_code=403,
            detail="User is not linked to a retailer",
        )

    retailer = session.get(Retailer, current_user.retailer_id)

    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=403,
            detail="Retailer account is inactive or not found",
        )
    quote = calculate_cart_quote(
        request,
        session,
        current_user.retailer_id,
    )
    if not quote.lines:
            raise HTTPException(
                status_code=400,
                detail="Cart cannot be empty",
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

    now = _utc_now()
    order_id = UUID(int=0)
    order_number = f"OF-{now:%y%m%d}-{now:%H%M%S%f}"[:22]

    order = Order(
        retailer_id=retailer.id,
        created_by_user_id=current_user.id,
        order_number=order_number,
        status="pending_review",
        subtotal=quote.subtotal,
        discount_total=quote.discount_total,
        free_quantity=quote.free_quantity,
        free_value=quote.free_value,
        total_amount=quote.total,
        note=None,
        updated_at=now,
    )

    session.add(order)
    session.flush()

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

    session.commit()
    session.refresh(order)

    return _order_to_response(session, order)


@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer", "order_desk")),
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
        Depends(require_roles("retailer", "order_desk")),
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

    order = session.execute(query).scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return _order_to_response(session, order)


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
        Depends(require_roles("order_desk")),
    ],
) -> DemoOrder:
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

    order.status = action_statuses[request.action]
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
        session.execute(delete(OrderItem))
        session.execute(delete(Order))
        session.commit()