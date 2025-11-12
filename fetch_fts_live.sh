#!/usr/bin/env bash
set -euo pipefail

BASE="https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
PARAMS="stages=tender&status=active&limit=100"
OUT="fts_live.json"
TMP=$(mktemp /tmp/fts_live.XXXXXX.json)

echo "[" > "$OUT"
CURSOR=""
PAGE=1
TOTAL=0

while :; do
  echo "[$(date '+%H:%M:%S')] Fetching page $PAGE..."
  URL="${BASE}?${PARAMS}&cursor=${CURSOR}"
  RESP=$(curl -m 30 -s "$URL" -H "Accept: application/json")

  COUNT=$(echo "$RESP" | jq '.releases | length')
  echo "Page $PAGE: $COUNT releases"
  [ "$COUNT" -eq 0 ] && echo "No more pages — done." && break

  # Append each release
  echo "$RESP" | jq -c '.releases[]' >> "$TMP"
  TOTAL=$((TOTAL + COUNT))

  # Get next cursor
  NEXT=$(echo "$RESP" | jq -r '.links.nextCursor // empty')
  [ -z "$NEXT" ] && echo "No nextCursor — all done." && break
  CURSOR="$NEXT"

  PAGE=$((PAGE + 1))
  sleep 1
done

# Combine and format as a proper JSON array
jq -s '.' "$TMP" >> "$OUT"
rm -f "$TMP"

echo "]" >> "$OUT"
echo "✅ Done. Saved $TOTAL live tenders to $OUT"
jq length "$OUT"
