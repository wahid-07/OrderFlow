from decimal import Decimal
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.main import app
from app.models import (
    Inventory,
    Order,
    OrderItem,
    Product,
    Retailer,
    RetailerPrice,
    Salesman,
    SalesmanRetailerAssignment,
    SalesmanVisitNote,
    StockMovement,
    User,
)
from app.orders import clear_demo_orders

client = TestClient(app)


def authenticate_as(seeded_database, auth_subject: str) -> User:
    with Session(seeded_database) as session:
        user = session.scalar(
            select(User).where(User.auth_subject == auth_subject)
        )
        assert user is not None, f"Missing test user: {auth_subject}"
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user
    return user


@pytest.fixture(autouse=True)
def cleanup_between_tests(seeded_database):
    clear_demo_orders(seeded_database)
    yield
    clear_demo_orders(seeded_database)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def salesman_setup(seeded_database):
    """Sets up a salesman, user, and assignment to DEMO-RETAILER."""
    with Session(seeded_database, expire_on_commit=False) as session:
        retailer1 = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer2 = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER-2")
        )

        salesman_user = User(
            auth_subject="test-salesman-user",
            role="salesman",
            is_active=True,
        )
        session.add(salesman_user)
        session.flush()

        salesman = Salesman(
            user_id=salesman_user.id,
            display_name="Ramesh Kumar",
            phone="9876543210",
            is_active=True,
        )
        session.add(salesman)
        session.flush()

        # Assign salesman to retailer1 only
        assignment = SalesmanRetailerAssignment(
            salesman_id=salesman.id,
            retailer_id=retailer1.id,
            is_active=True,
        )
        session.add(assignment)
        session.commit()
        session.expunge_all()

        return {
            "salesman_user": salesman_user,
            "salesman": salesman,
            "retailer1": retailer1,
            "retailer2": retailer2,
        }


# ==============================================================================
# Part A: Repeat Order Tests
# ==============================================================================

def test_retailer_can_generate_repeat_order_draft(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # 1. Place initial order
    order_res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # 2. Call repeat draft endpoint
    repeat_res = client.post(f"/orders/{order_id}/repeat-draft")
    assert repeat_res.status_code == 200
    data = repeat_res.json()

    assert data["original_order_id"] == order_id
    assert data["has_unavailable_items"] is False
    assert len(data["unavailable_items"]) == 0
    assert data["valid_lines_count"] == 1
    assert data["draft_quote"] is not None
    assert data["draft_quote"]["lines"][0]["sku"] == "SKU-BS-075"
    assert data["draft_quote"]["lines"][0]["paid_quantity"] == 10
    # Live scheme buy 10 get 1 free applied
    assert data["draft_quote"]["lines"][0]["free_quantity"] == 1


def test_cross_retailer_repeat_order_rejected(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # Retailer 1 places order
    order_res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 5}]},
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Switch to Retailer 2
    authenticate_as(seeded_database, "second-demo-retailer-user")

    # Retailer 2 attempts to repeat Retailer 1's order
    repeat_res = client.post(f"/orders/{order_id}/repeat-draft")
    assert repeat_res.status_code == 403
    assert "Retailers can only repeat their own orders" in repeat_res.json()["detail"]


def test_repeat_order_flags_inactive_or_out_of_stock_products(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # Place order with 2 items
    order_res = client.post(
        "/orders",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 10},
                {"sku": "SKU-DP-1KG", "quantity": 5},
            ]
        },
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Now simulate SKU-DP-1KG becoming inactive and SKU-BS-075 running out of stock
    with Session(seeded_database) as session:
        dp = session.scalar(select(Product).where(Product.sku == "SKU-DP-1KG"))
        dp.is_active = False

        bs = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        inv = session.scalar(select(Inventory).where(Inventory.product_id == bs.id))
        inv.on_hand_stock = 0
        inv.reserved_stock = 0
        session.commit()

    # Call repeat draft
    repeat_res = client.post(f"/orders/{order_id}/repeat-draft")
    assert repeat_res.status_code == 200
    data = repeat_res.json()

    assert data["has_unavailable_items"] is True
    assert len(data["unavailable_items"]) == 2

    reasons = {item["sku"]: item["reason"] for item in data["unavailable_items"]}
    assert reasons["SKU-DP-1KG"] == "inactive_or_discontinued"
    assert reasons["SKU-BS-075"] == "out_of_stock"
    assert data["valid_lines_count"] == 0


