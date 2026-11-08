import pytest

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import uuid4
from decimal import Decimal

from fastapi.testclient import TestClient

from app import ai_capture
from app.auth import get_current_user
from app.main import app
from app.models import User

client = TestClient(app)
@pytest.fixture
def authenticated_retailer(seeded_database):
    with Session(seeded_database) as session:
        user = session.scalar(
            select(User).where(
                User.auth_subject == "demo-retailer-user"
            )
        )

        assert user is not None
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user

    yield

    app.dependency_overrides.pop(get_current_user, None)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cart_quote_applies_database_scheme_rules(
    seeded_database,
    authenticated_retailer,
) -> None:
    response = client.post(
        "/cart/quote",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 25},
                {"sku": "SKU-DP-1KG", "quantity": 5},
                {"sku": "SKU-TL-250", "quantity": 1},
            ]
        },
    )

    assert response.status_code == 200
    quote = response.json()
    assert quote["source"] == "database"
    assert quote["subtotal"] == "34310.00"
    assert quote["discount_total"] == "304.50"
    assert quote["free_quantity"] == 2
    assert quote["total"] == "34005.50"

    lines_by_sku = {line["sku"]: line for line in quote["lines"]}
    assert lines_by_sku["SKU-BS-075"]["delivered_quantity"] == 27
    assert lines_by_sku["SKU-DP-1KG"]["total"] == "9845.50"


def test_cart_quote_rejects_unknown_sku(
    seeded_database,
    authenticated_retailer,
) -> None:
    response = client.post(
        "/cart/quote",
        json={"items": [{"sku": "unknown", "quantity": 1}]},
    )

    assert response.status_code == 404


def test_demo_capture_matches_example_and_requires_human_review(
    monkeypatch,
    seeded_database,
    authenticated_retailer,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/ai/order-captures",
        json={
            "raw_text": (
                "bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, "
                "chai patti 250 wala 1 peti"
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["source"] == "demo_parser"
    assert result["review_required"] is True
    assert result["order_placed"] is False
    assert [line["matched_sku"] for line in result["lines"]] == [
        "SKU-BS-075",
        "SKU-DP-1KG",
        "SKU-TL-250",
    ]
    assert [Decimal(str(line["quantity"])) for line in result["lines"]] == [
        Decimal("5"),
        Decimal("2"),
        Decimal("1"),
    ]
    assert all(line["unit"] == "case" for line in result["lines"])
    assert all(not line["needs_clarification"] for line in result["lines"])


def test_demo_capture_asks_about_missing_unit_instead_of_guessing(
    monkeypatch,
    seeded_database,
    authenticated_retailer,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/ai/order-captures",
        json={"raw_text": "5 biscuit"},
    )

    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["quantity"] == "5"
    assert line["unit"] == "unknown"
    assert line["needs_clarification"] is True
    assert line["clarification_question"] == 'How should we interpret "5 biscuit"?'
    assert line["clarification_options"] == ["piece", "case"]
    assert response.json()["order_placed"] is False


def test_gemini_capture_requires_authentication_and_filters_unknown_skus(
    monkeypatch,
    seeded_database,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "configured-server-side")
    unauthenticated = client.post(
        "/ai/order-captures",
        json={"raw_text": "5 peti biscuit"},
    )
    assert unauthenticated.status_code == 401

    with Session(seeded_database) as session:
        user = session.scalar(
            select(User).where(User.auth_subject == "demo-retailer-user")
        )
        assert user is not None
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini",
            lambda *args, **kwargs: ai_capture.GeminiOrderResult(
                lines=[
                    ai_capture.GeminiOrderLine(
                        line_index=0,
                        quantity=Decimal("5"),
                        candidates=[
                            ai_capture.GeminiCandidate(sku="invented-sku", confidence=0.99),
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.82),
                        ],
                    )
                ]
            ),
        )
        authenticated = client.post(
            "/ai/order-captures",
            json={"raw_text": "5 peti biscuit"},
        )

        assert authenticated.status_code == 200
        result = authenticated.json()
        assert result["source"] == "gemini"
        assert result["lines"][0]["matched_sku"] == "SKU-BS-075"
        assert [candidate["sku"] for candidate in result["lines"][0]["candidates"]] == [
            "SKU-BS-075"
        ]
        assert result["order_placed"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_auth_profile_uses_local_user_role() -> None:
    user = User(
        id=uuid4(),
        auth_subject="supabase-subject",
        role="retailer",
    )
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = client.get("/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "role": "retailer",
        "retailer_id": None,
    }