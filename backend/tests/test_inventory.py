from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.main import app
from app.models import Inventory, Order, Product, Retailer, StockMovement, User
from app.orders import clear_demo_orders

client = TestClient(app)


def authenticate_as(seeded_database, auth_subject: str) -> None:
    with Session(seeded_database) as session:
        user = session.scalar(
            select(User).where(User.auth_subject == auth_subject)
        )
        assert user is not None, f"Missing test user: {auth_subject}"
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def setup_and_teardown(seeded_database):
    clear_demo_orders(seeded_database)
    yield
    clear_demo_orders(seeded_database)
    app.dependency_overrides.pop(get_current_user, None)


def test_inventory_list_requires_authentication(seeded_database) -> None:
    app.dependency_overrides.pop(get_current_user, None)
    response = client.get("/inventory")
    assert response.status_code == 401


def test_retailer_inventory_view_is_sanitized(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")
    response = client.get("/inventory")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3

    biscuit = next(i for i in items if i["sku"] == "SKU-BS-075")
    assert biscuit["available_stock"] == 500
    assert biscuit["is_out_of_stock"] is False
    assert biscuit["is_low_stock"] is False
    # Internal counts must be hidden from retailer
    assert biscuit["on_hand_stock"] is None
    assert biscuit["reserved_stock"] is None
    assert biscuit["low_stock_threshold"] is None


def test_order_desk_inventory_view_includes_internal_fields(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-order-desk-user")
    response = client.get("/inventory")
    assert response.status_code == 200
    items = response.json()

    biscuit = next(i for i in items if i["sku"] == "SKU-BS-075")
    assert biscuit["available_stock"] == 500
    assert biscuit["on_hand_stock"] == 500
    assert biscuit["reserved_stock"] == 0
    assert biscuit["low_stock_threshold"] == 20


def test_get_product_inventory_by_sku(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-order-desk-user")
    response = client.get("/inventory/SKU-DP-1KG")
    assert response.status_code == 200
    item = response.json()
    assert item["sku"] == "SKU-DP-1KG"
    assert item["on_hand_stock"] == 200
    assert item["available_stock"] == 200

    not_found = client.get("/inventory/NON-EXISTENT-SKU")
    assert not_found.status_code == 404


def test_retailer_cannot_receive_or_adjust_stock(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")

    res_recv = client.post(
        "/inventory/receive",
        json={"sku": "SKU-BS-075", "quantity": 50},
    )
    assert res_recv.status_code == 403

    res_adj = client.post(
        "/inventory/adjust",
        json={"sku": "SKU-BS-075", "new_on_hand": 400, "reason": "Physical count"},
    )
    assert res_adj.status_code == 403

    res_hist = client.get("/inventory/SKU-BS-075/history")
    assert res_hist.status_code == 403


def test_order_desk_receives_stock_and_records_movement(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-order-desk-user")

    response = client.post(
        "/inventory/receive",
        json={"sku": "SKU-BS-075", "quantity": 100, "reason": "PO-2026-001"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["on_hand_stock"] == 600
    assert updated["available_stock"] == 600

    # Verify history ledger
    hist = client.get("/inventory/SKU-BS-075/history")
    assert hist.status_code == 200
    history_entries = hist.json()
    assert len(history_entries) >= 1
    latest = history_entries[0]
    assert latest["movement_type"] == "receive"
    assert latest["quantity"] == 100
    assert latest["on_hand_before"] == 500
    assert latest["on_hand_after"] == 600
    assert latest["reason"] == "PO-2026-001"


def test_order_desk_adjusts_stock_with_audit_reason(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-order-desk-user")

    response = client.post(
        "/inventory/adjust",
        json={
            "sku": "SKU-TL-250",
            "new_on_hand": 85,
            "reason": "Physical stock count audit - 15 damaged cases",
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["on_hand_stock"] == 85
    assert updated["available_stock"] == 85

    # Check ledger
    hist = client.get("/inventory/SKU-TL-250/history")
    assert hist.status_code == 200
    entries = hist.json()
    assert entries[0]["movement_type"] == "adjustment"
    assert entries[0]["quantity"] == -15
    assert entries[0]["on_hand_before"] == 100
    assert entries[0]["on_hand_after"] == 85


def test_order_desk_cannot_adjust_stock_below_reserved(seeded_database) -> None:
    # First place an order to reserve 10 cases (+ 1 free bonus = 11 delivered)
    authenticate_as(seeded_database, "demo-retailer-user")
    order_res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )
    assert order_res.status_code == 201

    # Now attempt to adjust physical on-hand stock below 11 reserved cases
    authenticate_as(seeded_database, "demo-order-desk-user")
    bad_adjust = client.post(
        "/inventory/adjust",
        json={"sku": "SKU-BS-075", "new_on_hand": 5, "reason": "Inventory reduction"},
    )
    assert bad_adjust.status_code == 400
    assert "reserved" in bad_adjust.json()["detail"].lower()


def test_update_low_stock_threshold(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-order-desk-user")
    response = client.patch(
        "/inventory/SKU-TL-250/threshold",
        json={"low_stock_threshold": 120},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["low_stock_threshold"] == 120
    # Available is 100 <= 120 -> is_low_stock should be True
    assert data["is_low_stock"] is True


def test_order_creation_validates_and_reserves_stock_including_free_goods(
    seeded_database,
) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")

    # SKU-BS-075 has Buy 10 Get 1 Free scheme.
    # Requesting 20 cases yields 2 free cases -> delivered_quantity = 22 cases.
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 20}]},
    )
    assert res.status_code == 201
    order = res.json()
    assert order["status"] == "pending_review"
    assert order["lines"][0]["delivered_quantity"] == 22

    # Check inventory
    authenticate_as(seeded_database, "demo-order-desk-user")
    inv = client.get("/inventory/SKU-BS-075").json()
    assert inv["on_hand_stock"] == 500
    assert inv["reserved_stock"] == 22
    assert inv["available_stock"] == 478

    # Check ledger
    hist = client.get("/inventory/SKU-BS-075/history").json()
    assert hist[0]["movement_type"] == "reserve"
    assert hist[0]["quantity"] == 22


def test_order_rejected_when_stock_is_insufficient(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")

    # SKU-TL-250 has only 100 cases available in seeded fixture
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-TL-250", "quantity": 105}]},
    )
    assert res.status_code == 400
    assert "insufficient stock" in res.json()["detail"].lower()

    # Verify no reservation made
    authenticate_as(seeded_database, "demo-order-desk-user")
    inv = client.get("/inventory/SKU-TL-250").json()
    assert inv["on_hand_stock"] == 100
    assert inv["reserved_stock"] == 0
    assert inv["available_stock"] == 100


def test_credit_hold_order_does_not_reserve_stock(seeded_database) -> None:
    # Set retailer credit limit lower than order total
    with Session(seeded_database) as session:
        retailer = session.scalar(select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER"))
        retailer.credit_limit = Decimal("5000.00")
        session.commit()

    authenticate_as(seeded_database, "demo-retailer-user")
    # 10 cases of SKU-BS-075 is ₹7,776.00 > ₹5,000 credit limit
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )
    assert res.status_code == 201
    order = res.json()
    assert order["status"] == "credit_hold"

    # Verify stock was NOT reserved
    authenticate_as(seeded_database, "demo-order-desk-user")
    inv = client.get("/inventory/SKU-BS-075").json()
    assert inv["reserved_stock"] == 0
    assert inv["available_stock"] == 500


def test_approval_converts_reservation_to_committed_deduction(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-DP-1KG", "quantity": 10}]},
    )
    assert res.status_code == 201
    order_id = res.json()["id"]

    # Check reserved before approval
    authenticate_as(seeded_database, "demo-order-desk-user")
    inv_before = client.get("/inventory/SKU-DP-1KG").json()
    assert inv_before["on_hand_stock"] == 200
    assert inv_before["reserved_stock"] == 10
    assert inv_before["available_stock"] == 190

    # Approve order
    appr = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "approve"},
    )
    assert appr.status_code == 200
    assert appr.json()["status"] == "approved"

    # Check committed deduction
    inv_after = client.get("/inventory/SKU-DP-1KG").json()
    assert inv_after["on_hand_stock"] == 190
    assert inv_after["reserved_stock"] == 0
    assert inv_after["available_stock"] == 190

    # Check ledger
    hist = client.get("/inventory/SKU-DP-1KG/history").json()
    latest = hist[0]
    assert latest["movement_type"] == "deduct_approved"
    assert latest["quantity"] == -10
    assert latest["on_hand_before"] == 200
    assert latest["on_hand_after"] == 190


def test_rejection_releases_stock_reservation(seeded_database) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-DP-1KG", "quantity": 15}]},
    )
    assert res.status_code == 201
    order_id = res.json()["id"]

    authenticate_as(seeded_database, "demo-order-desk-user")
    inv_before = client.get("/inventory/SKU-DP-1KG").json()
    assert inv_before["reserved_stock"] == 15

    # Reject order
    rej = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "reject", "note": "Duplicate order"},
    )
    assert rej.status_code == 200
    assert rej.json()["status"] == "rejected"

    inv_after = client.get("/inventory/SKU-DP-1KG").json()
    assert inv_after["on_hand_stock"] == 200
    assert inv_after["reserved_stock"] == 0
    assert inv_after["available_stock"] == 200

    hist = client.get("/inventory/SKU-DP-1KG/history").json()
    assert hist[0]["movement_type"] == "release_reservation"
    assert hist[0]["quantity"] == -15


def test_release_hold_revalidates_and_reserves_stock(seeded_database) -> None:
    # Set low credit limit so order goes to credit_hold
    with Session(seeded_database) as session:
        retailer = session.scalar(select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER"))
        retailer.credit_limit = Decimal("5000.00")
        session.commit()

    authenticate_as(seeded_database, "demo-retailer-user")
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )
    assert res.status_code == 201
    order_id = res.json()["id"]
    assert res.json()["status"] == "credit_hold"

    authenticate_as(seeded_database, "demo-order-desk-user")
    # Release hold: should check stock fresh and reserve 11 cases
    rel = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "release_hold"},
    )
    assert rel.status_code == 200
    assert rel.json()["status"] == "pending_review"

    inv = client.get("/inventory/SKU-BS-075").json()
    assert inv["reserved_stock"] == 11
    assert inv["available_stock"] == 489


