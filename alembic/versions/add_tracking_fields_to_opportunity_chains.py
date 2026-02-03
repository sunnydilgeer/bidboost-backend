"""add pinecone_id, embedded_at, and scraped_at tracking fields

Revision ID: add_tracking_fields
Revises: <your_previous_revision>
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_tracking_fields'
down_revision = 'abc123enrichment'  # Update this
branch_labels = None
depends_on = None

def upgrade():
    # Embedding tracking
    op.add_column('opportunity_chains', 
        sa.Column('pinecone_id', sa.String(length=255), nullable=True))
    op.add_column('opportunity_chains', 
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True))
    
    # Scraping tracking
    op.add_column('opportunity_chains', 
        sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=True))
    
    # Indexes
    op.create_index('idx_pinecone_id', 'opportunity_chains', ['pinecone_id'])
    op.create_index('idx_embedded_at', 'opportunity_chains', ['embedded_at'])

def downgrade():
    op.drop_index('idx_embedded_at', table_name='opportunity_chains')
    op.drop_index('idx_pinecone_id', table_name='opportunity_chains')
    op.drop_column('opportunity_chains', 'scraped_at')
    op.drop_column('opportunity_chains', 'embedded_at')
    op.drop_column('opportunity_chains', 'pinecone_id')