"""add firm_subscriptions

Revision ID: b142d20d3335
Revises: 476853cfeb83
Create Date: 2025-12-22 15:43:28.158799
"""
from alembic import op
import sqlalchemy as sa

revision = "b142d20d3335"
down_revision = "476853cfeb83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firm_subscriptions",
        sa.Column("firm_id", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=False),
        sa.Column(
            "plan_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("firm_id"),
    )


def downgrade() -> None:
    op.drop_table("firm_subscriptions")