#!/bin/bash

# ============================================================
# DAILY CONTRACT DATA PIPELINE
# Automates the 8-stage contract ingestion process
# ============================================================

set -e  # Exit on error

# Configuration
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPTS_DIR")"
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"
export PYTHONUNBUFFERED=1
LOG_DIR="$ROOT_DIR/logs"
DATA_DIR="$ROOT_DIR/data"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="$LOG_DIR/pipeline_$TIMESTAMP.log"

# Create directories if they don't exist
mkdir -p "$LOG_DIR"
mkdir -p "$DATA_DIR/daily"

# ============================================================
# LOGGING FUNCTIONS
# ============================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_stage() {
    echo "" | tee -a "$LOG_FILE"
    echo "============================================================" | tee -a "$LOG_FILE"
    echo "STAGE $1: $2" | tee -a "$LOG_FILE"
    echo "============================================================" | tee -a "$LOG_FILE"
}

log_success() {
    echo "✅ $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo "❌ ERROR: $1" | tee -a "$LOG_FILE"
}

log_skip() {
    echo "⏭️  SKIPPED: $1" | tee -a "$LOG_FILE"
}

# ============================================================
# PARSE ARGUMENTS
# ============================================================

CSV_FILE=""
SKIP_STAGES=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --csv)
            CSV_FILE="$2"
            shift 2
            ;;
        --skip)
            SKIP_STAGES="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./daily_pipeline.sh --csv <path> [--skip <stage_numbers>] [--dry-run]"
            echo "Example: ./daily_pipeline.sh --csv ContractOpportunitiesFullCSV.csv"
            echo "Example: ./daily_pipeline.sh --csv ContractOpportunitiesFullCSV.csv --skip 5,6,7"
            exit 1
            ;;
    esac
done

# Validate CSV file
if [ -z "$CSV_FILE" ]; then
    log_error "No CSV file specified. Use --csv <path>"
    exit 1
fi

if [ ! -f "$CSV_FILE" ]; then
    log_error "CSV file not found: $CSV_FILE"
    exit 1
fi

# ============================================================
# PIPELINE START
# ============================================================

log "=========================================="
log "DAILY CONTRACT DATA PIPELINE"
log "=========================================="
log "CSV Input: $CSV_FILE"
log "Log File: $LOG_FILE"
if [ "$DRY_RUN" = true ]; then
    log "Mode: DRY RUN (no database changes)"
fi
if [ -n "$SKIP_STAGES" ]; then
    log "Skipping stages: $SKIP_STAGES"
fi
log ""

PIPELINE_START=$(date +%s)

# ============================================================
# STAGE 1: UPDATE TRUTH LAYER
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "1" ]]; then
    log_stage 1 "UPDATE TRUTH LAYER (Incremental UPSERT)"
    
    STAGE_START=$(date +%s)
    
    if [ "$DRY_RUN" = true ]; then
        log "Dry run mode - would run: python build_contract_truth.py $CSV_FILE"
        log_success "Stage 1 completed (dry run)"
    else
        if python -u "$ROOT_DIR/build_contract_truth.py" "$CSV_FILE" >> "$LOG_FILE" 2>&1; then
            STAGE_END=$(date +%s)
            STAGE_DURATION=$((STAGE_END - STAGE_START))
            log_success "Stage 1 completed in ${STAGE_DURATION}s"
        else
            log_error "Stage 1 failed - check log file"
            exit 1
        fi
    fi
else
    log_skip "Stage 1 (Update Truth Layer)"
fi

# ============================================================
# STAGE 2: EMBED NEW CONTRACTS
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "2" ]]; then
    log_stage 2 "EMBED NEW CONTRACTS (Incremental)"
    
    STAGE_START=$(date +%s)
    
    if [ "$DRY_RUN" = true ]; then
        log "Dry run mode - would run: python scripts/embed_new_contracts.py --dry-run"
        log_success "Stage 2 completed (dry run)"
    else
        if python -u "$SCRIPTS_DIR/embed_new_contracts.py" >> "$LOG_FILE" 2>&1; then
            STAGE_END=$(date +%s)
            STAGE_DURATION=$((STAGE_END - STAGE_START))
            log_success "Stage 2 completed in ${STAGE_DURATION}s"
        else
            log_error "Stage 2 failed - check log file"
            exit 1
        fi
    fi
else
    log_skip "Stage 2 (Embed New Contracts)"
fi

