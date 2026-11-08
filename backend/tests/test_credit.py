"""Tests for OrderFlow Phase 4: Retailer Credit Management & Automatic Credit Hold."""

import csv
from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.main import app
from app.models import Order, Product, Retailer, User
from app.orders import clear_demo_orders

client = TestClient(app)


def authenticate_user(seeded_database, auth_subject: str) -> User:
    """Helper to authenticate test requests as a specific user."""
    with Session(seeded_database) as session:
        user = session.scalar(select(User).where(User.auth_subject == auth_subject))
        assert user is not None, f"Missing test user: {auth_subject}"
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user
    return user


def clear_auth() -> None:
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def clean_database_state(seeded_database):
    clear_demo_orders(seeded_database)
    yield
    clear_demo_orders(seeded_database)
    clear_auth()


# =====================================================================
# 1. Retailer Credit Information & API Tests
# =====================================================================


def test_retailer_can_view_own_credit_information(seeded_database) -> None:
    """Retailer can view their own credit information and utilization via /retailer/credit."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.get("/retailer/credit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["retailer_name"] == "Demo Retailer"
        assert Decimal(data["credit_limit"]) == Decimal("100000.00")
        assert Decimal(data["current_outstanding"]) == Decimal("0.00")
        assert Decimal(data["available_credit"]) == Decimal("100000.00")
        assert Decimal(data["pending_orders_total"]) == Decimal("0.00")
        assert Decimal(data["effective_available_credit"]) == Decimal("100000.00")
        assert Decimal(data["credit_utilization_percent"]) == Decimal("0.00")
    finally:
        clear_auth()


def test_cross_retailer_credit_access_is_forbidden(seeded_database) -> None:
    """Retailer 1 must be forbidden from inspecting Retailer 2's credit information."""
    with Session(seeded_database) as session:
        second_retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER-2")
        )
        assert second_retailer is not None
        second_id = str(second_retailer.id)

    # Retailer 1 logs in
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Attempting to view Retailer 2's credit returns 403 Forbidden
        resp = client.get(f"/retailers/{second_id}/credit")
        assert resp.status_code == 403
        assert "not authorized" in resp.json()["detail"]
    finally:
        clear_auth()


def test_order_desk_can_view_and_update_retailer_credit(seeded_database) -> None:
    """Order Desk user can inspect any retailer's credit and update limit and balance."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        assert retailer is not None
        retailer_id = str(retailer.id)

    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # 1. Order desk inspects retailer credit
        get_resp = client.get(f"/retailers/{retailer_id}/credit")
        assert get_resp.status_code == 200
        assert get_resp.json()["retailer_name"] == "Demo Retailer"

        # 2. Order desk updates credit limit and outstanding balance
        patch_resp = client.patch(
            f"/retailers/{retailer_id}/credit",
            json={
                "credit_limit": "75000.00",
                "current_outstanding": "15000.00",
            },
        )
        assert patch_resp.status_code == 200
        updated = patch_resp.json()
        assert Decimal(updated["credit_limit"]) == Decimal("75000.00")
        assert Decimal(updated["current_outstanding"]) == Decimal("15000.00")
        assert Decimal(updated["available_credit"]) == Decimal("60000.00")
        # Utilization: 15000 / 75000 = 20.00%
        assert Decimal(updated["credit_utilization_percent"]) == Decimal("20.00")
    finally:
        clear_auth()


def test_retailer_cannot_modify_own_credit_information(seeded_database) -> None:
    """Retailers are strictly forbidden from modifying credit limit or outstanding balance."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        assert retailer is not None
        retailer_id = str(retailer.id)

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"credit_limit": "500000.00"},
        )
        assert resp.status_code == 403
    finally:
        clear_auth()


