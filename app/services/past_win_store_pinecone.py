"""
Pinecone-based past win storage service
Stores company past contract wins in Pinecone namespace for semantic matching
"""
from pinecone import Pinecone
from app.models.company import PastWin
from app.services.llm import LLMService
from app.core.config import settings
from typing import List, Dict, Optional
import uuid
import logging

logger = logging.getLogger(__name__)

class PastWinStorePinecone:
    """Store company past wins in Pinecone for semantic matching"""
    
    NAMESPACE = "past_wins"  # Separate namespace in same index
    
    def __init__(self):
        """Initialize Pinecone client and connect to index"""
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        self.index = pc.Index("contracts")  # Same index, different namespace
        logger.info("✅ Connected to Pinecone past_wins namespace")
    
    async def add_past_win(
        self,
        past_win: PastWin,
        llm_service: LLMService
    ) -> str:
        """
        Add past win with embedding to Pinecone
        
        Args:
            past_win: PastWin DB model
            llm_service: LLM service for generating embeddings
            
        Returns:
            Pinecone vector ID (UUID)
        """
        try:
            # Create comprehensive text from past win
            text = f"{past_win.contract_title}. {past_win.description or ''}"
            if past_win.buyer_name:
                text += f" Buyer: {past_win.buyer_name}"
            
            # Generate embedding
            embedding = await llm_service.generate_embeddings(text)
            
            # Create unique ID
            vector_id = str(uuid.uuid4())
            
            # Upsert to Pinecone
            self.index.upsert(
                vectors=[{
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "past_win_id": past_win.id,
                        "company_id": past_win.company_id,
                        "contract_title": past_win.contract_title,
                        "buyer_name": past_win.buyer_name or "",
                        "contract_value": float(past_win.contract_value) if past_win.contract_value else 0.0,
                        "award_date": past_win.award_date.isoformat() if past_win.award_date else "",
                        "description_text": (past_win.description or "")[:1000]  # First 1000 chars
                    }
                }],
                namespace=self.NAMESPACE
            )
            
            logger.info(f"✅ Added past win {past_win.id} to Pinecone: {past_win.contract_title[:50]}...")
            return vector_id
        
        except Exception as e:
            logger.error(f"Failed to add past win {past_win.id}: {e}")
            raise
    
    def get_past_win(self, vector_id: str) -> Optional[Dict]:
        """
        Fetch past win by ID with vector
        
        Args:
            vector_id: Pinecone vector ID
            
        Returns:
            Dict with id, vector, and metadata, or None if not found
        """
        try:
            result = self.index.fetch(
                ids=[vector_id],
                namespace=self.NAMESPACE
            )
            
            if vector_id in result.vectors:
                vec = result.vectors[vector_id]
                return {
                    "id": vector_id,
                    "vector": list(vec.values), 
                    "metadata": vec.metadata
                }
            
            logger.warning(f"Past win {vector_id} not found in Pinecone")
            return None
        
        except Exception as e:
            logger.error(f"Failed to fetch past win {vector_id}: {e}")
            return None
    
    def get_past_wins_batch(self, vector_ids: List[str]) -> Dict[str, List[float]]:
        """
        Fetch multiple past wins at once (more efficient)
        
        Args:
            vector_ids: List of Pinecone vector IDs
            
        Returns:
            Dict mapping vector_id -> vector (list of floats)
        """
        try:
            if not vector_ids:
                return {}
            
            result = self.index.fetch(
                ids=vector_ids,
                namespace=self.NAMESPACE
            )
            
            past_wins = {}
            for vec_id, vec_data in result.vectors.items():
                past_wins[vec_id] = list(vec_data.values)
            
            logger.info(f"✅ Fetched {len(past_wins)}/{len(vector_ids)} past wins from Pinecone")
            return past_wins
        
        except Exception as e:
            logger.error(f"Failed to fetch past wins batch: {e}")
            return {}
    
    def delete_past_win(self, vector_id: str):
        """
        Delete past win from Pinecone
        
        Args:
            vector_id: Pinecone vector ID to delete
        """
        try:
            self.index.delete(
                ids=[vector_id],
                namespace=self.NAMESPACE
            )
            logger.info(f"✅ Deleted past win {vector_id} from Pinecone")
        
        except Exception as e:
            logger.error(f"Failed to delete past win {vector_id}: {e}")
            raise
    
    def get_namespace_stats(self) -> Dict:
        """Get statistics about past_wins namespace"""
        try:
            stats = self.index.describe_index_stats()
            namespace_stats = stats.namespaces.get(self.NAMESPACE, {})
            
            return {
                "total_past_wins": namespace_stats.vector_count if namespace_stats else 0,
                "dimension": 768
            }
        
        except Exception as e:
            logger.error(f"Failed to get namespace stats: {e}")
            return {"total_past_wins": 0, "dimension": 768}


# Singleton instance
_past_win_store = None

def get_past_win_store() -> PastWinStorePinecone:
    """Get singleton instance of PastWinStorePinecone"""
    global _past_win_store
    if _past_win_store is None:
        _past_win_store = PastWinStorePinecone()
    return _past_win_store