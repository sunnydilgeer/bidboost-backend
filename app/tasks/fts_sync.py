"""
FTS Award Contract Sync Task
Syncs awarded contracts from FTS JSON to Qdrant
Runs daily at 4:00 AM (1 hour before CF sync)
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.fts_processor import FTSProcessor
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

# Path to FTS scraped data
FTS_JSON_PATH = "fts_live_rich.json"


async def sync_fts_contracts() -> Dict[str, Any]:
    """
    Main sync function: Read FTS JSON, process BOTH opportunities and awards, upsert to Qdrant.
    Matches the pattern from csv_sync.py
    """
    logger.info("🚀 Starting FTS contract sync (opportunities + awards)")
    
    fts_processor = FTSProcessor(json_file_path=FTS_JSON_PATH)
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    start_time = datetime.now()
    total_opportunities = 0
    total_awards = 0
    
    try:
        # Step 1: Fetch FTS opportunities
        logger.info("📥 Loading FTS opportunities from JSON...")
        opportunities = await fts_processor.fetch_opportunities()
        
        if opportunities:
            logger.info(f"✅ Loaded {len(opportunities)} FTS opportunities")
            logger.info("📊 Upserting opportunities to Qdrant...")
            await vector_store.add_contracts(opportunities, llm_service)
            total_opportunities = len(opportunities)
        else:
            logger.warning("⚠️ No FTS opportunities found")
        
        # Step 2: Fetch FTS awarded contracts
        logger.info("📥 Loading FTS awarded contracts from JSON...")
        awards = await fts_processor.fetch_awarded_contracts()
        
        if awards:
            logger.info(f"✅ Loaded {len(awards)} FTS awards")
            logger.info("📊 Upserting awards to Qdrant...")
            await vector_store.add_fts_awards(awards, llm_service)
            total_awards = len(awards)
        else:
            logger.warning("⚠️ No FTS awards found")
        
        # Log sync results
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"🎉 FTS sync complete!")
        logger.info(f"  Opportunities synced: {total_opportunities}")
        logger.info(f"  Awards synced: {total_awards}")
        logger.info(f"  Total: {total_opportunities + total_awards}")
        logger.info(f"  Duration: {duration:.2f}s")
        
        return {
            "status": "complete",
            "opportunities_synced": total_opportunities,
            "awards_synced": total_awards,
            "total_synced": total_opportunities + total_awards,
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"❌ FTS sync failed: {str(e)}")
        return {
            "status": "failed",
            "opportunities_synced": total_opportunities,
            "awards_synced": total_awards,
            "error": str(e),
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        }
    
    finally:
        await fts_processor.close()


async def run_initial_sync():
    """Run sync immediately on startup (for testing/deployment)"""
    logger.info("🚀 Running initial FTS sync...")
    result = await sync_fts_awards()
    logger.info(f"Initial FTS sync result: {result}")
    return result


def setup_scheduler() -> AsyncIOScheduler:
    """
    Setup daily scheduled sync at 4:00 AM UTC (1 hour before CF sync).
    Matches pattern from csv_sync.py
    """
    scheduler = AsyncIOScheduler()
    
    # Schedule daily sync at 4:00 AM UTC
    scheduler.add_job(
        sync_fts_awards,
        trigger=CronTrigger(hour=4, minute=0),  # 4:00 AM daily
        id="fts_award_sync",
        name="Daily FTS Award Contract Sync",
        replace_existing=True
    )
    
    logger.info("⏰ Scheduled daily FTS sync at 4:00 AM UTC")
    return scheduler


async def manual_sync() -> Dict[str, Any]:
    """
    Manually trigger FTS sync (for API endpoint).
    Matches signature from csv_sync.py
    """
    logger.info("🔧 Manual FTS sync triggered")
    return await sync_fts_awards()


async def start_sync_service() -> AsyncIOScheduler:
    """
    Start the FTS sync service (call this in your FastAPI startup).
    Matches pattern from csv_sync.py
    """
    # Run initial sync
    await run_initial_sync()
    
    # Setup daily scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    
    logger.info("✅ FTS sync service started")
    return scheduler


# For standalone testing
async def test_sync():
    """Test the FTS sync process"""
    result = await sync_fts_contracts()
    print(f"\n{'='*50}")
    print(f"FTS Sync Result:")
    print(f"  Status: {result['status']}")
    print(f"  Total Synced: {result.get('total_synced', 0)}")
    print(f"  Duration: {result.get('duration', 0):.2f}s")
    if result['status'] == 'failed':
        print(f"  Error: {result.get('error', 'Unknown')}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    asyncio.run(test_sync())