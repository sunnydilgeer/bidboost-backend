import asyncio
from app.services.contracts_api import ContractsAPIService
from app.core.logging_config import logger

async def sync_contracts_background(limit: int = 10000, days_back: int = 365):
    """
    Background task to sync large number of contracts without timeout.
    Runs on Railway server in the background.
    """
    logger.info(f"🚀 Starting background sync: {limit} contracts, {days_back} days back")
    
    service = ContractsAPIService()
    batch_size = 100
    batches = limit // batch_size
    
    total_synced = 0
    total_failed = 0
    
    for i in range(batches):
        try:
            logger.info(f"📦 Processing batch {i+1}/{batches}")
            result = await service.sync_contracts(limit=batch_size, days_back=days_back)
            synced = result.get("synced", 0)
            total_synced += synced
            
            logger.info(f"✅ Batch {i+1}/{batches} complete. Synced: {synced} | Total: {total_synced}")
            
            # Small delay between batches to avoid rate limits
            await asyncio.sleep(1)
            
        except Exception as e:
            total_failed += 1
            logger.error(f"❌ Error in batch {i+1}: {str(e)}")
            # Continue with next batch even if one fails
            continue
    
    logger.info(f"🎉 Background sync complete! Total synced: {total_synced} | Failed batches: {total_failed}")
    return {
        "status": "complete", 
        "total_synced": total_synced,
        "total_failed": total_failed,
        "batches_processed": batches
    }