def test_negative_credit_values_are_rejected(seeded_database) -> None:
    """Negative values for credit limit or outstanding balance must return 400 Bad Request."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer_id = str(retailer.id)

    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # Negative credit limit
        neg_limit = client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"credit_limit": "-1000.00"},
        )
        assert neg_limit.status_code == 400
        assert "cannot be negative" in neg_limit.json()["detail"]

        # Negative outstanding
        neg_out = client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"current_outstanding": "-500.00"},
        )
        assert neg_out.status_code == 400
        assert "cannot be negative" in neg_out.json()["detail"]
    finally:
        clear_auth()


# =====================================================================
# 2. Automatic Credit Check During Order Placement
# =====================================================================


def test_order_placement_with_sufficient_available_credit(seeded_database) -> None:
    """When order total is within available credit, order status is pending_review."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("50000.00")
        retailer.current_outstanding = Decimal("10000.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Order of 10 cases of biscuits: price 864.00 * 10 = 8640, with scheme: paid 9, delivered 10 -> total 7776.00
        resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert resp.status_code == 201
        order = resp.json()
        assert order["status"] == "pending_review"
        assert order["hold_reason"] is None
        assert Decimal(order["total"]) == Decimal("7776.00")
        assert Decimal(order["retailer_credit_limit"]) == Decimal("50000.00")
        assert Decimal(order["retailer_current_outstanding"]) == Decimal("10000.00")
        assert Decimal(order["retailer_available_credit"]) == Decimal("40000.00")
    finally:
        clear_auth()


def test_order_placement_exactly_equal_to_available_credit(seeded_database) -> None:
    """When order total exactly equals available credit, order status is pending_review."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        # 10 cases biscuit total is 7776.00
        retailer.credit_limit = Decimal("7776.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert resp.status_code == 201
        order = resp.json()
        assert order["status"] == "pending_review"
        assert order["hold_reason"] is None
        assert Decimal(order["total"]) == Decimal("7776.00")
    finally:
        clear_auth()


def test_order_placement_exceeding_available_credit_placed_on_credit_hold(
    seeded_database,
) -> None:
    """When order total exceeds available credit, order is automatically placed on credit_hold."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        # Limit 5,000 < order total 7,776.00
        retailer.credit_limit = Decimal("5000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert resp.status_code == 201
        order = resp.json()
        assert order["status"] == "credit_hold"
        assert order["hold_reason"] is not None
        assert "exceeds available credit" in order["hold_reason"]
        assert "7776.00" in order["hold_reason"]
    finally:
        clear_auth()


def test_zero_credit_limit_automatically_places_all_orders_on_credit_hold(
    seeded_database,
) -> None:
    """A retailer with zero credit limit has any non-zero order placed on credit hold."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("0.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 1}]},
        )
        assert resp.status_code == 201
        order = resp.json()
        assert order["status"] == "credit_hold"
        assert "exceeds available credit" in order["hold_reason"]
    finally:
        clear_auth()


def test_scheme_discounts_correctly_reflected_in_credit_calculation(
    seeded_database,
) -> None:
    """Credit calculation checks final payable amount after scheme discounts, not pre-discount subtotal."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        # Pre-discount subtotal for 5 cases of SKU-DP-1KG = 10150.00.
        # Net payable total after 3% scheme discount = 9845.50.
        # Set available credit to 10000.00 (which is < 10150.00 subtotal, but > 9845.50 net payable).
        retailer.credit_limit = Decimal("10000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-DP-1KG", "quantity": 5}]},
        )
        assert resp.status_code == 201
        order = resp.json()
        # Must pass credit check based on net payable amount (9845.50 <= 10000.00)
        assert order["status"] == "pending_review"
        assert order["hold_reason"] is None
        assert Decimal(order["total"]) == Decimal("9845.50")
        assert Decimal(order["subtotal"]) == Decimal("10150.00")
    finally:
        clear_auth()


# =====================================================================
# 3. Concurrent Orders & Exposure Double-Counting Protection
# =====================================================================


