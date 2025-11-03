import asyncio
from app.services.contract_fetcher import ContractFetcherService
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.core.logging_config import logger

async def sync_contracts_background(limit: int = 10000, days_back: int = 365):
    """
    Background task to sync large number of contracts without timeout.
    Runs on Railway server in the background.
    """
    logger.info(f"🚀 Starting background sync: {limit} contracts, {days_back} days back")
    
    contract_service = ContractFetcherService()
    vector_store = VectorStoreService()
    llm_service = LLMService()
    
    batch_size = 100
    batches = limit // batch_size
    
    total_synced = 0
    total_failed = 0
    
    try:
        for i in range(batches):
            try:
                offset = i * batch_size
                logger.info(f"📦 Processing batch {i+1}/{batches} (offset: {offset})")
                
                # Fetch contracts from API
                contracts = await contract_service.fetch_contracts(
                    limit=batch_size,
                    days_back=days_back,
                    offset=offset
                )
                
                # Stop if no more contracts
                if not contracts:
                    logger.info(f"No more contracts found at offset {offset}")
                    break
                
                # Store in Qdrant
                await vector_store.add_contracts(contracts, llm_service)
                total_synced += len(contracts)
                
                logger.info(f"✅ Batch {i+1}/{batches} complete. Synced: {len(contracts)} | Total: {total_synced}")
                
                # Small delay between batches
                await asyncio.sleep(1)
                
            except Exception as e:
                total_failed += 1
                logger.error(f"❌ Error in batch {i+1}: {str(e)}")
                continue
        
        logger.info(f"🎉 Background sync complete! Total synced: {total_synced} | Failed batches: {total_failed}")
        return {
            "status": "complete", 
            "total_synced": total_synced,
            "total_failed": total_failed,
            "batches_processed": batches
        }
        
    finally:
        await contract_service.close()