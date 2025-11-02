from app.services.legal_chunker import LegalDocumentChunker, LegalChunk
from typing import Optional, Dict, Any, List
import re
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile
import logging
import io

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """
    Handles file processing for PDF, DOCX, and TXT files.
    Extracts text and metadata with user-provided metadata taking priority.
    """
    
    SUPPORTED_TYPES = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt"
    }
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    def __init__(self):
        """Initialize the document processor with legal chunker."""
        self.legal_chunker = LegalDocumentChunker()
    
    async def process_file(
        self, 
        file: UploadFile, 
        user_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Process uploaded file and return structured data for ingestion.
        
        Returns:
            Dict with 'content' and 'metadata' keys, or None if processing fails
        """
        try:
            # Validate file type
            if file.content_type not in self.SUPPORTED_TYPES:
                logger.error(f"Unsupported file type: {file.content_type}")
                return None
            
            # Read file content
            file_content = await file.read()
            
            # Check file size
            if len(file_content) > self.MAX_FILE_SIZE:
                logger.error(f"File too large: {len(file_content)} bytes")
                return None
            
            # Extract text based on file type
            file_type = self.SUPPORTED_TYPES[file.content_type]
            
            if file_type == "pdf":
                text = self._extract_pdf(file_content)
            elif file_type == "docx":
                text = self._extract_docx(file_content)
            else:  # txt
                text = file_content.decode('utf-8', errors='ignore')
            
            if not text or len(text.strip()) < 10:
                logger.error("Extracted text too short or empty")
                return None
            
            # Extract file metadata
            file_metadata = self._extract_file_metadata(file.filename, file_type)
            
            # Merge metadata (user-provided wins)
            final_metadata = {**file_metadata, **(user_metadata or {})}
            
            return {
                "content": text,
                "metadata": final_metadata
            }
            
        except Exception as e:
            logger.error(f"File processing failed for {file.filename}: {str(e)}")
            return None
    
    def _extract_pdf(self, file_content: bytes) -> str:
        """Extract text from PDF with page markers for accurate page tracking."""
        try:
            import pdfplumber
            
            pdf_file = io.BytesIO(file_content)
            text_parts = []
            
            with pdfplumber.open(pdf_file) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Extracting {total_pages} pages from PDF")
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()
                    
                    if page_text and page_text.strip():
                        # Add page marker at the START of each page's text
                        # This is critical for legal_chunker to track pages correctly
                        text_parts.append(f"[Page {page_num}]\n{page_text.strip()}")
                    else:
                        logger.warning(f"Page {page_num} extracted no text")
                        # Still add marker for empty pages to maintain page count
                        text_parts.append(f"[Page {page_num}]\n")
            
            final_text = "\n\n".join(text_parts)
            logger.info(f"PDF extraction complete: {len(final_text)} characters, {total_pages} pages")
            return final_text
        
        except ImportError:
            logger.error("pdfplumber not installed. Install with: pip install pdfplumber")
            return ""
        except Exception as e:
            logger.error(f"PDF extraction failed: {str(e)}")
            return ""
    
    def _extract_docx(self, file_content: bytes) -> str:
        """Extract text from DOCX, preserving paragraph structure."""
        try:
            from docx import Document as DocxDocument
            
            docx_file = io.BytesIO(file_content)
            doc = DocxDocument(docx_file)
            
            paragraphs = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
            
            # DOCX doesn't have explicit page breaks in the API
            # Estimate pages based on content length (rough approximation)
            full_text = "\n\n".join(paragraphs)
            
            # Add a single page marker since DOCX page tracking is unreliable
            return f"[Page 1]\n{full_text}"
        
        except ImportError:
            logger.error("python-docx not installed. Install with: pip install python-docx")
            return ""
        except Exception as e:
            logger.error(f"DOCX extraction failed: {str(e)}")
            return ""
    
    def _extract_file_metadata(self, filename: str, file_type: str) -> Dict[str, Any]:
        """Extract metadata from filename and file properties."""
        metadata = {
            "filename": filename,
            "file_type": file_type,
            "upload_date": datetime.utcnow().isoformat()
        }
        
        # Try to extract case_id from filename (e.g., EMP-2024-001_contract.pdf)
        case_pattern = r'([A-Z]{2,4}-\d{4}-\d{3})'
        match = re.search(case_pattern, filename)
        if match:
            metadata["case_id"] = match.group(1)
        
        # Extract potential document type from filename
        filename_lower = filename.lower()
        doc_types = {
            "contract": "contract",
            "agreement": "agreement",
            "policy": "policy",
            "employment": "employment_contract",
            "nda": "non_disclosure_agreement",
            "lease": "commercial_lease",
            "terms": "terms_and_conditions"
        }
        
        for keyword, doc_type in doc_types.items():
            if keyword in filename_lower:
                metadata["document_type"] = doc_type
                break
        
        return metadata
    
    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Chunk text using legal-aware chunking with page number extraction.
        
        Args:
            text: Document text to chunk (should contain [Page X] markers)
            metadata: Base metadata to attach to each chunk
            
        Returns:
            List of chunks with text and enriched metadata including page numbers
        """
        legal_chunks: List[LegalChunk] = self.legal_chunker.chunk_document(text, metadata)
        
        if not legal_chunks:
            logger.warning("No chunks created - document may be empty or invalid")
            return []
        
        # Convert to dict format for Qdrant
        chunks = []
        for idx, legal_chunk in enumerate(legal_chunks):
            # The page number is already set by legal_chunker._get_page_for_position
            # DO NOT re-extract from chunk text - trust the chunker's page tracking
            chunk_metadata = legal_chunk.metadata.copy()
            
            chunk_metadata.update({
                'chunk_index': idx,
                'total_chunks': len(legal_chunks),
                'chunk_type': legal_chunk.chunk_type,
                'chunk_size': len(legal_chunk.text)
                # 'page' is already in legal_chunk.metadata from the chunker
            })
            
            chunks.append({
                'text': legal_chunk.text,
                'metadata': chunk_metadata
            })
        
        # Log sample of page assignments for verification
        sample_pages = [c['metadata'].get('page', 'MISSING') for c in chunks[:5]]
        logger.info(
            f"Created {len(chunks)} chunks using '{legal_chunks[0].chunk_type}' strategy. "
            f"Sample page numbers: {sample_pages}"
        )
        
        return chunks