# ==============================================================================
# Part B: Server-Side Idempotency Tests
# ==============================================================================

def test_idempotent_order_submission_returns_existing_order(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    idempotency_key = f"test-idem-{uuid.uuid4()}"

    # 1. First submission
    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res1.status_code == 201
    order1 = res1.json()
    assert order1["idempotency_key"] == idempotency_key

    # Check reserved stock after first order
    with Session(seeded_database) as session:
        bs = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        inv = session.scalar(select(Inventory).where(Inventory.product_id == bs.id))
        reserved_after_order1 = inv.reserved_stock
        assert reserved_after_order1 == 11  # 10 paid + 1 free

        # Count stock movements
        mov_count = session.query(StockMovement).filter(StockMovement.reference_id == order1["order_number"]).count()
        assert mov_count == 1

    # 2. Second submission with SAME idempotency key (simulating offline retry)
    res2 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res2.status_code in (200, 201)
    order2 = res2.json()

    # Verify identical order returned
    assert order2["id"] == order1["id"]
    assert order2["order_number"] == order1["order_number"]

    # Verify no double-reservation occurred
    with Session(seeded_database) as session:
        bs = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        inv = session.scalar(select(Inventory).where(Inventory.product_id == bs.id))
        assert inv.reserved_stock == reserved_after_order1

        # Still only 1 stock movement
        mov_count2 = session.query(StockMovement).filter(StockMovement.reference_id == order1["order_number"]).count()
        assert mov_count2 == 1


# ==============================================================================
# Part C: Salesman Role, Assignment & Ordering Workflow Tests
# ==============================================================================

def test_salesman_can_place_order_for_assigned_retailer(seeded_database, salesman_setup):
    authenticate_as(seeded_database, "test-salesman-user")

    retailer1_id = str(salesman_setup["retailer1"].id)
    idempotency_key = f"salesman-order-{uuid.uuid4()}"

    res = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer1_id,
            "idempotency_key": idempotency_key,
            "order_source": "salesman",
        },
    )
    assert res.status_code == 201
    order = res.json()

    assert order["retailer_id"] == retailer1_id
    assert order["salesman_id"] == str(salesman_setup["salesman"].id)
    assert order["order_source"] == "salesman"
    assert order["status"] == "pending_review"


def test_salesman_cannot_place_order_for_unassigned_retailer(seeded_database, salesman_setup):
    authenticate_as(seeded_database, "test-salesman-user")

    # Retailer 2 is not assigned to this salesman
    retailer2_id = str(salesman_setup["retailer2"].id)

    res = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer2_id,
        },
    )
    assert res.status_code == 403
    assert "Salesman is not assigned to this retailer" in res.json()["detail"]


def test_salesman_cannot_approve_orders(seeded_database, salesman_setup):
    # 1. Place order as salesman
    authenticate_as(seeded_database, "test-salesman-user")
    retailer1_id = str(salesman_setup["retailer1"].id)

    res = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer1_id,
        },
    )
    assert res.status_code == 201
    order_id = res.json()["id"]

    # 2. Salesman attempts to approve the order
    decision_res = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "approve"},
    )
    # Salesman role is not in require_roles("order_desk", "distributor_admin", "super_admin")
    assert decision_res.status_code == 403


def test_salesman_assigned_retailers_endpoint(seeded_database, salesman_setup):
    authenticate_as(seeded_database, "test-salesman-user")

    res = client.get("/salesman/assigned-retailers")
    assert res.status_code == 200
    retailers = res.json()

    assert len(retailers) == 1
    assert retailers[0]["external_ref"] == "DEMO-RETAILER"
    assert "credit_limit" in retailers[0]
    assert "available_credit" in retailers[0]


def test_salesman_visit_notes(seeded_database, salesman_setup):
    authenticate_as(seeded_database, "test-salesman-user")
    retailer1_id = str(salesman_setup["retailer1"].id)

    # 1. Create note
    post_res = client.post(
        "/salesman/visit-notes",
        json={
            "retailer_id": retailer1_id,
            "note": "Checked shelf displays, competitor Parle-G prominent.",
        },
    )
    assert post_res.status_code == 201
    note_data = post_res.json()
    assert note_data["note"] == "Checked shelf displays, competitor Parle-G prominent."

    # 2. List notes
    list_res = client.get(f"/salesman/visit-notes?retailer_id={retailer1_id}")
    assert list_res.status_code == 200
    notes = list_res.json()
    assert len(notes) >= 1
    assert notes[0]["note"] == "Checked shelf displays, competitor Parle-G prominent."


