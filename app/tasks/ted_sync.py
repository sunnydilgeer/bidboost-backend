import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.services.ted_processor import TEDProcessor
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def sync_ted_opportunities():
    """Upload TED opportunities to Qdrant"""
    try:
        logger.info("Starting TED sync...")
        
        # Initialize services
        vector_store = VectorStoreService()
        llm_service = LLMService()
        ted_processor = TEDProcessor()
        
        # Fetch and process TED opportunities
        logger.info("Fetching TED opportunities...")
        opportunities = await ted_processor.fetch_opportunities()
        
        if not opportunities:
            logger.warning("No TED opportunities to sync")
            return
        
        logger.info(f"Processing {len(opportunities)} TED opportunities...")
        
        # Upload to Qdrant (reuse existing method)
        await vector_store.add_contracts(opportunities, llm_service)
        
        logger.info(f"✅ Successfully synced {len(opportunities)} TED opportunities")
        
        # Log statistics
        english_native = sum(1 for o in opportunities if not o.metadata.get('translated'))
        translated = sum(1 for o in opportunities if o.metadata.get('translated'))
        
        logger.info(f"Stats: {english_native} English-native, {translated} translated")
        
    except Exception as e:
        logger.error(f"❌ TED sync failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(sync_ted_opportunities())