"""Salesman management, retailer assignments, and visit notes router for Phase 6."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.database import get_db_session
from app.models import Retailer, Salesman, SalesmanRetailerAssignment, SalesmanVisitNote, User
from app.supabase_admin import provision_supabase_salesman, rollback_supabase_salesman

router = APIRouter(tags=["salesman"])


class SalesmanItemResponse(BaseModel):
    id: str
    user_id: str
    display_name: str
    phone: str | None
    is_active: bool
    assigned_retailers_count: int
    created_at: datetime
    invitation_link: str | None = None


class CreateSalesmanRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    auth_subject: str | None = Field(default=None, max_length=255, description="Supabase auth subject or username if pre-created")
    password: str | None = Field(default=None, min_length=6, max_length=128, description="Initial temporary password if provisioning via Supabase Admin")


class UpdateSalesmanRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None


class AssignRetailerRequest(BaseModel):
    retailer_id: UUID


class AssignedRetailerResponse(BaseModel):
    id: str
    name: str
    external_ref: str | None
    phone: str | None
    contact_person: str | None
    address: str | None
    credit_limit: str
    current_outstanding: str
    available_credit: str


class CreateVisitNoteRequest(BaseModel):
    retailer_id: UUID
    note: str = Field(min_length=2, max_length=1000)


class VisitNoteResponse(BaseModel):
    id: str
    salesman_id: str
    retailer_id: str
    retailer_name: str
    note: str
    created_at: datetime


def get_current_salesman(
    current_user: Annotated[User, Depends(require_roles("salesman"))],
    session: Annotated[Session, Depends(get_db_session)],
) -> Salesman:
    salesman = session.scalar(
        select(Salesman).where(
            Salesman.user_id == current_user.id,
            Salesman.is_active.is_(True),
        )
    )
    if salesman is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active salesman profile not found for this user account",
        )
    return salesman


# =====================================================================
# 1. Order Desk / Admin Salesman Management Endpoints
# =====================================================================


@router.get("/salesmen", response_model=list[SalesmanItemResponse])
def list_salesmen(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> list[SalesmanItemResponse]:
    """List all salesmen and their assigned retailer counts."""
    rows = session.execute(
        select(
            Salesman,
            func.count(SalesmanRetailerAssignment.id).label("assigned_count"),
        )
        .outerjoin(
            SalesmanRetailerAssignment,
            (SalesmanRetailerAssignment.salesman_id == Salesman.id)
            & (SalesmanRetailerAssignment.is_active.is_(True)),
        )
        .group_by(Salesman.id)
        .order_by(Salesman.display_name)
    ).all()

    return [
        SalesmanItemResponse(
            id=str(s.id),
            user_id=str(s.user_id),
            display_name=s.display_name,
            phone=s.phone,
            is_active=s.is_active,
            assigned_retailers_count=count,
            created_at=s.created_at,
        )
        for s, count in rows
    ]


@router.post("/salesmen", response_model=SalesmanItemResponse, status_code=status.HTTP_201_CREATED)
def create_salesman(
    payload: CreateSalesmanRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> SalesmanItemResponse:
    """Provision a new salesman account and user profile."""
    clean_email = payload.email.strip().lower() if payload.email and payload.email.strip() else None
    if clean_email:
        existing_email = session.scalar(
            select(User).where(func.lower(User.email) == clean_email)
        )
        if existing_email is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A user with email '{clean_email}' already exists",
            )

    clean_auth_subject = payload.auth_subject.strip() if payload.auth_subject and payload.auth_subject.strip() else None
    if clean_auth_subject:
        existing_user = session.scalar(
            select(User).where(User.auth_subject == clean_auth_subject)
        )
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this auth subject already exists",
            )

    # 1. Provision via Supabase Auth Admin API (if configured) or generate secure auth_subject
    auth_subject, created_remotely, invitation_link = provision_supabase_salesman(
        email=clean_email,
        display_name=payload.display_name,
        phone=payload.phone,
        password=payload.password,
        auth_subject=clean_auth_subject,
    )

    # 2. Persist local User and Salesman records
    user = User(
        auth_subject=auth_subject,
        role="salesman",
        email=clean_email,
        phone=payload.phone.strip() if payload.phone else None,
        retailer_id=None,
        is_active=True,
    )
    session.add(user)
    session.flush()

    salesman = Salesman(
        user_id=user.id,
        display_name=payload.display_name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        is_active=True,
    )
    session.add(salesman)

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        # Compensation: clean up the newly created remote Supabase user if local DB commit failed
        if created_remotely:
            rollback_supabase_salesman(auth_subject)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict creating salesman profile. Rolled back authentication state.",
        ) from exc

    session.refresh(salesman)

    return SalesmanItemResponse(
        id=str(salesman.id),
        user_id=str(salesman.user_id),
        display_name=salesman.display_name,
        phone=salesman.phone,
        is_active=salesman.is_active,
        assigned_retailers_count=0,
        created_at=salesman.created_at,
        invitation_link=invitation_link,
    )


@router.patch("/salesmen/{salesman_id}", response_model=SalesmanItemResponse)
def update_salesman(
    salesman_id: UUID,
    payload: UpdateSalesmanRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> SalesmanItemResponse:
    """Update or activate/deactivate a salesman profile."""
    salesman = session.get(Salesman, salesman_id)
    if salesman is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Salesman profile not found",
        )

    if payload.display_name is not None:
        salesman.display_name = payload.display_name.strip()
    if payload.phone is not None:
        salesman.phone = payload.phone.strip() or None
    if payload.is_active is not None:
        salesman.is_active = payload.is_active
        # Also sync User.is_active
        user = session.get(User, salesman.user_id)
        if user:
            user.is_active = payload.is_active

    session.commit()
    session.refresh(salesman)

    count = session.scalar(
        select(func.count(SalesmanRetailerAssignment.id)).where(
            SalesmanRetailerAssignment.salesman_id == salesman.id,
            SalesmanRetailerAssignment.is_active.is_(True),
        )
    ) or 0

    return SalesmanItemResponse(
        id=str(salesman.id),
        user_id=str(salesman.user_id),
        display_name=salesman.display_name,
        phone=salesman.phone,
        is_active=salesman.is_active,
        assigned_retailers_count=count,
        created_at=salesman.created_at,
    )


@router.get("/salesmen/{salesman_id}/retailers", response_model=list[AssignedRetailerResponse])
def get_salesman_assigned_retailers(
    salesman_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> list[AssignedRetailerResponse]:
    """List retailers assigned to a specific salesman."""
    salesman = session.get(Salesman, salesman_id)
    if salesman is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Salesman profile not found",
        )

    rows = session.execute(
        select(Retailer)
        .join(
            SalesmanRetailerAssignment,
            SalesmanRetailerAssignment.retailer_id == Retailer.id,
        )
        .where(
            SalesmanRetailerAssignment.salesman_id == salesman.id,
            SalesmanRetailerAssignment.is_active.is_(True),
            Retailer.is_active.is_(True),
        )
        .order_by(Retailer.name)
    ).scalars().all()

    return [
        AssignedRetailerResponse(
            id=str(r.id),
            name=r.name,
            external_ref=r.external_ref,
            phone=r.phone,
            contact_person=r.contact_person,
            address=r.address,
            credit_limit=f"{r.credit_limit:.2f}",
            current_outstanding=f"{r.current_outstanding:.2f}",
            available_credit=f"{r.available_credit:.2f}",
        )
        for r in rows
    ]


@router.post(
    "/salesmen/{salesman_id}/retailers",
    response_model=AssignedRetailerResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_retailer_to_salesman(
    salesman_id: UUID,
    payload: AssignRetailerRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> AssignedRetailerResponse:
    """Assign a retailer to a salesman."""
    salesman = session.get(Salesman, salesman_id)
    if salesman is None or not salesman.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active salesman profile not found",
        )

    retailer = session.get(Retailer, payload.retailer_id)
    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active retailer not found",
        )

    existing = session.scalar(
        select(SalesmanRetailerAssignment).where(
            SalesmanRetailerAssignment.salesman_id == salesman.id,
            SalesmanRetailerAssignment.retailer_id == retailer.id,
        )
    )

    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Retailer is already assigned to this salesman",
            )
        existing.is_active = True
        existing.assigned_by_user_id = current_user.id
    else:
        assignment = SalesmanRetailerAssignment(
            salesman_id=salesman.id,
            retailer_id=retailer.id,
            is_active=True,
            assigned_by_user_id=current_user.id,
        )
        session.add(assignment)

    session.commit()

    return AssignedRetailerResponse(
        id=str(retailer.id),
        name=retailer.name,
        external_ref=retailer.external_ref,
        phone=retailer.phone,
        contact_person=retailer.contact_person,
        address=retailer.address,
        credit_limit=f"{retailer.credit_limit:.2f}",
        current_outstanding=f"{retailer.current_outstanding:.2f}",
        available_credit=f"{retailer.available_credit:.2f}",
    )


@router.delete(
    "/salesmen/{salesman_id}/retailers/{retailer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_retailer_assignment(
    salesman_id: UUID,
    retailer_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("order_desk", "distributor_admin", "super_admin")),
    ],
) -> None:
    """Remove a retailer assignment from a salesman."""
    assignment = session.scalar(
        select(SalesmanRetailerAssignment).where(
            SalesmanRetailerAssignment.salesman_id == salesman_id,
            SalesmanRetailerAssignment.retailer_id == retailer_id,
            SalesmanRetailerAssignment.is_active.is_(True),
        )
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active assignment not found",
        )

    assignment.is_active = False
    session.commit()


# =====================================================================
# 2. Authenticated Salesman Workspace Endpoints
# =====================================================================


@router.get("/salesman/assigned-retailers", response_model=list[AssignedRetailerResponse])
def get_my_assigned_retailers(
    salesman: Annotated[Salesman, Depends(get_current_salesman)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[AssignedRetailerResponse]:
    """Authenticated salesman retrieves their assigned active retailers."""
    rows = session.execute(
        select(Retailer)
        .join(
            SalesmanRetailerAssignment,
            SalesmanRetailerAssignment.retailer_id == Retailer.id,
        )
        .where(
            SalesmanRetailerAssignment.salesman_id == salesman.id,
            SalesmanRetailerAssignment.is_active.is_(True),
            Retailer.is_active.is_(True),
        )
        .order_by(Retailer.name)
    ).scalars().all()

    return [
        AssignedRetailerResponse(
            id=str(r.id),
            name=r.name,
            external_ref=r.external_ref,
            phone=r.phone,
            contact_person=r.contact_person,
            address=r.address,
            credit_limit=f"{r.credit_limit:.2f}",
            current_outstanding=f"{r.current_outstanding:.2f}",
            available_credit=f"{r.available_credit:.2f}",
        )
        for r in rows
    ]


@router.post("/salesman/visit-notes", response_model=VisitNoteResponse, status_code=status.HTTP_201_CREATED)
def create_visit_note(
    payload: CreateVisitNoteRequest,
    salesman: Annotated[Salesman, Depends(get_current_salesman)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> VisitNoteResponse:
    """Salesman logs a field visit note for an assigned retailer."""
    # Verify salesman is assigned to this retailer
    assignment = session.scalar(
        select(SalesmanRetailerAssignment).where(
            SalesmanRetailerAssignment.salesman_id == salesman.id,
            SalesmanRetailerAssignment.retailer_id == payload.retailer_id,
            SalesmanRetailerAssignment.is_active.is_(True),
        )
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this retailer",
        )

    retailer = session.get(Retailer, payload.retailer_id)
    if retailer is None or not retailer.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active retailer not found",
        )

    note = SalesmanVisitNote(
        salesman_id=salesman.id,
        retailer_id=retailer.id,
        note=payload.note.strip(),
        created_by_user_id=current_user.id,
    )
    session.add(note)
    session.commit()
    session.refresh(note)

    return VisitNoteResponse(
        id=str(note.id),
        salesman_id=str(note.salesman_id),
        retailer_id=str(note.retailer_id),
        retailer_name=retailer.name,
        note=note.note,
        created_at=note.created_at,
    )


@router.get("/salesman/visit-notes", response_model=list[VisitNoteResponse])
def list_visit_notes(
    retailer_id: UUID | None = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    session: Annotated[Session, Depends(get_db_session)] = None,
) -> list[VisitNoteResponse]:
    """List visit notes for assigned retailers (Salesman) or all (Order Desk)."""
    query = (
        select(SalesmanVisitNote, Retailer.name)
        .join(Retailer, Retailer.id == SalesmanVisitNote.retailer_id)
        .order_by(SalesmanVisitNote.created_at.desc())
    )

    if current_user.role == "salesman":
        salesman = session.scalar(
            select(Salesman).where(
                Salesman.user_id == current_user.id,
                Salesman.is_active.is_(True),
            )
        )
        if not salesman:
            raise HTTPException(status_code=403, detail="Active salesman not found")
        query = query.where(SalesmanVisitNote.salesman_id == salesman.id)
    elif current_user.role not in ("order_desk", "distributor_admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient role")

    if retailer_id:
        query = query.where(SalesmanVisitNote.retailer_id == retailer_id)

    rows = session.execute(query).all()
    return [
        VisitNoteResponse(
            id=str(n.id),
            salesman_id=str(n.salesman_id),
            retailer_id=str(n.retailer_id),
            retailer_name=name,
            note=n.note,
            created_at=n.created_at,
        )
        for n, name in rows
    ]