def test_release_hold_fails_if_stock_depleted(seeded_database) -> None:
    # 1. Place order on credit_hold
    with Session(seeded_database) as session:
        retailer = session.scalar(select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER"))
        retailer.credit_limit = Decimal("1000.00")
        session.commit()

    authenticate_as(seeded_database, "demo-retailer-user")
    res = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-TL-250", "quantity": 100}]},
    )
    assert res.status_code == 201
    order_id = res.json()["id"]
    assert res.json()["status"] == "credit_hold"

    # 2. Meanwhile, stock of SKU-TL-250 is depleted to 10 cases via audit adjustment
    authenticate_as(seeded_database, "demo-order-desk-user")
    client.post(
        "/inventory/adjust",
        json={"sku": "SKU-TL-250", "new_on_hand": 10, "reason": "Stock transferred out"},
    )

    # 3. Attempting to release hold must fail with 409 Conflict due to insufficient stock
    rel_fail = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "release_hold"},
    )
    assert rel_fail.status_code == 409
    assert "insufficient available stock" in rel_fail.json()["detail"].lower()


def test_multiple_lines_for_same_sku_aggregated_before_stock_validation(
    seeded_database,
) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")

    # SKU-TL-250 has 100 cases available.
    # Submitting two items for SKU-TL-250 (60 cases + 50 cases = 110 cases > 100 available)
    res = client.post(
        "/orders",
        json={
            "items": [
                {"sku": "SKU-TL-250", "quantity": 60},
                {"sku": "SKU-TL-250", "quantity": 50},
            ]
        },
    )
    assert res.status_code == 400
    assert "insufficient stock" in res.json()["detail"].lower()

    # Verify no partial reservation was committed
    authenticate_as(seeded_database, "demo-order-desk-user")
    inv = client.get("/inventory/SKU-TL-250").json()
    assert inv["reserved_stock"] == 0
    assert inv["available_stock"] == 100


