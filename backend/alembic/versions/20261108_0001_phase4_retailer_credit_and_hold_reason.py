"""Phase 4: Add retailer credit limit, current outstanding, and order hold reason.

Revision ID: 20261108_0001
Revises: 
Create Date: 2026-11-08 15:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261108_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add credit_limit and current_outstanding to retailers table
    op.add_column(
        "retailers",
        sa.Column(
            "credit_limit",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.add_column(
        "retailers",
        sa.Column(
            "current_outstanding",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )

    # 2. Add hold_reason to orders table
    op.add_column(
        "orders",
        sa.Column(
            "hold_reason",
            sa.String(length=500),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "hold_reason")
    op.drop_column("retailers", "current_outstanding")
    op.drop_column("retailers", "credit_limit")

