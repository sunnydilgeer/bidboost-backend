"""
Clean vector store service for contract opportunities only.
Supports Pinecone with PostgreSQL metadata.
🆕 NOW USES SOW TEXT when available for better semantic matching
"""
import logging
from typing import List, Dict, Any, Optional
from pinecone import Pinecone
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.contract_sow import ContractSOW

logger = logging.getLogger(__name__)

class VectorStoreService:
    """Vector store service for contract opportunities - Pinecone"""
    
    def __init__(self, db: Session = None):
        self.settings = settings
        self.vector_size = 768  # OpenAI text-embedding-3-small
        self.db = db  # 🆕 Database session for SOW lookups
        
        # Index name for contracts
        self.index_name = "contracts"
        
        # Initialize Pinecone client
        logger.info(f"Connecting to Pinecone")
        try:
            self.pc = Pinecone(api_key=self.settings.PINECONE_API_KEY)
            self.index = self.pc.Index(self.index_name)
            logger.info("✅ Pinecone client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Pinecone client: {e}")
            raise
    
    def _get_text_for_embedding(self, contract_data: Dict[str, Any]) -> str:
        """
        🆕 Get the best text for embedding - SOW if available, else description.
        
        This is THE KEY METHOD that improves match quality!
        
        Args:
            contract_data: Contract dict with notice_id, description, etc.
            
        Returns:
            Text to use for embedding (SOW or description)
        """
        notice_id = contract_data.get("notice_id")
        description = contract_data.get("description", "")
        
        # Try to get SOW from database
        if self.db and notice_id:
            sow = self.db.query(ContractSOW).filter(
                ContractSOW.notice_id == notice_id,
                ContractSOW.confidence.in_(["HIGH", "MEDIUM"])  # Only use HIGH/MEDIUM confidence
            ).first()
            
            if sow:
                logger.debug(f"Using SOW text for {notice_id} (confidence: {sow.confidence}, {sow.word_count} words)")
                return sow.sow_text
        
        # Fallback to description
        logger.debug(f"Using description for {notice_id}")
        return description
    
    async def upsert_contracts(
        self,
        contracts: List[Dict[str, Any]],
        llm_service
    ):
        """
        🆕 Upsert contract opportunities to Pinecone with SOW text when available.
        
        Args:
            contracts: List of contract dicts with metadata
            llm_service: LLM service for generating embeddings
        """
        try:
            if not contracts:
                logger.warning("No contracts to upsert")
                return
            
            vectors = []
            
            for contract in contracts:
                notice_id = contract.get("notice_id")
                
                # 🆕 Get best text for embedding (SOW or description)
                text_for_embedding = self._get_text_for_embedding(contract)
                
                if not text_for_embedding:
                    logger.warning(f"Skipping {notice_id}: no text available")
                    continue
                
                # Generate embedding
                embedding = await llm_service.generate_embeddings(text_for_embedding)
                
                # Prepare metadata (exclude large text fields from metadata)
                metadata = {
                    "notice_id": notice_id,
                    "title": contract.get("title", ""),
                    "buyer_name": contract.get("buyer_name", ""),
                    "description": contract.get("description", "")[:500],  # Truncated
                    "value": contract.get("value"),
                    "region": contract.get("region"),
                    "closing_date": contract.get("closing_date"),
                    "naics_code": contract.get("naics_code"),
                    "psc_code": contract.get("psc_code"),
                    "set_aside": contract.get("set_aside"),
                    # 🆕 Add SOW metadata
                    "has_sow": self._has_sow(notice_id),
                }
                
                # Remove None values
                metadata = {k: v for k, v in metadata.items() if v is not None}
                
                vectors.append({
                    "id": notice_id,
                    "values": embedding,
                    "metadata": metadata
                })
            
            # Upsert to Pinecone in batches of 100
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                self.index.upsert(vectors=batch)
                logger.info(f"Upserted batch {i//batch_size + 1}: {len(batch)} vectors")
            
            logger.info(f"✅ Upserted {len(vectors)} contracts to Pinecone")
            
        except Exception as e:
            logger.error(f"Error upserting contracts: {e}")
            raise
    
    def _has_sow(self, notice_id: str) -> bool:
        """Check if contract has extracted SOW"""
        if not self.db or not notice_id:
            return False
        
        sow = self.db.query(ContractSOW).filter(
            ContractSOW.notice_id == notice_id
        ).first()
        
        return sow is not None
    
    async def search_contracts(
        self,
        query_text: str,
        llm_service,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for contract opportunities using semantic search.
        
        Args:
            query_text: Search query
            llm_service: LLM service for generating embeddings
            limit: Max number of results
            filters: Optional Pinecone filters
            
        Returns:
            List of contract opportunity dicts with scores
        """
        try:
            # Generate query embedding
            query_vector = await llm_service.generate_embeddings(query_text)
            
            # Search Pinecone
            results = self.index.query(
                vector=query_vector,
                top_k=limit,
                filter=filters,
                include_metadata=True
            )
            
            # Format results
            formatted_results = []
            for match in results.matches:
                contract = match.metadata
                contract['score'] = match.score
                contract['notice_id'] = match.id
                formatted_results.append(contract)
            
            logger.info(f"Found {len(formatted_results)} results for query: {query_text[:50]}...")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching contracts: {e}")
            raise
    
    def get_document_count(self) -> int:
        """Get total number of contracts in Pinecone"""
        try:
            stats = self.index.describe_index_stats()
            count = stats.total_vector_count
            logger.info(f"Total contracts in Pinecone: {count}")
            return count
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0
    
    def delete_index(self):
        """Delete the Pinecone index (use with caution!)"""
        try:
            self.pc.delete_index(self.index_name)
            logger.info(f"🗑️ Deleted Pinecone index: {self.index_name}")
        except Exception as e:
            logger.error(f"Error deleting index: {e}")
            raise