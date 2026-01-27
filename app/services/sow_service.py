import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.contract_sow import ContractSOW, SOWExtractionQueue
from app.services.sow_extractor import SOWExtractor
from app.services.description_classifier import DescriptionClassifier

logger = logging.getLogger(__name__)

class SOWService:
    """
    High-level service for managing SOW extraction.
    Orchestrates classifier, extractor, and database operations.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.extractor = SOWExtractor()
    
    async def close(self):
        """Close resources"""
        await self.extractor.close()
    
    def get_sow(self, notice_id: str) -> Optional[ContractSOW]:
        """
        Get extracted SOW for a contract.
        
        Args:
            notice_id: Contract notice ID
            
        Returns:
            ContractSOW object or None if not found
        """
        return self.db.query(ContractSOW).filter(
            ContractSOW.notice_id == notice_id
        ).first()
    
    def should_extract_sow(self, description: str) -> bool:
        """
        Determine if a contract needs SOW extraction.
        
        Args:
            description: Contract description text
            
        Returns:
            True if description is garbage and needs SOW extraction
        """
        return DescriptionClassifier.is_description_garbage(description)
    
    async def extract_and_save_sow(
        self,
        notice_id: str,
        attachments: List[dict],
        description: str
    ) -> Optional[ContractSOW]:
        """
        Extract SOW from attachments and save to database.
        
        Args:
            notice_id: Contract notice ID
            attachments: List of attachment dicts with 'url' and 'title'
            description: Original contract description
            
        Returns:
            ContractSOW object or None if extraction failed
        """
        try:
            # Check if SOW already exists
            existing = self.get_sow(notice_id)
            if existing:
                logger.info(f"SOW already exists for {notice_id}")
                return existing
            
            # Find best attachment to extract from
            best_attachment = self._select_best_attachment(attachments)
            if not best_attachment:
                logger.warning(f"No suitable attachments for {notice_id}")
                return None
            
            # Extract SOW
            extraction_result = await self.extractor.extract_sow_from_url(
                pdf_url=best_attachment["url"],
                filename=best_attachment["title"]
            )
            
            if not extraction_result:
                logger.warning(f"SOW extraction failed for {notice_id}")
                return None
            
            # Save to database
            sow = ContractSOW(
                notice_id=notice_id,
                sow_text=extraction_result["sow_text"],
                confidence=extraction_result["confidence"],
                source_filename=extraction_result["source_filename"],
                word_count=extraction_result["word_count"],
                has_deliverables=extraction_result["has_deliverables"],
                has_tasks=extraction_result["has_tasks"],
                extraction_method=extraction_result["extraction_method"],
                pdf_url=extraction_result["pdf_url"],
                pdf_size_bytes=extraction_result["pdf_size_bytes"],
            )
            
            self.db.add(sow)
            self.db.commit()
            self.db.refresh(sow)
            
            logger.info(f"✅ Saved SOW for {notice_id} (confidence: {sow.confidence}, {sow.word_count} words)")
            return sow
            
        except Exception as e:
            logger.error(f"Failed to extract and save SOW for {notice_id}: {str(e)}")
            self.db.rollback()
            return None
    
    def _select_best_attachment(self, attachments: List[dict]) -> Optional[dict]:
        """
        Select the best attachment for SOW extraction.
        
        Priority:
        1. SOW/PWS files
        2. Full solicitation packages
        3. Any PDF
        
        Args:
            attachments: List of attachment dicts
            
        Returns:
            Best attachment dict or None
        """
        if not attachments:
            return None
        
        sow_files = []
        solicitation_files = []
        other_pdfs = []
        
        for attachment in attachments:
            title = attachment.get("title", "").lower()
            doc_type = self.extractor.classify_document(title)
            
            if doc_type == "SOW_PRIMARY":
                sow_files.append(attachment)
            elif doc_type == "SOLICITATION_FULL":
                solicitation_files.append(attachment)
            elif doc_type not in ["AMENDMENT", "ADMIN"]:
                other_pdfs.append(attachment)
        
        # Return in priority order
        if sow_files:
            logger.info(f"Selected SOW file: {sow_files[0]['title']}")
            return sow_files[0]
        elif solicitation_files:
            logger.info(f"Selected solicitation: {solicitation_files[0]['title']}")
            return solicitation_files[0]
        elif other_pdfs:
            logger.info(f"Selected PDF: {other_pdfs[0]['title']}")
            return other_pdfs[0]
        
        return None
    
    def add_to_queue(
        self,
        notice_id: str,
        priority: str = "MEDIUM",
        reason: str = "Garbage description detected"
    ) -> SOWExtractionQueue:
        """
        Add contract to SOW extraction queue.
        
        Args:
            notice_id: Contract notice ID
            priority: HIGH | MEDIUM | LOW
            reason: Why extraction is needed
            
        Returns:
            SOWExtractionQueue object
        """
        # Check if already in queue
        existing = self.db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.notice_id == notice_id,
            SOWExtractionQueue.status.in_(["PENDING", "PROCESSING"])
        ).first()
        
        if existing:
            logger.info(f"Contract {notice_id} already in queue")
            return existing
        
        # Add to queue
        queue_item = SOWExtractionQueue(
            notice_id=notice_id,
            priority=priority,
            reason=reason
        )
        
        self.db.add(queue_item)
        self.db.commit()
        self.db.refresh(queue_item)
        
        logger.info(f"Added {notice_id} to extraction queue (priority: {priority})")
        return queue_item
    
    def get_queue_stats(self) -> dict:
        """Get statistics about the extraction queue"""
        total = self.db.query(SOWExtractionQueue).count()
        pending = self.db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "PENDING"
        ).count()
        processing = self.db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "PROCESSING"
        ).count()
        completed = self.db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "COMPLETED"
        ).count()
        failed = self.db.query(SOWExtractionQueue).filter(
            SOWExtractionQueue.status == "FAILED"
        ).count()
        
        return {
            "total_queued": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed
        }