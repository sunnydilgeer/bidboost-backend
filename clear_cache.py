from app.database import SessionLocal
from app.models.company import CachedContractMatch

db = SessionLocal()

# Delete cache for firm-fti
deleted = db.query(CachedContractMatch).filter(
    CachedContractMatch.firm_id == "firm-fti"
).delete()

db.commit()
print(f"✅ Deleted {deleted} cached matches for firm-fti")
db.close()