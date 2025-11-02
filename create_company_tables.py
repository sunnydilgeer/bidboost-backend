# create_company_tables.py
from app.database import engine, Base
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference

# Create all tables
Base.metadata.create_all(bind=engine)
print("✓ Company profile tables created successfully!")