from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db_session
from app.main import app
from app.auth import get_current_user
from app.models import Base, Product, Retailer, RetailerPrice, Scheme, User


@pytest.fixture
def catalogue_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        retailer = Retailer(name="Seeded retailer", external_ref="DEMO-RETAILER")
        session.add(retailer)
        session.flush()
        catalogue_user = User(
            auth_subject="catalogue-retailer-user",
            role="retailer",
            retailer_id=retailer.id,
            is_active=True,
        )

        session.add(catalogue_user)
        session.flush()

        catalogue_user_id = catalogue_user.id

        products = [
            Product(sku="SKU-BS-075", name="Glucose biscuit", pack_label="75 g"),
            Product(sku="SKU-DP-1KG", name="Detergent powder", pack_label="1 kg"),
            Product(sku="SKU-TL-250", name="Tea leaf", pack_label="250 g"),
        ]
        session.add_all(products)
        session.flush()
        session.add_all(
            [
                RetailerPrice(
                    retailer_id=retailer.id,
                    product_id=products[0].id,
                    unit_price=Decimal("777.60"),
                ),
                RetailerPrice(
                    retailer_id=retailer.id,
                    product_id=products[1].id,
                    unit_price=Decimal("2030.00"),
                ),
                RetailerPrice(
                    retailer_id=retailer.id,
                    product_id=products[2].id,
                    unit_price=Decimal("4720.00"),
                ),
            ]
        )
        session.add_all(
            [
                Scheme(
                    name="Buy 10 Get 1 Free",
                    scheme_type="buy_x_get_y",
                    definition={"buy_quantity": 10, "free_quantity": 1},
                ),
                Scheme(
                    name="5+ Cases 3% Off",
                    scheme_type="quantity_discount",
                    definition={"minimum_quantity": 5, "discount_percent": 3},
                ),
            ]
        )
        session.commit()

    def override_db_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    def override_current_user() -> User:
        with Session(engine) as session:
            user = session.get(User, catalogue_user_id)
            assert user is not None
            return user

    app.dependency_overrides[get_current_user] = override_current_user
    try:
        with TestClient(app) as test_client:
            yield test_client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_catalogue_reads_retailer_products_prices_and_legacy_schemes(
    catalogue_client: tuple[TestClient, object],
) -> None:
    test_client, _ = catalogue_client
    response = test_client.get("/catalogue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "database"
    products = {item["sku"]: item for item in payload["items"]}

    assert list(products) == ["SKU-BS-075", "SKU-DP-1KG", "SKU-TL-250"]
    assert [products[sku]["unit_price"] for sku in products] == [
        "777.60",
        "2030.00",
        "4720.00",
    ]
    assert [products[sku]["stock_quantity"] for sku in products] == [340, 85, 0]
    assert products["SKU-BS-075"]["scheme_label"] == "10+ cases → 1 free"
    assert products["SKU-DP-1KG"]["scheme_label"] == "5+ cases → 3% off"
    assert products["SKU-TL-250"]["scheme_label"] is None
    assert all("scheme_rule" not in item for item in products.values())


def test_catalogue_prefers_sku_in_scheme_definition(
    catalogue_client: tuple[TestClient, object],
) -> None:
    test_client, engine = catalogue_client
    with Session(engine) as session:
        session.add(
            Scheme(
                name="Extra biscuit scheme",
                scheme_type="buy_x_get_y",
                definition={
                    "sku": "SKU-TL-250",
                    "buy_quantity": 4,
                    "free_quantity": 1,
                },
            )
        )
        session.commit()

    response = test_client.get("/catalogue")
    products = {item["sku"]: item for item in response.json()["items"]}
    assert products["SKU-TL-250"]["scheme_label"] == "4+ cases → 1 free"
    
    
@pytest.mark.parametrize(
    ("quantity", "expected_free"),
    [(10, 1), (20, 2)],
)
def test_biscuit_buy_x_get_y_uses_database_rule(
    catalogue_client: tuple[TestClient, object],
    quantity: int,
    expected_free: int,
) -> None:
    test_client, _ = catalogue_client
    response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-BS-075", "quantity": quantity}]},
    )

    assert response.status_code == 200
    quote = response.json()
    line = quote["lines"][0]
    expected_subtotal = Decimal("777.60") * quantity
    assert quote["source"] == "database"
    assert line["unit_price"] == "777.60"
    assert line["subtotal"] == str(expected_subtotal.quantize(Decimal("0.01")))
    assert line["free_quantity"] == expected_free
    assert line["delivered_quantity"] == quantity + expected_free
    assert line["discount"] == "0.00"
    assert line["total"] == line["subtotal"]

    
