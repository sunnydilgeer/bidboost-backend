"""
Clean vector store service for contract opportunities only.
Supports both Qdrant (dev) and will support Pinecone (production).
"""
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client import models
from app.core.config import settings

logger = logging.getLogger(__name__)

class VectorStoreService:
    """Vector store service for contract opportunities - Qdrant/Pinecone ready"""
    
    def __init__(self):
        self.settings = settings
        self.vector_size = 768  # OpenAI text-embedding-3-small
        
        # Collection name for contracts
        self.collection_name = "contracts"
        
        # Initialize Qdrant client
        logger.info(f"Connecting to Qdrant at: {self.settings.QDRANT_URL}")
        try:
            self.client = QdrantClient(
                url=self.settings.QDRANT_URL,
                timeout=30
            )
            logger.info("✅ Qdrant client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            raise
    
    def ensure_collection_exists(self):
        """Create contracts collection if it doesn't exist"""
        try:
            collections = self.client.get_collections().collections
            collection_exists = any(c.name == self.collection_name for c in collections)
            
            if not collection_exists:
                logger.info(f"Creating collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(f"✅ Collection '{self.collection_name}' created successfully")
            else:
                logger.info(f"✅ Collection '{self.collection_name}' already exists")
                
        except Exception as e:
            logger.error(f"Error ensuring collection exists: {e}")
            raise
    
    def upsert_documents(self, documents: List[Dict[str, Any]]):
        """
        Upsert contract opportunity documents to vector store
        
        Args:
            documents: List of dicts with 'id', 'vector', and 'payload' keys
        """
        try:
            if not documents:
                logger.warning("No documents to upsert")
                return
            
            # Convert to Qdrant points
            points = [
                models.PointStruct(
                    id=doc["id"],
                    vector=doc["vector"],
                    payload=doc["payload"]
                )
                for doc in documents
            ]
            
            # Upsert to Qdrant
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            
            logger.info(f"✅ Upserted {len(documents)} documents to {self.collection_name}")
            
        except Exception as e:
            logger.error(f"Error upserting documents: {e}")
            raise
    
    async def search_contracts(
        self,
        query_text: str,
        llm_service,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for contract opportunities using semantic search
        
        Args:
            query_text: Search query
            llm_service: LLM service for generating embeddings
            limit: Max number of results
            filters: Optional Qdrant filters
            
        Returns:
            List of contract opportunity dicts with scores
        """
        try:
            # Generate query embedding
            query_vector = await llm_service.generate_embeddings(query_text)
            
            # Search Qdrant
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=filters
            )
            
            # Format results
            formatted_results = []
            for result in results:
                contract = result.payload
                contract['score'] = result.score
                formatted_results.append(contract)
            
            logger.info(f"Found {len(formatted_results)} results for query: {query_text[:50]}...")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching contracts: {e}")
            raise
    
    def get_document_count(self) -> int:
        """Get total number of contracts in vector store"""
        try:
            collection_info = self.client.get_collection(self.collection_name)
            count = collection_info.points_count
            logger.info(f"Total contracts in {self.collection_name}: {count}")
            return count
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0
    
    def delete_collection(self):
        """Delete the contracts collection (use with caution!)"""
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"🗑️ Deleted collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            raise