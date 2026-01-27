import httpx
import re
import logging
from typing import Optional, Tuple
from io import BytesIO
import PyPDF2
from datetime import datetime

logger = logging.getLogger(__name__)

class SOWExtractor:
    """
    Extracts Statement of Work text from SAM.gov contract attachments.
    Solves the "garbage description" problem where 30% of contracts have useless descriptions.
    """
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    def classify_document(self, filename: str) -> str:
        """
        Classify document type by filename.
        
        Priority order:
        1. SOW_PRIMARY - dedicated SOW/PWS files
        2. SOLICITATION_FULL - full RFP packages (extract Section C/L/M)
        3. AMENDMENT - skip (delta text only)
        4. ADMIN - skip (boilerplate)
        
        Returns:
            Document type: SOW_PRIMARY | SOLICITATION_FULL | AMENDMENT | ADMIN | UNKNOWN
        """
        filename_lower = filename.lower()
        
        # Priority 1: Dedicated SOW files
        sow_keywords = [
            "sow", "pws", "soo", "statement of work",
            "performance work statement", "scope of work",
            "statement_of_work", "performance_work"
        ]
        if any(kw in filename_lower for kw in sow_keywords):
            return "SOW_PRIMARY"
        
        # Priority 2: Full solicitation packages
        solicitation_keywords = ["solicitation", "rfp", "rfq", "combined synopsis"]
        if any(kw in filename_lower for kw in solicitation_keywords):
            # Skip if it's also an amendment
            if any(kw in filename_lower for kw in ["amendment", "mod", "modification"]):
                return "AMENDMENT"
            return "SOLICITATION_FULL"
        
        # Priority 3: Amendments (SKIP)
        if any(kw in filename_lower for kw in ["amendment", "mod", "q&a", "modification"]):
            return "AMENDMENT"
        
        # Priority 4: Admin (SKIP)
        admin_keywords = ["synopsis", "sf1449", "sf-1449", "cover", "face sheet"]
        if any(kw in filename_lower for kw in admin_keywords):
            return "ADMIN"
        
        return "UNKNOWN"
    
    async def download_pdf(self, url: str) -> Optional[bytes]:
        """
        Download PDF from URL.
        
        Args:
            url: Direct URL to PDF file
            
        Returns:
            PDF bytes or None if download failed
        """
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            
            # Verify it's actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and not url.lower().endswith('.pdf'):
                logger.warning(f"URL doesn't appear to be a PDF: {url} (Content-Type: {content_type})")
                return None
            
            pdf_bytes = response.content
            logger.info(f"Downloaded PDF: {len(pdf_bytes)} bytes from {url[:50]}...")
            return pdf_bytes
            
        except Exception as e:
            logger.error(f"Failed to download PDF from {url}: {str(e)}")
            return None
    
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> Optional[str]:
        """
        Extract text from PDF using PyPDF2.
        
        Args:
            pdf_bytes: PDF file as bytes
            
        Returns:
            Extracted text or None if extraction failed
        """
        try:
            pdf_file = BytesIO(pdf_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            # Extract text from all pages
            text_parts = []
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num}: {str(e)}")
                    continue
            
            full_text = "\n\n".join(text_parts)
            
            if not full_text.strip():
                logger.warning("PDF text extraction returned empty string")
                return None
            
            logger.info(f"Extracted {len(full_text)} characters from PDF ({len(pdf_reader.pages)} pages)")
            return full_text
            
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {str(e)}")
            return None
    
    def extract_sow_sections(self, full_text: str, doc_type: str) -> str:
        """
        Extract SOW-relevant sections from full document text.
        
        Args:
            full_text: Complete text from PDF
            doc_type: Document classification (SOW_PRIMARY | SOLICITATION_FULL)
            
        Returns:
            Extracted SOW text
        """
        # For dedicated SOW files, return full text (up to 5000 words)
        if doc_type == "SOW_PRIMARY":
            words = full_text.split()
            return " ".join(words[:5000])
        
        # For full solicitations, try to extract Section C/L/M
        if doc_type == "SOLICITATION_FULL":
            return self._extract_from_full_solicitation(full_text)
        
        # Fallback: return first 3000 words
        words = full_text.split()
        return " ".join(words[:3000])
    
    def _extract_from_full_solicitation(self, full_text: str) -> str:
        """
        Extract SOW sections from full RFP/RFQ document.
        
        Common patterns:
        - Section C - Description/Specifications/Work Statement
        - Section L - Instructions to Offerors
        - Section M - Evaluation Criteria
        
        Returns:
            Extracted section text
        """
        # Strategy 1: Look for Section C (most common location for SOW)
        section_c_patterns = [
            r"(?i)section\s+c[\s\-:]+.*?(?=section\s+[d-z]|\Z)",
            r"(?i)part\s+(?:iii|3)[\s\-:]+.*?(?=part\s+(?:iv|4)|\Z)",
        ]
        
        for pattern in section_c_patterns:
            match = re.search(pattern, full_text, re.DOTALL)
            if match and len(match.group(0)) > 500:
                extracted = match.group(0)
                logger.info(f"Extracted Section C: {len(extracted)} characters")
                # Limit to 5000 words
                words = extracted.split()
                return " ".join(words[:5000])
        
        # Strategy 2: Look for SOW/PWS headers
        sow_patterns = [
            r"(?i)(statement of work|scope of work|performance work statement).*?(?=\n\n\n|section|appendix|\Z)",
        ]
        
        for pattern in sow_patterns:
            match = re.search(pattern, full_text, re.DOTALL)
            if match and len(match.group(0)) > 500:
                extracted = match.group(0)
                logger.info(f"Extracted SOW section: {len(extracted)} characters")
                words = extracted.split()
                return " ".join(words[:5000])
        
        # Fallback: return first 3000 words
        logger.warning("Could not identify specific SOW section, using first 3000 words")
        words = full_text.split()
        return " ".join(words[:3000])
    
    def calculate_confidence(self, sow_text: str, doc_type: str, source_filename: str) -> str:
        """
        Calculate confidence level for extracted SOW.
        
        Args:
            sow_text: Extracted SOW text
            doc_type: Document classification
            source_filename: Original filename
            
        Returns:
            Confidence level: HIGH | MEDIUM | LOW
        """
        word_count = len(sow_text.split())
        
        # HIGH confidence: dedicated SOW file with good length
        if doc_type == "SOW_PRIMARY" and word_count >= 200:
            return "HIGH"
        
        # MEDIUM confidence: extracted from full solicitation
        if doc_type == "SOLICITATION_FULL" and word_count >= 500:
            return "MEDIUM"
        
        # LOW confidence: short extraction or unknown source
        return "LOW"
    
    def detect_quality_indicators(self, sow_text: str) -> Tuple[bool, bool]:
        """
        Detect quality indicators in SOW text.
        
        Returns:
            (has_deliverables, has_tasks)
        """
        text_lower = sow_text.lower()
        
        # Check for deliverables
        deliverable_keywords = [
            "deliverable", "milestone", "submission", "report",
            "documentation", "final product"
        ]
        has_deliverables = any(kw in text_lower for kw in deliverable_keywords)
        
        # Check for tasks
        task_keywords = [
            "shall", "will provide", "must", "required to",
            "task", "perform", "conduct", "develop"
        ]
        has_tasks = any(kw in text_lower for kw in task_keywords)
        
        return has_deliverables, has_tasks
    
    async def extract_sow_from_url(
        self,
        pdf_url: str,
        filename: str
    ) -> Optional[dict]:
        """
        Main method: Extract SOW from PDF URL.
        
        Args:
            pdf_url: Direct URL to PDF attachment
            filename: Original filename
            
        Returns:
            Dict with extraction results or None if failed
        """
        try:
            # Step 1: Classify document
            doc_type = self.classify_document(filename)
            
            # Skip non-SOW documents
            if doc_type in ["AMENDMENT", "ADMIN"]:
                logger.info(f"Skipping {doc_type}: {filename}")
                return None
            
            # Step 2: Download PDF
            pdf_bytes = await self.download_pdf(pdf_url)
            if not pdf_bytes:
                return None
            
            # Step 3: Extract text
            full_text = self.extract_text_from_pdf(pdf_bytes)
            if not full_text:
                return None
            
            # Step 4: Extract SOW sections
            sow_text = self.extract_sow_sections(full_text, doc_type)
            
            # Step 5: Calculate confidence and quality
            confidence = self.calculate_confidence(sow_text, doc_type, filename)
            has_deliverables, has_tasks = self.detect_quality_indicators(sow_text)
            
            return {
                "sow_text": sow_text,
                "confidence": confidence,
                "source_filename": filename,
                "word_count": len(sow_text.split()),
                "has_deliverables": has_deliverables,
                "has_tasks": has_tasks,
                "extraction_method": "pdf_text",
                "pdf_url": pdf_url,
                "pdf_size_bytes": len(pdf_bytes),
            }
            
        except Exception as e:
            logger.error(f"SOW extraction failed for {filename}: {str(e)}")
            return None