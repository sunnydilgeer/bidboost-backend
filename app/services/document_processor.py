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

class DocumentProcessor:
    def __init__(self):
        # Use QDRANT_URL if available (for cloud), otherwise use host/port (for local)
        if settings.QDRANT_URL and "cloud.qdrant.io" in settings.QDRANT_URL:
            self.qdrant = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY
            )
        else:
            self.qdrant = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT
            )
        self.llm_service = LLMService()
        self._ensure_collection_exists()
    
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
        Find contracts matching user's uploaded documents
        Uses average of all document chunk embeddings
        Sorts by: 1) New contracts first, 2) Then similarity score
        """
        # Get all document chunks for this user
        search_result = self.qdrant.scroll(
            collection_name="user_documents",
            scroll_filter={
                "must": [
                    {"key": "user_id", "match": {"value": user_id}}
                ]
            },
            limit=100,
            with_vectors=True
        )
        
        if not search_result[0]:
            return []
        
        # Average all chunk embeddings to create user "signature"
        chunk_vectors = [point.vector for point in search_result[0]]
        avg_vector = [
            sum(vectors) / len(vectors) 
            for vectors in zip(*chunk_vectors)
        ]
        
        # Search contracts using averaged embedding (get more to sort)
        matches = self.qdrant.search(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query_vector=avg_vector,
            limit=limit * 2
        )
        
        # Convert to dict and check if new
        results = []
        for hit in matches:
            published_date = hit.payload.get("metadata", {}).get("published_date")
            is_new = False
            
            if published_date:
                try:
                    pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                    is_new = (datetime.now(pub_date.tzinfo) - pub_date).days <= 7
                except:
                    pass
            
            results.append({
                "contract_id": hit.id,
                "notice_id": hit.payload.get("notice_id", ""),
                "title": hit.payload.get("metadata", {}).get("title", ""),
                "buyer": hit.payload.get("buyer_name", ""),
                "value": hit.payload.get("value"),
                "deadline": hit.payload.get("metadata", {}).get("closing_date"),
                "published_date": published_date,
                "score": round(hit.score, 3),
                "is_new": is_new,
                "url": f"https://www.contractsfinder.service.gov.uk/notice/{hit.payload.get('notice_id', '')}" if hit.payload.get("notice_id") else "",
                "description": hit.payload.get("content", "")[:200] + "..." if hit.payload.get("content") else "",
                "cpv_codes": hit.payload.get("metadata", {}).get("cpv_codes", []),
                "region": hit.payload.get("region", "")
            })
        
        # Sort: new contracts first, then by similarity
        results.sort(key=lambda x: (not x["is_new"], -x["score"]))
        
        return results[:limit]

# Singleton instance
processor = DocumentProcessor()