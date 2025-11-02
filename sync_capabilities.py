import asyncio
from app.database import get_db
from app.services.vector_store import VectorStoreService
from app.services.capability_store import CapabilityStoreService
from app.services.llm import LLMService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def sync_capabilities():
    """Sync all company capabilities to Qdrant"""
    
    # Initialize services
    vector_store = VectorStoreService()
    capability_store = CapabilityStoreService(vector_store.client)
    llm_service = LLMService()
    
    # Get database session
    db = next(get_db())
    
    try:
        logger.info("Starting capability sync...")
        count = await capability_store.sync_all_capabilities(db, llm_service)
        logger.info(f"✅ Successfully synced {count} capabilities!")
    
    except Exception as e:
        logger.error(f"❌ Sync failed: {str(e)}")
        raise
    
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(sync_capabilities())