def test_concurrent_orders_exposure_and_held_orders_safety(
    seeded_database,
) -> None:
    """Pending orders reserve available credit; held orders do NOT reduce available credit twice."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        # Set limit to 10,000. Each 10-case order is 7,776.00.
        retailer.credit_limit = Decimal("10000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # 1. First order for 7,776.00 succeeds (7,776 <= 10,000)
        first_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert first_resp.status_code == 201
        assert first_resp.json()["status"] == "pending_review"

        # 2. Second order for 7,776.00 exceeds remaining effective credit (10,000 - 7,776 = 2,224)
        second_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert second_resp.status_code == 201
        assert second_resp.json()["status"] == "credit_hold"

        # 3. Third order for a smaller amount: 2 cases (price 864 * 2 = 1728.00)
        # Effective available credit is STILL 2,224.00 because held order does NOT reduce available credit!
        third_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 2}]},
        )
        assert third_resp.status_code == 201
        # 1728.00 <= 2224.00 -> passes!
        assert third_resp.json()["status"] == "pending_review"
    finally:
        clear_auth()


# =====================================================================
# 4. Credit Hold Decision & Explicit Release Workflow
# =====================================================================


def test_credit_hold_and_explicit_release_workflow(seeded_database) -> None:
    """Held orders cannot be approved directly; require explicit release_hold after credit adjustment."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("5000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()
        retailer_id = str(retailer.id)

    # 1. Retailer places order exceeding limit -> placed on credit_hold
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        order_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert order_resp.status_code == 201
        order = order_resp.json()
        assert order["status"] == "credit_hold"
        order_id = order["id"]
    finally:
        clear_auth()

    # 2. Order desk attempts to approve directly from credit_hold -> 409 Conflict
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        direct_approve = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        assert direct_approve.status_code == 409

        # 3. Order desk increases credit limit to 50,000
        patch_limit = client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"credit_limit": "50000.00"},
        )
        assert patch_limit.status_code == 200

        # Changing credit limit does NOT automatically release held order
        check_order = client.get(f"/orders/{order_id}")
        assert check_order.status_code == 200
        assert check_order.json()["status"] == "credit_hold"

        # 4. Order desk explicitly releases the hold -> status becomes pending_review
        release_resp = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "release_hold"},
        )
        assert release_resp.status_code == 200
        assert release_resp.json()["status"] == "pending_review"

        # 5. Now order desk approves the order -> status approved, outstanding updated
        approve_resp = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Verify retailer current_outstanding is incremented by order total (7776.00)
        credit_check = client.get(f"/retailers/{retailer_id}/credit")
        assert Decimal(credit_check.json()["current_outstanding"]) == Decimal("7776.00")
        assert Decimal(credit_check.json()["available_credit"]) == Decimal("42224.00")
    finally:
        clear_auth()


def test_order_approval_blocks_if_credit_was_exhausted(seeded_database) -> None:
    """Never silently approve an order if available credit was exhausted in the meantime."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("50000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()
        retailer_id = str(retailer.id)

    # 1. Retailer creates order for 7,776.00 with status pending_review
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        order_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]
        assert order_resp.json()["status"] == "pending_review"
    finally:
        clear_auth()

    # 2. Before approval, retailer outstanding increases to 45,000 (available credit becomes 5,000 < 7,776)
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"current_outstanding": "45000.00"},
        )

        # 3. Order desk attempts to approve -> blocked with 409 and order is placed on credit_hold
        approve_fail = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        assert approve_fail.status_code == 409
        assert "exceeds available credit" in approve_fail.json()["detail"]

        # Verify order was moved to credit_hold
        refreshed = client.get(f"/orders/{order_id}").json()
        assert refreshed["status"] == "credit_hold"
        assert "exceeds available credit" in refreshed["hold_reason"]
    finally:
        clear_auth()


def test_approved_order_tally_csv_export_regression(seeded_database) -> None:
    """Approved orders export Tally CSV correctly without regression."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        order_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        order_id = order_resp.json()["id"]
    finally:
        clear_auth()

    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # Approve
        client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        csv_resp = client.get(f"/orders/{order_id}/tally.csv")
        assert csv_resp.status_code == 200
        rows = list(csv.reader(StringIO(csv_resp.text)))
        assert rows[0][0] == "Order Number"
        assert rows[1][2] == "SKU-BS-075"
        assert rows[1][-1] == "7776.00"
    finally:
        clear_auth()


# =====================================================================
# 5. Approval-Time Formula, Idempotency & Balance Integrity Tests
# =====================================================================


