#!/bin/bash
# Railway Daily Pipeline - Processes latest CSV from volume
# Runs via Railway cron job after manual CSV upload

set -e

CSV_DIR="/data/csvs"
LOG_DIR="/app/logs"

# Ensure directories exist
mkdir -p "$CSV_DIR"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "RAILWAY DAILY PIPELINE"
echo "=========================================="
echo "Time: $(date)"
echo ""

# Find the latest CSV file
LATEST_CSV=$(ls -t "$CSV_DIR"/ContractOpportunitiesFullCSV*.csv 2>/dev/null | head -1)

if [ -z "$LATEST_CSV" ]; then
    echo "❌ ERROR: No CSV files found in $CSV_DIR"
    echo ""
    echo "Please upload CSV using:"
    echo "  railway run upload /path/to/ContractOpportunitiesFullCSV.csv $CSV_DIR/"
    exit 1
fi

echo "📂 Found CSV: $(basename $LATEST_CSV)"
echo "📊 File size: $(du -h $LATEST_CSV | cut -f1)"
echo ""

# Check if CSV was uploaded today (prevents re-running on old CSVs)
CSV_AGE_HOURS=$(( ($(date +%s) - $(stat -f %m "$LATEST_CSV" 2>/dev/null || stat -c %Y "$LATEST_CSV")) / 3600 ))
echo "⏰ CSV age: ${CSV_AGE_HOURS} hours"

if [ $CSV_AGE_HOURS -gt 48 ]; then
    echo "⚠️  WARNING: CSV is older than 48 hours"
    echo "   Upload a fresh CSV before running pipeline"
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "🚀 Starting pipeline with: $(basename $LATEST_CSV)"
echo ""

# Set Python path
export PYTHONPATH=/app

# Run full pipeline (all 8 stages)
/app/scripts/daily_pipeline.sh --csv "$LATEST_CSV"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ RAILWAY PIPELINE COMPLETE"
    echo "=========================================="
    echo "Processed: $(basename $LATEST_CSV)"
    echo "Time: $(date)"
else
    echo ""
    echo "=========================================="
    echo "❌ RAILWAY PIPELINE FAILED"
    echo "=========================================="
    echo "Exit code: $EXIT_CODE"
    echo "Check logs for details"
    exit $EXIT_CODE
fi