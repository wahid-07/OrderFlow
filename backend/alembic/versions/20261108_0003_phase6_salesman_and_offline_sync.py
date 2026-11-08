"""Phase 6 Salesman workflow, retailer assignments, visit notes, and offline sync idempotency.

Revision ID: 20261108_0003
Revises: 20261108_0002
Create Date: 2026-11-08 00:03:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261108_0003"
down_revision: Union[str, None] = "20261108_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add fields to salesmen table
    op.add_column(
        "salesmen",
        sa.Column("phone", sa.String(32), nullable=True),
    )
    op.add_column(
        "salesmen",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # 2. Create salesman_retailer_assignments table
    op.create_table(
        "salesman_retailer_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("salesman_id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["salesman_id"], ["salesmen.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("salesman_id", "retailer_id", name="uq_salesman_retailer_assignment"),
    )
    op.create_index(
        "ix_salesman_retailer_assignments_salesman_id",
        "salesman_retailer_assignments",
        ["salesman_id"],
    )
    op.create_index(
        "ix_salesman_retailer_assignments_retailer_id",
        "salesman_retailer_assignments",
        ["retailer_id"],
    )

    # 3. Create salesman_visit_notes table
    op.create_table(
        "salesman_visit_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("salesman_id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["salesman_id"], ["salesmen.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_salesman_visit_notes_salesman_id",
        "salesman_visit_notes",
        ["salesman_id"],
    )
    op.create_index(
        "ix_salesman_visit_notes_retailer_id",
        "salesman_visit_notes",
        ["retailer_id"],
    )

    # 4. Add audit and idempotency columns to orders table
    op.add_column(
        "orders",
        sa.Column("salesman_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_salesman_id",
        "orders",
        "salesmen",
        ["salesman_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "orders",
        sa.Column(
            "order_source",
            sa.String(32),
            nullable=False,
            server_default="retailer",
        ),
    )
    op.add_column(
        "orders",
        sa.Column("idempotency_key", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_orders_idempotency_key",
        "orders",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_idempotency_key", table_name="orders")
    op.drop_column("orders", "idempotency_key")
    op.drop_column("orders", "order_source")
    op.drop_constraint("fk_orders_salesman_id", "orders", type_="foreignkey")
    op.drop_column("orders", "salesman_id")

    op.drop_index("ix_salesman_visit_notes_retailer_id", table_name="salesman_visit_notes")
    op.drop_index("ix_salesman_visit_notes_salesman_id", table_name="salesman_visit_notes")
    op.drop_table("salesman_visit_notes")

    op.drop_index("ix_salesman_retailer_assignments_retailer_id", table_name="salesman_retailer_assignments")
    op.drop_index("ix_salesman_retailer_assignments_salesman_id", table_name="salesman_retailer_assignments")
    op.drop_table("salesman_retailer_assignments")

    op.drop_column("salesmen", "is_active")
    op.drop_column("salesmen", "phone")

