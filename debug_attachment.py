# debug_attachment.py
from polite_sam_scraper import PoliteSAMScraper

scraper = PoliteSAMScraper()
notice_id = "2d7924b19d054a6da78dfcb433ff0dc8"

api_url = f"https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources"

response = scraper.client.request("GET", api_url)
data = response.json()

print("Full API Response:")
print("=" * 70)

import json
print(json.dumps(data, indent=2))

scraper.close()