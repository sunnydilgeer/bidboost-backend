"""add_matched_capabilities_and_why_this_matches_to_cached_matches

Revision ID: 94a49a9c41e1
Revises: add_match_score_to_saved
Create Date: 2026-01-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '94a49a9c41e1'
down_revision = 'add_match_score_to_saved'  # Points to your latest migration
branch_labels = None
depends_on = None


def upgrade():
    # Add matched_capabilities column (JSON array)
    op.add_column('cached_contract_matches', 
        sa.Column('matched_capabilities', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )
    
    # Add why_this_matches column (JSON array)
    op.add_column('cached_contract_matches', 
        sa.Column('why_this_matches', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )
    
    # Set default empty arrays for existing rows
    op.execute("UPDATE cached_contract_matches SET matched_capabilities = '[]' WHERE matched_capabilities IS NULL")
    op.execute("UPDATE cached_contract_matches SET why_this_matches = '[]' WHERE why_this_matches IS NULL")


def downgrade():
    # Remove columns if rolling back
    op.drop_column('cached_contract_matches', 'why_this_matches')
    op.drop_column('cached_contract_matches', 'matched_capabilities')