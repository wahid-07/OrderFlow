from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_engine
from app.models import Base, Product, Retailer, RetailerPrice, Scheme, User


PRODUCTS = [
    # -------------------------------------------------------------
    # 1. Biscuits & Cookies
    # -------------------------------------------------------------
    {
        "sku": "SKU-BS-075",
        "name": "Glucose biscuit",
        "description": "Glucose biscuit 75 g",
        "pack_label": "75 g",
        "price": Decimal("777.60"),
        "scheme_name": "Buy 10 Get 1 Free",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-BC-MARIE",
        "name": "Marie Gold Biscuits",
        "description": "Britannia Marie Gold crisp tea biscuits 120 g",
        "pack_label": "120 g",
        "price": Decimal("920.00"),
        "scheme_name": "Buy 12 Get 1 Free - Marie Gold",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-BC-MARIE",
            "buy_quantity": 12,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-BC-BOURN",
        "name": "Bourbon Chocolate Cream Biscuits",
        "description": "Britannia Bourbon chocolate sandwich biscuits 150 g",
        "pack_label": "150 g",
        "price": Decimal("1140.00"),
        "scheme_name": "5+ Cases 4% Off - Bourbon",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-BC-BOURN",
            "minimum_quantity": 5,
            "discount_percent": 4,
        },
    },
    {
        "sku": "SKU-BC-OREO",
        "name": "Oreo Vanilla Creme Biscuits",
        "description": "Cadbury Oreo rich vanilla cream sandwich cookies 120 g",
        "pack_label": "120 g",
        "price": Decimal("1380.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-BC-GDAY",
        "name": "Good Day Butter Cookies",
        "description": "Britannia Good Day rich butter delight cookies 100 g",
        "pack_label": "100 g",
        "price": Decimal("1050.00"),
        "scheme_name": "Buy 15 Get 1 Free - Good Day",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-BC-GDAY",
            "buy_quantity": 15,
            "free_quantity": 1,
        },
    },

    # -------------------------------------------------------------
    # 2. Snacks & Namkeen
    # -------------------------------------------------------------
    {
        "sku": "SKU-SN-ALBHJ",
        "name": "Aloo Bhujia Namkeen",
        "description": "Haldiram's crispy spiced potato mint noodles 200 g",
        "pack_label": "200 g",
        "price": Decimal("1260.00"),
        "scheme_name": "5+ Cases 5% Off - Aloo Bhujia",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-SN-ALBHJ",
            "minimum_quantity": 5,
            "discount_percent": 5,
        },
    },
    {
        "sku": "SKU-SN-MNGDL",
        "name": "Moong Dal Salted",
        "description": "Bikaji crunchy roasted salted split yellow moong dal 180 g",
        "pack_label": "180 g",
        "price": Decimal("1180.00"),
        "scheme_name": "Buy 10 Get 1 Free - Moong Dal",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-SN-MNGDL",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-SN-LAYS",
        "name": "Lay's Classic Salted Potato Chips",
        "description": "Lay's golden crispy classic salted potato chips 50 g",
        "pack_label": "50 g",
        "price": Decimal("840.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-SN-KURK",
        "name": "Kurkure Masala Munch",
        "description": "Kurkure chatpata spicy masala munch crisps 90 g",
        "pack_label": "90 g",
        "price": Decimal("960.00"),
        "scheme_name": "Buy 12 Get 1 Free - Kurkure",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-SN-KURK",
            "buy_quantity": 12,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-SN-KHATA",
        "name": "Khatta Meetha Namkeen",
        "description": "Haldiram's sweet and sour blend of sev flakes and peas 200 g",
        "pack_label": "200 g",
        "price": Decimal("1150.00"),
        "scheme_name": "4+ Cases 3% Off - Khatta Meetha",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-SN-KHATA",
            "minimum_quantity": 4,
            "discount_percent": 3,
        },
    },

    # -------------------------------------------------------------
    # 3. Tea & Beverages
    # -------------------------------------------------------------
    {
        "sku": "SKU-TL-250",
        "name": "Tea leaf",
        "description": "Tea leaf 250 g",
        "pack_label": "250 g",
        "price": Decimal("4720.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-TB-REDLB",
        "name": "Red Label Strong Tea",
        "description": "Brooke Bond Red Label swad apnepan ka strong blend 500 g",
        "pack_label": "500 g",
        "price": Decimal("3850.00"),
        "scheme_name": "Buy 8 Get 1 Free - Red Label",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-TB-REDLB",
            "buy_quantity": 8,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-TB-TAJMH",
        "name": "Taj Mahal Royal Tea",
        "description": "Brooke Bond Taj Mahal premium rich aroma tea leaves 250 g",
        "pack_label": "250 g",
        "price": Decimal("4200.00"),
        "scheme_name": "5+ Cases 4% Off - Taj Mahal",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-TB-TAJMH",
            "minimum_quantity": 5,
            "discount_percent": 4,
        },
    },
    {
        "sku": "SKU-TB-NESCF",
        "name": "Nescafé Classic Instant Coffee",
        "description": "Nestlé Nescafé 100% pure instant coffee granules 100 g",
        "pack_label": "100 g",
        "price": Decimal("5100.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-TB-BOURN",
        "name": "Bournvita Nutrition Drink",
        "description": "Cadbury Bournvita chocolate nutrition health drink powder 500 g",
        "pack_label": "500 g",
        "price": Decimal("3400.00"),
        "scheme_name": "Buy 10 Get 1 Free - Bournvita",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-TB-BOURN",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },

    # -------------------------------------------------------------
    # 4. Home Care
    # -------------------------------------------------------------
    {
        "sku": "SKU-DP-1KG",
        "name": "Detergent powder",
        "description": "Detergent powder 1 kg",
        "pack_label": "1 kg",
        "price": Decimal("2030.00"),
        "scheme_name": "5+ Cases 3% Off",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "minimum_quantity": 5,
            "discount_percent": 3,
        },
    },
    {
        "sku": "SKU-HC-RINBR",
        "name": "Rin Detergent Bar",
        "description": "Rin advanced whiteness laundry detergent soap bar 250 g",
        "pack_label": "250 g",
        "price": Decimal("1240.00"),
        "scheme_name": "Buy 15 Get 2 Free - Rin Bar",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-HC-RINBR",
            "buy_quantity": 15,
            "free_quantity": 2,
        },
    },
    {
        "sku": "SKU-HC-VIMGL",
        "name": "Vim Dishwash Gel",
        "description": "Vim lemon concentrate degreasing dishwash gel bottle 500 ml",
        "pack_label": "500 ml",
        "price": Decimal("1680.00"),
        "scheme_name": "Buy 10 Get 1 Free - Vim Gel",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-HC-VIMGL",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-HC-LYSOL",
        "name": "Lysol Disinfectant Surface Cleaner",
        "description": "Lysol citrus floral antibacterial floor cleaner liquid 500 ml",
        "pack_label": "500 ml",
        "price": Decimal("2150.00"),
        "scheme_name": "5+ Cases 5% Off - Lysol",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-HC-LYSOL",
            "minimum_quantity": 5,
            "discount_percent": 5,
        },
    },
    {
        "sku": "SKU-HC-HARPC",
        "name": "Harpic Power Plus Toilet Cleaner",
        "description": "Harpic 10x max power disinfectant toilet cleaner gel 500 ml",
        "pack_label": "500 ml",
        "price": Decimal("1920.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },

    # -------------------------------------------------------------
    # 5. Personal Care
    # -------------------------------------------------------------
    {
        "sku": "SKU-PC-DOVE",
        "name": "Dove Daily Shine Soap",
        "description": "Dove 1/4th moisturizing cream beauty bathing bar 100 g",
        "pack_label": "100 g",
        "price": Decimal("1560.00"),
        "scheme_name": "Buy 10 Get 1 Free - Dove Soap",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-PC-DOVE",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-PC-DETTL",
        "name": "Dettol Original Antiseptic Soap",
        "description": "Dettol 99.9% germ protection antibacterial soap 125 g",
        "pack_label": "125 g",
        "price": Decimal("1420.00"),
        "scheme_name": "5+ Cases 3% Off - Dettol Soap",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-PC-DETTL",
            "minimum_quantity": 5,
            "discount_percent": 3,
        },
    },
    {
        "sku": "SKU-PC-COLGT",
        "name": "Colgate Strong Teeth Toothpaste",
        "description": "Colgate calcium boost anticavity daily dental toothpaste 200 g",
        "pack_label": "200 g",
        "price": Decimal("1850.00"),
        "scheme_name": "Buy 12 Get 1 Free - Colgate",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-PC-COLGT",
            "buy_quantity": 12,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-PC-CLINC",
        "name": "Clinic Plus Strong & Long Shampoo",
        "description": "Clinic Plus milk protein health and vitality shampoo 340 ml",
        "pack_label": "340 ml",
        "price": Decimal("2240.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-PC-NYCVL",
        "name": "Nycil Cool Prickly Heat Powder",
        "description": "Nycil herbal germ defense cooling body talcum powder 150 g",
        "pack_label": "150 g",
        "price": Decimal("1780.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },

    # -------------------------------------------------------------
    # 6. Chocolates & Confectionery
    # -------------------------------------------------------------
    {
        "sku": "SKU-CC-DRYML",
        "name": "Cadbury Dairy Milk Chocolate",
        "description": "Cadbury Dairy Milk smooth rich milk chocolate bar 50 g",
        "pack_label": "50 g",
        "price": Decimal("1600.00"),
        "scheme_name": "Buy 10 Get 1 Free - Dairy Milk",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-CC-DRYML",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-CC-KITKT",
        "name": "KitKat 4-Finger Wafer",
        "description": "Nestlé KitKat crisp chocolate covered wafer bar 38 g",
        "pack_label": "38 g",
        "price": Decimal("1450.00"),
        "scheme_name": "5+ Cases 4% Off - KitKat",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-CC-KITKT",
            "minimum_quantity": 5,
            "discount_percent": 4,
        },
    },
    {
        "sku": "SKU-CC-5STAR",
        "name": "Cadbury 5 Star Chocolate Bar",
        "description": "Cadbury 5 Star caramel and nougat rich chocolate 40 g",
        "pack_label": "40 g",
        "price": Decimal("1200.00"),
        "scheme_name": "Buy 12 Get 1 Free - 5 Star",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-CC-5STAR",
            "buy_quantity": 12,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-CC-PERK",
        "name": "Cadbury Perk Chocolate Wafer",
        "description": "Cadbury Perk light crunchy chocolate layered wafer 28 g",
        "pack_label": "28 g",
        "price": Decimal("980.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-CC-ECLRS",
        "name": "Cadbury Choclairs Gold Candy",
        "description": "Cadbury Choclairs Gold chewy caramel with chocolate centre pouch",
        "pack_label": "200 pcs pouch",
        "price": Decimal("1350.00"),
        "scheme_name": "Buy 10 Get 1 Free - Choclairs",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-CC-ECLRS",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },

    # -------------------------------------------------------------
    # 7. Food Essentials
    # -------------------------------------------------------------
    {
        "sku": "SKU-FE-AASH",
        "name": "Aashirvaad Superior Sharbati Atta",
        "description": "Aashirvaad 100% whole wheat stone ground chakki atta 5 kg",
        "pack_label": "5 kg",
        "price": Decimal("2450.00"),
        "scheme_name": "5+ Cases 3% Off - Aashirvaad Atta",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-FE-AASH",
            "minimum_quantity": 5,
            "discount_percent": 3,
        },
    },
    {
        "sku": "SKU-FE-FORTN",
        "name": "Fortune Sunlite Refined Sunflower Oil",
        "description": "Fortune Sunlite light and healthy refined sunflower cooking oil 1 L",
        "pack_label": "1 L",
        "price": Decimal("2100.00"),
        "scheme_name": "Buy 10 Get 1 Free - Fortune Oil",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-FE-FORTN",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-FE-TATST",
        "name": "Tata Salt Vacuum Evaporated",
        "description": "Tata Salt iodized vacuum evaporated purity guaranteed salt 1 kg",
        "pack_label": "1 kg",
        "price": Decimal("720.00"),
        "scheme_name": "Buy 20 Get 1 Free - Tata Salt",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-FE-TATST",
            "buy_quantity": 20,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-FE-DHWAT",
        "name": "Daawat Rozana Gold Basmati Rice",
        "description": "Daawat Rozana Gold aromatic aged long grain basmati rice 5 kg",
        "pack_label": "5 kg",
        "price": Decimal("3100.00"),
        "scheme_name": "Tiered Volume Discount - Daawat Rice",
        "scheme_type": "slab_discount",
        "scheme_definition": {
            "sku": "SKU-FE-DHWAT",
            "tiers": [
                {"min_quantity": 5, "max_quantity": 9, "discount_percent": 3},
                {"min_quantity": 10, "max_quantity": 24, "discount_percent": 5},
                {"min_quantity": 25, "max_quantity": None, "discount_percent": 8},
            ],
            "priority": 0,
            "is_stackable": False,
        },
    },
    {
        "sku": "SKU-FE-EVERM",
        "name": "Everest Turmeric Powder",
        "description": "Everest pure aromatic natural golden turmeric haldi powder 200 g",
        "pack_label": "200 g",
        "price": Decimal("1380.00"),
        "scheme_name": "5+ Cases 4% Off - Everest Turmeric",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-FE-EVERM",
            "minimum_quantity": 5,
            "discount_percent": 4,
        },
    },

    # -------------------------------------------------------------
    # 8. Instant Foods
    # -------------------------------------------------------------
    {
        "sku": "SKU-IF-MAGGI",
        "name": "Maggi 2-Minute Masala Noodles",
        "description": "Nestlé Maggi 2-minute instant masala spiced noodles 70 g",
        "pack_label": "70 g",
        "price": Decimal("1120.00"),
        "scheme_name": "Buy 10 Get 1 Free - Maggi Noodles",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-IF-MAGGI",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-IF-YIPPE",
        "name": "Sunfeast YiPPee! Magic Masala Noodles",
        "description": "Sunfeast YiPPee! non-sticky round block masala instant noodles 65 g",
        "pack_label": "65 g",
        "price": Decimal("1040.00"),
        "scheme_name": "Buy 12 Get 1 Free - YiPPee Noodles",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-IF-YIPPE",
            "buy_quantity": 12,
            "free_quantity": 1,
        },
    },
    {
        "sku": "SKU-IF-TOPRM",
        "name": "Top Ramen Curry Veg Noodles",
        "description": "Nissin Top Ramen saucy delicious curry instant noodles 70 g",
        "pack_label": "70 g",
        "price": Decimal("990.00"),
        "scheme_name": None,
        "scheme_type": None,
        "scheme_definition": None,
    },
    {
        "sku": "SKU-IF-KNORS",
        "name": "Knorr Classic Thick Tomato Soup",
        "description": "Knorr 100% real vegetables classic thick tomato instant soup 53 g",
        "pack_label": "53 g",
        "price": Decimal("1250.00"),
        "scheme_name": "5+ Cases 3% Off - Knorr Soup",
        "scheme_type": "quantity_discount",
        "scheme_definition": {
            "sku": "SKU-IF-KNORS",
            "minimum_quantity": 5,
            "discount_percent": 3,
        },
    },
    {
        "sku": "SKU-IF-MTRUP",
        "name": "MTR Instant Rava Upma Mix",
        "description": "MTR traditional south Indian roasted semolina rava upma breakfast mix 160 g",
        "pack_label": "160 g",
        "price": Decimal("1420.00"),
        "scheme_name": "Buy 10 Get 1 Free - MTR Upma",
        "scheme_type": "buy_x_get_y",
        "scheme_definition": {
            "sku": "SKU-IF-MTRUP",
            "buy_quantity": 10,
            "free_quantity": 1,
        },
    },
]


def seed():
    engine = get_engine()

    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE retailers ADD COLUMN IF NOT EXISTS contact_person VARCHAR(200);"))
        conn.execute(text("ALTER TABLE retailers ADD COLUMN IF NOT EXISTS address VARCHAR(500);"))
        conn.commit()

    with Session(engine) as session:
        retailer = session.execute(
            select(Retailer).where(
                Retailer.external_ref == "DEMO-RETAILER"
            )
        ).scalar_one_or_none()

        if retailer is None:
            retailer = Retailer(
                name="Demo Retailer",
                external_ref="DEMO-RETAILER",
                phone="9999999999",
                is_active=True,
            )
            session.add(retailer)
            session.flush()

        demo_user = session.execute(
            select(User).where(
                User.auth_subject == "demo-retailer-user"
            )
        ).scalar_one_or_none()

        if demo_user is None:
            demo_user = User(
                auth_subject="demo-retailer-user",
                role="retailer",
                retailer_id=retailer.id,
                is_active=True,
            )
            session.add(demo_user)

        for data in PRODUCTS:
            product = session.execute(
                select(Product).where(Product.sku == data["sku"])
            ).scalar_one_or_none()

            if product is None:
                product = Product(
                    sku=data["sku"],
                    name=data["name"],
                    description=data["description"],
                    pack_label=data["pack_label"],
                    is_active=True,
                )
                session.add(product)
                session.flush()

            price = session.execute(
                select(RetailerPrice).where(
                    RetailerPrice.retailer_id == retailer.id,
                    RetailerPrice.product_id == product.id,
                )
            ).scalar_one_or_none()

            if price is None:
                session.add(
                    RetailerPrice(
                        retailer_id=retailer.id,
                        product_id=product.id,
                        unit_price=data["price"],
                    )
                )

            if data["scheme_type"]:
                existing_scheme = session.execute(
                    select(Scheme).where(
                        Scheme.name == data["scheme_name"],
                        Scheme.scheme_type == data["scheme_type"],
                    )
                ).scalar_one_or_none()

                if existing_scheme is None:
                    session.add(
                        Scheme(
                            name=data["scheme_name"],
                            scheme_type=data["scheme_type"],
                            definition=data["scheme_definition"],
                            is_active=True,
                        )
                    )

        session.commit()

    print("PostgreSQL seed completed successfully (40 products, categories, schemes, and retailer prices)")


if __name__ == "__main__":
    seed()
