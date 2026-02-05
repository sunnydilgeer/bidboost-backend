"""Add final_score to cached_contract_matches

Revision ID: c69bd31e97aa
Revises: [previous_revision]
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c69bd31e97aa'
down_revision = '2037b2e7d980'  # ← You'll need to fill this in with the actual previous revision
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Add final_score column as NULLABLE
    op.add_column('cached_contract_matches', 
        sa.Column('final_score', sa.Numeric(precision=5, scale=2), nullable=True)
    )
    
    # Step 2: Backfill final_score from total_score
    op.execute("""
        UPDATE cached_contract_matches 
        SET final_score = total_score 
        WHERE final_score IS NULL
    """)
    
    # Step 3: Make final_score NOT NULL
    op.alter_column('cached_contract_matches', 'final_score',
        existing_type=sa.Numeric(precision=5, scale=2),
        nullable=False
    )
    
    # Step 4: Add index on final_score
    op.create_index('ix_cached_contract_matches_final_score', 
                    'cached_contract_matches', 
                    ['final_score'], 
                    unique=False)


def downgrade():
    # Remove index
    op.drop_index('ix_cached_contract_matches_final_score', 
                  table_name='cached_contract_matches')
    
    # Remove column
    op.drop_column('cached_contract_matches', 'final_score')