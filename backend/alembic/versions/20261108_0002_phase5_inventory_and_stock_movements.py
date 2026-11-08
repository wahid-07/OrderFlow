"""Phase 5 Live inventory and stock movements tables with stock backfill.

Revision ID: 20261108_0002
Revises: 20261108_0001
Create Date: 2026-11-08 00:02:00.000000
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261108_0002"
down_revision: Union[str, None] = "20261108_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Option B: Zero-Stock Clean Baseline
# Products are initialized with on_hand_stock = 0 and reserved_stock = 0.
# Hardcoded demo quantities are not used in migration backfill to preserve data integrity.


def upgrade() -> None:
    # 1. Create inventory table with data integrity check constraints
    op.create_table(
        "inventory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("on_hand_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_inventory_product_id"),
        sa.CheckConstraint("reserved_stock >= 0", name="ck_inventory_reserved_non_negative"),
        sa.CheckConstraint("on_hand_stock >= 0", name="ck_inventory_on_hand_non_negative"),
        sa.CheckConstraint("reserved_stock <= on_hand_stock", name="ck_inventory_reserved_le_on_hand"),
    )
    op.create_index("ix_inventory_product_id", "inventory", ["product_id"], unique=True)

    # 2. Create stock_movements ledger table
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("movement_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("on_hand_before", sa.Integer(), nullable=False),
        sa.Column("on_hand_after", sa.Integer(), nullable=False),
        sa.Column("reserved_before", sa.Integer(), nullable=False),
        sa.Column("reserved_after", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_movements_product_id", "stock_movements", ["product_id"], unique=False)
    op.create_index("ix_stock_movements_movement_type", "stock_movements", ["movement_type"], unique=False)
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"], unique=False)

    # 3. Existing Product Stock Backfill (Idempotent: preserves existing inventory, creates missing rows)
    bind = op.get_bind()
    products_table = sa.table(
        "products",
        sa.column("id", sa.Uuid()),
        sa.column("sku", sa.String()),
    )
    inventory_table = sa.table(
        "inventory",
        sa.column("id", sa.Uuid()),
        sa.column("product_id", sa.Uuid()),
        sa.column("on_hand_stock", sa.Integer()),
        sa.column("reserved_stock", sa.Integer()),
        sa.column("low_stock_threshold", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    stock_movements_table = sa.table(
        "stock_movements",
        sa.column("id", sa.Uuid()),
        sa.column("product_id", sa.Uuid()),
        sa.column("movement_type", sa.String()),
        sa.column("quantity", sa.Integer()),
        sa.column("on_hand_before", sa.Integer()),
        sa.column("on_hand_after", sa.Integer()),
        sa.column("reserved_before", sa.Integer()),
        sa.column("reserved_after", sa.Integer()),
        sa.column("reference_id", sa.String()),
        sa.column("reason", sa.String()),
        sa.column("created_by_user_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    existing_products = bind.execute(
        sa.select(products_table.c.id, products_table.c.sku)
    ).fetchall()

    now = datetime.now(timezone.utc)
    for prod in existing_products:
        prod_id = prod[0]

        # Check if an inventory row already exists for this product
        existing_inv = bind.execute(
            sa.select(inventory_table.c.id).where(inventory_table.c.product_id == prod_id)
        ).scalar_one_or_none()

        if existing_inv is None:
            inv_id = uuid.uuid4()
            bind.execute(
                inventory_table.insert().values(
                    id=inv_id,
                    product_id=prod_id,
                    on_hand_stock=0,
                    reserved_stock=0,
                    low_stock_threshold=10,
                    created_at=now,
                    updated_at=now,
                )
            )

            bind.execute(
                stock_movements_table.insert().values(
                    id=uuid.uuid4(),
                    product_id=prod_id,
                    movement_type="init",
                    quantity=0,
                    on_hand_before=0,
                    on_hand_after=0,
                    reserved_before=0,
                    reserved_after=0,
                    reference_id="ZERO-STOCK-INIT",
                    reason="Initial zero-stock inventory baseline initialization during migration",
                    created_by_user_id=None,
                    created_at=now,
                )
            )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
    op.drop_index("ix_stock_movements_movement_type", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product_id", table_name="stock_movements")
    op.drop_table("stock_movements")

    op.drop_index("ix_inventory_product_id", table_name="inventory")
    op.drop_table("inventory")
