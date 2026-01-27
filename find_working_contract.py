# find_working_contract.py
from app.database import SessionLocal
from app.models.company import OpportunityChain

db = SessionLocal()

# Try to find the contract from your screenshot
# It had "DLA Transportation" and "PWS.docx"
contracts = db.query(OpportunityChain).filter(
    OpportunityChain.base_description_quality.in_(['POOR', 'MISSING'])
).all()

print("Looking for contracts with actual SAM-hosted files (not external links)...")
print()

# Show 10 more to test
for c in contracts[5:15]:  # Skip the first 5 we already tried
    print(f"Sol#: {c.solicitation_number}")
    print(f"Notice ID: {c.base_notice_id}")
    print(f"Link: https://sam.gov/opp/{c.base_notice_id}/view")
    print()

db.close()