import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from app.services.contract_fetcher import ContractFetcherService
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

async def sync_contracts_background(limit: int = 10000, days_back: int = 365):
    """
    Background task to sync large number of contracts without timeout.
    Uses date-based pagination instead of offset (UK API ignores offset with publishedFrom).
    """
    logger.info(f"🚀 Starting background sync: {limit} contracts, {days_back} days back")
    
    contract_service = ContractFetcherService()
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    batch_size = 100
    batches = limit // batch_size
    
    total_synced = 0
    total_failed = 0
    
    # Start from days_back ago and move forward in time
    current_date = datetime.utcnow() - timedelta(days=days_back)
    end_date = datetime.utcnow()
    
    try:
        batch_num = 0
        
        while batch_num < batches and current_date < end_date:
            try:
                batch_num += 1
                logger.info(f"📦 Processing batch {batch_num}/{batches} (from: {current_date.isoformat()})")
                
                # Fetch contracts from current_date forward
                contracts = await contract_service.fetch_contracts_from_date(
                    published_from=current_date,
                    limit=batch_size
                )
                
                # Stop if no more contracts
                if not contracts:
                    logger.info(f"No more contracts found from {current_date.isoformat()}")
                    break
                
                # Store in Qdrant
                await vector_store.add_contracts(contracts, llm_service)
                total_synced += len(contracts)
                
                logger.info(f"✅ Batch {batch_num}/{batches} complete. Synced: {len(contracts)} | Total: {total_synced}")
                
                # Move current_date forward to AFTER the latest contract in this batch
                # This prevents fetching the same contracts again
                latest_date = max(c.published_date for c in contracts if c.published_date)
                
                # Add 1 second to avoid getting the same contract again
                current_date = latest_date + timedelta(seconds=1)
                
                logger.info(f"📅 Next batch will start from: {current_date.isoformat()}")
                
                # Small delay between batches
                await asyncio.sleep(1)
                
            except Exception as e:
                total_failed += 1
                logger.error(f"❌ Error in batch {batch_num}: {str(e)}")
                # Move forward anyway to avoid infinite loop
                current_date = current_date + timedelta(hours=1)
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