@pytest.mark.parametrize(
    ("quantity", "expected_discount", "expected_total"),
    [
        (4, "0.00", "8120.00"),
        (5, "304.50", "9845.50"),
    ],
)
def test_detergent_discount_uses_database_rule(
    catalogue_client: tuple[TestClient, object],
    quantity: int,
    expected_discount: str,
    expected_total: str,
) -> None:
    test_client, _ = catalogue_client
    response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-DP-1KG", "quantity": quantity}]},
    )

    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["unit_price"] == "2030.00"
    assert line["discount"] == expected_discount
    assert line["total"] == expected_total


def test_tea_quote_uses_database_price_without_a_scheme(
    catalogue_client: tuple[TestClient, object],
) -> None:
    test_client, _ = catalogue_client
    response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-TL-250", "quantity": 1}]},
    )

    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["unit_price"] == "4720.00"
    assert line["scheme_label"] is None
    assert line["free_quantity"] == 0
    assert line["discount"] == "0.00"
    assert line["total"] == "4720.00"


def test_quote_uses_the_authenticated_retailer_price(
    catalogue_client,
) -> None:
    test_client, engine = catalogue_client

    with Session(engine) as session:
        retailer = Retailer(
            name="Alternate retailer",
            external_ref="ALT-RETAILER",
        )
        session.add(retailer)
        session.flush()

        alternate_user = User(
            auth_subject="alternate-retailer-user",
            role="retailer",
            retailer_id=retailer.id,
            is_active=True,
        )
        session.add(alternate_user)
        session.flush()

        product = session.scalar(
            select(Product).where(Product.sku == "SKU-BS-075")
        )
        assert product is not None

        session.add(
            RetailerPrice(
                retailer_id=retailer.id,
                product_id=product.id,
                unit_price=Decimal("999.00"),
            )
        )
        session.commit()

    def override_alternate_user():
        with Session(engine) as session:
            user = session.scalar(
                select(User).where(
                    User.auth_subject == "alternate-retailer-user"
                )
            )
            assert user is not None
            session.expunge(user)
            return user

    app.dependency_overrides[get_current_user] = override_alternate_user

    response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 1}]},
    )

    assert response.status_code == 200
    assert response.json()["lines"][0]["unit_price"] == "999.00"
    assert response.json()["total"] == "999.00"


def test_catalogue_and_quote_use_latest_active_retailer_price(
    catalogue_client: tuple[TestClient, object],
) -> None:
    test_client, engine = catalogue_client
    with Session(engine) as session:
        retailer = session.scalar(
            select(Retailer).where(Retailer.external_ref == "DEMO-RETAILER")
        )
        product = session.scalar(
            select(Product).where(Product.sku == "SKU-BS-075")
        )
        assert retailer is not None
        assert product is not None
        session.add(
            RetailerPrice(
                retailer_id=retailer.id,
                product_id=product.id,
                unit_price=Decimal("888.00"),
                valid_from=datetime.now(timezone.utc),
            )
        )
        session.commit()

    catalogue_response = test_client.get("/catalogue")
    catalogue_products = {
        item["sku"]: item for item in catalogue_response.json()["items"]
    }
    quote_response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 1}]},
    )

    assert catalogue_products["SKU-BS-075"]["unit_price"] == "888.00"
    assert quote_response.json()["lines"][0]["unit_price"] == "888.00"
    assert quote_response.json()["total"] == "888.00"


def test_quote_rejects_inactive_product(
    catalogue_client: tuple[TestClient, object],
) -> None:
    test_client, engine = catalogue_client
    with Session(engine) as session:
        product = session.scalar(
            select(Product).where(Product.sku == "SKU-BS-075")
        )
        assert product is not None
        product.is_active = False
        session.commit()

    response = test_client.post(
        "/cart/quote",
        json={"items": [{"sku": "SKU-BS-075", "quantity": 1}]},
    )

    assert response.status_code == 404


def test_catalogue_rejects_user_without_retailer_link() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(
            auth_subject="unlinked-retailer-user",
            role="retailer",
            retailer_id=None,
            is_active=True,
        )
        session.add(user)
        session.commit()
        user_id = user.id

    def override_db_session():
        with Session(engine) as session:
            yield session

    def override_current_user():
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            session.expunge(user)
            return user

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as test_client:
            response = test_client.get("/catalogue")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        engine.dispose()

    assert response.status_code == 403