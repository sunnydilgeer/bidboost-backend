import pdfplumber
from docx import Document
from typing import Tuple
import asyncio
from app.services.llm import LLMService
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.core.config import settings
import hashlib
from datetime import datetime, timedelta
import uuid
import logging

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        """Initialize with retry logic for Qdrant connection"""
        import time
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Use QDRANT_URL if available (for cloud), otherwise use host/port (for local)
                if settings.QDRANT_URL and "cloud.qdrant.io" in settings.QDRANT_URL:
                    self.qdrant = QdrantClient(
                        url=settings.QDRANT_URL,
                        api_key=settings.QDRANT_API_KEY
                    )
                else:
                    # Railway internal connection
                    self.qdrant = QdrantClient(url=settings.QDRANT_URL)
                
                self.llm_service = LLMService()
                self._ensure_collection_exists()
                
                logger.info(f"✅ DocumentProcessor connected to Qdrant on attempt {attempt + 1}")
                break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Qdrant connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to connect to Qdrant after {max_retries} attempts")
                    raise
    
    def _ensure_collection_exists(self):
        """Create user_documents collection if it doesn't exist"""
        try:
            self.qdrant.get_collection("user_documents")
        except:
            self.qdrant.create_collection(
                collection_name="user_documents",
                vectors_config=VectorParams(size=768, distance=Distance.COSINE)
            )
    
    def extract_text(self, file_path: str, file_type: str) -> str:
        """Extract text from PDF, DOCX, or TXT"""
        if file_type == "pdf":
            with pdfplumber.open(file_path) as pdf:
                text = "\n\n".join([
                    page.extract_text() or "" 
                    for page in pdf.pages
                ])
        elif file_type in ["docx", "doc"]:
            doc = Document(file_path)
            text = "\n\n".join([para.text for para in doc.paragraphs if para.text.strip()])
        elif file_type == "txt":
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        return text.strip()
    
    def clean_text(self, text: str) -> str:
        """Remove excessive whitespace and clean text"""
        text = "\n".join([line.strip() for line in text.split("\n") if line.strip()])
        text = " ".join(text.split())
        return text
    
    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
        """Split text into overlapping chunks for better semantic coverage"""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i:i + chunk_size])
            if len(chunk.strip()) > 100:
                chunks.append(chunk)
        
        return chunks
    
    async def process_and_store(
        self, 
        file_path: str, 
        file_type: str, 
        user_id: str,
        filename: str
    ) -> dict:
        """
        Extract → Clean → Chunk → Embed → Store
        Returns: Processing stats
        """
        start_time = datetime.now()
        
        # 1. Extract and clean text
        raw_text = self.extract_text(file_path, file_type)
        clean_text = self.clean_text(raw_text)
        
        # 2. Create chunks
        chunks = self.chunk_text(clean_text)
        
        # 3. Generate embeddings for all chunks (parallel)
        embeddings = await asyncio.gather(*[
            self.llm_service.generate_embeddings(chunk) for chunk in chunks
        ])
        
        # 4. Create document ID from content hash
        doc_hash = hashlib.md5(clean_text.encode()).hexdigest()[:12]
        doc_id = f"user_{user_id}_doc_{doc_hash}"
        
        # 5. Store in Qdrant
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload={
                    "user_id": user_id,
                    "document_id": doc_id,
                    "chunk_text": chunk,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "filename": filename,
                    "uploaded_at": datetime.utcnow().isoformat(),
                    "file_type": file_type
                }
            )
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]
        
        self.qdrant.upsert(
            collection_name="user_documents",
            points=points
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "document_id": doc_id,
            "chunks_stored": len(chunks),
            "total_words": len(clean_text.split()),
            "processing_time_seconds": round(processing_time, 2)
        }
    
    async def find_matching_contracts(
        self, 
        user_id: str,
        limit: int = 10
    ) -> list[dict]:
        """
        Find SAM.gov contracts matching user's uploaded documents
        Uses average of all document chunk embeddings
        """
        # Get all document chunks for this user
        search_result = self.qdrant.scroll(
            collection_name="user_documents",
            limit=100,
            with_vectors=True,
            scroll_filter={
                "must": [
                    {
                        "key": "user_id",
                        "match": {"value": user_id}
                    }
                ]
            }
        )
        
        if not search_result[0]:
            logger.warning(f"No documents found for user {user_id}")
            return []
        
        # Average all chunk embeddings to create user "signature"
        chunk_vectors = [point.vector for point in search_result[0]]
        avg_vector = [
            sum(vectors) / len(vectors) 
            for vectors in zip(*chunk_vectors)
        ]
        
        logger.info(f"Searching SAM contracts with averaged embedding from {len(chunk_vectors)} chunks")
        
        # Search SAM contracts using averaged embedding
        # Check if using Pinecone or Qdrant for SAM contracts
        use_pinecone = settings.USE_PINECONE
        
        if use_pinecone:
            # Use Pinecone for SAM contracts
            from pinecone import Pinecone
            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            index = pc.Index(settings.PINECONE_INDEX_NAME)
            
            matches = index.query(
                vector=avg_vector,
                top_k=limit,
                include_metadata=True
            )
            
            # Convert Pinecone response to standard format
            results = []
            for match in matches.matches:
                metadata = match.metadata or {}
                results.append({
                    "contract_id": match.id,
                    "notice_id": metadata.get("notice_id", ""),
                    "title": metadata.get("title", ""),
                    "buyer": metadata.get("buyer_name", ""),
                    "buyer_name": metadata.get("buyer_name", ""),
                    "value": metadata.get("value"),
                    "deadline": metadata.get("closing_date"),
                    "closing_date": metadata.get("closing_date"),
                    "published_date": metadata.get("published_date"),
                    "score": round(match.score, 3),
                    "url": metadata.get("source_url", ""),
                    "source_url": metadata.get("source_url", ""),
                    "description": metadata.get("description", "")[:300] + "..." if metadata.get("description") else "",
                    "region": metadata.get("region", ""),
                    "set_aside": metadata.get("set_aside", ""),
                    "psc_code": metadata.get("psc_code", [])
                })
        else:
            # Use Qdrant for SAM contracts (fallback)
            matches = self.qdrant.search(
                collection_name="sam_contracts",  # SAM contracts collection
                query_vector=avg_vector,
                limit=limit
            )
            
            # Convert Qdrant response to standard format
            results = []
            for hit in matches:
                payload = hit.payload or {}
                results.append({
                    "contract_id": hit.id,
                    "notice_id": payload.get("notice_id", ""),
                    "title": payload.get("title", ""),
                    "buyer": payload.get("buyer_name", ""),
                    "buyer_name": payload.get("buyer_name", ""),
                    "value": payload.get("value"),
                    "deadline": payload.get("closing_date"),
                    "closing_date": payload.get("closing_date"),
                    "published_date": payload.get("published_date"),
                    "score": round(hit.score, 3),
                    "url": payload.get("source_url", ""),
                    "source_url": payload.get("source_url", ""),
                    "description": payload.get("description", "")[:300] + "..." if payload.get("description") else "",
                    "region": payload.get("region", ""),
                    "set_aside": payload.get("set_aside", ""),
                    "psc_code": payload.get("psc_code", [])
                })
        
        logger.info(f"Found {len(results)} SAM contract matches for user {user_id}")
        
        return results


# Lazy initialization - only create when actually needed
_processor_instance = None

def get_processor():
    """Get or create DocumentProcessor singleton with lazy initialization"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = DocumentProcessor()
    return _processor_instance