#!/bin/bash

# 🧪 Test Match Score Improvement
# Run this AFTER adding new capabilities

TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdXJpbmRlci5kaWxnZWVyKzY5QGdtYWlsLmNvbSIsInVzZXJfaWQiOiIzM2E0ZmZhOC1iMTY5LTRmNDQtOGNjNC1mM2E2NGQ0MjFhNjEiLCJmaXJtX2lkIjoiZmlybS1jbGFyZW5jZS1hbmQtZmlzaGJ1cm4tbGxwIiwicm9sZSI6InVzZXIiLCJuYW1lIjoiQ2xhaXJlIiwiZXhwIjoxNzY1MzM0NjQzLCJpYXQiOjE3NjUzMDU4NDN9.DgmMiHYYOczV0BBAlgpeAqm4ApLPf_dlVCyoSfaciYg"
API_BASE="https://backend-api-production-387c.up.railway.app/api"

echo "🧪 Testing Match Score Improvements"
echo "===================================="
echo ""

echo "📊 Test 1: Search Endpoint - 'cloud migration DevOps AWS'"
echo "-----------------------------------------------------------"
curl -s "$API_BASE/contracts/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "cloud migration DevOps AWS GovCloud cybersecurity FedRAMP", "limit": 5}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Found: {data[\"total_found\"]} contracts\n')
for i, r in enumerate(data['results'][:5], 1):
    scores = r.get('match_scores', {})
    print(f'{i}. {r[\"title\"][:60]}...')
    print(f'   Total Score: {scores.get(\"total_score\", 0)*100:.0f}%')
    print(f'   Capability:  {scores.get(\"capability_score\", 0)*100:.0f}%')
    print(f'   Past Wins:   {scores.get(\"past_win_score\", 0)*100:.0f}%')
    print(f'   Preference:  {scores.get(\"preference_score\", 0)*100:.0f}%')
    print()
"

echo ""
echo "📊 Test 2: Recommendations Endpoint (Personalized Matches)"
echo "-----------------------------------------------------------"
curl -s "$API_BASE/contracts/recommended?limit=5" \
  -H "Authorization: Bearer $TOKEN" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Found: {data[\"total_found\"]} personalized matches\n')
for i, r in enumerate(data['results'][:5], 1):
    scores = r.get('match_scores', {})
    print(f'{i}. {r[\"title\"][:60]}...')
    print(f'   Total Score: {scores.get(\"total_score\", 0)*100:.0f}%')
    print(f'   Capability:  {scores.get(\"capability_score\", 0)*100:.0f}%')
    print(f'   Past Wins:   {scores.get(\"past_win_score\", 0)*100:.0f}%')
    print(f'   Agency: {r.get(\"buyer_name\", \"N/A\")[:40]}')
    print()
"

echo ""
echo "📊 Test 3: Specific Contract Detail"
echo "-----------------------------------------------------------"
curl -s "$API_BASE/contracts/SP470926Q2007" \
  -H "Authorization: Bearer $TOKEN" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Contract: {data[\"title\"]}')
print(f'Agency: {data[\"buyer_name\"]}')
print(f'Value: \${data.get(\"value\", 0):,.0f}')
print(f'Closing: {data.get(\"closing_date\", \"N/A\")}')
print(f'NAICS: {data.get(\"naics_code\", \"N/A\")}')
print(f'Set-Aside: {data.get(\"set_aside\", \"N/A\")}')
"

echo ""
echo "✅ Test Complete!"
echo ""
echo "📈 Score Analysis:"
echo "  - Look for capability scores 50%+ (was 32-39%)"
echo "  - Look for total scores 40%+ (was 28-32%)"
echo "  - Higher scores = better capability matching"