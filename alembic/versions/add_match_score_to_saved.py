"""Add match_score to saved_contracts

Revision ID: add_match_score_to_saved
Revises: a3f8b2c91d4e
Create Date: 2026-01-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_match_score_to_saved'
down_revision = 'a3f8b2c91d4e'  # ✅ Your current head
branch_labels = None
depends_on = None


def upgrade():
    # Add match_score column to saved_contracts table
    op.add_column(
        'saved_contracts',
        sa.Column('match_score', sa.Numeric(precision=5, scale=2), nullable=True)
    )


def downgrade():
    # Remove match_score column
    op.drop_column('saved_contracts', 'match_score')