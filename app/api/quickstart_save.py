"""
Sticky onboarding - Save quick-start results when user creates account
Stores capabilities extracted from website scraping to Qdrant
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional
import logging
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import CompanyProfile, CompanyCapability
from app.services.llm import LLMService
from app.services.capability_store import CapabilityStoreService
from app.core.config import settings
from app.auth.utils import get_current_user
from app.api.routes import trigger_cache_refresh  # ✅ NEW: Import cache refresh


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quickstart", tags=["Quick Start"])

# ========== REQUEST/RESPONSE MODELS ==========

class SaveQuickStartRequest(BaseModel):
    """Save quick-start capabilities after signup"""
    company_url: str = Field(..., description="Website URL that was scraped")
    capabilities_text: str = Field(..., description="Extracted capabilities text")
    company_name: Optional[str] = Field(None, description="Extracted company name")
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_url": "https://kainos.com",
                "capabilities_text": "Digital transformation experts and Workday partners...",
                "company_name": "Kainos"
            }
        }

class SaveQuickStartResponse(BaseModel):
    """Response after saving quick-start data"""
    success: bool
    capabilities_created: int
    message: str
    profile_updated: bool

# ========== ENDPOINT ==========

@router.post("/save", response_model=SaveQuickStartResponse)
async def save_quickstart_results(
    request: SaveQuickStartRequest,
    background_tasks: BackgroundTasks,  # ✅ NEW: Add background tasks
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Save quick-start results to user's profile after signup.
    
    This creates the "sticky" onboarding experience:
    1. User tries quick-start (anonymous)
    2. Sees great results
    3. Signs up to save capabilities
    4. We auto-populate their profile with extracted data
    
    Flow:
    - Extract structured capabilities from scraped text using LLM
    - Store each capability in Qdrant with embeddings
    - Link capabilities to user's company profile
    - Update company name if provided
    """
    try:
        firm_id = current_user.get("firm_id")
        if not firm_id:
            raise HTTPException(
                status_code=400,
                detail="User must have a company profile"
            )
        
        logger.info(f"💾 Saving quick-start results for firm {firm_id}")
        
        # Get user's company profile
        profile = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Company profile not found"
            )
        
        # Update company name if provided and not already set
        profile_updated = False
        if request.company_name and not profile.company_name:
            profile.company_name = request.company_name
            profile_updated = True
            logger.info(f"Updated company name to: {request.company_name}")
        
        # STEP 1: Extract structured capabilities using LLM
        llm_service = LLMService()
        
        # Parse capabilities into structured list
        extracted_capabilities = await llm_service.extract_capabilities_from_text(
            request.capabilities_text
        )
        
        if not extracted_capabilities:
            # Fallback: Create one general capability from the text
            extracted_capabilities = [{
                "text": request.capabilities_text[:500],  # Truncate to 500 chars
                "category": "General"
            }]
        
        logger.info(f"Extracted {len(extracted_capabilities)} capabilities from text")
        
        # STEP 2: Store each capability to database + Qdrant
        capability_store = CapabilityStoreService()
        capabilities_created = 0
        
        for cap_data in extracted_capabilities[:5]:  # Limit to top 5 to avoid spam
            try:
                # Generate embedding
                embedding = await llm_service.generate_embeddings(cap_data["text"])
                
                # Store in Qdrant
                qdrant_id = await capability_store.store_capability(
                    firm_id=firm_id,
                    capability_text=cap_data["text"],
                    embedding=embedding,
                    category=cap_data.get("category")
                )
                
                # Create database record
                new_capability = CompanyCapability(
                    firm_id=firm_id,
                    capability_text=cap_data["text"],
                    category=cap_data.get("category"),
                    qdrant_id=qdrant_id
                )
                
                db.add(new_capability)
                capabilities_created += 1
                
                logger.info(f"Created capability: {cap_data['text'][:50]}...")
                
            except Exception as e:
                logger.error(f"Failed to create capability: {e}")
                continue
        
        # Commit all changes
        db.commit()
        
        logger.info(f"✅ Saved {capabilities_created} capabilities for firm {firm_id}")
        trigger_cache_refresh(db, firm_id, background_tasks)
        logger.info(f"🔄 Triggered cache refresh for firm {firm_id}")
        
        return SaveQuickStartResponse(
            success=True,
            capabilities_created=capabilities_created,
            message=f"Successfully saved {capabilities_created} capabilities to your profile",
            profile_updated=profile_updated
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Save quick-start failed: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save quick-start results: {str(e)}"
        )