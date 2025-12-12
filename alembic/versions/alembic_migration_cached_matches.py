"""Add cached contract matches table

Revision ID: add_cached_matches
Revises: <your_previous_revision>
Create Date: 2025-01-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_cached_matches'
down_revision = '8ea68ab7395c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cached_contract_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('firm_id', sa.String(length=255), nullable=False),
        sa.Column('notice_id', sa.String(length=255), nullable=False),
        sa.Column('pinecone_id', sa.String(length=100), nullable=False),
        
        # Contract data
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('buyer_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('contract_value', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('closing_date', sa.String(length=100), nullable=True),
        sa.Column('posted_date', sa.String(length=100), nullable=True),
        
        # Enriched data
        sa.Column('office', sa.String(length=255), nullable=True),
        sa.Column('naics_code', sa.String(length=10), nullable=True),
        sa.Column('naics_name', sa.String(length=255), nullable=True),
        sa.Column('psc_code', sa.String(length=10), nullable=True),
        sa.Column('psc_name', sa.String(length=255), nullable=True),
        sa.Column('set_aside', sa.String(length=100), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('contact_name', sa.String(length=255), nullable=True),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('contact_phone', sa.String(length=50), nullable=True),
        
        # Pre-computed scores
        sa.Column('total_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('capability_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('past_win_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('preference_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('match_reasons', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        
        # Cache metadata
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('cached_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for fast queries
    op.create_index('idx_firm_score', 'cached_contract_matches', ['firm_id', 'total_score'])
    op.create_index('idx_firm_rank', 'cached_contract_matches', ['firm_id', 'rank'])
    op.create_index('idx_firm_cached', 'cached_contract_matches', ['firm_id', 'cached_at'])
    op.create_index(op.f('ix_cached_contract_matches_firm_id'), 'cached_contract_matches', ['firm_id'])
    op.create_index(op.f('ix_cached_contract_matches_notice_id'), 'cached_contract_matches', ['notice_id'])
    op.create_index(op.f('ix_cached_contract_matches_total_score'), 'cached_contract_matches', ['total_score'])


def downgrade():
    op.drop_index(op.f('ix_cached_contract_matches_total_score'), table_name='cached_contract_matches')
    op.drop_index(op.f('ix_cached_contract_matches_notice_id'), table_name='cached_contract_matches')
    op.drop_index(op.f('ix_cached_contract_matches_firm_id'), table_name='cached_contract_matches')
    op.drop_index('idx_firm_cached', table_name='cached_contract_matches')
    op.drop_index('idx_firm_rank', table_name='cached_contract_matches')
    op.drop_index('idx_firm_score', table_name='cached_contract_matches')
    op.drop_table('cached_contract_matches')