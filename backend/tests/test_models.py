import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth
from app.models import Base, Product, Retailer, User


def test_core_schema_creates_and_enforces_unique_auth_subject() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {
        "users",
        "retailers",
        "salesmen",
        "products",
        "retailer_prices",
        "schemes",
        "orders",
        "order_items",
        "ai_captures",
        "sku_aliases",
    } <= table_names

    with Session(engine) as session:
        retailer = Retailer(name="Example retailer")
        session.add(retailer)
        session.flush()

        session.add_all(
            [
                User(
                    auth_subject="supabase-user-1",
                    role="retailer",
                    retailer_id=retailer.id,
                ),
                Product(sku="SKU-1", name="Example product"),
            ]
        )
        session.commit()

        session.add(User(auth_subject="supabase-user-1", role="retailer"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_supabase_auth_requires_project_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from app.auth import get_supabase_subject

    monkeypatch.delenv("SUPABASE_URL", raising=False)

    with pytest.raises(HTTPException) as error:
        get_supabase_subject("not-a-token")

    assert error.value.status_code == 503


def test_supabase_subject_verifies_signature_issuer_and_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    supabase_url = "https://orderflow-test.supabase.co"
    issuer = f"{supabase_url}/auth/v1"

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
            return SimpleNamespace(key=public_key)

    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setattr(auth, "_jwks_client", lambda _: FakeJwksClient())

    def create_token(audience: str, include_expiration: bool = True) -> str:
        claims = {
            "sub": "supabase-user-1",
            "iss": issuer,
            "aud": audience,
        }
        if include_expiration:
            claims["exp"] = datetime.now(timezone.utc) + timedelta(minutes=5)
        return jwt.encode(claims, private_key, algorithm="RS256")

    assert auth.get_supabase_subject(create_token("authenticated")) == "supabase-user-1"

    with pytest.raises(HTTPException) as error:
        auth.get_supabase_subject(create_token("anon"))

    assert error.value.status_code == 401

    with pytest.raises(HTTPException) as error:
        auth.get_supabase_subject(create_token("authenticated", include_expiration=False))

    assert error.value.status_code == 401