"""add_pinecone_id_to_past_wins

Revision ID: 88cda53389ca
Revises: add_cached_matches
Create Date: 2025-12-12 18:22:59.148711

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '88cda53389ca'
down_revision = 'add_cached_matches'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add pinecone_id column to past_wins table
    op.add_column('past_wins', sa.Column('pinecone_id', sa.String(length=100), nullable=True))
    
    # Create index on pinecone_id for faster lookups
    op.create_index('ix_past_wins_pinecone_id', 'past_wins', ['pinecone_id'], unique=False)


def downgrade() -> None:
    # Drop index first
    op.drop_index('ix_past_wins_pinecone_id', table_name='past_wins')
    
    # Drop column
    op.drop_column('past_wins', 'pinecone_id')