"""add founder pricing fields

Revision ID: a3f8b2c91d4e
Revises: f71a60d1b71c_add_us_federal_fields_to_company_
Create Date: 2025-01-14 07:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f8b2c91d4e'
down_revision = '3ab3df51f57d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add founder pricing columns to firm_subscriptions
    op.add_column('firm_subscriptions', 
        sa.Column('founder_eligible', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column('firm_subscriptions', 
        sa.Column('founder_revoked_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('firm_subscriptions', 
        sa.Column('billing_price', sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('firm_subscriptions', 'billing_price')
    op.drop_column('firm_subscriptions', 'founder_revoked_at')
    op.drop_column('firm_subscriptions', 'founder_eligible')