# Edit: alembic/versions/88cda53389ca_add_pinecone_id_to_past_wins.py

"""add_pinecone_id_to_past_wins

Revision ID: 88cda53389ca
Revises: add_cached_matches
Create Date: 2025-12-12 18:22:59.148711

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '88cda53389ca'
down_revision = 'add_cached_matches'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists (Railway already has it)
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('past_wins')]
    
    if 'pinecone_id' not in columns:
        op.add_column('past_wins', sa.Column('pinecone_id', sa.String(length=100), nullable=True))
        op.create_index('ix_past_wins_pinecone_id', 'past_wins', ['pinecone_id'], unique=False)


def downgrade() -> None:
    # Check before dropping too
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('past_wins')]
    
    if 'pinecone_id' in columns:
        op.drop_index('ix_past_wins_pinecone_id', table_name='past_wins')
        op.drop_column('past_wins', 'pinecone_id')