"""
SAM.GOV contract opportunities sync to vector store
Supports syncing from JSON files: urgent, biddable, or full CSV
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any
import hashlib
import math

# Add project root to path FIRST
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# NOW import everything
from app.services.vector_store import VectorStoreService
from app.services.pinecone_store import PineconeStoreService
from app.services.llm import LLMService
from app.core.config import settings

def get_vector_store():
    """Factory: returns Pinecone or Qdrant based on config"""
    if settings.USE_PINECONE:
        return PineconeStoreService(api_key=settings.PINECONE_API_KEY)
    else:
        return VectorStoreService()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_value(val):
    """
    Convert None, NaN, 'nan' string to empty string
    Ensures Pinecone never receives null values
    """
    if val is None:
        return ""
    # Check for NaN (float)
    if isinstance(val, float) and math.isnan(val):
        return ""
    # Check for 'nan' string
    if str(val).lower() == 'nan':
        return ""
    return str(val)


def truncate_for_embedding(text: str, max_tokens: int = 8000) -> str:
    """
    Truncate text to fit within token limit
    Rough estimate: 1 token ≈ 4 characters
    """
    max_chars = max_tokens * 4  # Conservative estimate
    if len(text) <= max_chars:
        return text
    
    # Truncate and add indicator
    return text[:max_chars] + "... [truncated]"


class SAMSync:
    """Sync SAM.GOV opportunities to vector store"""
    
    def __init__(self):
        self.vector_store = get_vector_store()
        self.llm_service = LLMService()
        self.project_root = project_root
        
    def _generate_doc_id(self, notice_id: str) -> str:
        """Generate consistent document ID from notice_id"""
        return hashlib.md5(f"sam_{notice_id}".encode()).hexdigest()
    
    def _create_embedding_text(self, opp: Dict[str, Any]) -> str:
        """Create rich text for embedding from opportunity data"""
        parts = []
        
        # Title (prioritize - always include)
        if opp.get('title'):
            parts.append(opp['title'])
        
        # Description (truncate if needed)
        description = opp.get('description', '')
        if description:
            # Limit description to first 3000 chars (~750 tokens)
            truncated_desc = description[:3000]
            parts.append(truncated_desc)
        
        # Agency
        if opp.get('agency'):
            parts.append(f"Agency: {opp['agency']}")
        
        # NAICS code
        naics = clean_value(opp.get('naics_code'))
        if naics:
            parts.append(f"NAICS: {naics}")
        
        # PSC/Classification code
        psc = clean_value(opp.get('classification_code'))
        if psc:
            parts.append(f"PSC: {psc}")
        
        # Set-aside type
        set_aside = clean_value(opp.get('set_aside_type'))
        if set_aside:
            parts.append(f"Set-Aside: {set_aside}")
        
        embedding_text = ' | '.join(parts)
        
        # Final safety check - truncate if still too long
        return truncate_for_embedding(embedding_text, max_tokens=8000)
    
    def load_opportunities(self, source: str) -> List[Dict[str, Any]]:
        """
        Load opportunities from JSON file
        
        Args:
            source: 'urgent', 'biddable', or 'csv' (full dataset)
        """
        file_map = {
            'urgent': 'sam_urgent_opportunities.json',
            'biddable': 'sam_biddable_opportunities.json',
            'csv': 'sam_active_solicitations_full.json'
        }
        
        filename = file_map.get(source)
        if not filename:
            raise ValueError(f"Invalid source: {source}. Choose: urgent, biddable, or csv")
        
        filepath = self.project_root / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        logger.info(f"Loading opportunities from: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"✅ Loaded {len(data)} opportunities from {source}")
        return data
    
    async def sync_opportunities(
        self,
        opportunities: List[Dict[str, Any]],
        batch_size: int = 100
    ):
        """
        Sync opportunities to vector store in batches
        
        Args:
            opportunities: List of opportunity dicts
            batch_size: Number of opportunities per batch (100 for Pinecone)
        """
        total = len(opportunities)
        logger.info(f"Starting sync of {total} opportunities (batch size: {batch_size})")
        
        # Ensure collection exists (Qdrant only)
        if hasattr(self.vector_store, 'ensure_collection_exists'):
            self.vector_store.ensure_collection_exists()
        
        # Process in batches
        for i in range(0, total, batch_size):
            batch = opportunities[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} opportunities)...")
            
            # Prepare documents for upsert
            documents = []
            for opp in batch:
                try:
                    # Generate embedding text
                    embedding_text = self._create_embedding_text(opp)
                    
                    # Get embedding vector
                    vector = await self.llm_service.generate_embeddings(embedding_text)
                    
                    # Create document - clean ALL values to prevent None/NaN
                    doc = {
                        'id': self._generate_doc_id(opp['notice_id']),
                        'embedding': vector,
                        'payload': {
                            'notice_id': opp['notice_id'],
                            'title': clean_value(opp.get('title')),
                            'description': clean_value(opp.get('description')),
                            'agency': clean_value(opp.get('agency')),
                            'office': clean_value(opp.get('office')),
                            'naics': clean_value(opp.get('naics_code')),
                            'psc': clean_value(opp.get('classification_code')),
                            'set_aside': clean_value(opp.get('set_aside_type')),
                            'state': clean_value(opp.get('state')),
                            'city': clean_value(opp.get('city')),
                            'posted_date': clean_value(opp.get('posted_date')),
                            'response_deadline': clean_value(opp.get('response_deadline')),
                            'source_url': clean_value(opp.get('source_url')),
                            'contact_email': clean_value(opp.get('contact_email')),
                            'contact_name': clean_value(opp.get('contact_name')),
                        }
                    }
                    documents.append(doc)
                    
                except Exception as e:
                    logger.error(f"Error processing opportunity {opp.get('notice_id')}: {e}")
                    continue
            
            # Upsert batch
            if documents:
                self.vector_store.upsert_documents(documents)
                logger.info(f"✅ Batch {batch_num}/{total_batches} complete ({len(documents)} synced)")
            
        logger.info(f"🎉 Sync complete! Total: {total} opportunities")


async def main():
    """Main sync function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync SAM.GOV opportunities to vector store')
    parser.add_argument(
        '--source',
        choices=['urgent', 'biddable', 'csv'],
        default='urgent',
        help='Data source to sync'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for processing (default: 100 for Pinecone)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of opportunities to sync (for testing)'
    )
    
    args = parser.parse_args()
    
    try:
        syncer = SAMSync()
        
        # Load opportunities
        opportunities = syncer.load_opportunities(args.source)
        
        # Apply limit if specified
        if args.limit:
            opportunities = opportunities[:args.limit]
            logger.info(f"Limited to {args.limit} opportunities for testing")
        
        # Sync to vector store
        await syncer.sync_opportunities(opportunities, batch_size=args.batch_size)
        
        # Show final count
        total_count = syncer.vector_store.get_document_count()
        logger.info(f"📊 Total contracts in vector store: {total_count}")
        
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())