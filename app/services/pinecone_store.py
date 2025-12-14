"""
Pinecone Vector Store Service for SAM.GOV contracts
Maps new JSON schema to existing API schema for backward compatibility

UPDATES:
- Added naics_name field support
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
        batch_size: int = 100,
        namespace: str = "contracts"
    ) -> int:
        """
        Upsert documents to Pinecone
        Maps new schema fields to existing API schema
        
        Args:
            documents: List of dicts with 'id', 'embedding', and metadata
            batch_size: Vectors per batch (Pinecone max: 100)
            namespace: Pinecone namespace (default: "contracts")
        
        Returns:
            Number of documents upserted
        """
        try:
            vectors = []
            for doc in documents:
                payload = doc.get("payload", {})
                
                # Helper function to ensure no None values
                def safe_str(value, default=""):
                    """Convert None to empty string"""
                    return value if value is not None else default
                
                # Map new schema → existing schema for backward compatibility
                vectors.append({
                    "id": doc["id"],
                    "values": doc["embedding"],
                    "metadata": {
                        "notice_id": safe_str(payload.get("notice_id")),
                        "title": safe_str(payload.get("title")),
                        "agency": safe_str(payload.get("agency")),
                        "office": safe_str(payload.get("office")),
                        "description": safe_str(payload.get("description"))[:1000],
                        # NAICS: now supports both code and name
                        "naics_code": safe_str(payload.get("naics_code") or payload.get("naics")),
                        "naics_name": safe_str(payload.get("naics_name")),
                        # PSC
                        "psc_code": safe_str(payload.get("psc_code") or payload.get("psc")),
                        "psc_name": safe_str(payload.get("psc_name")),
                        "set_aside": safe_str(payload.get("set_aside")),
                        "state": safe_str(payload.get("state")),
                        "city": safe_str(payload.get("city")),
                        "posted_date": safe_str(payload.get("posted_date")),
                        "response_deadline": safe_str(payload.get("response_deadline")),
                        "url": safe_str(payload.get("url") or payload.get("source_url")),
                        "contact_email": safe_str(payload.get("contact_email")),
                        "contact_name": safe_str(payload.get("contact_name")),
                        "contract_value": 0.0,
                    }
                })
            
            # Batch upsert with namespace
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                self.index.upsert(vectors=batch, namespace=namespace)
            
            logger.info(f"✅ Upserted {len(vectors)} vectors to Pinecone (namespace: {namespace})")
            return len(vectors)
            
        except Exception as e:
            logger.error(f"❌ Pinecone upsert failed: {e}")
            raise
    
    def search_contracts(
        self,
        query_vector: List[float],
        limit: int = 10,
        min_score: float = 0.0,
        filter_dict: Optional[Dict[str, Any]] = None,
        namespace: str = "contracts"
    ) -> List[Dict[str, Any]]:
        """
        Search contracts by semantic similarity
        Returns data in existing API schema format
        
        Args:
            query_vector: 768-dim embedding
            limit: Max results
            min_score: Minimum similarity score (0-1)
            filter_dict: Pinecone metadata filters (optional)
            namespace: Pinecone namespace (default: "contracts")
        
        Returns:
            List of matching contracts with scores
        """
        try:
            results = self.index.query(
                vector=query_vector,
                top_k=limit,
                include_metadata=True,
                filter=filter_dict,
                namespace=namespace
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
                        "office": match.metadata.get("office"),
                        "description": match.metadata.get("description"),
                        # NAICS: return both code and name
                        "naics_code": match.metadata.get("naics_code"),
                        "naics_name": match.metadata.get("naics_name"),
                        # PSC
                        "psc_code": match.metadata.get("psc_code"),
                        "psc_name": match.metadata.get("psc_name"),
                        "set_aside": match.metadata.get("set_aside"),
                        "state": match.metadata.get("state"),
                        "city": match.metadata.get("city"),
                        "posted_date": match.metadata.get("posted_date"),
                        "response_deadline": match.metadata.get("response_deadline"),
                        "url": match.metadata.get("url"),
                        "contact_email": match.metadata.get("contact_email"),
                        "contact_name": match.metadata.get("contact_name"),
                        "contract_value": match.metadata.get("contract_value"),
                    })
            
            logger.info(f"🔍 Found {len(contracts)} contracts (score >= {min_score}, namespace: {namespace})")
            return contracts
            
        except Exception as e:
            logger.error(f"❌ Pinecone search failed: {e}")
            raise
    
    def get_document_count(self, namespace: Optional[str] = None) -> int:
        """
        Get total number of vectors in index
        
        Args:
            namespace: Specific namespace to count (None = all namespaces)
        """
        try:
            stats = self.index.describe_index_stats()
            
            if namespace:
                count = stats.namespaces.get(namespace, {}).get('vector_count', 0)
                logger.info(f"📊 Namespace '{namespace}' has {count} vectors")
                return count
            else:
                total = stats.total_vector_count
                logger.info(f"📊 Pinecone index has {total} total vectors")
                return total
        except Exception as e:
            logger.error(f"❌ Failed to get count: {e}")
            return 0
    
    def delete_all(self, namespace: str = "contracts"):
        """
        Delete all vectors from a namespace (use with caution!)
        
        Args:
            namespace: Namespace to clear (default: "contracts")
        """
        try:
            self.index.delete(delete_all=True, namespace=namespace)
            logger.warning(f"⚠️ Deleted all vectors from namespace: {namespace}")
        except Exception as e:
            logger.error(f"❌ Delete failed: {e}")
            raise
    
    def get_by_id(self, notice_id: str, namespace: str = "contracts") -> Optional[Dict[str, Any]]:
        """
        Fetch a contract by notice_id
        
        Args:
            notice_id: Contract notice ID
            namespace: Pinecone namespace (default: "contracts")
        """
        try:
            result = self.index.fetch(ids=[notice_id], namespace=namespace)
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