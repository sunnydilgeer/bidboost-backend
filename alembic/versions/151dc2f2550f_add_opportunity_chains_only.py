"""add opportunity chains only

Revision ID: 151dc2f2550f
Revises: add_sow_tables
Create Date: 2026-01-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '151dc2f2550f'
down_revision = 'add_sow_tables'  # Change this to match your last migration
branch_labels = None
depends_on = None


def upgrade():
    # Create opportunity_chains table
    op.create_table('opportunity_chains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('solicitation_number', sa.String(length=255), nullable=False),
        sa.Column('base_notice_id', sa.String(length=255), nullable=False),
        sa.Column('base_sol_number', sa.String(length=255), nullable=False),
        sa.Column('base_description', sa.Text(), nullable=True),
        sa.Column('base_posted_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('base_type', sa.String(length=100), nullable=True),
        sa.Column('notice_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('has_amendments', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('latest_closing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('has_attachments', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('attachment_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('attachments_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('base_description_quality', sa.String(length=20), nullable=True),
        sa.Column('needs_sow_extraction', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('solicitation_number')
    )
    op.create_index('idx_base_notice', 'opportunity_chains', ['base_notice_id'], unique=False)
    op.create_index('idx_quality', 'opportunity_chains', ['base_description_quality'], unique=False)
    op.create_index('idx_sol_number', 'opportunity_chains', ['solicitation_number'], unique=False)
    
    # Create opportunity_attachments table
    op.create_table('opportunity_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=500), nullable=False),
        sa.Column('file_type', sa.String(length=50), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('download_url', sa.Text(), nullable=True),
        sa.Column('is_sow', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_amendment', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('downloaded', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('extracted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['chain_id'], ['opportunity_chains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_opportunity_attachments_chain_id', 'opportunity_attachments', ['chain_id'], unique=False)


def downgrade():
    op.drop_index('ix_opportunity_attachments_chain_id', table_name='opportunity_attachments')
    op.drop_table('opportunity_attachments')
    op.drop_index('idx_sol_number', table_name='opportunity_chains')
    op.drop_index('idx_quality', table_name='opportunity_chains')
    op.drop_index('idx_base_notice', table_name='opportunity_chains')
    op.drop_table('opportunity_chains')