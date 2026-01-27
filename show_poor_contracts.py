# show_poor_contracts.py
from app.database import SessionLocal
from app.models.company import OpportunityChain

db = SessionLocal()

# Get 5 POOR/MISSING contracts
contracts = db.query(OpportunityChain).filter(
    OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
).limit(5).all()

print("Sample POOR/MISSING contracts:")
print("=" * 70)
for c in contracts:
    print(f"Sol#: {c.solicitation_number}")
    print(f"Notice ID: {c.base_notice_id}")
    print(f"Quality: {c.base_description_quality}")
    print(f"Description: {c.base_description[:100] if c.base_description else 'None'}")
    print(f"SAM.gov: https://sam.gov/opp/{c.base_notice_id}/view")
    print()

db.close()