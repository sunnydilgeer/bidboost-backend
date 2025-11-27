"""Add US federal contract fields to company profiles

Revision ID: 8ea68ab7395c
Revises: f71a60d1b71c
Create Date: 2025-11-23 08:51:10.583537

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '8ea68ab7395c'
down_revision = 'f71a60d1b71c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # Check and drop old index on company_capabilities
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'idx_capabilities_qdrant_id'"
    )).fetchone()
    if result:
        op.drop_index('idx_capabilities_qdrant_id', table_name='company_capabilities')
    
    # Check and create new index on company_capabilities
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_company_capabilities_qdrant_id'"
    )).fetchone()
    if not result:
        op.create_index(op.f('ix_company_capabilities_qdrant_id'), 'company_capabilities', ['qdrant_id'], unique=False)
    
    # Alter columns
    op.alter_column('saved_contracts', 'status',
               existing_type=postgresql.ENUM('interested', 'bidding', 'won', 'lost', name='contractstatus'),
               type_=sa.String(length=50),
               existing_nullable=False,
               existing_server_default=sa.text("'interested'::contractstatus"))
    
    op.alter_column('saved_contracts', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    
    # Drop old indexes on saved_contracts
    for old_index in ['idx_saved_contracts_firm_id', 'idx_saved_contracts_notice_id', 'idx_saved_contracts_user_email']:
        result = conn.execute(sa.text(
            f"SELECT 1 FROM pg_indexes WHERE indexname = '{old_index}'"
        )).fetchone()
        if result:
            op.drop_index(old_index, table_name='saved_contracts')
    
    # Create new indexes on saved_contracts
    new_indexes = [
        ('ix_saved_contracts_firm_id', ['firm_id']),
        ('ix_saved_contracts_id', ['id']),
        ('ix_saved_contracts_notice_id', ['notice_id']),
        ('ix_saved_contracts_user_email', ['user_email'])
    ]
    
    for index_name, columns in new_indexes:
        result = conn.execute(sa.text(
            f"SELECT 1 FROM pg_indexes WHERE indexname = '{index_name}'"
        )).fetchone()
        if not result:
            op.create_index(op.f(index_name), 'saved_contracts', columns, unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    
    # Drop new indexes
    for index in ['ix_saved_contracts_user_email', 'ix_saved_contracts_notice_id', 'ix_saved_contracts_id', 'ix_saved_contracts_firm_id']:
        result = conn.execute(sa.text(
            f"SELECT 1 FROM pg_indexes WHERE indexname = '{index}'"
        )).fetchone()
        if result:
            op.drop_index(op.f(index), table_name='saved_contracts')
    
    # Recreate old indexes
    old_indexes = [
        ('idx_saved_contracts_user_email', ['user_email']),
        ('idx_saved_contracts_notice_id', ['notice_id']),
        ('idx_saved_contracts_firm_id', ['firm_id'])
    ]
    
    for index_name, columns in old_indexes:
        result = conn.execute(sa.text(
            f"SELECT 1 FROM pg_indexes WHERE indexname = '{index_name}'"
        )).fetchone()
        if not result:
            op.create_index(op.f(index_name), 'saved_contracts', columns, unique=False)
    
    # Revert columns
    op.alter_column('saved_contracts', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    
    op.alter_column('saved_contracts', 'status',
               existing_type=sa.String(length=50),
               type_=postgresql.ENUM('interested', 'bidding', 'won', 'lost', name='contractstatus'),
               existing_nullable=False,
               existing_server_default=sa.text("'interested'::contractstatus"))
    
    # Drop new capability index
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_company_capabilities_qdrant_id'"
    )).fetchone()
    if result:
        op.drop_index(op.f('ix_company_capabilities_qdrant_id'), table_name='company_capabilities')
    
    # Recreate old capability index
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'idx_capabilities_qdrant_id'"
    )).fetchone()
    if not result:
        op.create_index(op.f('idx_capabilities_qdrant_id'), 'company_capabilities', ['qdrant_id'], unique=False)