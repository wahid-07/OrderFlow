import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import Product, Retailer, RetailerPrice, User

client = TestClient(app)


def test_registration_requires_bearer_token(seeded_database) -> None:
    response = client.post(
        "/auth/register",
        json={
            "shop_name": "New Kirana Store",
            "owner_name": "Rajesh Kumar",
            "phone": "9876543210",
            "address": "123 Market Street, Jaipur",
            "email": "rajesh@example.com",
        },
    )
    assert response.status_code == 401
    assert "Bearer token required" in response.json()["detail"]


def test_registration_rejects_invalid_token(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_subject(token: str) -> str:
        raise HTTPException(status_code=401, detail="Invalid access token")

    monkeypatch.setattr("app.auth.get_supabase_subject", fake_get_subject)

    response = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer bad-token"},
        json={
            "shop_name": "New Kirana Store",
            "owner_name": "Rajesh Kumar",
            "phone": "9876543210",
            "address": "123 Market Street, Jaipur",
            "email": "rajesh@example.com",
        },
    )
    assert response.status_code == 401
    assert "Invalid access token" in response.json()["detail"]


def test_registration_successful_creates_retailer_and_user(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_sub = "new-supabase-user-uuid-101"
    monkeypatch.setattr("app.auth.get_supabase_subject", lambda token: new_sub)

    response = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer valid-new-token"},
        json={
            "shop_name": "Shree Ganesh Kirana",
            "owner_name": "Suresh Sharma",
            "phone": "9123456789",
            "address": "Shop 4, Gandhi Chowk, Alwar",
            "email": "suresh.kirana@example.com",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "retailer"
    assert payload["shop_name"] == "Shree Ganesh Kirana"
    assert payload["retailer_id"] is not None
    assert payload["id"] is not None

    # Verify database state
    with Session(seeded_database) as session:
        user = session.scalar(select(User).where(User.auth_subject == new_sub))
        assert user is not None
        assert user.role == "retailer"
        assert user.email == "suresh.kirana@example.com"
        assert user.phone == "9123456789"
        assert user.is_active is True

        retailer = session.scalar(select(Retailer).where(Retailer.id == user.retailer_id))
        assert retailer is not None
        assert retailer.name == "Shree Ganesh Kirana"
        assert retailer.contact_person == "Suresh Sharma"
        assert retailer.address == "Shop 4, Gandhi Chowk, Alwar"
        assert retailer.phone == "9123456789"
        assert retailer.is_active is True

        # Verify RetailerPrice entries were created for active products
        prices = list(
            session.scalars(
                select(RetailerPrice).where(RetailerPrice.retailer_id == retailer.id)
            )
        )
        assert len(prices) > 0


def test_registration_rejects_duplicate_supabase_subject(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 'demo-retailer-user' already exists in seeded database
    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "demo-retailer-user",
    )

    response = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer already-registered-token"},
        json={
            "shop_name": "Another Store",
            "owner_name": "Amit Kumar",
            "phone": "9876543211",
            "address": "Shop 2, Civil Lines",
            "email": "another@example.com",
        },
    )
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_registration_rejects_duplicate_email(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First, register a user
    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "user-alpha-uuid",
    )
    resp1 = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer token-alpha"},
        json={
            "shop_name": "Alpha Store",
            "owner_name": "Alpha Owner",
            "phone": "9988776655",
            "address": "Shop 1, Main Bazaar",
            "email": "duplicate@example.com",
        },
    )
    assert resp1.status_code == 201

    # Second user tries to use the same email
    monkeypatch.setattr(
        "app.auth.get_supabase_subject",
        lambda token: "user-beta-uuid",
    )
    resp2 = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer token-beta"},
        json={
            "shop_name": "Beta Store",
            "owner_name": "Beta Owner",
            "phone": "9988776644",
            "address": "Shop 2, Main Bazaar",
            "email": "DUPLICATE@EXAMPLE.COM",  # case-insensitive check
        },
    )
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"]


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_err"),
    [
        ("shop_name", "   ", "cannot be empty"),
        ("owner_name", " ", "cannot be empty"),
        ("phone", "12345", "10 to 13 digits"),
        ("address", "Apt", "at least 5 characters"),
        ("email", "not-an-email", "Invalid email format"),
    ],
)
def test_registration_validates_inputs(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: str,
    expected_err: str,
) -> None:
    monkeypatch.setattr("app.auth.get_supabase_subject", lambda token: "uid-valid-test")

    payload = {
        "shop_name": "Valid Store Name",
        "owner_name": "Valid Owner Name",
        "phone": "9876543210",
        "address": "Valid Shop Address 123",
        "email": "valid@example.com",
    }
    payload[field] = bad_value

    response = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer test-token"},
        json=payload,
    )
    assert response.status_code == 422


