import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from app.services.contract_fetcher import ContractFetcherService
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

async def sync_contracts_background(days_back: int = 365):
    """
    Background task to sync ALL open contracts (no arbitrary limit).
    Uses cursor-based pagination and filters for closing_date > today.
    
    Args:
        days_back: How many days back to look for published contracts
    """
    logger.info(f"🚀 Starting background sync: ALL open contracts from last {days_back} days")
    
    contract_service = ContractFetcherService()
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    batch_size = 100
    total_synced = 0
    total_failed = 0
    batch_num = 0
    cursor = None
    
    # Start date for filtering
    published_from = datetime.utcnow() - timedelta(days=days_back)
    
    try:
        while True:  # Keep syncing until no more open contracts
            try:
                batch_num += 1
                logger.info(f"📦 Processing batch {batch_num} (cursor: {cursor or 'initial'})")
                
                # Fetch contracts with cursor (already filtered by closing_date in contract_fetcher)
                contracts, next_cursor = await contract_service.fetch_contracts_with_cursor(
                    published_from=published_from,
                    limit=batch_size,
                    cursor=cursor
                )
                
                if not contracts:
                    logger.info(f"✅ No more open contracts found at batch {batch_num}")
                    break
                
                # Store in Qdrant
                await vector_store.add_contracts(contracts, llm_service)
                total_synced += len(contracts)
                
                logger.info(f"✅ Batch {batch_num} complete. Synced: {len(contracts)} | Total: {total_synced}")
                
                # Move to next cursor
                cursor = next_cursor
                
                if not cursor:
                    logger.info(f"✅ Reached end of results - all open contracts synced")
                    break
                
                logger.info(f"📅 Next cursor: {cursor}")
                await asyncio.sleep(1)
                
            except Exception as e:
                total_failed += 1
                logger.error(f"❌ Error in batch {batch_num}: {str(e)}")
                if not cursor:
                    break
                continue
        
        logger.info(f"🎉 Background sync complete! Total synced: {total_synced} | Failed batches: {total_failed}")
        return {
            "status": "complete", 
            "total_synced": total_synced,
            "total_failed": total_failed,
            "batches_processed": batch_num
        }
        
    finally:
        await contract_service.close()