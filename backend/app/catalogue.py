import logging
import os
from uuid import UUID
from pathlib import Path
from dotenv import load_dotenv
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from app.auth import require_roles

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import Product, Retailer, RetailerPrice, Scheme, User
from app.scheme_engine import BuyXGetYScheme, QuantityDiscountScheme, SchemeRule

logger = logging.getLogger(__name__)
router = APIRouter()


PRODUCT_PRESENTATION = {
    # 1. Biscuits & Cookies
    "SKU-BS-075": {
        "category": "Biscuits & Cookies",
        "brand": "Parle-G",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1558961363-fa8fdf82db35"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-BC-MARIE": {
        "category": "Biscuits & Cookies",
        "brand": "Britannia",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1590080875515-8a3a8dc5735e"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-BC-BOURN": {
        "category": "Biscuits & Cookies",
        "brand": "Britannia",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1583743814966-8936f5b7be1a"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-BC-OREO": {
        "category": "Biscuits & Cookies",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1563729784474-d77dbb933a9e"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-BC-GDAY": {
        "category": "Biscuits & Cookies",
        "brand": "Britannia",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1509440159596-0249088772ff"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 2. Snacks & Namkeen
    "SKU-SN-ALBHJ": {
        "category": "Snacks & Namkeen",
        "brand": "Haldiram's",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1626082927389-6cd097cdc6ec"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-SN-MNGDL": {
        "category": "Snacks & Namkeen",
        "brand": "Bikaji",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1601050690597-df0568f70950"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-SN-LAYS": {
        "category": "Snacks & Namkeen",
        "brand": "Lay's",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1566478989037-eec170784d0b"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-SN-KURK": {
        "category": "Snacks & Namkeen",
        "brand": "Kurkure",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1621996346565-e3d5d6281729"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-SN-KHATA": {
        "category": "Snacks & Namkeen",
        "brand": "Haldiram's",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1599488615731-7e5c2823ff28"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 3. Tea & Beverages
    "SKU-TL-250": {
        "category": "Tea & Beverages",
        "brand": "Tata Tea",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1556679343-c7306c1976bc"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-TB-REDLB": {
        "category": "Tea & Beverages",
        "brand": "Brooke Bond",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1576092768241-dec231879fc3"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-TB-TAJMH": {
        "category": "Tea & Beverages",
        "brand": "Brooke Bond",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1544787219-7f47ccb76574"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-TB-NESCF": {
        "category": "Tea & Beverages",
        "brand": "Nestlé",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-TB-BOURN": {
        "category": "Tea & Beverages",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1584473457406-6240486418e9"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 4. Home Care
    "SKU-DP-1KG": {
        "category": "Home Care",
        "brand": "Surf Excel",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1649005011845-ef225c89da86"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-HC-RINBR": {
        "category": "Home Care",
        "brand": "Rin",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1610557892470-55d9e80c0bce"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-HC-VIMGL": {
        "category": "Home Care",
        "brand": "Vim",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1585421514738-01798e348b17"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-HC-LYSOL": {
        "category": "Home Care",
        "brand": "Lysol",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1584813470613-5b1c1cad3d69"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-HC-HARPC": {
        "category": "Home Care",
        "brand": "Harpic",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1585421514284-efb74c2b69ba"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 5. Personal Care
    "SKU-PC-DOVE": {
        "category": "Personal Care",
        "brand": "Dove",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1608248597359-5437894a47f4"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-PC-DETTL": {
        "category": "Personal Care",
        "brand": "Dettol",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1607613009820-a29f7bb81c04"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-PC-COLGT": {
        "category": "Personal Care",
        "brand": "Colgate",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1559567249-663c0a4b6ea4"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-PC-CLINC": {
        "category": "Personal Care",
        "brand": "Clinic Plus",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1535585209827-a15fcdbc4c2d"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-PC-NYCVL": {
        "category": "Personal Care",
        "brand": "Nycil",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 6. Chocolates & Confectionery
    "SKU-CC-DRYML": {
        "category": "Chocolates & Confectionery",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1549007994-cb92caebd54b"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-CC-KITKT": {
        "category": "Chocolates & Confectionery",
        "brand": "Nestlé",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1582293041079-7814c2f12063"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-CC-5STAR": {
        "category": "Chocolates & Confectionery",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1606313564200-e75d5e30476c"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-CC-PERK": {
        "category": "Chocolates & Confectionery",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1575224300306-1b8da36134ec"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-CC-ECLRS": {
        "category": "Chocolates & Confectionery",
        "brand": "Cadbury",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1579372786545-d24232daf58c"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 7. Food Essentials
    "SKU-FE-AASH": {
        "category": "Food Essentials",
        "brand": "Aashirvaad",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1509440159596-0249088772ff"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-FE-FORTN": {
        "category": "Food Essentials",
        "brand": "Fortune",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-FE-TATST": {
        "category": "Food Essentials",
        "brand": "Tata Salt",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1518977676601-b53f82aba655"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-FE-DHWAT": {
        "category": "Food Essentials",
        "brand": "Daawat",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1586201375761-83865001e31c"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-FE-EVERM": {
        "category": "Food Essentials",
        "brand": "Everest",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1615485290382-441e4d049cb5"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },

    # 8. Instant Foods
    "SKU-IF-MAGGI": {
        "category": "Instant Foods",
        "brand": "Nestlé",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1612927601601-6638404737ce"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-IF-YIPPE": {
        "category": "Instant Foods",
        "brand": "Sunfeast",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1569718212165-3a8278d5f624"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-IF-TOPRM": {
        "category": "Instant Foods",
        "brand": "Nissin",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1552611052-33e04de081de"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-IF-KNORS": {
        "category": "Instant Foods",
        "brand": "Knorr",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1547592166-23ac45744acd"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
    "SKU-IF-MTRUP": {
        "category": "Instant Foods",
        "brand": "MTR",
        "order_unit": "case",
        "image_url": (
            "https://images.unsplash.com/photo-1589301760014-d929f3979dbc"
            "?auto=format&fit=crop&w=720&q=85"
        ),
    },
}

STOCK_BY_SKU = {
    # 1. Biscuits & Cookies
    "SKU-BS-075": 340,
    "SKU-BC-MARIE": 150,
    "SKU-BC-BOURN": 90,
    "SKU-BC-OREO": 110,
    "SKU-BC-GDAY": 180,

    # 2. Snacks & Namkeen
    "SKU-SN-ALBHJ": 140,
    "SKU-SN-MNGDL": 85,
    "SKU-SN-LAYS": 210,
    "SKU-SN-KURK": 160,
    "SKU-SN-KHATA": 75,

    # 3. Tea & Beverages
    "SKU-TL-250": 0,
    "SKU-TB-REDLB": 120,
    "SKU-TB-TAJMH": 65,
    "SKU-TB-NESCF": 90,
    "SKU-TB-BOURN": 110,

    # 4. Home Care
    "SKU-DP-1KG": 85,
    "SKU-HC-RINBR": 200,
    "SKU-HC-VIMGL": 130,
    "SKU-HC-LYSOL": 95,
    "SKU-HC-HARPC": 160,

    # 5. Personal Care
    "SKU-PC-DOVE": 140,
    "SKU-PC-DETTL": 190,
    "SKU-PC-COLGT": 175,
    "SKU-PC-CLINC": 115,
    "SKU-PC-NYCVL": 0,

    # 6. Chocolates & Confectionery
    "SKU-CC-DRYML": 220,
    "SKU-CC-KITKT": 180,
    "SKU-CC-5STAR": 150,
    "SKU-CC-PERK": 240,
    "SKU-CC-ECLRS": 130,

    # 7. Food Essentials
    "SKU-FE-AASH": 160,
    "SKU-FE-FORTN": 125,
    "SKU-FE-TATST": 310,
    "SKU-FE-DHWAT": 95,
    "SKU-FE-EVERM": 140,

    # 8. Instant Foods
    "SKU-IF-MAGGI": 280,
    "SKU-IF-YIPPE": 190,
    "SKU-IF-TOPRM": 110,
    "SKU-IF-KNORS": 130,
    "SKU-IF-MTRUP": 85,
}

LEGACY_SCHEME_SKUS = {
    ("Buy 10 Get 1 Free", "buy_x_get_y"): "SKU-BS-075",
    ("5+ Cases 3% Off", "quantity_discount"): "SKU-DP-1KG",
}


def get_catalogue_retailer(
    session: Session,
    retailer_id: UUID,
) -> Retailer:
    retailer = session.scalar(
        select(Retailer).where(
            Retailer.id == retailer_id,
            Retailer.is_active.is_(True),
        )
    )

    if retailer is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Retailer is inactive or not available",
        )

    return retailer


def get_active_schemes(session: Session) -> list[Scheme]:
    now = datetime.now(timezone.utc)
    return list(
        session.scalars(
            select(Scheme)
            .where(
                Scheme.is_active.is_(True),
                or_(Scheme.starts_at.is_(None), Scheme.starts_at <= now),
                or_(Scheme.ends_at.is_(None), Scheme.ends_at >= now),
            )
            .order_by(Scheme.created_at.desc())
        )
    )


def resolve_scheme_for_sku(
    sku: str,
    schemes: Iterable[Scheme],
) -> tuple[str, SchemeRule] | None:
    for scheme in schemes:
        definition = scheme.definition or {}
        if "sku" in definition:
            associated_sku = definition.get("sku")
        else:
            associated_sku = LEGACY_SCHEME_SKUS.get(
                (scheme.name, scheme.scheme_type)
            )
        if associated_sku != sku:
            continue

        rule_fields = {key: value for key, value in definition.items() if key != "sku"}
        try:
            if scheme.scheme_type == "buy_x_get_y":
                rule = BuyXGetYScheme(type="buy_x_get_y", **rule_fields)
                label = f"{rule.buy_quantity}+ cases → {rule.free_quantity} free"
            elif scheme.scheme_type == "quantity_discount":
                rule = QuantityDiscountScheme(type="quantity_discount", **rule_fields)
                percent = format(rule.discount_percent.normalize(), "f")
                label = f"{rule.minimum_quantity}+ cases → {percent}% off"
            else:
                continue
        except (TypeError, ValidationError):
            logger.warning("Skipping invalid scheme definition %s", scheme.name)
            continue

        return label, rule
    return None


def active_price_conditions(now: datetime) -> tuple[object, object]:
    return (
        or_(RetailerPrice.valid_from.is_(None), RetailerPrice.valid_from <= now),
        or_(RetailerPrice.valid_to.is_(None), RetailerPrice.valid_to >= now),
    )


class CatalogueItem(BaseModel):
    sku: str
    name: str
    category: str
    brand: str | None = None
    pack_label: str
    order_unit: str
    unit_price: Decimal
    stock_quantity: int
    gst_status: str
    scheme_label: str | None
    image_url: str
    scheme_rule: BuyXGetYScheme | QuantityDiscountScheme | None = Field(
        default=None,
        exclude=True,
    )


class CatalogueResponse(BaseModel):
    source: Literal["database", "demo_fixture"]
    items: list[CatalogueItem]


DEMO_CATALOGUE = CatalogueResponse(
    source="demo_fixture",
    items=[
        CatalogueItem(
            sku="SKU-BS-075",
            name="Glucose biscuit",
            category="Biscuits & Cookies",
            brand="Parle-G",
            pack_label="75 g",
            order_unit="case",
            unit_price=Decimal("840.00"),
            stock_quantity=340,
            gst_status="Rate not configured",
            scheme_label="10 cases → 1 free",
            image_url=(
                "https://images.unsplash.com/photo-1558961363-fa8fdf82db35"
                "?auto=format&fit=crop&w=720&q=85"
            ),
            scheme_rule=BuyXGetYScheme(
                type="buy_x_get_y",
                buy_quantity=10,
                free_quantity=1,
            ),
        ),
        CatalogueItem(
            sku="SKU-DP-1KG",
            name="Detergent powder",
            category="Home Care",
            brand="Surf Excel",
            pack_label="1 kg",
            order_unit="case",
            unit_price=Decimal("980.00"),
            stock_quantity=85,
            gst_status="Rate not configured",
            scheme_label="5+ cases → 3% off",
            image_url=(
                "https://images.unsplash.com/photo-1649005011845-ef225c89da86"
                "?auto=format&fit=crop&w=720&q=85"
            ),
            scheme_rule=QuantityDiscountScheme(
                type="quantity_discount",
                minimum_quantity=5,
                discount_percent=Decimal("3"),
            ),
        ),
        CatalogueItem(
            sku="SKU-TL-250",
            name="Tea leaf",
            category="Tea & Beverages",
            brand="Tata Tea",
            pack_label="250 g",
            order_unit="case",
            unit_price=Decimal("1200.00"),
            stock_quantity=0,
            gst_status="Rate not configured",
            scheme_label=None,
            image_url=(
                "https://images.unsplash.com/photo-1556679343-c7306c1976bc"
                "?auto=format&fit=crop&w=720&q=85"
            ),
            scheme_rule=None,
        ),
    ],
)


@router.get("/catalogue", response_model=CatalogueResponse)
def get_catalogue(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[
        User,
        Depends(require_roles("retailer")),
    ],
) -> CatalogueResponse:

    if current_user.retailer_id is None:
        raise HTTPException(
            status_code=403,
            detail="User is not linked to a retailer",
        )

    retailer = get_catalogue_retailer(
        session,
        current_user.retailer_id,
    )
    now = datetime.now(timezone.utc)

    rows = session.execute(
        select(Product, RetailerPrice)
        .join(RetailerPrice, RetailerPrice.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            RetailerPrice.retailer_id == retailer.id,
            *active_price_conditions(now),
        )
        .order_by(
            Product.sku,
            RetailerPrice.valid_from.desc().nullslast(),
            RetailerPrice.created_at.desc(),
        )
    ).all()
    latest_rows: dict[str, tuple[Product, RetailerPrice]] = {}
    for product, retailer_price in rows:
        latest_rows.setdefault(product.sku, (product, retailer_price))
    schemes = get_active_schemes(session)

    items: list[CatalogueItem] = []
    for product, retailer_price in latest_rows.values():
        presentation = PRODUCT_PRESENTATION.get(product.sku, {})
        scheme = resolve_scheme_for_sku(product.sku, schemes)
        gst_status = (
            f"{product.gst_rate.normalize()}% configured"
            if product.gst_rate is not None
            else "Rate not configured"
        )
        items.append(
            CatalogueItem(
                sku=product.sku,
                name=product.name,
                category=presentation.get("category", "Other"),
                brand=presentation.get("brand"),
                pack_label=product.pack_label or "Pack not configured",
                order_unit=presentation.get("order_unit", "case"),
                unit_price=retailer_price.unit_price,
                stock_quantity=STOCK_BY_SKU.get(product.sku, 0),
                gst_status=gst_status,
                scheme_label=scheme[0] if scheme else None,
                image_url=presentation.get("image_url", ""),
                scheme_rule=scheme[1] if scheme else None,
            )
        )

    return CatalogueResponse(source="database", items=items)
