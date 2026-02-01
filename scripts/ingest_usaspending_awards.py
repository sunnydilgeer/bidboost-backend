"""
Ingest historical contract awards from USASpending.gov bulk downloads.

DATA SOURCE: https://www.usaspending.gov/download_center/award_data_archive
FILES: FY*_All_Contracts_Full_*.csv

PROCESS:
1. Download CSVs (last 3-4 years: 2022-2025)
2. Load ALL contracts (no NAICS filtering)
3. Load into PostgreSQL
4. ~100GB raw → ~30-40GB in database (ALL contracts)
"""

import sys
import os

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import logging
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from app.database import SessionLocal
from app.models.contract_awards import ContractAward
from datetime import datetime
from typing import List
import glob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ NO NAICS FILTERING - INGEST EVERYTHING
# This ensures we never have coverage gaps for any industry

def _safe_int(value):
    """Safely convert value to int, handling NaN and empty strings."""
    if pd.isna(value) or value == "" or value is None:
        return None
    try:
        return int(float(value))  # Convert to float first, then int
    except (ValueError, TypeError):
        return None

def clean_currency(value):
    """Convert currency string to float."""
    if pd.isna(value) or value == "" or value is None:
        return None
    try:
        # Remove $ and commas
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None

def clean_date(value):
    """Convert date string to datetime."""
    if pd.isna(value) or value == "" or value is None:
        return None
    try:
        return pd.to_datetime(value).date()
    except:
        return None

def _is_contract_active(end_date_str):
    """Check if contract is still active based on end date."""
    if not end_date_str or pd.isna(end_date_str):
        return False
    
    try:
        end_date = pd.to_datetime(end_date_str).date()
        return end_date >= datetime.now().date()
    except:
        return False

def ingest_awards_csv(csv_path: str, db: Session, batch_size: int = 1000):
    """
    Ingest awards from a single CSV file.
    
    ✅ INGESTS ALL NAICS CODES - NO FILTERING
    """
    
    logger.info(f"Reading {csv_path}...")
    
    # Read CSV in chunks (memory efficient)
    try:
        chunk_iter = pd.read_csv(
            csv_path,
            chunksize=batch_size,
            dtype=str,  # Read everything as string first
            low_memory=False
        )
    except Exception as e:
        logger.error(f"Failed to read {csv_path}: {e}")
        return
    
    total_processed = 0
    total_inserted = 0
    total_skipped = 0
    
    for chunk in chunk_iter:
        # ✅ NO NAICS FILTERING - Process everything
        
        award_dicts = []
        
        for _, row in chunk.iterrows():
            try:
                # Skip if missing critical data
                if pd.isna(row.get('award_id_piid')) or pd.isna(row.get('recipient_name')):
                    continue
                
                award_dict = {
                    # Identifiers
                    'award_id': row.get('award_id_piid'),
                    'piid': row.get('award_id_piid'),  # Use same as award_id
                    
                    # Incumbent (awardee) - WHO WON
                    'awardee_name': row.get('recipient_name', '').strip(),
                    'awardee_uei': row.get('recipient_uei'),
                    'awardee_duns': row.get('recipient_duns'),
                    
                    # Agency information
                    'agency_name': row.get('awarding_agency_name', '').strip(),
                    'sub_agency_name': row.get('awarding_sub_agency_name'),
                    'office_name': row.get('awarding_office_name'),
                    
                    # Classification codes
                    'naics_code': row.get('naics_code'),
                    'naics_description': row.get('naics_description'),
                    'psc_code': row.get('product_or_service_code'),
                    'psc_description': row.get('product_or_service_code_description'),
                    
                    # Award details
                    'award_amount': clean_currency(row.get('current_total_value_of_award')),
                    'contract_start_date': clean_date(row.get('period_of_performance_start_date')),
                    'contract_end_date': clean_date(row.get('period_of_performance_current_end_date')),
                    'award_date': clean_date(row.get('action_date')),
                    
                    # Competition intelligence
                    'number_of_offers': _safe_int(row.get('number_of_offers_received')),
                    'extent_competed': row.get('extent_competed'),
                    'set_aside_type': row.get('type_of_set_aside'),
                    
                    # Contract details
                    'contract_type': row.get('type_of_contract_pricing'),
                    'description': row.get('transaction_description'),
                    
                    # Place of performance
                    'pop_state': row.get('primary_place_of_performance_state_code'),
                    'pop_city': row.get('primary_place_of_performance_city_name'),
                    'pop_country': row.get('primary_place_of_performance_country_code'),
                    
                    # Metadata
                    'fiscal_year': _safe_int(row.get('action_date_fiscal_year')),
                    'is_active': _is_contract_active(row.get('period_of_performance_current_end_date'))
                }
                
                award_dicts.append(award_dict)
                
            except Exception as e:
                logger.error(f"Error processing row: {e}")
                continue
        
        # Bulk insert with ON CONFLICT (skip duplicates)
        if award_dicts:
            try:
                stmt = insert(ContractAward.__table__).values(award_dicts)
                stmt = stmt.on_conflict_do_nothing(index_elements=['award_id'])
                
                result = db.execute(stmt)
                db.commit()
                
                inserted_count = result.rowcount
                skipped_count = len(award_dicts) - inserted_count
                
                total_inserted += inserted_count
                total_skipped += skipped_count
                
                logger.info(f"✅ Inserted {inserted_count} new awards, ⏭️ skipped {skipped_count} duplicates (total: {total_inserted} inserted, {total_skipped} skipped)")
                
            except Exception as e:
                db.rollback()
                logger.error(f"Bulk insert failed: {e}")
        
        total_processed += len(chunk)
    
    logger.info(f"✅ Completed {csv_path}: Processed {total_processed}, Inserted {total_inserted}, Skipped {total_skipped}")

def main():
    """
    Main ingestion workflow.
    
    ✅ INGESTS ALL NAICS CODES FOR COMPLETE COVERAGE
    """
    
    csv_files = glob.glob("data/usaspending/FY*_All_Contracts_Full_*.csv")
    
    if not csv_files:
        logger.error("No CSV files found in data/usaspending/")
        logger.info("Expected path: data/usaspending/FY*_All_Contracts_Full_*.csv")
        return
    
    logger.info(f"Found {len(csv_files)} CSV files to process")
    logger.info(f"⚠️ INGESTING ALL NAICS CODES - This will take 1-2 hours")
    
    db = SessionLocal()
    
    try:
        for csv_file in sorted(csv_files):
            logger.info(f"\n{'='*80}")
            logger.info(f"Processing {csv_file}...")
            logger.info(f"{'='*80}")
            ingest_awards_csv(csv_file, db)
    
    finally:
        db.close()
    
    logger.info("\n" + "="*80)
    logger.info("🎉 USASpending ingestion complete!")
    logger.info("="*80)

if __name__ == "__main__":
    main()