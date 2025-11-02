from app.database import SessionLocal
from app.models.company import CompanyProfile

db = SessionLocal()

try:
    company = db.query(CompanyProfile).filter(
        CompanyProfile.firm_id == "firm-suninho"
    ).first()
    
    if company:
        company.onboarding_completed = 0  # Reset to not completed
        company.onboarding_step = 0
        company.onboarding_completed_at = None
        db.commit()
        print(f"✅ Reset onboarding for {company.company_name}")
        print(f"   Status: {company.onboarding_completed}, Step: {company.onboarding_step}")
    else:
        print("❌ Company not found")
finally:
    db.close()
