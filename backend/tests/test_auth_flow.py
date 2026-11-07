from decimal import Decimal
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    get_current_user,
    get_supabase_subject,
    require_roles,
)
from app.main import app
from app.models import Product, Retailer, RetailerPrice, User
from app.orders import clear_demo_orders

client = TestClient(app)


def test_get_supabase_subject_requires_supabase_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        get_supabase_subject("any-token")
    assert exc_info.value.status_code == 503
    assert "not configured" in exc_info.value.detail


def test_get_supabase_subject_rejects_invalid_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    with pytest.raises(HTTPException) as exc_info:
        get_supabase_subject("malformed.jwt.token")
    assert exc_info.value.status_code == 401
    assert "Invalid access token" in exc_info.value.detail


def test_get_current_user_requires_credentials(seeded_database) -> None:
    with Session(seeded_database) as session:
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(None, session)
        assert exc_info.value.status_code == 401
        assert "Bearer token required" in exc_info.value.detail


def test_get_current_user_rejects_unlinked_profile(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "unknown-supabase-uuid-999",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    with Session(seeded_database) as session:
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(creds, session)
        assert exc_info.value.status_code == 403
        assert "No active OrderFlow profile is linked" in exc_info.value.detail


def test_get_current_user_rejects_inactive_user(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(seeded_database) as session:
        inactive_user = User(
            auth_subject="inactive-user-subject",
            role="retailer",
            is_active=False,
        )
        session.add(inactive_user)
        session.commit()

    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "inactive-user-subject",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    with Session(seeded_database) as session:
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(creds, session)
        assert exc_info.value.status_code == 403


def test_get_current_user_returns_active_user(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "demo-retailer-user",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    with Session(seeded_database) as session:
        user = get_current_user(creds, session)
        assert user.auth_subject == "demo-retailer-user"
        assert user.role == "retailer"


def test_require_roles_enforces_allowed_roles() -> None:
    retailer_user = User(
        auth_subject="sub1",
        role="retailer",
        is_active=True,
    )
    guard = require_roles("order_desk")
    with pytest.raises(HTTPException) as exc_info:
        guard(retailer_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient role"

    desk_guard = require_roles("retailer", "order_desk")
    assert desk_guard(retailer_user) == retailer_user


@pytest.fixture
def mock_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_subject(token: str) -> str:
        if token == "retailer-token":
            return "demo-retailer-user"
        if token == "second-retailer-token":
            return "second-demo-retailer-user"
        if token == "order-desk-token":
            return "demo-order-desk-user"
        if token == "unlinked-token":
            return "nonexistent-auth-sub"
        raise HTTPException(status_code=401, detail="Invalid access token")

    monkeypatch.setattr("app.auth.get_supabase_subject", fake_get_subject)


def test_auth_me_endpoint(seeded_database, mock_auth: None) -> None:
    # 1. Missing token -> 401
    resp_no_token = client.get("/auth/me")
    assert resp_no_token.status_code == 401

    # 2. Invalid token -> 401
    resp_bad_token = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp_bad_token.status_code == 401

    # 3. Unlinked user -> 403
    resp_unlinked = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer unlinked-token"},
    )
    assert resp_unlinked.status_code == 403

    # 4. Valid retailer token -> 200 with role and retailer_id
    resp_retailer = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp_retailer.status_code == 200
    data = resp_retailer.json()
    assert data["role"] == "retailer"
    assert data["retailer_id"] is not None

    # 5. Valid order desk token -> 200 with role 'order_desk'
    resp_desk = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp_desk.status_code == 200
    assert resp_desk.json()["role"] == "order_desk"


def test_role_restrictions_on_catalogue_and_orders(
    seeded_database,
    mock_auth: None,
) -> None:
    # Retailer can access catalogue
    resp = client.get(
        "/catalogue",
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp.status_code == 200

    # Order Desk cannot access catalogue (role restriction)
    resp = client.get(
        "/catalogue",
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Insufficient role"

    # Order Desk cannot place retailer orders
    resp = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Insufficient role"


def test_retailer_order_isolation_and_order_desk_review(
    seeded_database,
    mock_auth: None,
) -> None:
    clear_demo_orders(seeded_database)

    # Seed price for second retailer so they can place an order
    with Session(seeded_database) as session:
        second_retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER-2")
        )
        dp_product = session.scalar(
            select(Product).where(Product.sku == "SKU-DP-1KG")
        )
        assert second_retailer is not None
        assert dp_product is not None
        session.add(
            RetailerPrice(
                retailer_id=second_retailer.id,
                product_id=dp_product.id,
                unit_price=Decimal("2030.00"),
            )
        )
        session.commit()

    # 1. Retailer 1 places an order
    resp1 = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp1.status_code == 201
    order1 = resp1.json()

    # 2. Retailer 2 places an order
    resp2 = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-DP-1KG", "quantity": 5}]},
        headers={"Authorization": "Bearer second-retailer-token"},
    )
    assert resp2.status_code == 201
    order2 = resp2.json()

    # 3. Retailer 1 lists orders: should only see Order 1
    resp_r1_list = client.get(
        "/orders",
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp_r1_list.status_code == 200
    r1_ids = [o["id"] for o in resp_r1_list.json()["orders"]]
    assert order1["id"] in r1_ids
    assert order2["id"] not in r1_ids

    # 4. Retailer 1 attempts to access Retailer 2's order directly: blocked with 404
    resp_cross = client.get(
        f"/orders/{order2['id']}",
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp_cross.status_code == 404

    # 5. Retailer cannot approve or reject orders
    resp_illegal_decision = client.patch(
        f"/orders/{order1['id']}/decision",
        json={"action": "approve"},
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp_illegal_decision.status_code == 403

    # 6. Retailer cannot download Tally CSV
    resp_illegal_csv = client.get(
        f"/orders/{order1['id']}/tally.csv",
        headers={"Authorization": "Bearer retailer-token"},
    )
    assert resp_illegal_csv.status_code == 403

    # 7. Order Desk sees all orders
    resp_desk_list = client.get(
        "/orders",
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp_desk_list.status_code == 200
    desk_ids = [o["id"] for o in resp_desk_list.json()["orders"]]
    assert order1["id"] in desk_ids
    assert order2["id"] in desk_ids

    # 8. Order Desk approves Order 1
    resp_approve = client.patch(
        f"/orders/{order1['id']}/decision",
        json={"action": "approve", "note": "Verified by distributor"},
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "approved"

    # 9. Order Desk downloads Tally CSV for approved order
    resp_csv = client.get(
        f"/orders/{order1['id']}/tally.csv",
        headers={"Authorization": "Bearer order-desk-token"},
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert order1["order_number"] in resp_csv.text

    clear_demo_orders(seeded_database)
