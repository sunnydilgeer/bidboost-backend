from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.models.company import CompanyCapability
from app.services.llm import LLMService
from sqlalchemy.orm import Session
from typing import List
import uuid
import logging

logger = logging.getLogger(__name__)

class CapabilityStoreService:
    """Service to manage company capabilities in Qdrant for semantic matching"""
    
    COLLECTION_NAME = "capabilities"
    VECTOR_SIZE = 768  # Match your embedding model dimension
    
    def __init__(self, qdrant_client: QdrantClient):
        self.client = qdrant_client
        self._ensure_collection_exists()
    
    def _ensure_collection_exists(self):
        """Create capabilities collection if it doesn't exist"""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.COLLECTION_NAME not in collection_names:
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=self.VECTOR_SIZE,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"✅ Created '{self.COLLECTION_NAME}' collection")
            else:
                logger.info(f"Collection '{self.COLLECTION_NAME}' already exists")
        
        except Exception as e:
            logger.error(f"Failed to ensure collection exists: {str(e)}")
            raise
    
    async def add_capability(
        self,
        capability: CompanyCapability,
        llm_service: LLMService
    ) -> str:
        """
        Add a single capability to Qdrant with embedding.
        Returns the Qdrant point ID.
        """
        try:
            # Generate embedding for capability text
            embedding = await llm_service.generate_embeddings(capability.capability_text)
            
            # Create unique point ID
            point_id = str(uuid.uuid4())
            
            # Create point with metadata
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "capability_id": capability.id,
                    "firm_id": capability.company.firm_id,
                    "capability_text": capability.capability_text,
                    "category": capability.category,
                    "years_experience": capability.years_experience
                }
            )
            
            # Upload to Qdrant
            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=[point]
            )
            
            logger.info(f"Added capability {capability.id} to Qdrant (point: {point_id})")
            
            return point_id
        
        except Exception as e:
            logger.error(f"Failed to add capability: {str(e)}")
            raise
    
    async def sync_all_capabilities(
        self,
        db: Session,
        llm_service: LLMService
    ) -> int:
        """
        Sync all capabilities from database to Qdrant.
        Returns count of capabilities synced.
        """
        try:
            # Get all capabilities without qdrant_id
            capabilities = db.query(CompanyCapability).filter(
                CompanyCapability.qdrant_id.is_(None)
            ).all()
            
            synced_count = 0
            
            for capability in capabilities:
                try:
                    point_id = await self.add_capability(capability, llm_service)
                    
                    # Update database with qdrant_id
                    capability.qdrant_id = point_id
                    db.commit()
                    
                    synced_count += 1
                
                except Exception as e:
                    logger.error(f"Failed to sync capability {capability.id}: {str(e)}")
                    db.rollback()
                    continue
            
            logger.info(f"✅ Synced {synced_count}/{len(capabilities)} capabilities to Qdrant")
            
            return synced_count
        
        except Exception as e:
            logger.error(f"Failed to sync capabilities: {str(e)}")
            raise
    
    def delete_capability(self, qdrant_id: str):
        """Delete a capability from Qdrant"""
        try:
            self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=[qdrant_id]
            )
            logger.info(f"Deleted capability {qdrant_id} from Qdrant")
        
        except Exception as e:
            logger.error(f"Failed to delete capability: {str(e)}")
            raise