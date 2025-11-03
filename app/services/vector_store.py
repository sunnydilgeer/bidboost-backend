from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, FilterSelector
from typing import List, Dict, Any, Optional
import uuid
import logging
from app.core.config import settings
from app.models.schemas import ContractOpportunity

logger = logging.getLogger(__name__)

class VectorStoreService:
    def __init__(self):
        # Use QDRANT_URL if available (for cloud), otherwise use host/port (for local)
        if settings.QDRANT_URL and "cloud.qdrant.io" in settings.QDRANT_URL:
            self.client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY
            )
        else:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT
            )
        self.collection_name = settings.QDRANT_COLLECTION_NAME
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        collection_names = [col.name for col in collections]
        
        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=768,  # nomic-embed-text dimension
                    distance=Distance.COSINE
                )
            )
            logger.info(f"Created collection: {self.collection_name}")

    try:
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="document_type",
            field_schema="keyword"
        )
        logger.info(f"Created index on document_type field")
    except Exception as e:
        # Index might already exist
        logger.debug(f"Index creation skipped: {e}")
    
    async def add_documents(self, documents: List[Dict], llm_service):
        """
        Add legal documents with embeddings to Qdrant.
        
        Args:
            documents: List of dicts with 'id', 'content', and 'metadata' keys
            llm_service: Service for generating embeddings
            
        Returns:
            Number of points added
        """
        points = []
        
        for doc in documents:
            # Generate embedding
            embedding = await llm_service.generate_embeddings(doc["content"])
            
            # Extract key fields from metadata for top-level access
            metadata = doc.get("metadata", {})
            
            point = PointStruct(
                id=doc["id"],
                vector=embedding,
                payload={
                    "content": doc["content"],
                    "metadata": metadata,
                    "document_type": "legal_document",
                    "page": metadata.get("page", 1),
                    "document_id": metadata.get("document_id", ""),
                    "firm_id": metadata.get("firm_id", "")
                }
            )
            points.append(point)
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        
        logger.info(f"Added {len(points)} legal document chunks to vector store")
        return len(points)
    
    async def add_contracts(self, contracts: List[ContractOpportunity], llm_service) -> None:
        """Add contract opportunities to vector store for semantic search."""
        try:
            points = []
            
            for contract in contracts:
                # Safe value formatting
                if contract.value is not None:
                    value_text = f"£{contract.value:,.2f}"
                else:
                    value_text = "Not specified"
                
                # Safe date formatting
                if contract.closing_date:
                    closing_date_text = contract.closing_date.strftime('%Y-%m-%d')
                else:
                    closing_date_text = "Not specified"
                
                # Create searchable text combining key fields
                contract_text = f"""Title: {contract.title}
Description: {contract.description or 'No description'}
Buyer: {contract.buyer_name}
Value: {value_text}
CPV Codes: {', '.join(contract.cpv_codes) if contract.cpv_codes else 'None'}
Region: {contract.region or 'Not specified'}
Closing Date: {closing_date_text}""".strip()
                
                # Clean and limit text for embedding to prevent Ollama crashes
                clean_text = contract_text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
                embedding_text = clean_text[:1500]  # Limit to 1500 characters
                
                # Generate embedding with cleaned, truncated text
                embedding = await llm_service.generate_embeddings(embedding_text)
                
                point = PointStruct(
                    id=contract.notice_id,  # ✅ Use notice_id as ID to prevent duplicates
                    vector=embedding,
                    payload={
                        "content": contract_text,  # Store full text for display
                        "document_type": "contract_opportunity",
                        "metadata": {
                            "notice_id": contract.notice_id,
                            "title": contract.title,
                            "buyer_name": contract.buyer_name,
                            "published_date": contract.published_date.isoformat() if contract.published_date else None,
                            "closing_date": contract.closing_date.isoformat() if contract.closing_date else None,
                            "value": contract.value,
                            "cpv_codes": contract.cpv_codes,
                            "region": contract.region
                        },
                        # Top-level fields for easy filtering
                        "notice_id": contract.notice_id,
                        "buyer_name": contract.buyer_name,
                        "value": contract.value,
                        "region": contract.region
                    }
                )
                points.append(point)
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            
            logger.info(f"Added {len(contracts)} contracts to vector store")
            
        except Exception as e:
            logger.error(f"Failed to add contracts to vector store: {str(e)}")
            raise
    
    async def search(
        self, 
        query_text: str, 
        llm_service, 
        limit: int = 5,
        filter_conditions: Optional[Dict[str, Any]] = None,
        document_type: Optional[str] = None
    ):
        """
        Search for similar documents/contracts with optional filtering.
        
        Args:
            query_text: The search query
            llm_service: Service for generating query embeddings
            limit: Maximum number of results to return
            filter_conditions: Dict of filters (e.g., {"firm_id": "123"})
            document_type: Filter by document type ("legal_document" or "contract_opportunity")
            
        Returns:
            List of search results with content, metadata, and score
        """
        # Generate query embedding
        query_embedding = await llm_service.generate_embeddings(query_text)
        
        # Build Qdrant filter
        must_conditions = []
        
        # Add document type filter if specified
        if document_type:
            must_conditions.append(
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value=document_type)
                )
            )
        
        # Add custom filter conditions
        if filter_conditions:
            for key, value in filter_conditions.items():
                # Check if key needs metadata prefix
                if key in ["page", "document_id", "firm_id", "notice_id", "buyer_name", "value", "region"]:
                    # Top-level fields
                    field_key = key
                else:
                    # Nested metadata fields
                    field_key = f"metadata.{key}"
                
                must_conditions.append(
                    FieldCondition(
                        key=field_key,
                        match=MatchValue(value=value)
                    )
                )
        
        query_filter = Filter(must=must_conditions) if must_conditions else None
        
        # Search in Qdrant with optional filter
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter
        )
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_result = {
                "id": result.id,  # ADD THIS LINE - Qdrant point ID
                "content": result.payload["content"],
                "metadata": result.payload.get("metadata", {}),
                "score": result.score,
                "document_type": result.payload.get("document_type", "unknown")
            }
            
            # Add type-specific fields
            if result.payload.get("document_type") == "legal_document":
                formatted_result.update({
                    "page": result.payload.get("page", 1),
                    "document_id": result.payload.get("document_id", "")
                })
            elif result.payload.get("document_type") == "contract_opportunity":
                formatted_result.update({
                    "notice_id": result.payload.get("notice_id", ""),
                    "buyer_name": result.payload.get("buyer_name", ""),
                    "value": result.payload.get("value"),
                    "region": result.payload.get("region")
                })
            
            formatted_results.append(formatted_result)
        
        return formatted_results
    
    async def search_contracts(
        self,
        query_text: str,
        llm_service,
        limit: int = 10,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        region: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search specifically for contract opportunities with contract-specific filters.
        
        Args:
            query_text: Search query
            llm_service: Service for embeddings
            limit: Max results
            min_value: Minimum contract value
            max_value: Maximum contract value
            region: Filter by region
        """
        # Start with base contract filter
        filter_conditions = {}
        
        if region:
            filter_conditions["region"] = region
        
        # Search for contracts only
        results = await self.search(
            query_text=query_text,
            llm_service=llm_service,
            limit=limit,
            filter_conditions=filter_conditions,
            document_type="contract_opportunity"
        )
        
        # Post-filter by value range (since Qdrant range queries need special handling)
        if min_value is not None or max_value is not None:
            filtered_results = []
            for result in results:
                contract_value = result.get("value")
                if contract_value is None:
                    continue
                
                if min_value is not None and contract_value < min_value:
                    continue
                if max_value is not None and contract_value > max_value:
                    continue
                    
                filtered_results.append(result)
            
            results = filtered_results
        
        return results
    
    def delete_by_document_id(self, document_id: str, firm_id: str):
        """Delete all chunks belonging to a specific legal document."""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id)
                        ),
                        FieldCondition(
                            key="firm_id",
                            match=MatchValue(value=firm_id)
                        )
                    ]
                )
            )
        )
        
        logger.info(f"Deleted all chunks for document: {document_id}")
    
    def delete_contracts_older_than(self, days: int = 30):
        """Delete contract opportunities older than specified days."""
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # This would require a more complex query with date comparison
        # For now, log the intent - you may want to implement this based on your needs
        logger.info(f"Contract cleanup requested for entries older than {days} days")
    
    def get_document_count(self, firm_id: Optional[str] = None, document_type: Optional[str] = None) -> int:
        """
        Get count of documents/contracts with optional filtering.
        
        Args:
            firm_id: Filter by firm ID (for legal documents)
            document_type: Filter by document type
        """
        must_conditions = []
        
        if firm_id:
            must_conditions.append(
                FieldCondition(
                    key="firm_id",
                    match=MatchValue(value=firm_id)
                )
            )
        
        if document_type:
            must_conditions.append(
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value=document_type)
                )
            )
        
        if must_conditions:
            result = self.client.count(
                collection_name=self.collection_name,
                count_filter=Filter(must=must_conditions)
            )
            return result.count
        else:
            collection_info = self.client.get_collection(self.collection_name)
            return collection_info.points_count