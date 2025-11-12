set -euo pipefail

OUT="fts_live.json"
TMP=$(mktemp)

echo "[🚀] Fetching all live tenders from Find a Tender (FTS)..."
echo "[" > "$OUT"

PAGE=1
BASE_URL="https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
TOTAL=0

while true; do
  echo "[→] Fetching page $PAGE..."
  DATA=$(curl -s "${BASE_URL}?page=$PAGE")

  COUNT=$(echo "$DATA" | jq '.releases | length')
  if [ "$COUNT" -eq 0 ]; then
    echo "[✅] No more results after page $PAGE."
    break
  fi

  echo "$DATA" | jq -c '.releases[] | select(.tender.status == "active")' >> "$TMP"
  TOTAL=$((TOTAL + COUNT))
  PAGE=$((PAGE + 1))
  sleep 1
done

# Format as JSON array
jq -s '.' "$TMP" > "$OUT"
rm -f "$TMP"

echo "[✅] Done. Saved all active tenders to $OUT"
jq length "$OUT"