# ============================================================
# STAGE 3: VERIFY DATA QUALITY (Quick Check)
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "3" ]]; then
    log_stage 3 "VERIFY DATA QUALITY"
    
    # Quick verification - count records
    if [ "$DRY_RUN" = false ]; then
        EMBEDDED_COUNT=$(python -c "
from app.database import SessionLocal
from app.models.company import OpportunityChain

db = SessionLocal()
count = db.query(OpportunityChain).filter(
    OpportunityChain.pinecone_id.isnot(None)
).count()
print(count)
db.close()
" 2>/dev/null)
        
        log "   Contracts in Pinecone: $EMBEDDED_COUNT"
        log_success "Stage 3 completed"
    else
        log_skip "Stage 3 (Dry run mode)"
    fi
else
    log_skip "Stage 3 (Verify Quality)"
fi

# ============================================================
# STAGE 4: IDENTIFY POOR CONTRACTS
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "4" ]]; then
    log_stage 4 "IDENTIFY POOR CONTRACTS"
    
    STAGE_START=$(date +%s)
    
    if [ "$DRY_RUN" = true ]; then
        log "Dry run mode - would run: python scripts/identify_poor_contracts.py --limit 500"
        log_success "Stage 4 completed (dry run)"
    else
        if python -u "$SCRIPTS_DIR/identify_poor_contracts.py" --limit 500 >> "$LOG_FILE" 2>&1; then
            STAGE_END=$(date +%s)
            STAGE_DURATION=$((STAGE_END - STAGE_START))
            log_success "Stage 4 completed in ${STAGE_DURATION}s"
        else
            log_error "Stage 4 failed - check log file"
            exit 1
        fi
    fi
else
    log_skip "Stage 4 (Identify Poor Contracts)"
fi

# ============================================================
# STAGE 5: SCRAPE & ENRICH
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "5" ]]; then
    log_stage 5 "SCRAPE & ENRICH"
    
    if [ -f "$SCRIPTS_DIR/daily_scrape.py" ]; then
        STAGE_START=$(date +%s)
        
        if [ "$DRY_RUN" = true ]; then
            log "Dry run mode - would run: python scripts/daily_scrape.py --limit 500"
            log_success "Stage 5 completed (dry run)"
        else
            if [ -f "$DATA_DIR/to_scrape.csv" ]; then
                if python -u "$SCRIPTS_DIR/daily_scrape.py" --limit 190 >> "$LOG_FILE" 2>&1; then
                    STAGE_END=$(date +%s)
                    STAGE_DURATION=$((STAGE_END - STAGE_START))
                    log_success "Stage 5 completed in ${STAGE_DURATION}s"
                else
                    log_error "Stage 5 failed - check log file"
                    exit 1
                fi
            else
                log_skip "Stage 5 (No to_scrape.csv found - Stage 4 may have been skipped)"
            fi
        fi
    else
        log_skip "Stage 5 (daily_scrape.py not found - create it later)"
    fi
else
    log_skip "Stage 5 (Scrape & Enrich)"
fi

# ============================================================
# STAGE 6: RE-EMBED ENRICHED CONTRACTS
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "6" ]]; then
    log_stage 6 "RE-EMBED ENRICHED CONTRACTS"
    
    if [ -f "$SCRIPTS_DIR/daily_re_embed.py" ]; then
        STAGE_START=$(date +%s)
        
        if [ "$DRY_RUN" = true ]; then
            log "Dry run mode - would run: python scripts/daily_re_embed.py --hours 24"
            log_success "Stage 6 completed (dry run)"
        else
            if python -u "$SCRIPTS_DIR/daily_re_embed.py" --hours 24 >> "$LOG_FILE" 2>&1; then
                STAGE_END=$(date +%s)
                STAGE_DURATION=$((STAGE_END - STAGE_START))
                log_success "Stage 6 completed in ${STAGE_DURATION}s"
            else
                log_error "Stage 6 failed - check log file"
                exit 1
            fi
        fi
    else
        log_skip "Stage 6 (daily_re_embed.py not found - create it later)"
    fi
else
    log_skip "Stage 6 (Re-embed Enriched)"
fi

# ============================================================
# STAGE 7: UPDATE MATCH CACHE (Placeholder - Already Done in Backend)
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "7" ]]; then
    log_stage 7 "UPDATE MATCH CACHE"
    
    log "   Match cache updated by nightly cron job (already implemented)"
    log_skip "Stage 7 (Handled by existing backend service)"
else
    log_skip "Stage 7 (Update Match Cache)"
fi

# ============================================================
# STAGE 8: HEALTH CHECK
# ============================================================

if [[ ! "$SKIP_STAGES" =~ "8" ]]; then
    log_stage 8 "HEALTH CHECK"
    
    STAGE_START=$(date +%s)
    
    if python -u "$SCRIPTS_DIR/daily_health_check.py" >> "$LOG_FILE" 2>&1; then
        STAGE_END=$(date +%s)
        STAGE_DURATION=$((STAGE_END - STAGE_START))
        log_success "Stage 8 completed in ${STAGE_DURATION}s"
    else
        log_error "Stage 8 health check failed - review pipeline logs"
        exit 1
    fi
else
    log_skip "Stage 8 (Health Check)"
fi

# ============================================================
# PIPELINE COMPLETE
# ============================================================

PIPELINE_END=$(date +%s)
PIPELINE_DURATION=$((PIPELINE_END - PIPELINE_START))
PIPELINE_MINUTES=$((PIPELINE_DURATION / 60))
PIPELINE_SECONDS=$((PIPELINE_DURATION % 60))

log ""
log "=========================================="
log "✅ PIPELINE COMPLETE"
log "=========================================="
log "Total duration: ${PIPELINE_MINUTES}m ${PIPELINE_SECONDS}s"
log "Log file: $LOG_FILE"
log ""