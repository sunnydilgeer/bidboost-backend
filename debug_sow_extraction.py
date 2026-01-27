"""
Debug script to see what GPT is receiving
"""

import csv
from collections import defaultdict

csv_path = "data/ContractOpportunitiesFullCSV.csv"
test_sol = "A039831-2026"  # The one we know has "see attached"

sol_to_notices = defaultdict(list)

with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
    reader = csv.DictReader(f)
    
    for row in reader:
        sol_num = row.get('Sol#', '').strip()
        
        if sol_num == test_sol:
            sol_to_notices[sol_num].append(row)

notices = sol_to_notices[test_sol]

print(f"Found {len(notices)} notices for {test_sol}")
print()

for idx, notice in enumerate(notices, 1):
    print(f"Notice {idx}:")
    print(f"  Title: {notice.get('Title', '')}")
    print(f"  Type: {notice.get('Type', '')}")
    print(f"  BaseType: {notice.get('BaseType', '')}")
    print(f"  Description: {notice.get('Description', '')}")
    print(f"  PostedDate: {notice.get('PostedDate', '')}")
    print()