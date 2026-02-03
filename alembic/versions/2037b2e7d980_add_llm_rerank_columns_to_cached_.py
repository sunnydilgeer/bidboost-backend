"""add_llm_rerank_columns_to_cached_contract_match

Revision ID: 2037b2e7d980
Revises: add_tracking_fields
Create Date: 2026-02-03 14:56:47.854326

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2037b2e7d980'
down_revision = 'add_tracking_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add LLM re-ranking columns to cached_contract_matches
    op.add_column('cached_contract_matches', 
        sa.Column('llm_score', sa.Integer(), nullable=True))
    op.add_column('cached_contract_matches', 
        sa.Column('llm_verdict', sa.String(length=20), nullable=True))
    op.add_column('cached_contract_matches', 
        sa.Column('llm_reasons', sa.Text(), nullable=True))
    op.add_column('cached_contract_matches', 
        sa.Column('llm_flags', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove LLM re-ranking columns
    op.drop_column('cached_contract_matches', 'llm_flags')
    op.drop_column('cached_contract_matches', 'llm_reasons')
    op.drop_column('cached_contract_matches', 'llm_verdict')
    op.drop_column('cached_contract_matches', 'llm_score')