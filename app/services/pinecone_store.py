"""
Pinecone Vector Store Service for SAM.GOV contracts
Drop-in replacement for Qdrant with identical interface
"""
from typing import List, Dict, Any, Optional
from pinecone import Pinecone
import logging

logger = logging.getLogger(__name__)

class PineconeStoreService:
    def __init__(self, api_key: str):
        """Initialize Pinecone client and connect to index"""
        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index("contracts")
        logger.info("✅ Connected to Pinecone index: contracts")
    
    def upsert_documents(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 100
    ) -> int:
        """
        Upsert documents to Pinecone
        
        Args:
            documents: List of dicts with 'id', 'embedding', and metadata
            batch_size: Vectors per batch (Pinecone max: 100)
        
        Returns:
            Number of documents upserted
        """
        try:
            vectors = []
            for doc in documents:
                payload = doc.get("payload", {})
                vectors.append({
                    "id": doc["id"],
                    "values": doc["embedding"],
                    "metadata": {
                        "notice_id": payload.get("notice_id") or "",
                        "title": payload.get("title") or "",
                        "agency": payload.get("agency") or "",
                        "description": (payload.get("description") or "")[:1000],
                        "posted_date": payload.get("published_date") or "",
                        "response_deadline": payload.get("closing_date") or "",
                        "naics_code": str(payload.get("cpv_codes") or []),
                        "set_aside": payload.get("metadata", {}).get("set_aside") or "",
                        "contract_value": float(payload.get("value") or 0.0),
                        "state": payload.get("region") or "",
                        "url": payload.get("source_url") or "",
                    }
                })
            
            # Batch upsert
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                self.index.upsert(vectors=batch)
            
            logger.info(f"✅ Upserted {len(vectors)} vectors to Pinecone")
            return len(vectors)
            
        except Exception as e:
            logger.error(f"❌ Pinecone upsert failed: {e}")
            raise
    
    def search_contracts(
        self,
        query_vector: List[float],
        limit: int = 10,
        min_score: float = 0.0,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search contracts by semantic similarity
        
        Args:
            query_vector: 768-dim embedding
            limit: Max results
            min_score: Minimum similarity score (0-1)
            filter_dict: Pinecone metadata filters (optional)
        
        Returns:
            List of matching contracts with scores
        """
        try:
            results = self.index.query(
                vector=query_vector,
                top_k=limit,
                include_metadata=True,
                filter=filter_dict  # e.g., {"agency": {"$eq": "DHS"}}
            )
            
            contracts = []
            for match in results.matches:
                if match.score >= min_score:
                    contracts.append({
                        "id": match.id,
                        "score": match.score,
                        "notice_id": match.metadata.get("notice_id"),
                        "title": match.metadata.get("title"),
                        "agency": match.metadata.get("agency"),
                        "description": match.metadata.get("description"),
                        "posted_date": match.metadata.get("posted_date"),
                        "response_deadline": match.metadata.get("response_deadline"),
                        "naics_code": match.metadata.get("naics_code"),
                        "set_aside": match.metadata.get("set_aside"),
                        "contract_value": match.metadata.get("contract_value"),
                        "state": match.metadata.get("state"),
                        "url": match.metadata.get("url"),
                    })
            
            logger.info(f"🔍 Found {len(contracts)} contracts (score >= {min_score})")
            return contracts
            
        except Exception as e:
            logger.error(f"❌ Pinecone search failed: {e}")
            raise
    
    def get_document_count(self) -> int:
        """Get total number of vectors in index"""
        try:
            stats = self.index.describe_index_stats()
            total = stats.total_vector_count
            logger.info(f"📊 Pinecone index has {total} vectors")
            return total
        except Exception as e:
            logger.error(f"❌ Failed to get count: {e}")
            return 0
    
    def delete_all(self):
        """Delete all vectors (use with caution!)"""
        try:
            self.index.delete(delete_all=True)
            logger.warning("⚠️ Deleted all vectors from Pinecone")
        except Exception as e:
            logger.error(f"❌ Delete failed: {e}")
            raise
    
    def get_by_id(self, notice_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a contract by notice_id"""
        try:
            result = self.index.fetch(ids=[notice_id])
            if notice_id in result.vectors:
                vec = result.vectors[notice_id]
                return {
                    "id": notice_id,
                    **vec.metadata
                }
            return None
        except Exception as e:
            logger.error(f"❌ Fetch by ID failed: {e}")
            return None