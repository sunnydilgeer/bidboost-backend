# app/routers/company.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import logging
from app.database import get_db
from app.models.schemas import (
    CompanyProfileCreate, CompanyProfileResponse, CompanyProfileFull, CompanyProfileResponse,
    CompanyCapabilityCreate, CompanyCapabilityResponse,
    PastWinCreate, PastWinResponse,
    SearchPreferenceCreate, SearchPreferenceResponse
)
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference, CompanySize
from app.core.auth import get_current_user
from app.services.capability_store import CapabilityStoreService
from app.services.llm import LLMService
from app.core.config import settings
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/company", tags=["Company Profile"])

# ========== COMPANY PROFILE ENDPOINTS ==========

@router.post("/profile", response_model=CompanyProfileResponse, status_code=status.HTTP_201_CREATED)
def create_company_profile(
    profile_data: CompanyProfileCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Create a company profile for the current user's firm.
    Only one profile per firm is allowed.
    """
    firm_id = current_user.firm_id
    
    # Check if profile already exists
    existing = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company profile already exists for this firm. Use PUT to update."
        )
    
    # Create profile
    company = CompanyProfile(
        firm_id=firm_id,
        company_name=profile_data.company_name,
        registration_number=profile_data.registration_number,
        size=CompanySize[profile_data.size.upper()],
        founded_year=profile_data.founded_year,
        description=profile_data.description
    )
    
    db.add(company)
    db.commit()
    db.refresh(company)
    
    return company

@router.get("/profile", response_model=CompanyProfileFull)
def get_company_profile(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get complete company profile with all related data:
    - Basic profile info
    - All capabilities
    - All past wins
    - Search preferences
    """
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found. Create one first using POST /api/company/profile"
        )
    
    return CompanyProfileFull(
        profile=company,
        capabilities=company.capabilities,
        past_wins=company.past_wins,
        search_preference=company.search_preference
    )

@router.put("/profile", response_model=CompanyProfileResponse)
def update_company_profile(
    profile_data: CompanyProfileCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update existing company profile"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found. Create one first using POST /api/company/profile"
        )
    
    # Update fields
    company.company_name = profile_data.company_name
    company.registration_number = profile_data.registration_number
    company.size = CompanySize[profile_data.size.upper()]
    company.founded_year = profile_data.founded_year
    company.description = profile_data.description
    
    db.commit()
    db.refresh(company)
    
    return company

@router.delete("/profile", status_code=status.HTTP_204_NO_CONTENT)
def delete_company_profile(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Delete company profile and all related data (capabilities, past wins, preferences).
    This is a cascading delete.
    """
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    db.delete(company)
    db.commit()
    
    return None

# ========== CAPABILITIES ENDPOINTS ==========

@router.post("/capabilities", response_model=CompanyCapabilityResponse, status_code=status.HTTP_201_CREATED)
async def add_capability(
    capability_data: CompanyCapabilityCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Add a capability to company profile.
    Capabilities describe what services/solutions the company can deliver.
    """
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found. Create one first."
        )
    
    # Create capability in database
    capability = CompanyCapability(
        company_id=company.id,
        capability_text=capability_data.capability_text,
        category=capability_data.category
    )
    
    db.add(capability)
    db.commit()
    db.refresh(capability)
    
    # Embed capability in Qdrant for semantic matching
    try:
        qdrant_client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        capability_store = CapabilityStoreService(qdrant_client)
        llm_service = LLMService()
        
        qdrant_id = await capability_store.add_capability(capability, llm_service)
        
        # Update capability with qdrant_id
        capability.qdrant_id = qdrant_id
        db.commit()
        db.refresh(capability)
        
        logger.info(f"✅ Capability {capability.id} embedded in Qdrant with ID {qdrant_id}")
    
    except Exception as e:
        logger.error(f"Failed to embed capability in Qdrant: {str(e)}")
        # Don't fail the request - capability is still in database
    
    return capability

@router.get("/capabilities", response_model=List[CompanyCapabilityResponse])
def list_capabilities(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List all capabilities for current company"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    return company.capabilities

@router.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capability(
    capability_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a specific capability"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    capability = db.query(CompanyCapability).filter(
        CompanyCapability.id == capability_id,
        CompanyCapability.company_id == company.id
    ).first()
    
    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capability not found or doesn't belong to your company"
        )
    
    db.delete(capability)
    db.commit()
    
    return None

# ========== PAST WINS ENDPOINTS ==========

@router.post("/past-wins", response_model=PastWinResponse, status_code=status.HTTP_201_CREATED)
def add_past_win(
    win_data: PastWinCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Add a past contract win.
    Used to demonstrate track record and help match similar future opportunities.
    """
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found. Create one first."
        )
    
    past_win = PastWin(
        company_id=company.id,
        contract_title=win_data.contract_title,
        buyer_name=win_data.buyer_name,
        contract_value=win_data.contract_value,
        award_date=win_data.award_date,
        contract_duration_months=win_data.contract_duration_months,
        description=win_data.description
    )
    
    db.add(past_win)
    db.commit()
    db.refresh(past_win)
    
    return past_win

@router.get("/past-wins", response_model=List[PastWinResponse])
def list_past_wins(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List all past contract wins, sorted by award date (most recent first)"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    return sorted(company.past_wins, key=lambda x: x.award_date, reverse=True)

@router.delete("/past-wins/{win_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_past_win(
    win_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a specific past win"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    win = db.query(PastWin).filter(
        PastWin.id == win_id,
        PastWin.company_id == company.id
    ).first()
    
    if not win:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Past win not found or doesn't belong to your company"
        )
    
    db.delete(win)
    db.commit()
    
    return None

# ========== SEARCH PREFERENCES ENDPOINTS ==========

@router.put("/search-preferences", response_model=SearchPreferenceResponse)
def update_search_preferences(
    prefs_data: SearchPreferenceCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Create or update search preferences.
    These preferences filter and prioritize contract opportunities.
    """
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found. Create one first."
        )
    
    # Check if preferences exist
    prefs = db.query(SearchPreference).filter(SearchPreference.company_id == company.id).first()
    
    if prefs:
        # Update existing
        prefs.min_contract_value = prefs_data.min_contract_value
        prefs.max_contract_value = prefs_data.max_contract_value
        prefs.preferred_regions = prefs_data.preferred_regions
        prefs.excluded_categories = prefs_data.excluded_categories
        prefs.keywords = prefs_data.keywords
    else:
        # Create new
        prefs = SearchPreference(
            company_id=company.id,
            min_contract_value=prefs_data.min_contract_value,
            max_contract_value=prefs_data.max_contract_value,
            preferred_regions=prefs_data.preferred_regions,
            excluded_categories=prefs_data.excluded_categories,
            keywords=prefs_data.keywords
        )
        db.add(prefs)
    
    db.commit()
    db.refresh(prefs)
    
    return prefs

@router.get("/search-preferences", response_model=SearchPreferenceResponse)
def get_search_preferences(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get current search preferences"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    if not company.search_preference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search preferences not set. Use PUT /api/company/search-preferences to create them."
        )
    
    return company.search_preference

@router.delete("/search-preferences", status_code=status.HTTP_204_NO_CONTENT)
def delete_search_preferences(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete search preferences (reset to defaults)"""
    firm_id = current_user.firm_id
    
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found"
        )
    
    if company.search_preference:
        db.delete(company.search_preference)
        db.commit()
    
    return None