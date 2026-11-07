from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db_session
from app.auth import get_current_user
from app.main import app
from app.models import Base, Product, Retailer, RetailerPrice, Scheme, User


@pytest.fixture
def seeded_database() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        retailer = Retailer(
            name="Demo Retailer",
            external_ref="DEMO-RETAILER",
            is_active=True,
        )
        session.add(retailer)
        session.flush()

        demo_user = User(
            auth_subject="demo-retailer-user",
            role="retailer",
            retailer_id=retailer.id,
            is_active=True,
        )

        session.add(demo_user)
        session.flush()

        order_desk_user = User(
            auth_subject="demo-order-desk-user",
            role="order_desk",
            retailer_id=None,
            is_active=True,
        )

        session.add(order_desk_user)
        session.flush() 

        second_retailer = Retailer(
            name="Second Demo Retailer",
            external_ref="DEMO-RETAILER-2",
            is_active=True,
        )

        session.add(second_retailer)
        session.flush()

        second_retailer_user = User(
            auth_subject="second-demo-retailer-user",
            role="retailer",
            retailer_id=second_retailer.id,
            is_active=True,
        )

        session.add(second_retailer_user)
        session.flush()  

        products = [
            Product(
                sku="SKU-BS-075",
                name="Glucose biscuit",
                description="Glucose biscuit 75 g",
                pack_label="75 g",
                is_active=True,
            ),
            Product(
                sku="SKU-DP-1KG",
                name="Detergent powder",
                description="Detergent powder 1 kg",
                pack_label="1 kg",
                is_active=True,
            ),
            Product(
                sku="SKU-TL-250",
                name="Tea leaf",
                description="Tea leaf 250 g",
                pack_label="250 g",
                is_active=True,
            ),
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
                    is_active=True,
                ),
                Scheme(
                    name="5+ Cases 3% Off",
                    scheme_type="quantity_discount",
                    definition={"minimum_quantity": 5, "discount_percent": 3},
                    is_active=True,
                ),
            ]
        )
        session.commit()

    def override_db_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        yield engine
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()