# ==============================================================================
# Part D: Additional Security, Idempotency & Edge Case Tests
# ==============================================================================

def test_idempotency_key_reused_with_different_payload_fails(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    idempotency_key = f"payload-test-{uuid.uuid4()}"

    # First submission: 10 cases of SKU-BS-075
    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res1.status_code == 201

    # Second submission: same idempotency key but different quantity (5 instead of 10)
    res2 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 5}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res2.status_code == 409
    assert "different order payload" in res2.json()["detail"]


def test_cross_retailer_idempotency_key_reuse_fails(seeded_database):
    # Retailer 1 uses key
    authenticate_as(seeded_database, "demo-retailer-user")
    idempotency_key = f"cross-ret-{uuid.uuid4()}"

    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res1.status_code == 201

    # Retailer 2 attempts to use same key
    authenticate_as(seeded_database, "second-demo-retailer-user")
    res2 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "idempotency_key": idempotency_key,
        },
    )
    assert res2.status_code == 409
    assert "different retailers" in res2.json()["detail"]


def test_cross_salesman_idempotency_key_reuse_fails(seeded_database, salesman_setup):
    retailer1_id = str(salesman_setup["retailer1"].id)
    idempotency_key = f"cross-salesman-{uuid.uuid4()}"

    # Salesman 1 uses key
    authenticate_as(seeded_database, "test-salesman-user")
    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer1_id,
            "idempotency_key": idempotency_key,
            "order_source": "salesman",
        },
    )
    assert res1.status_code == 201

    # Setup Salesman 2 assigned to same retailer
    with Session(seeded_database) as session:
        user2 = User(auth_subject="test-salesman-user-2", role="salesman", is_active=True)
        session.add(user2)
        session.flush()

        salesman2 = Salesman(
            user_id=user2.id,
            display_name="Suresh Sharma",
            phone="9123456789",
            is_active=True,
        )
        session.add(salesman2)
        session.flush()

        assign2 = SalesmanRetailerAssignment(
            salesman_id=salesman2.id,
            retailer_id=salesman_setup["retailer1"].id,
            is_active=True,
        )
        session.add(assign2)
        session.commit()

    # Salesman 2 attempts to use Salesman 1's key
    authenticate_as(seeded_database, "test-salesman-user-2")
    res2 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer1_id,
            "idempotency_key": idempotency_key,
            "order_source": "salesman",
        },
    )
    assert res2.status_code == 409
    assert "different salesman" in res2.json()["detail"]


def test_duplicate_salesman_provisioning_rejected(seeded_database):
    authenticate_as(seeded_database, "demo-order-desk-user")

    # 1. Provision new salesman
    res1 = client.post(
        "/salesmen",
        json={
            "display_name": "Vikas Gupta",
            "auth_subject": "vikas-auth-001",
            "email": "vikas.gupta@distributor.com",
            "phone": "9988776655",
        },
    )
    assert res1.status_code == 201

    # 2. Duplicate auth_subject -> 409 Conflict
    res2 = client.post(
        "/salesmen",
        json={
            "display_name": "Vikas Two",
            "auth_subject": "vikas-auth-001",
            "email": "different@distributor.com",
            "phone": "9988776656",
        },
    )
    assert res2.status_code == 409
    assert "auth subject already exists" in res2.json()["detail"]

    # 3. Duplicate email -> 409 Conflict
    res3 = client.post(
        "/salesmen",
        json={
            "display_name": "Vikas Three",
            "auth_subject": "vikas-auth-different",
            "email": "vikas.gupta@distributor.com",
            "phone": "9988776657",
        },
    )
    assert res3.status_code == 409
    assert "already exists" in res3.json()["detail"]


def test_inactive_salesman_cannot_access_or_order(seeded_database, salesman_setup):
    # Inactivate salesman
    with Session(seeded_database) as session:
        s = session.get(Salesman, salesman_setup["salesman"].id)
        s.is_active = False
        session.commit()

    authenticate_as(seeded_database, "test-salesman-user")
    retailer1_id = str(salesman_setup["retailer1"].id)

    # Cannot get assigned retailers
    ret_res = client.get("/salesman/assigned-retailers")
    assert ret_res.status_code == 403

    # Cannot log visit notes
    note_res = client.post(
        "/salesman/visit-notes",
        json={"retailer_id": retailer1_id, "note": "Visited shop"},
    )
    assert note_res.status_code == 403

    # Cannot create orders
    order_res = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "retailer_id": retailer1_id,
        },
    )
    assert order_res.status_code == 403


