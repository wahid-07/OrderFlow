"""Retailer Credit Management API for OrderFlow Phase 4."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.database import get_db_session
from app.models import Order, Retailer, User

router = APIRouter()


class RetailerCreditResponse(BaseModel):
    retailer_id: str
    retailer_name: str
    credit_limit: Decimal
    current_outstanding: Decimal
    available_credit: Decimal
    pending_orders_total: Decimal
    effective_available_credit: Decimal
    credit_utilization_percent: Decimal


class RetailerCreditUpdateRequest(BaseModel):
    credit_limit: Decimal | None = Field(default=None)
    current_outstanding: Decimal | None = Field(default=None)


def calculate_retailer_credit_summary(
    session: Session, retailer: Retailer
) -> RetailerCreditResponse:
    """Calculate complete retailer credit overview with uncommitted pending orders."""
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
    available = limit - outstanding
    effective_available = available - pending_total

    if limit > Decimal("0.00"):
        utilization = ((outstanding / limit) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        utilization = (
            Decimal("100.00") if outstanding > Decimal("0.00") else Decimal("0.00")
        )

    return RetailerCreditResponse(
        retailer_id=str(retailer.id),
        retailer_name=retailer.name,
        credit_limit=limit,
        current_outstanding=outstanding,
        available_credit=available,
        pending_orders_total=pending_total,
        effective_available_credit=effective_available,
        credit_utilization_percent=utilization,
    )


@router.get("/retailer/credit", response_model=RetailerCreditResponse)
def get_current_retailer_credit(
    current_user: Annotated[User, Depends(require_roles("retailer"))],
    session: Annotated[Session, Depends(get_db_session)],
) -> RetailerCreditResponse:
    """Retailer views their own credit information."""
    if current_user.retailer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a retailer entity",
        )

    retailer = session.get(Retailer, current_user.retailer_id)
    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retailer account not found or inactive",
        )

    return calculate_retailer_credit_summary(session, retailer)


@router.get(
    "/retailers/{retailer_id}/credit", response_model=RetailerCreditResponse
)
def get_retailer_credit(
    retailer_id: str,
    current_user: Annotated[
        User,
        Depends(
            require_roles(
                "retailer", "order_desk", "distributor_admin", "super_admin"
            )
        ),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> RetailerCreditResponse:
    """View retailer credit info with strict cross-retailer access isolation."""
    try:
        retailer_uuid = UUID(retailer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid retailer ID format",
        )

    # Retailer can only view their own credit
    if current_user.role == "retailer":
        if current_user.retailer_id != retailer_uuid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Retailers are not authorized to view other retailers' credit information",
            )

    retailer = session.get(Retailer, retailer_uuid)
    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retailer not found",
        )

    return calculate_retailer_credit_summary(session, retailer)


@router.patch(
    "/retailers/{retailer_id}/credit", response_model=RetailerCreditResponse
)
def update_retailer_credit(
    retailer_id: str,
    payload: RetailerCreditUpdateRequest,
    current_user: Annotated[
        User,
        Depends(
            require_roles("order_desk", "distributor_admin", "super_admin")
        ),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> RetailerCreditResponse:
    """Order Desk and Admin update credit limit or outstanding balance."""
    try:
        retailer_uuid = UUID(retailer_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid retailer ID format",
        )

    if payload.credit_limit is None and payload.current_outstanding is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of credit_limit or current_outstanding must be provided",
        )

    if payload.credit_limit is not None and payload.credit_limit < Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credit_limit cannot be negative",
        )

    if (
        payload.current_outstanding is not None
        and payload.current_outstanding < Decimal("0.00")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current_outstanding cannot be negative",
        )

    retailer = session.execute(
        select(Retailer).where(Retailer.id == retailer_uuid).with_for_update()
    ).scalar_one_or_none()

    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retailer not found",
        )

    if payload.credit_limit is not None:
        retailer.credit_limit = payload.credit_limit

    if payload.current_outstanding is not None:
        retailer.current_outstanding = payload.current_outstanding

    session.commit()
    session.refresh(retailer)

    return calculate_retailer_credit_summary(session, retailer)

