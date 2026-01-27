"""add sow extraction tables

Revision ID: add_sow_tables
Revises: <your_previous_revision>
Create Date: 2024-01-26 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_sow_tables'
down_revision = '94a49a9c41e1'  # Replace with your latest revision
branch_labels = None
depends_on = None


def upgrade():
    # Create contract_sows table
    op.create_table(
        'contract_sows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notice_id', sa.String(length=255), nullable=False),
        sa.Column('sow_text', sa.Text(), nullable=False),
        sa.Column('confidence', sa.String(length=20), nullable=False),
        sa.Column('source_filename', sa.String(length=500), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('has_deliverables', sa.Boolean(), nullable=True, default=False),
        sa.Column('has_tasks', sa.Boolean(), nullable=True, default=False),
        sa.Column('extraction_method', sa.String(length=50), nullable=True),
        sa.Column('pdf_url', sa.Text(), nullable=True),
        sa.Column('pdf_size_bytes', sa.Integer(), nullable=True),
        sa.Column('extracted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for contract_sows
    op.create_index('idx_sows_notice_id', 'contract_sows', ['notice_id'], unique=True)
    op.create_index('idx_sows_confidence', 'contract_sows', ['confidence'], unique=False)
    
    # Create sow_extraction_queue table
    op.create_table(
        'sow_extraction_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notice_id', sa.String(length=255), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=True, server_default='MEDIUM'),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='PENDING'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for sow_extraction_queue
    op.create_index('idx_queue_notice_id', 'sow_extraction_queue', ['notice_id'], unique=False)
    op.create_index('idx_queue_status', 'sow_extraction_queue', ['status'], unique=False)
    op.create_index('idx_queue_priority', 'sow_extraction_queue', ['priority'], unique=False)
    op.create_index('idx_queue_created_at', 'sow_extraction_queue', ['created_at'], unique=False)


def downgrade():
    # Drop indexes first
    op.drop_index('idx_queue_created_at', table_name='sow_extraction_queue')
    op.drop_index('idx_queue_priority', table_name='sow_extraction_queue')
    op.drop_index('idx_queue_status', table_name='sow_extraction_queue')
    op.drop_index('idx_queue_notice_id', table_name='sow_extraction_queue')
    op.drop_index('idx_sows_confidence', table_name='contract_sows')
    op.drop_index('idx_sows_notice_id', table_name='contract_sows')
    
    # Drop tables
    op.drop_table('sow_extraction_queue')
    op.drop_table('contract_sows')