def test_repeat_order_with_changed_prices_and_schemes(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # 1. Place order when unit_price is 777.60
    order_res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )
    assert order_res.status_code == 201
    order_data = order_res.json()
    order_id = order_data["id"]
    original_total = order_data["total"]

    # 2. Update price in database for SKU-BS-075 to 900.00
    with Session(seeded_database) as session:
        retailer = session.scalar(select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER"))
        bs = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        price_row = session.scalar(
            select(RetailerPrice).where(
                RetailerPrice.retailer_id == retailer.id,
                RetailerPrice.product_id == bs.id,
            )
        )
        price_row.unit_price = Decimal("900.00")
        session.commit()

    # 3. Request repeat order draft
    repeat_res = client.post(f"/orders/{order_id}/repeat-draft")
    assert repeat_res.status_code == 200
    draft = repeat_res.json()

    # Verify unit price reflects the new price (900.00)
    line = draft["draft_quote"]["lines"][0]
    assert Decimal(str(line["unit_price"])) == Decimal("900.00")
    # Subtotal is 10 * 900 = 9000
    assert Decimal(str(line["subtotal"])) == Decimal("9000.00")
    # Total is different from the original order
    assert str(draft["total"]) != str(original_total)


# ==============================================================================
# Part E: Gap Closure Tests (Consolidation, Actor Isolation & Provisioning)
# ==============================================================================

def test_duplicate_sku_line_consolidation(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # Send order with duplicate lines for SKU-BS-075 (5 + 5 = 10 cases)
    # Tier scheme for SKU-BS-075 gives 5% discount at >= 10 cases
    res = client.post(
        "/cart/quote",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 5},
                {"sku": "SKU-BS-075", "quantity": 5},
            ]
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["lines"]) == 1
    line = data["lines"][0]
    assert line["sku"] == "SKU-BS-075"
    assert line["requested_quantity"] == 10
    # Live scheme for SKU-BS-075 (Buy 10 Get 1 Free) applies to consolidated quantity
    assert line["free_quantity"] == 1
    assert line["delivered_quantity"] == 11

    # Place order with duplicate lines
    order_res = client.post(
        "/orders",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 5},
                {"sku": "SKU-BS-075", "quantity": 5},
            ],
            "idempotency_key": "IDEMP-DUP-LINES-001",
        },
    )
    assert order_res.status_code == 201
    order_data = order_res.json()
    assert len(order_data["lines"]) == 1
    assert order_data["lines"][0]["requested_quantity"] == 10

    # Idempotent retry with the same aggregated payload succeeds
    retry_res = client.post(
        "/orders",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 10},
            ],
            "idempotency_key": "IDEMP-DUP-LINES-001",
        },
    )
    assert retry_res.status_code == 201
    assert retry_res.json()["id"] == order_data["id"]


def test_idempotency_actor_cross_salesman_rejection(seeded_database, salesman_setup):
    retailer1_id = str(salesman_setup["retailer1"].id)

    # 1. Salesman 1 places order with key IDEMP-SALES-X
    authenticate_as(seeded_database, "test-salesman-user")
    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 2}],
            "retailer_id": retailer1_id,
            "idempotency_key": "IDEMP-SALES-X",
        },
    )
    assert res1.status_code == 201

    # 2. Set up Salesman 2 assigned to same retailer
    with Session(seeded_database) as session:
        salesman2_user = User(
            auth_subject="test-salesman-2-user",
            role="salesman",
            is_active=True,
        )
        session.add(salesman2_user)
        session.flush()

        salesman2 = Salesman(
            user_id=salesman2_user.id,
            display_name="Suresh Verma",
            phone="9123456780",
            is_active=True,
        )
        session.add(salesman2)
        session.flush()

        session.add(
            SalesmanRetailerAssignment(
                salesman_id=salesman2.id,
                retailer_id=salesman_setup["retailer1"].id,
                is_active=True,
            )
        )
        session.commit()

    # Salesman 2 tries to reuse IDEMP-SALES-X -> 409 Conflict
    authenticate_as(seeded_database, "test-salesman-2-user")
    res2 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 2}],
            "retailer_id": retailer1_id,
            "idempotency_key": "IDEMP-SALES-X",
        },
    )
    assert res2.status_code == 409
    assert "different salesman" in res2.json()["detail"]

    # Retailer tries to reuse IDEMP-SALES-X -> 409 Conflict
    authenticate_as(seeded_database, "demo-retailer-user")
    res3 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 2}],
            "idempotency_key": "IDEMP-SALES-X",
        },
    )
    assert res3.status_code == 409
    assert "salesman order" in res3.json()["detail"]


