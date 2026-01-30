"""add_contract_awards_table

Revision ID: aea8fe99572e
Revises: 151dc2f2550f
Create Date: 2025-01-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'aea8fe99572e'
down_revision = '151dc2f2550f'
branch_labels = None
depends_on = None


def upgrade():
    # Get database inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    # ========== STEP 1: Create CompanySize enum type ==========
    companysize_enum = postgresql.ENUM('MICRO', 'SMALL', 'MEDIUM', 'LARGE', name='companysize', create_type=False)
    companysize_enum.create(op.get_bind(), checkfirst=True)
    
    # ========== STEP 2: Alter company_profiles.size column to use enum ==========
    if 'company_profiles' in existing_tables:
        # Check if column exists and is not already enum type
        columns = {col['name']: col for col in inspector.get_columns('company_profiles')}
        if 'size' in columns:
            column_type = str(columns['size']['type'])
            if 'companysize' not in column_type.lower():
                op.alter_column('company_profiles', 'size',
                           existing_type=sa.VARCHAR(length=20),
                           type_=sa.Enum('MICRO', 'SMALL', 'MEDIUM', 'LARGE', name='companysize'),
                           existing_nullable=False,
                           postgresql_using='size::companysize')
    
    # ========== STEP 3: Create contract_awards table ==========
    if 'contract_awards' not in existing_tables:
        op.create_table('contract_awards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('award_id', sa.String(length=255), nullable=False),
        sa.Column('piid', sa.String(length=255), nullable=True),
        sa.Column('awardee_name', sa.String(length=255), nullable=False),
        sa.Column('awardee_uei', sa.String(length=50), nullable=True),
        sa.Column('awardee_duns', sa.String(length=50), nullable=True),
        sa.Column('agency_name', sa.String(length=255), nullable=False),
        sa.Column('sub_agency_name', sa.String(length=255), nullable=True),
        sa.Column('office_name', sa.Text(), nullable=True),
        sa.Column('naics_code', sa.String(length=10), nullable=True),
        sa.Column('naics_description', sa.Text(), nullable=True),
        sa.Column('psc_code', sa.String(length=10), nullable=True),
        sa.Column('psc_description', sa.Text(), nullable=True),
        sa.Column('award_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('contract_start_date', sa.Date(), nullable=True),
        sa.Column('contract_end_date', sa.Date(), nullable=True),
        sa.Column('award_date', sa.Date(), nullable=True),
        sa.Column('number_of_offers', sa.Integer(), nullable=True),
        sa.Column('extent_competed', sa.String(length=100), nullable=True),
        sa.Column('set_aside_type', sa.String(length=100), nullable=True),
        sa.Column('contract_type', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('pop_state', sa.String(length=50), nullable=True),
        sa.Column('pop_city', sa.String(length=100), nullable=True),
        sa.Column('pop_country', sa.String(length=100), nullable=True),
        sa.Column('fiscal_year', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        
        # Create indexes only if table was just created
        op.create_index(op.f('ix_contract_awards_agency_name'), 'contract_awards', ['agency_name'], unique=False)
        op.create_index(op.f('ix_contract_awards_award_id'), 'contract_awards', ['award_id'], unique=True)
        op.create_index(op.f('ix_contract_awards_awardee_name'), 'contract_awards', ['awardee_name'], unique=False)
        op.create_index(op.f('ix_contract_awards_contract_end_date'), 'contract_awards', ['contract_end_date'], unique=False)
        op.create_index(op.f('ix_contract_awards_fiscal_year'), 'contract_awards', ['fiscal_year'], unique=False)
        op.create_index(op.f('ix_contract_awards_naics_code'), 'contract_awards', ['naics_code'], unique=False)
        op.create_index(op.f('ix_contract_awards_piid'), 'contract_awards', ['piid'], unique=False)
        op.create_index(op.f('ix_contract_awards_psc_code'), 'contract_awards', ['psc_code'], unique=False)
        
        # Composite indexes for common queries
        op.create_index('idx_agency_naics', 'contract_awards', ['agency_name', 'naics_code'], unique=False)
        op.create_index('idx_awardee_agency', 'contract_awards', ['awardee_name', 'agency_name'], unique=False)
        op.create_index('idx_end_date_active', 'contract_awards', ['contract_end_date', 'is_active'], unique=False)


def downgrade():
    # Get database inspector
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    # ========== STEP 1: Drop contract_awards table ==========
    if 'contract_awards' in existing_tables:
        # Get existing indexes
        indexes = [idx['name'] for idx in inspector.get_indexes('contract_awards')]
        
        # Drop indexes if they exist
        if 'idx_end_date_active' in indexes:
            op.drop_index('idx_end_date_active', table_name='contract_awards')
        if 'idx_awardee_agency' in indexes:
            op.drop_index('idx_awardee_agency', table_name='contract_awards')
        if 'idx_agency_naics' in indexes:
            op.drop_index('idx_agency_naics', table_name='contract_awards')
        if 'ix_contract_awards_psc_code' in indexes:
            op.drop_index(op.f('ix_contract_awards_psc_code'), table_name='contract_awards')
        if 'ix_contract_awards_piid' in indexes:
            op.drop_index(op.f('ix_contract_awards_piid'), table_name='contract_awards')
        if 'ix_contract_awards_naics_code' in indexes:
            op.drop_index(op.f('ix_contract_awards_naics_code'), table_name='contract_awards')
        if 'ix_contract_awards_fiscal_year' in indexes:
            op.drop_index(op.f('ix_contract_awards_fiscal_year'), table_name='contract_awards')
        if 'ix_contract_awards_contract_end_date' in indexes:
            op.drop_index(op.f('ix_contract_awards_contract_end_date'), table_name='contract_awards')
        if 'ix_contract_awards_awardee_name' in indexes:
            op.drop_index(op.f('ix_contract_awards_awardee_name'), table_name='contract_awards')
        if 'ix_contract_awards_award_id' in indexes:
            op.drop_index(op.f('ix_contract_awards_award_id'), table_name='contract_awards')
        if 'ix_contract_awards_agency_name' in indexes:
            op.drop_index(op.f('ix_contract_awards_agency_name'), table_name='contract_awards')
        
        op.drop_table('contract_awards')
    
    # ========== STEP 2: Revert company_profiles.size column to VARCHAR ==========
    if 'company_profiles' in existing_tables:
        columns = {col['name']: col for col in inspector.get_columns('company_profiles')}
        if 'size' in columns:
            column_type = str(columns['size']['type'])
            if 'companysize' in column_type.lower():
                op.alter_column('company_profiles', 'size',
                           existing_type=sa.Enum('MICRO', 'SMALL', 'MEDIUM', 'LARGE', name='companysize'),
                           type_=sa.VARCHAR(length=20),
                           existing_nullable=False)
    
    # ========== STEP 3: Drop CompanySize enum type ==========
    sa.Enum(name='companysize').drop(op.get_bind(), checkfirst=True)