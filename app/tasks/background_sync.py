import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from app.services.contract_fetcher import ContractFetcherService
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

async def sync_date_range(
    contract_service: ContractFetcherService,
    vector_store: VectorStoreService,
    llm_service: LLMService,
    published_from: datetime,
    published_to: datetime
) -> int:
    """
    Sync contracts within a specific date range.
    Returns number of contracts synced.
    """
    batch_size = 100
    total_synced = 0
    batch_num = 0
    cursor = None
    
    # Add publishedTo filter to params (will be used in first request only)
    # We'll pass this to the fetcher somehow - for now just log it
    logger.info(f"Syncing from {published_from.date()} to {published_to.date()}")
    
    while True:
        try:
            batch_num += 1
            
            # Fetch contracts with cursor
            contracts, next_cursor = await contract_service.fetch_contracts_with_cursor(
                published_from=published_from,
                limit=batch_size,
                cursor=cursor
            )
            
            # Filter by publishedTo (client-side since API doesn't support it well)
            filtered_contracts = [
                c for c in contracts 
                if c.published_date and c.published_date <= published_to
            ]
            
            if not filtered_contracts:
                logger.info(f"No more contracts in this date range")
                break
            
            # Store in Qdrant
            await vector_store.add_contracts(filtered_contracts, llm_service)
            total_synced += len(filtered_contracts)
            
            logger.info(f"Batch {batch_num}: {len(filtered_contracts)} contracts | Range total: {total_synced}")
            
            # Move to next cursor
            cursor = next_cursor
            
            if not cursor:
                logger.info(f"Reached end of results for this date range")
                break
            
            # Stop if we've gone past the date range
            if contracts and contracts[-1].published_date and contracts[-1].published_date < published_from:
                logger.info(f"Passed date range start, stopping")
                break
            
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error in batch {batch_num}: {str(e)}")
            break
    
    return total_synced


async def sync_contracts_background(days_back: int = 365):
    """
    Background task to sync ALL open tender contracts.
    Uses 30-day chunks to avoid API pagination limits.
    
    Args:
        days_back: How many days back to sync (default 365)
    """
    logger.info(f"🚀 Starting chunked sync: {days_back} days in 30-day batches")
    
    contract_service = ContractFetcherService()
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    total_synced = 0
    chunk_size_days = 30
    chunks = (days_back + chunk_size_days - 1) // chunk_size_days  # Ceiling division
    
    try:
        for chunk in range(chunks):
            days_start = chunk * chunk_size_days
            days_end = min((chunk + 1) * chunk_size_days, days_back)
            
            published_from = datetime.utcnow() - timedelta(days=days_end)
            published_to = datetime.utcnow() - timedelta(days=days_start)
            
            logger.info(f"📅 Chunk {chunk+1}/{chunks}: {published_from.date()} to {published_to.date()}")
            
            # Sync this date range
            chunk_synced = await sync_date_range(
                contract_service, vector_store, llm_service,
                published_from, published_to
            )
            
            total_synced += chunk_synced
            logger.info(f"✅ Chunk {chunk+1}/{chunks} complete: {chunk_synced} contracts | Total: {total_synced}")
            
            # Small delay between chunks
            await asyncio.sleep(2)
        
        logger.info(f"🎉 Chunked sync complete! Total synced: {total_synced}")
        return {
            "status": "complete", 
            "total_synced": total_synced,
            "chunks_processed": chunks
        }
        
    except Exception as e:
        logger.error(f"Chunked sync failed: {str(e)}")
        return {
            "status": "failed",
            "total_synced": total_synced,
            "error": str(e)
        }
    finally:
        await contract_service.close()