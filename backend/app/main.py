import os
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_cors_origins, load_environment

# Ensure backend environment is loaded before any other initialization
load_environment()

from app.auth import get_current_user, router as auth_router
from app.ai_capture import router as ai_capture_router
from app.cart import router as cart_router
from app.catalogue import router as catalogue_router
from app.credit import router as credit_router
from app.database import get_db_session, get_engine
from app.inventory import router as inventory_router
from app.models import Salesman, User
from app.orders import router as orders_router
from app.salesman import router as salesman_router
from sqlalchemy import select
from sqlalchemy.orm import Session

app = FastAPI(title="OrderFlow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(catalogue_router)
app.include_router(cart_router)
app.include_router(ai_capture_router)
app.include_router(credit_router)
app.include_router(orders_router)
app.include_router(inventory_router)
app.include_router(salesman_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def get_profile_db_session() -> Generator[Session | None, None, None]:
    if get_db_session in app.dependency_overrides:
        override = app.dependency_overrides[get_db_session]
        gen = override()
        if hasattr(gen, "__enter__"):
            with gen as s:
                yield s
                return
        elif hasattr(gen, "__next__"):
            try:
                s = next(gen)
                yield s
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass
            return
        else:
            yield gen
            return
    try:
        engine = get_engine()
        with Session(engine) as session:
            yield session
    except RuntimeError:
        yield None


@app.get("/auth/me")
def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session | None, Depends(get_profile_db_session)],
) -> dict[str, str | None]:
    profile: dict[str, str | None] = {
        "id": str(current_user.id),
        "role": current_user.role,
        "retailer_id": (
            str(current_user.retailer_id) if current_user.retailer_id else None
        ),
    }
    if current_user.role == "salesman" and session is not None:
        s = session.scalar(select(Salesman).where(Salesman.user_id == current_user.id))
        profile["salesman_id"] = str(s.id) if s else None
        profile["salesman_name"] = s.display_name if s else None

    return profile
