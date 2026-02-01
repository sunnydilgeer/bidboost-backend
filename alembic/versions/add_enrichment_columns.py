"""Add enrichment tracking to cached_contract_matches

Revision ID: abc123enrichment
Revises: 8f9a2b3c4d5e
Create Date: 2026-02-01 15:45:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'abc123enrichment'
down_revision = '8f9a2b3c4d5e'  # ← UPDATE THIS to your actual latest revision
branch_labels = None
depends_on = None


def upgrade():
    """Add enrichment tracking columns to cached_contract_matches table."""
    
    # Add enrichment_status column with default 'pending'
    op.add_column(
        'cached_contract_matches',
        sa.Column('enrichment_status', sa.String(20), server_default='pending', nullable=False)
    )
    
    # Add enriched_at timestamp column
    op.add_column(
        'cached_contract_matches',
        sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    # Create index on enrichment_status for fast filtering
    op.create_index(
        'idx_enrichment_status',
        'cached_contract_matches',
        ['enrichment_status']
    )
    
    # Update existing rows to 'complete' (they already have strategic intel)
    op.execute("""
        UPDATE cached_contract_matches 
        SET enrichment_status = 'complete', 
            enriched_at = cached_at 
        WHERE enrichment_status = 'pending';
    """)


def downgrade():
    """Remove enrichment tracking columns."""
    
    # Drop in reverse order
    op.drop_index('idx_enrichment_status', table_name='cached_contract_matches')
    op.drop_column('cached_contract_matches', 'enriched_at')
    op.drop_column('cached_contract_matches', 'enrichment_status')