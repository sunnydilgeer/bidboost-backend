"""
CSV-based Contract Sync Task
Replaces API-based sync with daily CSV download
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.csv_contract_processor import CSVContractProcessor
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

# Path to your local CSV file
CSV_FILE_PATH = "data/notices.csv"  # ← Your CSV file location


async def sync_contracts_from_csv() -> Dict[str, Any]:
    """
    Main sync function: Read CSV, process contracts, upsert to Qdrant.
    Matches the pattern from background_sync.py
    """
    logger.info("🚀 Starting CSV contract sync")
    
    csv_processor = CSVContractProcessor(csv_file_path=CSV_FILE_PATH)
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    start_time = datetime.now()
    total_synced = 0
    
    try:
        # Step 1: Fetch open contracts from CSV
        logger.info("📥 Fetching contracts from CSV...")
        contracts = await csv_processor.fetch_contracts()
        
        if not contracts:
            logger.warning("⚠️ No contracts fetched from CSV")
            return {
                "status": "complete",
                "total_synced": 0,
                "duration": 0,
                "timestamp": datetime.now().isoformat()
            }
        
        logger.info(f"✅ Fetched {len(contracts)} ACTIVE contracts from CSV")
        
        # Step 2: Store in Qdrant (matches existing pattern with llm_service)
        logger.info("📊 Upserting contracts to Qdrant...")
        await vector_store.add_contracts(contracts, llm_service)
        total_synced = len(contracts)  # add_contracts returns None, so we count manually
        
        # Log sync results
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"🎉 CSV sync complete!")
        logger.info(f"  Total contracts: {len(contracts)}")
        logger.info(f"  Synced to Qdrant: {total_synced}")
        logger.info(f"  Duration: {duration:.2f}s")
        
        return {
            "status": "complete",
            "total_synced": total_synced,
            "total_contracts": len(contracts),
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ CSV sync failed: {str(e)}")
        return {
            "status": "failed",
            "total_synced": total_synced,
            "error": str(e),
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        }
    
    finally:
        await csv_processor.close()


async def run_initial_sync():
    """Run sync immediately on startup (for testing/deployment)"""
    logger.info("🚀 Running initial CSV sync...")
    result = await sync_contracts_from_csv()
    logger.info(f"Initial sync result: {result}")
    return result


def setup_scheduler() -> AsyncIOScheduler:
    """
    Setup daily scheduled sync at 7:00 AM UTC.
    Matches pattern from background_sync.py
    """
    scheduler = AsyncIOScheduler()
    
    # Schedule daily sync at 7:00 AM UTC
    scheduler.add_job(
        sync_contracts_from_csv,
        trigger=CronTrigger(hour=7, minute=0),  # 7:00 AM daily
        id="csv_contract_sync",
        name="Daily CSV Contract Sync",
        replace_existing=True
    )
    
    logger.info("⏰ Scheduled daily CSV sync at 7:00 AM UTC")
    return scheduler


async def manual_sync() -> Dict[str, Any]:
    """
    Manually trigger CSV sync (for API endpoint).
    Matches signature from background_sync.py
    """
    logger.info("🔧 Manual CSV sync triggered")
    return await sync_contracts_from_csv()


async def start_sync_service() -> AsyncIOScheduler:
    """
    Start the sync service (call this in your FastAPI startup).
    Matches pattern from background_sync.py
    """
    # Run initial sync
    await run_initial_sync()
    
    # Setup daily scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    
    logger.info("✅ CSV sync service started")
    return scheduler


# For standalone testing
async def test_sync():
    """Test the CSV sync process"""
    result = await sync_contracts_from_csv()
    print(f"\n{'='*50}")
    print(f"Sync Result:")
    print(f"  Status: {result['status']}")
    print(f"  Total Synced: {result.get('total_synced', 0)}")
    print(f"  Duration: {result.get('duration', 0):.2f}s")
    if result['status'] == 'failed':
        print(f"  Error: {result.get('error', 'Unknown')}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    asyncio.run(test_sync())