def test_registration_client_cannot_escalate_role(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = "role-escalation-test-uid"
    monkeypatch.setattr("app.auth.get_supabase_subject", lambda token: uid)

    # Attempting to supply role="order_desk" or role="admin"
    response = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer test-token"},
        json={
            "shop_name": "Hacker Store",
            "owner_name": "Hacker Person",
            "phone": "9876543210",
            "address": "Shop 99, Underground Street",
            "email": "hacker@example.com",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "retailer"

    with Session(seeded_database) as session:
        user = session.scalar(select(User).where(User.auth_subject == uid))
        assert user is not None
        assert user.role == "retailer"


def test_registered_retailer_can_immediately_access_catalogue(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = "immediate-catalogue-user-uid"
    monkeypatch.setattr("app.auth.get_supabase_subject", lambda token: uid)

    # 1. Register
    reg_resp = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer token-for-cat"},
        json={
            "shop_name": "Immediate Shop",
            "owner_name": "Owner Immediate",
            "phone": "9876543210",
            "address": "Shop 10, City Center",
            "email": "immediate@example.com",
        },
    )
    assert reg_resp.status_code == 201
    retailer_id = reg_resp.json()["retailer_id"]

    # 2. Query /auth/me
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer token-for-cat"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "retailer"
    assert me_resp.json()["retailer_id"] == retailer_id

    # 3. Query /catalogue
    cat_resp = client.get(
        "/catalogue",
        headers={"Authorization": "Bearer token-for-cat"},
    )
    assert cat_resp.status_code == 200
    cat_items = cat_resp.json()["items"]
    assert len(cat_items) > 0

    # 4. Request /cart/quote for a product
    sample_sku = cat_items[0]["sku"]
    quote_resp = client.post(
        "/cart/quote",
        headers={"Authorization": "Bearer token-for-cat"},
        json={"items": [{"sku": sample_sku, "quantity": 2}]},
    )
    assert quote_resp.status_code == 200
    assert quote_resp.json()["lines"][0]["sku"] == sample_sku


def test_unlinked_authenticated_supabase_user_completes_profile(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified_uid = "verified-supabase-email-confirmed-uuid"
    monkeypatch.setattr("app.auth.get_supabase_subject", lambda token: verified_uid)

    # 1. Before registration, /auth/me returns 403 (unlinked profile)
    pre_check = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer verified-email-token"},
    )
    assert pre_check.status_code == 403
    assert "No active OrderFlow profile is linked" in pre_check.json()["detail"]

    # 2. Verified user completes profile without signing up again
    complete_resp = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer verified-email-token"},
        json={
            "shop_name": "Verified Kirana",
            "owner_name": "Verified Owner",
            "phone": "9811223344",
            "address": "Shop 77, Ring Road, Jaipur",
            "email": "verified.retailer@example.com",
        },
    )
    assert complete_resp.status_code == 201
    assert complete_resp.json()["role"] == "retailer"

    # 3. After completion, /auth/me succeeds immediately with role="retailer"
    post_check = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer verified-email-token"},
    )
    assert post_check.status_code == 200
    assert post_check.json()["role"] == "retailer"
    assert post_check.json()["retailer_id"] == complete_resp.json()["retailer_id"]

    # 4. Attempting duplicate registration with same identity is rejected with 409
    dup_resp = client.post(
        "/auth/register",
        headers={"Authorization": "Bearer verified-email-token"},
        json={
            "shop_name": "Verified Kirana Duplicate",
            "owner_name": "Verified Owner",
            "phone": "9811223344",
            "address": "Shop 77, Ring Road, Jaipur",
            "email": "verified.retailer@example.com",
        },
    )
    assert dup_resp.status_code == 409
    assert "already registered" in dup_resp.json()["detail"]


def test_existing_order_desk_and_retailer_logins_unaffected(
    seeded_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_subject(token: str) -> str:
        if token == "retailer-tok":
            return "demo-retailer-user"
        if token == "desk-tok":
            return "demo-order-desk-user"
        raise HTTPException(status_code=401, detail="Invalid token")

    monkeypatch.setattr("app.auth.get_supabase_subject", fake_get_subject)

    # Existing retailer login
    ret_resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer retailer-tok"},
    )
    assert ret_resp.status_code == 200
    assert ret_resp.json()["role"] == "retailer"

    # Existing order desk login
    desk_resp = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer desk-tok"},
    )
    assert desk_resp.status_code == 200
    assert desk_resp.json()["role"] == "order_desk"


