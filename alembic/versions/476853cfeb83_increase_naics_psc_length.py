"""increase_naics_psc_length

Revision ID: 476853cfeb83
Revises: 88cda53389ca
Create Date: 2025-12-12 18:29:17.617845

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '476853cfeb83'
down_revision = '88cda53389ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('cached_contract_matches', 'naics_code',
                    type_=sa.String(255),
                    existing_type=sa.String(10))
    op.alter_column('cached_contract_matches', 'psc_code',
                    type_=sa.String(255),
                    existing_type=sa.String(10))
    op.alter_column('cached_contract_matches', 'set_aside',  # ADD THIS
                    type_=sa.String(255),
                    existing_type=sa.String(100))

def downgrade() -> None:
    op.alter_column('cached_contract_matches', 'set_aside',  # ADD THIS
                    type_=sa.String(100),
                    existing_type=sa.String(255))
    op.alter_column('cached_contract_matches', 'naics_code',
                    type_=sa.String(10),
                    existing_type=sa.String(255))
    op.alter_column('cached_contract_matches', 'psc_code',
                    type_=sa.String(10),
                    existing_type=sa.String(255))