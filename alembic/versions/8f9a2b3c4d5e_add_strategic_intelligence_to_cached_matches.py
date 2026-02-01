"""add strategic intelligence to cached matches

Revision ID: 8f9a2b3c4d5e
Revises: 151dc2f2550f
Create Date: 2026-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f9a2b3c4d5e'
down_revision = 'aea8fe99572e'  # Update this to your latest migration ID
branch_labels = None
depends_on = None


def upgrade():
    """
    Add strategic intelligence columns to cached_contract_matches table.
    
    New columns:
    - incumbent_data: JSON with incumbent contractor info (name, amount, dates, confidence)
    - pricing_benchmarks: JSON with avg/min/max award amounts and sample size
    - competition_stats: JSON with avg offers and set-aside distribution
    """
    
    # Check if table exists before adding columns
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'cached_contract_matches' in inspector.get_table_names():
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('cached_contract_matches')]
        
        # Add incumbent_data column if it doesn't exist
        if 'incumbent_data' not in existing_columns:
            op.add_column('cached_contract_matches', 
                sa.Column('incumbent_data', sa.Text(), nullable=True,
                         comment='JSON: Incumbent contractor info (name, amount, dates, confidence)'))
        
        # Add pricing_benchmarks column if it doesn't exist
        if 'pricing_benchmarks' not in existing_columns:
            op.add_column('cached_contract_matches', 
                sa.Column('pricing_benchmarks', sa.Text(), nullable=True,
                         comment='JSON: Pricing benchmarks (avg/min/max award amounts, sample size)'))
        
        # Add competition_stats column if it doesn't exist
        if 'competition_stats' not in existing_columns:
            op.add_column('cached_contract_matches', 
                sa.Column('competition_stats', sa.Text(), nullable=True,
                         comment='JSON: Competition stats (avg offers, set-aside distribution)'))
        
        print("✅ Strategic intelligence columns added to cached_contract_matches")
    else:
        print("⚠️ Table cached_contract_matches does not exist - skipping migration")


def downgrade():
    """
    Remove strategic intelligence columns from cached_contract_matches table.
    """
    
    # Check if table exists before removing columns
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'cached_contract_matches' in inspector.get_table_names():
        # Get existing columns
        existing_columns = [col['name'] for col in inspector.get_columns('cached_contract_matches')]
        
        # Remove columns if they exist
        if 'competition_stats' in existing_columns:
            op.drop_column('cached_contract_matches', 'competition_stats')
        
        if 'pricing_benchmarks' in existing_columns:
            op.drop_column('cached_contract_matches', 'pricing_benchmarks')
        
        if 'incumbent_data' in existing_columns:
            op.drop_column('cached_contract_matches', 'incumbent_data')
        
        print("✅ Strategic intelligence columns removed from cached_contract_matches")
    else:
        print("⚠️ Table cached_contract_matches does not exist - skipping rollback")