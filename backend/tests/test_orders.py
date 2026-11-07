import csv
from decimal import Decimal
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.models import User

from app.main import app
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
def clear_orders_between_tests(seeded_database):
    clear_demo_orders(seeded_database)

    authenticate_as(seeded_database, "demo-retailer-user")

    yield

    clear_demo_orders(seeded_database)
    app.dependency_overrides.pop(get_current_user, None)


def create_demo_order() -> dict:
    response = client.post(
        "/orders",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 10}]},
    )

    assert response.status_code == 201
    return response.json()


def test_order_submission_recalculates_quote_and_waits_for_review(seeded_database) -> None:
    response = client.post(
        "/orders",
        json={
            "items": [{"sku": "SKU-BS-075", "quantity": 10}],
            "total": "0.01",
        },
    )

    assert response.status_code == 201
    order = response.json()
    assert order["source"] == "database"
    assert order["status"] == "pending_review"
    assert order["total"] == "7776.00"
    assert Decimal(order["free_quantity"]) == Decimal("1")
    assert order["lines"][0]["delivered_quantity"] == 11


def test_manual_credit_hold_requires_release_before_approval(seeded_database) -> None:
    order = create_demo_order()
    order_id = order["id"]
    authenticate_as(seeded_database, "demo-order-desk-user")

    held = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "place_on_hold", "note": "Manual review required"},
    )
    assert held.status_code == 200
    assert held.json()["status"] == "credit_hold"
    assert held.json()["note"] == "Manual review required"

    cannot_approve = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "approve"},
    )
    assert cannot_approve.status_code == 409

    released = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "release_hold"},
    )
    assert released.status_code == 200
    assert released.json()["status"] == "pending_review"
    assert released.json()["note"] == "Manual review required"

    approved = client.patch(
        f"/orders/{order_id}/decision",
        json={"action": "approve"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_approved_order_exports_tally_csv(seeded_database) -> None:
    order = create_demo_order()
    order_id = order["id"]
    authenticate_as(seeded_database, "demo-order-desk-user")
    before_approval = client.get(f"/orders/{order_id}/tally.csv")
    assert before_approval.status_code == 409

    client.patch(f"/orders/{order_id}/decision", json={"action": "approve"})
    response = client.get(f"/orders/{order_id}/tally.csv")

    assert response.status_code == 200
    assert "attachment; filename=" in response.headers["content-disposition"]
    rows = list(csv.reader(StringIO(response.text)))
    assert rows[0] == [
        "Order Number",
        "Order Date",
        "SKU",
        "Product Name",
        "Paid Quantity",
        "Free Quantity",
        "Delivered Quantity",
        "Unit",
        "Unit Price",
        "Line Subtotal",
        "Scheme Discount",
        "Line Total",
    ]
    assert rows[1][2:8] == ["SKU-BS-075", "Glucose biscuit", "10", "1", "11", "case"]
    assert rows[1][-1] == "7776.00"


def test_unknown_sku_cannot_create_an_order(seeded_database) -> None:
    response = client.post(
        "/orders",
        json={"items": [{"sku": "UNKNOWN", "quantity": 1}]},
    )

    assert response.status_code == 404
    assert client.get("/orders").json()["orders"] == []

def test_retailer_cannot_access_another_retailers_order(
    seeded_database,
) -> None:
    # First retailer creates an order
    order = create_demo_order()
    order_id = order["id"]

    # Switch login to the second retailer
    authenticate_as(
        seeded_database,
        "second-demo-retailer-user",
    )

    # Second retailer should not see the first retailer's orders
    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json()["orders"] == []

    # Second retailer should not access the first retailer's order
    response = client.get(f"/orders/{order_id}")

    assert response.status_code == 404