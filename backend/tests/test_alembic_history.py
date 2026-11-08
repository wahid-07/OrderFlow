"""Tests for Alembic migration graph, Phase 5 zero-stock migration, and downgrade integrity."""

import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Product, User


def _load_phase5_migration():
    versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    file_path = versions_dir / "20261108_0002_phase5_inventory_and_stock_movements.py"
    spec = importlib.util.spec_from_file_location("phase5_migration", file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alembic_single_head_and_linear_history():
    """Verify that Alembic migrations form a single linear chain without duplicate revisions or multiple heads."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    script = ScriptDirectory.from_config(alembic_cfg)

    # 1. Verify exactly one head revision exists
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 head, found {heads}"
    assert heads[0] == "20261108_0003", f"Expected head to be Phase 6 (20261108_0003), got {heads[0]}"

    # 2. Verify linear chain: Phase 4 -> Phase 5 -> Phase 6
    revisions = list(script.walk_revisions(base="base", head="20261108_0003"))
    rev_ids = [r.revision for r in reversed(revisions)]
    assert rev_ids == [
        "20261108_0001",
        "20261108_0002",
        "20261108_0003",
    ], f"Expected linear chain ['20261108_0001', '20261108_0002', '20261108_0003'], got {rev_ids}"

    # 3. Verify down_revision pointers
    rev_map = {r.revision: r.down_revision for r in revisions}
    assert rev_map["20261108_0001"] is None
    assert rev_map["20261108_0002"] == "20261108_0001"
    assert rev_map["20261108_0003"] == "20261108_0002"


def test_phase5_migration_zero_stock_initialization_and_audit():
    """Verify that Phase 5 upgrade initializes existing products with 0 stock and creates audit trail."""
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create baseline products and users tables
    Base.metadata.create_all(engine, tables=[Product.__table__, User.__table__])

    prod1 = Product(sku="SKU-BS-075", name="Glucose biscuit", pack_label="75 g")
    prod2 = Product(sku="SKU-DP-1KG", name="Detergent powder", pack_label="1 kg")
    prod3 = Product(sku="CUSTOM-PROD-001", name="Custom Product", pack_label="500 g")

    with Session(engine) as session:
        session.add_all([prod1, prod2, prod3])
        session.commit()

    phase5 = _load_phase5_migration()

    # Execute migration upgrade against SQLite test connection
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            phase5.upgrade()
        conn.commit()

    # Verify inventory records
    with engine.connect() as conn:
        inv_rows = conn.execute(
            sa.text("SELECT product_id, on_hand_stock, reserved_stock, low_stock_threshold FROM inventory")
        ).fetchall()
        assert len(inv_rows) == 3

        for row in inv_rows:
            # All products MUST have exactly 0 on_hand_stock and 0 reserved_stock (clean baseline)
            assert row[1] == 0, f"Expected on_hand_stock=0, got {row[1]}"
            assert row[2] == 0, f"Expected reserved_stock=0, got {row[2]}"
            assert row[3] == 10

        # Verify stock_movements audit trail
        movement_rows = conn.execute(
            sa.text(
                "SELECT product_id, movement_type, quantity, on_hand_before, "
                "on_hand_after, reference_id, reason FROM stock_movements"
            )
        ).fetchall()
        assert len(movement_rows) == 3

        for row in movement_rows:
            assert row[1] == "init"
            assert row[2] == 0
            assert row[3] == 0
            assert row[4] == 0
            assert row[5] == "ZERO-STOCK-INIT"
            assert "zero-stock" in row[6].lower()

        # Verify existing products were not altered or dropped
        product_rows = conn.execute(sa.text("SELECT id, sku FROM products")).fetchall()
        assert len(product_rows) == 3
        skus = {r[1] for r in product_rows}
        assert skus == {"SKU-BS-075", "SKU-DP-1KG", "CUSTOM-PROD-001"}


def test_phase5_migration_downgrade():
    """Verify that Phase 5 downgrade cleanly drops inventory and stock_movements tables without affecting products."""
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Product.__table__, User.__table__])

    with Session(engine) as session:
        session.add(Product(sku="SKU-BS-075", name="Glucose biscuit"))
        session.commit()

    phase5 = _load_phase5_migration()

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            phase5.upgrade()
        conn.commit()

        # Downgrade
        with Operations.context(ctx):
            phase5.downgrade()
        conn.commit()

        # Inspector check
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert "inventory" not in tables
        assert "stock_movements" not in tables
        assert "products" in tables

        # Verify product data is still intact
        products = conn.execute(sa.text("SELECT sku FROM products")).fetchall()
        assert len(products) == 1
        assert products[0][0] == "SKU-BS-075"


