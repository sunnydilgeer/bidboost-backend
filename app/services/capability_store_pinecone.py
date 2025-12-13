"""
Pinecone-based capability storage service
Stores company capabilities in Pinecone namespace for semantic matching
"""
from pinecone import Pinecone
from app.models.company import CompanyCapability
from app.services.llm import LLMService
from app.core.config import settings
from typing import List, Dict, Optional
import uuid
import logging

logger = logging.getLogger(__name__)

class CapabilityStorePinecone:
    """Store company capabilities in Pinecone for semantic matching"""
    
    NAMESPACE = "capabilities"  # Separate namespace in same index
    
    def __init__(self):
        """Initialize Pinecone client and connect to index"""
        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        self.index = pc.Index("contracts")  # Same index, different namespace
        logger.info("✅ Connected to Pinecone capabilities namespace")
    
    async def add_capability(
        self,
        capability: CompanyCapability,
        llm_service: LLMService
    ) -> str:
        """
        Add capability with embedding to Pinecone
        
        Args:
            capability: CompanyCapability DB model
            llm_service: LLM service for generating embeddings
            
        Returns:
            Pinecone vector ID (UUID)
        """
        try:
            # Generate embedding
            embedding = await llm_service.generate_embeddings(capability.capability_text)
            
            # Create unique ID
            vector_id = str(uuid.uuid4())
            
            # Upsert to Pinecone
            self.index.upsert(
                vectors=[{
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "capability_id": capability.id,
                        "firm_id": capability.company.firm_id,
                        "capability_text": capability.capability_text,
                        "category": capability.category or "",
                        "years_experience": capability.years_experience or 0
                    }
                }],
                namespace=self.NAMESPACE
            )
            
            logger.info(f"✅ Added capability {capability.id} to Pinecone: {capability.capability_text[:50]}...")
            return vector_id
        
        except Exception as e:
            logger.error(f"Failed to add capability {capability.id}: {e}")
            raise
    
    def get_capability(self, vector_id: str) -> Optional[Dict]:
        """
        Fetch capability by ID with vector
        
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
            
            logger.warning(f"Capability {vector_id} not found in Pinecone")
            return None
        
        except Exception as e:
            logger.error(f"Failed to fetch capability {vector_id}: {e}")
            return None
    
    def get_capabilities_batch(self, vector_ids: List[str]) -> Dict[str, Dict]:
        """
        Fetch multiple capabilities at once (more efficient)
        
        Args:
            vector_ids: List of Pinecone vector IDs
            
        Returns:
            Dict mapping vector_id -> {id, vector, metadata}
        """
        if not vector_ids:
            logger.warning("⚠️ get_capabilities_batch called with empty vector_ids list")
            return {}
        
        try:
            logger.info(f"🔍 Fetching {len(vector_ids)} capabilities from Pinecone: {vector_ids}")
            
            result = self.index.fetch(
                ids=vector_ids,
                namespace=self.NAMESPACE
            )
            
            # ✅ FIX: Return proper dict structure, not just vector values
            capabilities = {}
            for vec_id, vec_data in result.vectors.items():
                capabilities[vec_id] = list(vec_data.values)  # Just the vector array

            
            # Log missing vectors
            missing = set(vector_ids) - set(capabilities.keys())
            if missing:
                logger.error(f"❌ Missing {len(missing)} capabilities from Pinecone: {missing}")
            
            logger.info(f"✅ Fetched {len(capabilities)}/{len(vector_ids)} capabilities from Pinecone")
            
            return capabilities
        
        except Exception as e:
            logger.error(f"❌ Failed to fetch capabilities batch: {e}")
            return {}
    
    def delete_capability(self, vector_id: str):
        """
        Delete capability from Pinecone
        
        Args:
            vector_id: Pinecone vector ID to delete
        """
        try:
            self.index.delete(
                ids=[vector_id],
                namespace=self.NAMESPACE
            )
            logger.info(f"✅ Deleted capability {vector_id} from Pinecone")
        
        except Exception as e:
            logger.error(f"Failed to delete capability {vector_id}: {e}")
            raise
    
    def get_namespace_stats(self) -> Dict:
        """Get statistics about capabilities namespace"""
        try:
            stats = self.index.describe_index_stats()
            namespace_stats = stats.namespaces.get(self.NAMESPACE, {})
            
            return {
                "total_capabilities": namespace_stats.vector_count if namespace_stats else 0,
                "dimension": 768
            }
        
        except Exception as e:
            logger.error(f"Failed to get namespace stats: {e}")
            return {"total_capabilities": 0, "dimension": 768}


# Singleton instance
_capability_store = None

def get_capability_store() -> CapabilityStorePinecone:
    """Get singleton instance of CapabilityStorePinecone"""
    global _capability_store
    if _capability_store is None:
        _capability_store = CapabilityStorePinecone()
    return _capability_store