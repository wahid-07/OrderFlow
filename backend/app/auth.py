import os
import re
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Callable
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWKClientError, PyJWTError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_supabase_url
from app.database import get_db_session
from app.models import Product, Retailer, RetailerPrice, User

bearer_scheme = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    issuer = f"{supabase_url.rstrip('/')}/auth/v1"
    return PyJWKClient(f"{issuer}/.well-known/jwks.json")


def get_supabase_claims(access_token: str) -> dict[str, Any]:
    supabase_url = get_supabase_url()
    if not supabase_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication is not configured",
        )

    issuer = f"{supabase_url.rstrip('/')}/auth/v1"
    try:
        signing_key = _jwks_client(supabase_url).get_signing_key_from_jwt(access_token)
        claims = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except (PyJWKClientError, PyJWTError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def get_supabase_subject(access_token: str) -> str:
    claims = get_supabase_claims(access_token)
    return str(claims["sub"])


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = get_supabase_subject(credentials.credentials)
    user = session.scalar(
        select(User).where(
            User.auth_subject == subject,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active OrderFlow profile is linked to this account",
        )
    return user


def require_roles(*allowed_roles: str) -> Callable[..., User]:
    def role_guard(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return current_user

    return role_guard


class RetailerRegisterRequest(BaseModel):
    shop_name: str = Field(min_length=2, max_length=200)
    owner_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=10, max_length=20)
    address: str = Field(min_length=5, max_length=500)
    email: str | None = Field(default=None, max_length=320)

    @field_validator("shop_name", "owner_name", "address")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Field cannot be empty or blank")
        return clean

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        clean = value.strip()
        digits = re.sub(r"\D", "", clean)
        if len(digits) < 10 or len(digits) > 13:
            raise ValueError("Mobile number must contain 10 to 13 digits")
        return clean

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format")
        return clean.lower()


class RegisterResponse(BaseModel):
    message: str = "Retailer registered successfully"
    id: str
    role: str
    retailer_id: str
    shop_name: str


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_retailer(
    payload: RetailerRegisterRequest,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> RegisterResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required for registration",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Verify Supabase JWT & extract verified UID
    subject = get_supabase_subject(credentials.credentials)

    # 2. Check if this Supabase UID is already registered
    existing_by_subject = session.scalar(
        select(User).where(User.auth_subject == subject)
    )
    if existing_by_subject is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account is already registered for this Supabase user",
        )

    # 3. Check if email is already taken
    email = payload.email
    if not email:
        try:
            claims = get_supabase_claims(credentials.credentials)
            token_email = claims.get("email")
            if isinstance(token_email, str) and token_email:
                email = token_email.lower().strip()
        except Exception:
            pass

    if email:
        existing_by_email = session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )
        if existing_by_email is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email address already exists",
            )

    # 4. Create Retailer & User inside a transaction
    external_ref = f"RET-{uuid4().hex[:8].upper()}"
    retailer = Retailer(
        name=payload.shop_name,
        external_ref=external_ref,
        phone=payload.phone,
        contact_person=payload.owner_name,
        address=payload.address,
        is_active=True,
    )
    session.add(retailer)
    session.flush()

    # Server exclusively enforces 'retailer' role
    user = User(
        auth_subject=subject,
        role="retailer",
        email=email,
        phone=payload.phone,
        retailer_id=retailer.id,
        is_active=True,
    )
    session.add(user)
    session.flush()

    # 5. Populate standard prices for all active products
    active_products = list(
        session.scalars(select(Product).where(Product.is_active.is_(True)))
    )
    if active_products:
        existing_prices = {
            rp.product_id: rp.unit_price
            for rp in session.scalars(
                select(RetailerPrice).order_by(RetailerPrice.created_at.desc())
            )
        }
        for prod in active_products:
            standard_price = existing_prices.get(prod.id, Decimal("500.00"))
            session.add(
                RetailerPrice(
                    retailer_id=retailer.id,
                    product_id=prod.id,
                    unit_price=standard_price,
                )
            )

    session.commit()

    return RegisterResponse(
        id=str(user.id),
        role=user.role,
        retailer_id=str(retailer.id),
        shop_name=retailer.name,
    )