def test_failed_multi_item_order_does_not_partially_reserve_stock(
    seeded_database,
) -> None:
    authenticate_as(seeded_database, "demo-retailer-user")

    # Line 1: 10 cases of SKU-BS-075 (sufficient, 500 available)
    # Line 2: 120 cases of SKU-TL-250 (insufficient, only 100 available)
    res = client.post(
        "/orders",
        json={
            "items": [
                {"sku": "SKU-BS-075", "quantity": 10},
                {"sku": "SKU-TL-250", "quantity": 120},
            ]
        },
    )
    assert res.status_code == 400

    # Ensure Line 1 was NOT reserved (all-or-nothing rollback)
    authenticate_as(seeded_database, "demo-order-desk-user")
    biscuit_inv = client.get("/inventory/SKU-BS-075").json()
    assert biscuit_inv["reserved_stock"] == 0
    assert biscuit_inv["available_stock"] == 500

    tea_inv = client.get("/inventory/SKU-TL-250").json()
    assert tea_inv["reserved_stock"] == 0
    assert tea_inv["available_stock"] == 100


def test_on_demand_inventory_creation_initializes_zero_stock(
    seeded_database,
) -> None:
    # Add a product
    with Session(seeded_database) as session:
        new_prod = Product(
            sku="SKU-BC-MARIE",
            name="Marie Gold",
            pack_label="120 g",
            is_active=True,
        )
        session.add(new_prod)
        session.commit()

    authenticate_as(seeded_database, "demo-order-desk-user")
    # Fetch inventory for the newly added product
    res = client.get("/inventory/SKU-BC-MARIE")
    assert res.status_code == 200
    data = res.json()
    # Must initialize with 0 stock to maintain the zero-stock clean baseline
    assert data["on_hand_stock"] == 0
    assert data["available_stock"] == 0
    assert data["reserved_stock"] == 0

    # History ledger must show zero-stock initialization movement
    hist = client.get("/inventory/SKU-BC-MARIE/history").json()
    assert len(hist) == 1
    assert hist[0]["movement_type"] == "init"
    assert hist[0]["quantity"] == 0
    assert hist[0]["reference_id"] == "ZERO-STOCK-INIT"


def test_inventory_check_constraints_prevent_negative_and_excessive_reservations(
    seeded_database,
) -> None:
    with Session(seeded_database) as session:
        prod = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
        inv = session.scalar(select(Inventory).where(Inventory.product_id == prod.id))

        # Attempting reserved_stock > on_hand_stock should violate check constraint
        inv.reserved_stock = inv.on_hand_stock + 10
        with pytest.raises(Exception):
            session.commit()
        session.rollback()

        # Attempting reserved_stock < 0 should violate check constraint
        inv.reserved_stock = -1
        with pytest.raises(Exception):
            session.commit()
        session.rollback()


