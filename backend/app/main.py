import os

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import get_current_user
from app.ai_capture import router as ai_capture_router
from app.cart import router as cart_router
from app.catalogue import router as catalogue_router
from app.models import User
from app.orders import router as orders_router

app = FastAPI(title="OrderFlow API", version="0.1.0")

allowed_origins = os.getenv(
    "ORDERFLOW_CORS_ORIGINS",
    "http://localhost:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(catalogue_router)
app.include_router(cart_router)
app.include_router(ai_capture_router)
app.include_router(orders_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/me")
def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str | None]:
    return {
        "id": str(current_user.id),
        "role": current_user.role,
        "retailer_id": (
            str(current_user.retailer_id) if current_user.retailer_id else None
        ),
    }