def test_approval_time_credit_calculation_accounts_for_other_pending_orders(
    seeded_database,
) -> None:
    """Approval check uses effective_available = limit - outstanding - sum(other pending_review orders)."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        # Limit = 20,000. Outstanding = 0.
        retailer.credit_limit = Decimal("20000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()
        retailer_id = str(retailer.id)

    # 1. Retailer creates Order 1 (7,776.00) and Order 2 (7,776.00). Both in pending_review.
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        r1 = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert r1.status_code == 201
        order1_id = r1.json()["id"]
        assert r1.json()["status"] == "pending_review"

        r2 = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        assert r2.status_code == 201
        order2_id = r2.json()["id"]
        assert r2.json()["status"] == "pending_review"
    finally:
        clear_auth()

    # 2. Before approving Order 1, outstanding is adjusted to 10,000
    # Available credit = 20,000 - 10,000 = 10,000.
    # Other pending order (Order 2) = 7,776.00.
    # Effective available for Order 1 = 20,000 - 10,000 - 7,776 = 2,224.00.
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        client.patch(
            f"/retailers/{retailer_id}/credit",
            json={"current_outstanding": "10000.00"},
        )

        # 3. Order Desk attempts to approve Order 1 (7,776.00 > 2,224.00)
        # Must be blocked by approval-time credit check and placed on credit_hold
        approve_resp = client.patch(
            f"/orders/{order1_id}/decision",
            json={"action": "approve"},
        )
        assert approve_resp.status_code == 409
        assert "exceeds" in approve_resp.json()["detail"]

        order1_refreshed = client.get(f"/orders/{order1_id}").json()
        assert order1_refreshed["status"] == "credit_hold"
        assert "Other pending: ₹7776.00" in order1_refreshed["hold_reason"]

        # 4. Now that Order 1 is on credit_hold, it no longer counts towards pending exposure!
        # For Order 2: other pending orders = 0.
        # Effective available for Order 2 = 20,000 - 10,000 - 0 = 10,000.00.
        # Order 2 (7,776.00) <= 10,000.00 -> Order 2 can be approved!
        approve_order2 = client.patch(
            f"/orders/{order2_id}/decision",
            json={"action": "approve"},
        )
        assert approve_order2.status_code == 200
        assert approve_order2.json()["status"] == "approved"

        # Verify outstanding incremented once by Order 2: 10,000 + 7,776 = 17,776.00
        check_credit = client.get(f"/retailers/{retailer_id}/credit").json()
        assert Decimal(check_credit["current_outstanding"]) == Decimal("17776.00")
    finally:
        clear_auth()


def test_repeated_approval_fails_and_does_not_double_increment_outstanding(
    seeded_database,
) -> None:
    """An already approved order cannot be approved again; outstanding is never double incremented."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("50000.00")
        retailer.current_outstanding = Decimal("0.00")
        session.commit()
        retailer_id = str(retailer.id)

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        order_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        order_id = order_resp.json()["id"]
    finally:
        clear_auth()

    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # 1. First approval succeeds
        first_approve = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        assert first_approve.status_code == 200

        # Outstanding is 7,776.00
        credit_1 = client.get(f"/retailers/{retailer_id}/credit").json()
        assert Decimal(credit_1["current_outstanding"]) == Decimal("7776.00")

        # 2. Repeated approval fails with 409 Conflict
        repeat_approve = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "approve"},
        )
        assert repeat_approve.status_code == 409
        assert "not allowed from 'approved'" in repeat_approve.json()["detail"]

        # Outstanding remains exactly 7,776.00 (NOT incremented twice)
        credit_2 = client.get(f"/retailers/{retailer_id}/credit").json()
        assert Decimal(credit_2["current_outstanding"]) == Decimal("7776.00")
    finally:
        clear_auth()


def test_order_rejection_does_not_alter_outstanding_balance(
    seeded_database,
) -> None:
    """Rejecting a pending or held order never alters current_outstanding."""
    with Session(seeded_database) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        retailer.credit_limit = Decimal("50000.00")
        retailer.current_outstanding = Decimal("12000.00")
        session.commit()
        retailer_id = str(retailer.id)

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        order_resp = client.post(
            "/orders",
            json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
        )
        order_id = order_resp.json()["id"]
    finally:
        clear_auth()

    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # Reject the pending order
        reject_resp = client.patch(
            f"/orders/{order_id}/decision",
            json={"action": "reject", "note": "Duplicate order"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

        # Outstanding remains exactly 12,000.00
        credit = client.get(f"/retailers/{retailer_id}/credit").json()
        assert Decimal(credit["current_outstanding"]) == Decimal("12000.00")
    finally:
        clear_auth()