def test_supabase_salesman_provisioning_compensation(seeded_database, monkeypatch):
    authenticate_as(seeded_database, "demo-order-desk-user")

    rolled_back_auth_ids = []

    def mock_provision(email, display_name, phone=None, password=None, auth_subject=None):
        return ("mock-supabase-uuid-1234", True, "http://localhost:5173/auth/setup-password?mock=1")

    def mock_rollback(auth_subject):
        rolled_back_auth_ids.append(auth_subject)
        return True

    import app.salesman as salesman_module
    monkeypatch.setattr(salesman_module, "provision_supabase_salesman", mock_provision)
    monkeypatch.setattr(salesman_module, "rollback_supabase_salesman", mock_rollback)

    # Monkeypatch Session.commit to simulate database failure during transaction
    def failing_commit(self):
        raise RuntimeError("Simulated DB commit error")

    monkeypatch.setattr(Session, "commit", failing_commit)

    res = client.post(
        "/salesmen",
        json={
            "display_name": "Rollback Test",
            "email": "rollback.test@distributor.com",
            "phone": "9998887771",
        },
    )
    assert res.status_code == 409
    assert "Rolled back authentication state" in res.json()["detail"]
    assert "mock-supabase-uuid-1234" in rolled_back_auth_ids


def test_repeat_order_draft_handles_null_valid_from(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # 1. Place initial order
    order_res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 3}]},
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # 2. Set valid_from to NULL in RetailerPrice (representing perpetual active price)
    with Session(seeded_database) as session:
        retailer = session.scalar(select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER"))
        bs = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        price_row = session.scalar(
            select(RetailerPrice).where(
                RetailerPrice.retailer_id == retailer.id,
                RetailerPrice.product_id == bs.id,
            )
        )
        price_row.valid_from = None
        session.commit()

    # 3. Repeat draft generation should succeed and find the price
    draft_res = client.post(f"/orders/{order_id}/repeat-draft")
    assert draft_res.status_code == 200
    draft = draft_res.json()
    assert draft["is_reorderable"] is True
    assert len(draft["draft_quote"]["lines"]) == 1
    assert draft["draft_quote"]["lines"][0]["sku"] == "SKU-BS-075"


def test_supabase_salesman_missing_credentials_fails_safely_in_production(monkeypatch):
    import app.supabase_admin as admin_module

    # Clear credentials and force production environment check
    monkeypatch.setattr(admin_module, "get_supabase_admin_config", lambda: (None, None))
    monkeypatch.setattr(admin_module, "is_test_environment", lambda: False)

    with pytest.raises(Exception) as exc_info:
        admin_module.provision_supabase_salesman(
            email="salesman@example.com",
            display_name="Ramesh Test",
        )
    assert exc_info.value.status_code == 503
    assert "Cannot provision salesman authentication safely" in exc_info.value.detail


def test_review_and_edit_idempotency_workflow(seeded_database):
    authenticate_as(seeded_database, "demo-retailer-user")

    # 1. User submits an order with KEY-ORIG-001
    res1 = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 2}],
            "idempotency_key": "KEY-ORIG-001",
        },
    )
    assert res1.status_code == 201
    orig_order_id = res1.json()["id"]

    # 2. Resubmission of a CHANGED payload with the SAME key produces 409 Conflict
    res_conflict = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 5}],
            "idempotency_key": "KEY-ORIG-001",
        },
    )
    assert res_conflict.status_code == 409
    assert "different order payload" in res_conflict.json()["detail"]

    # 3. In the UI Review & Edit workflow:
    # A fresh idempotency key is generated for the modified payload
    res_edited = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 5}],
            "idempotency_key": "KEY-EDITED-002",
        },
    )
    assert res_edited.status_code == 201
    edited_order = res_edited.json()
    assert edited_order["id"] != orig_order_id
    assert edited_order["lines"][0]["requested_quantity"] == 5




