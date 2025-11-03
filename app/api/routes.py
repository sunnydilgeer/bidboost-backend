import asyncio
from app.api.debug_routes import debug_router  
from app.services.contract_fetcher import ContractFetcherService
from app.services.match_scoring import ContractMatchScorer
from app.services.capability_store import CapabilityStoreService 
from app.models.contract import Contract
from app.models import User as DBUser
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference
from app.models.schemas import (
    ContractSyncResponse, 
    ContractSearchRequest, 
    ContractSearchResponse, 
    ContractSearchResult,
    CapabilityCreate,
    CapabilityUpdate,
    PastWinCreate,
    PastWinUpdate,
    PreferencesUpdate,
    CompanyProfileResponse,
    EmailPreferencesUpdate,
    EmailPreferencesResponse
)
from app.models.company import SavedContract, ContractStatus
from app.models.schemas import (
    SaveContractRequest, 
    UpdateContractStatusRequest,
    SavedContractResponse,
    SavedContractsListResponse
)
from qdrant_client.models import Filter, FieldCondition, MatchValue
from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, BackgroundTasks
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.services.document_processor import processor
import os 
import shutil 
from app.core.auth import User, get_current_active_user
from app.database import get_db
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Contracts"])
debug_router = APIRouter(prefix="/api/debug", tags=["Debug"])

vector_store = VectorStoreService()
llm_service = LLMService()

# ========== HELPER FUNCTION ==========

def get_company_profile(db: Session, firm_id: str) -> CompanyProfile:
    """Get company profile by firm_id, create if doesn't exist"""
    profile = db.query(CompanyProfile).filter(
        CompanyProfile.firm_id == firm_id
    ).first()
    
    if not profile:
        # Create default profile
        profile = CompanyProfile(
            firm_id=firm_id,
            company_name=firm_id,
            description="",
            size="SMALL"
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    
    return profile



# ========== DEBUGGING ==========

@debug_router.get("/match/{contract_id}")
async def debug_match_scoring(
    contract_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Debug endpoint showing detailed match scoring breakdown
    
    Returns:
    - All component scores (capability, past win, preference)
    - Individual capability similarity scores
    - Which capabilities matched and their text
    - Embedding vector norms to verify they're being retrieved
    - Identified issues and recommendations
    """
    
    try:
        # 1. Get contract from Qdrant
        scroll_result = vector_store.client.scroll(
            collection_name="legal_documents",
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="notice_id",
                        match=MatchValue(value=contract_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=True  # Get vectors for debugging
        )
        
        if not scroll_result[0]:
            raise HTTPException(status_code=404, detail="Contract not found in vector store")
        
        contract_point = scroll_result[0][0]
        metadata = contract_point.payload.get("metadata", {})
        
        # 2. Create Contract object
        temp_contract = Contract(
            notice_id=contract_id,
            title=metadata.get("title", ""),
            buyer_name=contract_point.payload.get("buyer_name", ""),
            description=metadata.get("description", ""),
            contract_value=contract_point.payload.get("value"),
            region=contract_point.payload.get("region"),
            qdrant_id=contract_point.id
        )
        
        # 3. Get company profile with capabilities
        profile = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == current_user.firm_id
        ).first()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Company profile not found")
        
        capabilities = db.query(CompanyCapability).filter(
            CompanyCapability.company_id == profile.id
        ).all()
        
        # 4. Run match scoring
        scorer = ContractMatchScorer(db, vector_store.client)
        match_result = scorer.score_contract(temp_contract, current_user.firm_id)
        
        # 5. Get detailed capability breakdown
        capability_details = []
        if contract_point.vector:
            contract_vector = contract_point.vector
            contract_vector_norm = float(sum(x**2 for x in contract_vector) ** 0.5)
            
            for cap in capabilities:
                if cap.qdrant_id:
                    # Retrieve capability with vector
                    cap_points = vector_store.client.retrieve(
                        collection_name="capabilities",
                        ids=[cap.qdrant_id],
                        with_vectors=True
                    )
                    
                    if cap_points:
                        cap_vector = cap_points[0].vector
                        cap_vector_norm = float(sum(x**2 for x in cap_vector) ** 0.5)
                        
                        # Calculate similarity
                        import numpy as np
                        similarity = float(np.dot(contract_vector, cap_vector) / 
                                         (np.linalg.norm(contract_vector) * np.linalg.norm(cap_vector)))
                        
                        capability_details.append({
                            "id": cap.id,
                            "text": cap.capability_text,
                            "qdrant_id": cap.qdrant_id,
                            "similarity_score": round(similarity, 4),
                            "vector_norm": round(cap_vector_norm, 4),
                            "vector_dimensions": len(cap_vector)
                        })
        
        # 6. Analyze issues
        issues = []
        recommendations = []
        
        if not match_result:
            issues.append("❌ Contract failed preference filters (excluded or out of value range)")
        
        if not capabilities:
            issues.append("❌ No capabilities found - add capabilities in Profile Manager")
            recommendations.append("Add 3-5 specific capabilities describing your services")
        
        if match_result and match_result["capability_score"] < 0.3:
            issues.append("⚠️ Low capability score - capabilities may not match contract well")
            recommendations.append("Review contract description and ensure capabilities are relevant")
        
        if not contract_point.vector:
            issues.append("❌ Contract has no embedding vector in Qdrant")
            recommendations.append("Re-sync contracts with /api/contracts/sync")
        
        for cap_detail in capability_details:
            if cap_detail["similarity_score"] == 0.0:
                issues.append(f"⚠️ Capability '{cap_detail['text'][:50]}' has 0% similarity")
        
        # 7. Build response
        return {
            "contract": {
                "notice_id": contract_id,
                "title": temp_contract.title,
                "description": temp_contract.description[:200] + "..." if temp_contract.description else None,
                "value": temp_contract.contract_value,
                "region": temp_contract.region,
                "qdrant_id": temp_contract.qdrant_id,
                "has_embedding": bool(contract_point.vector),
                "embedding_dimensions": len(contract_point.vector) if contract_point.vector else 0,
                "embedding_norm": round(contract_vector_norm, 4) if contract_point.vector else 0
            },
            "profile": {
                "firm_id": current_user.firm_id,
                "company_name": profile.company_name,
                "capabilities_count": len(capabilities),
                "past_wins_count": len(profile.past_wins) if profile.past_wins else 0,
                "has_preferences": profile.search_preference is not None
            },
            "match_scores": match_result if match_result else {
                "total_score": 0.0,
                "reason": "Contract filtered out by preferences"
            },
            "capability_breakdown": capability_details,
            "issues": issues,
            "recommendations": recommendations,
            "status": "✅ Scoring successful" if match_result else "❌ Contract filtered out"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Debug endpoint failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Debug failed: {str(e)}"
        )


@debug_router.get("/qdrant/status")
async def check_qdrant_status():
    """Check Qdrant collections and data quality"""
    try:
        collections = vector_store.client.get_collections().collections
        
        collection_info = []
        for collection in collections:
            info = vector_store.client.get_collection(collection.name)
            collection_info.append({
                "name": collection.name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status
            })
        
        return {
            "qdrant_connected": True,
            "collections": collection_info,
            "status": "✅ Qdrant operational"
        }
        
    except Exception as e:
        logger.error(f"Qdrant status check failed: {str(e)}")
        return {
            "qdrant_connected": False,
            "error": str(e),
            "status": "❌ Qdrant connection failed"
        }


# ========== USER INFO ROUTE ==========

@router.get("/auth/me", tags=["Authentication"])
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get current user info"""
    return current_user

# ========== EMAIL PREFERENCE ROUTES ==========

@router.get("/user/email-preferences", response_model=EmailPreferencesResponse, tags=["User Settings"])
async def get_email_preferences(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's email notification settings.
    
    Returns:
    - email_notifications_enabled: Whether emails are enabled
    - notification_frequency: "daily", "weekly", or "never"
    - last_email_sent_at: Timestamp of last email sent
    """
    # Get the database user object (not the Pydantic User)
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return EmailPreferencesResponse(
        email_notifications_enabled=db_user.email_notifications_enabled,
        notification_frequency=db_user.notification_frequency,
        last_email_sent_at=db_user.last_email_sent_at
    )


@router.put("/user/email-preferences", response_model=EmailPreferencesResponse, tags=["User Settings"])
async def update_email_preferences(
    preferences: EmailPreferencesUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update current user's email notification settings.
    
    Body parameters:
    - email_notifications_enabled (optional): Enable/disable all emails
    - notification_frequency (optional): "daily", "weekly", or "never"
    
    Returns updated preferences.
    """
    # Get the database user object
    db_user = db.query(DBUser).filter(DBUser.id == current_user.user_id).first()
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update only fields that were provided
    if preferences.email_notifications_enabled is not None:
        db_user.email_notifications_enabled = preferences.email_notifications_enabled
    
    if preferences.notification_frequency is not None:
        db_user.notification_frequency = preferences.notification_frequency
    
    try:
        db.commit()
        db.refresh(db_user)
        
        logger.info(f"Updated email preferences for {current_user.email}")
        
        return EmailPreferencesResponse(
            email_notifications_enabled=db_user.email_notifications_enabled,
            notification_frequency=db_user.notification_frequency,
            last_email_sent_at=db_user.last_email_sent_at
        )
    
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update email preferences: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update email preferences: {str(e)}"
        )


# OPTIONAL: Test endpoint to send a test email
@router.post("/user/test-email", tags=["User Settings"])
async def send_test_email(
    current_user: User = Depends(get_current_active_user)
):
    """
    Send a test email to the current user.
    Useful for verifying email setup.
    """
    from app.services.email_service import email_service
    
    # Send a test new contracts email
    test_contracts = [
        {
            "notice_id": "test-123",
            "title": "Test Contract - IT Services",
            "buyer_name": "Test Government Department",
            "value": "£50,000",
            "deadline": "2025-11-15",
            "match_score": 87,
            "match_reason": "This is a test email to verify your notification setup"
        }
    ]
    
    success = email_service.send_new_contracts_email(
        to_email=current_user.email,
        user_name=current_user.full_name,
        contracts=test_contracts,
        total_new_contracts=1
    )
    
    if success:
        logger.info(f"Test email sent to {current_user.email}")
        return {
            "success": True,
            "message": "Test email sent successfully",
            "email": current_user.email
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send test email"
        )




# ========== COMPANY PROFILE ROUTES ==========

@router.get("/company/profile", response_model=CompanyProfileResponse)
async def get_company_profile_endpoint(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get company profile with capabilities, past wins, and preferences"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        return profile
        
    except Exception as e:
        logger.error(f"Failed to get company profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve company profile: {str(e)}"
        )

@router.put("/company/profile")
async def update_company_profile_endpoint(
    company_name: str = None,
    description: str = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update company profile basic info"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        if company_name is not None:
            profile.company_name = company_name
        if description is not None:
            profile.description = description
        
        db.commit()
        db.refresh(profile)
        
        logger.info(f"Updated profile for firm {current_user.firm_id}")
        return {"success": True, "message": "Profile updated successfully"}
        
    except Exception as e:
        logger.error(f"Failed to update company profile: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update profile: {str(e)}"
        )

# ========== CAPABILITY ROUTES ==========

@router.get("/capabilities")
async def get_capabilities(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> List[Dict]:
    """Get all capabilities for the company"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        capabilities = db.query(CompanyCapability).filter(
            CompanyCapability.company_id == profile.id
        ).all()
        
        return [
            {
                "id": cap.id,
                "capability_text": cap.capability_text,
                "category": cap.category,
                "qdrant_id": cap.qdrant_id,
                "created_at": cap.created_at
            }
            for cap in capabilities
        ]
        
    except Exception as e:
        logger.error(f"Failed to get capabilities: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve capabilities: {str(e)}"
        )

@router.post("/capabilities")
async def add_capability(
    capability: CapabilityCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add a new capability and sync to Qdrant vector store"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        # Create capability in database first
        new_cap = CompanyCapability(
            company_id=profile.id,
            capability_text=capability.capability_text,
            category=capability.category
        )
        
        db.add(new_cap)
        db.flush()  # Get ID without committing
        db.refresh(new_cap)  # Load relationships including company
        
        # Sync to Qdrant
        cap_store = CapabilityStoreService(vector_store.client)
        qdrant_id = await cap_store.add_capability(new_cap, llm_service)
        
        # Update with qdrant_id
        new_cap.qdrant_id = qdrant_id
        db.commit()
        db.refresh(new_cap)
        
        logger.info(f"Added capability for firm {current_user.firm_id}: {capability.capability_text[:50]}")
        
        return {
            "success": True,
            "id": new_cap.id,
            "qdrant_id": new_cap.qdrant_id,
            "message": "Capability added and synced to vector store"
        }
        
    except Exception as e:
        logger.error(f"Failed to add capability: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add capability: {str(e)}"
        )

@router.put("/capabilities/{capability_id}")
async def update_capability(
    capability_id: int,
    capability: CapabilityUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update an existing capability and re-sync to Qdrant"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        # Verify capability belongs to this company
        existing_cap = db.query(CompanyCapability).filter(
            CompanyCapability.id == capability_id,
            CompanyCapability.company_id == profile.id
        ).first()
        
        if not existing_cap:
            raise HTTPException(
                status_code=404, 
                detail="Capability not found or does not belong to your company"
            )
        
        # Update text and category
        existing_cap.capability_text = capability.capability_text
        if capability.category is not None:
            existing_cap.category = capability.category
        
        db.flush()
        
        # Re-sync to Qdrant (delete old, add new)
        cap_store = CapabilityStoreService(vector_store.client)
        
        if existing_cap.qdrant_id:
            cap_store.delete_capability(existing_cap.qdrant_id)
        
        qdrant_id = await cap_store.add_capability(existing_cap, llm_service)
        existing_cap.qdrant_id = qdrant_id
        
        db.commit()
        
        logger.info(f"Updated capability {capability_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Capability updated and re-synced to vector store"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update capability: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update capability: {str(e)}"
        )

@router.delete("/capabilities/{capability_id}")
async def delete_capability(
    capability_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a capability and remove from Qdrant"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        # Verify capability belongs to this company
        existing_cap = db.query(CompanyCapability).filter(
            CompanyCapability.id == capability_id,
            CompanyCapability.company_id == profile.id
        ).first()
        
        if not existing_cap:
            raise HTTPException(
                status_code=404,
                detail="Capability not found or does not belong to your company"
            )
        
        # Delete from Qdrant first
        if existing_cap.qdrant_id:
            cap_store = CapabilityStoreService(vector_store.client)
            cap_store.delete_capability(existing_cap.qdrant_id)
        
        # Delete from database
        db.delete(existing_cap)
        db.commit()
        
        logger.info(f"Deleted capability {capability_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Capability deleted and removed from vector store"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete capability: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete capability: {str(e)}"
        )

# ========== PAST WINS ROUTES ==========

@router.get("/past-wins")
async def get_past_wins(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> List[Dict]:
    """Get all past contract wins for the company"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        wins = db.query(PastWin).filter(
            PastWin.company_id == profile.id
        ).order_by(PastWin.award_date.desc()).all()
        
        return [
            {
                "id": win.id,
                "contract_title": win.contract_title,
                "buyer_name": win.buyer_name,
                "contract_value": win.contract_value,
                "award_date": win.award_date,
                "description": win.description,
                "created_at": win.created_at
            }
            for win in wins
        ]
        
    except Exception as e:
        logger.error(f"Failed to get past wins: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve past wins: {str(e)}"
        )

@router.post("/past-wins")
async def add_past_win(
    win: PastWinCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add a new past contract win"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        new_win = PastWin(
            company_id=profile.id,
            contract_title=win.contract_title,
            buyer_name=win.buyer_name,
            contract_value=win.contract_value,
            award_date=win.award_date,
            description=win.description
        )
        
        db.add(new_win)
        db.commit()
        db.refresh(new_win)
        
        logger.info(f"Added past win for firm {current_user.firm_id}: {win.contract_title}")
        
        return {
            "success": True,
            "id": new_win.id,
            "message": "Past win added successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to add past win: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add past win: {str(e)}"
        )

@router.put("/past-wins/{win_id}")
async def update_past_win(
    win_id: int,
    win: PastWinUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update an existing past contract win"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        existing_win = db.query(PastWin).filter(
            PastWin.id == win_id,
            PastWin.company_id == profile.id
        ).first()
        
        if not existing_win:
            raise HTTPException(
                status_code=404,
                detail="Past win not found or does not belong to your company"
            )
        
        # Update fields
        if win.contract_title is not None:
            existing_win.contract_title = win.contract_title
        if win.buyer_name is not None:
            existing_win.buyer_name = win.buyer_name
        if win.contract_value is not None:
            existing_win.contract_value = win.contract_value
        if win.award_date is not None:
            existing_win.award_date = win.award_date
        if win.description is not None:
            existing_win.description = win.description
        
        db.commit()
        
        logger.info(f"Updated past win {win_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Past win updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update past win: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update past win: {str(e)}"
        )

@router.delete("/past-wins/{win_id}")
async def delete_past_win(
    win_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a past contract win"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        win = db.query(PastWin).filter(
            PastWin.id == win_id,
            PastWin.company_id == profile.id
        ).first()
        
        if not win:
            raise HTTPException(
                status_code=404,
                detail="Past win not found or does not belong to your company"
            )
        
        db.delete(win)
        db.commit()
        
        logger.info(f"Deleted past win {win_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Past win deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete past win: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete past win: {str(e)}"
        )

# ========== SEARCH PREFERENCES ROUTES ==========

@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get search preferences for the company"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        prefs = db.query(SearchPreference).filter(
            SearchPreference.company_id == profile.id
        ).first()
        
        if not prefs:
            # Create default preferences
            prefs = SearchPreference(
                company_id=profile.id,
                min_contract_value=None,
                max_contract_value=None,
                preferred_regions=[],
                excluded_categories=[],
                keywords=[]
            )
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        
        return {
            "min_contract_value": prefs.min_contract_value,
            "max_contract_value": prefs.max_contract_value,
            "preferred_regions": prefs.preferred_regions,
            "excluded_categories": prefs.excluded_categories,
            "keywords": prefs.keywords
        }
        
    except Exception as e:
        logger.error(f"Failed to get preferences: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve preferences: {str(e)}"
        )

@router.put("/preferences")
async def update_preferences(
    prefs: PreferencesUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update search preferences"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        existing_prefs = db.query(SearchPreference).filter(
            SearchPreference.company_id == profile.id
        ).first()
        
        if not existing_prefs:
            # Create new preferences
            existing_prefs = SearchPreference(company_id=profile.id)
            db.add(existing_prefs)
        
        # Update fields (only if provided)
        if prefs.min_contract_value is not None:
            existing_prefs.min_contract_value = prefs.min_contract_value
        if prefs.max_contract_value is not None:
            existing_prefs.max_contract_value = prefs.max_contract_value
        if prefs.preferred_regions is not None:
            existing_prefs.preferred_regions = prefs.preferred_regions
        if prefs.excluded_categories is not None:
            existing_prefs.excluded_categories = prefs.excluded_categories
        if prefs.keywords is not None:
            existing_prefs.keywords = prefs.keywords
        
        db.commit()
        
        logger.info(f"Updated preferences for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Preferences updated successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to update preferences: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update preferences: {str(e)}"
        )

# ========== CONTRACT SYNC ROUTE ==========

@router.post("/contracts/sync")
async def sync_contracts(
    total_target: int = 5000,
    batch_size: int = 100,
    days_back: int = 90,
    current_user: User = Depends(get_current_active_user)
) -> ContractSyncResponse:
    """
    Sync contract opportunities from Contracts Finder API with pagination.
    Safely fetches large numbers of contracts in batches of 100.
    """
    
    contract_service = ContractFetcherService()
    total_synced = 0
    batch_count = 0
    
    try:
        logger.info(f"Starting batch sync: target={total_target}, batch_size={batch_size}, days_back={days_back}")
        
        for offset in range(0, total_target, batch_size):
            batch_count += 1
            
            # Fetch batch
            contracts = await contract_service.fetch_contracts(
                limit=batch_size,
                days_back=days_back,
                offset=offset
            )
            
            # Stop if no more contracts
            if not contracts:
                logger.info(f"No more contracts found at offset {offset}")
                break
            
            # Store in vector database
            await vector_store.add_contracts(contracts, llm_service)
            total_synced += len(contracts)
            
            logger.info(f"Batch {batch_count}: Synced {len(contracts)} contracts (total: {total_synced})")
            
            # Rate limiting - wait 2 seconds between batches to be respectful
            if offset + batch_size < total_target:
                await asyncio.sleep(10)
        
        logger.info(f"Sync complete: {total_synced} contracts synced in {batch_count} batches")
        
        return ContractSyncResponse(
            success=True,
            contracts_fetched=total_synced,
            contracts_processed=total_synced,
            message=f"Successfully synced {total_synced} contracts in {batch_count} batches"
        )
        
    except Exception as e:
        logger.error(f"Batch sync failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Contract sync failed after {total_synced} contracts: {str(e)}"
        )
    finally:
        await contract_service.close()

@router.get("/contracts/recommended", response_model=ContractSearchResponse)
async def get_recommended_contracts(
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> ContractSearchResponse:
    """
    Get personalized contract recommendations based on company profile.
    
    This endpoint automatically returns contracts matched to the user's:
    - Company capabilities
    - Past wins
    - Search preferences
    
    Use this for the default contracts page view (no search query needed).
    """
    try:
        logger.info(f"Fetching recommended contracts for {current_user.email}")
        
        # Get company profile to use capabilities as search basis
        company = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == current_user.firm_id
        ).first()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company profile not found"
            )
        
        # Get company capabilities to use as search query
        capabilities = db.query(CompanyCapability).filter(
            CompanyCapability.company_id == company.id
        ).all()
        
        if not capabilities:
            # No capabilities - return empty results with helpful message
            return ContractSearchResponse(
                query="",
                results=[],
                total_found=0,
                message="No capabilities set. Add capabilities to your profile to see personalized matches."
            )
        
        # Create a search query from capabilities
        # Use the first few capabilities as the search basis
        capability_texts = [cap.capability_text for cap in capabilities[:3]]
        combined_query = " ".join(capability_texts)
        
        logger.info(f"Using capabilities as search query: {combined_query[:100]}...")
        
        # Search contracts using combined capability query
        # Get more results for filtering
        search_limit = limit * 2
        
        results = await vector_store.search_contracts(
            query_text=combined_query,
            llm_service=llm_service,
            limit=search_limit,
            min_value=None,
            max_value=None,
            region=None
        )
        
        # Initialize match scorer for personalized ranking
        scorer = ContractMatchScorer(db, vector_store.client)
        
        # Convert to response format with personalized scoring
        search_results = []
        for result in results:
            metadata = result.get("metadata", {})
            
            # Create base contract result
            contract_result = ContractSearchResult(
                notice_id=result.get("notice_id", ""),
                title=metadata.get("title", ""),
                buyer_name=result.get("buyer_name", ""),
                description=metadata.get("description", metadata.get("title", "")),
                value=result.get("value"),
                region=result.get("region"),
                closing_date=metadata.get("closing_date"),
                score=result.get("score", 0.0)
            )
            
            # Create Contract object for scoring
            temp_contract = Contract(
                notice_id=result.get("notice_id", ""),
                title=metadata.get("title", ""),
                buyer_name=result.get("buyer_name", ""),
                description=metadata.get("description", ""),
                contract_value=result.get("value"),
                region=result.get("region"),
                qdrant_id=result.get("id")
            )
            
            # Calculate match scores
            match_scores = scorer.score_contract(temp_contract, current_user.firm_id)
            
            if match_scores:
                contract_result.match_scores = match_scores
                contract_result.total_match_score = match_scores["total_score"]
                contract_result.match_reasons = match_scores.get("match_reasons", [])
                search_results.append(contract_result)
        
        # Sort by match score
        search_results.sort(key=lambda x: x.total_match_score or 0, reverse=True)
        
        # Limit to requested amount
        search_results = search_results[:limit]
        
        logger.info(f"Returning {len(search_results)} recommended contracts for {current_user.firm_id}")
        
        return ContractSearchResponse(
            query="",
            results=search_results,
            total_found=len(search_results),
            message=f"Found {len(search_results)} contracts matched to your profile"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get recommended contracts: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get recommendations: {str(e)}"
        )



# ========== CONTRACT SEARCH ROUTE WITH PERSONALIZED MATCH SCORING ==========

@router.post("/contracts/search", response_model=ContractSearchResponse)
async def search_contracts(
    search_request: ContractSearchRequest,
    include_match_scores: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> ContractSearchResponse:
    """
    Search contract opportunities using semantic search with personalized match scoring.
    
    Query Parameters:
    - include_match_scores: Enable personalized scoring based on company profile (default: True)
    
    Returns contracts ranked by relevance, with optional personalized match scores
    based on company capabilities, past wins, and search preferences.
    """
    try:
        logger.info(f"Contract search by {current_user.email}: '{search_request.query}' (match_scoring={include_match_scores})")
        
        # Get more results if scoring enabled (some may be filtered out by preferences)
        search_limit = search_request.limit * 2 if include_match_scores else search_request.limit
        
        # Search contracts using vector store semantic search
        results = await vector_store.search_contracts(
            query_text=search_request.query,
            llm_service=llm_service,
            limit=search_limit,
            min_value=search_request.min_value,
            max_value=search_request.max_value,
            region=search_request.region
        )
        
        # Initialize match scorer if personalized scoring enabled
        scorer = ContractMatchScorer(db, vector_store.client) if include_match_scores else None
        
        # Convert to response format with optional personalized scoring
        search_results = []
        for result in results:
            metadata = result.get("metadata", {})
            
            # Create base contract result with semantic score
            contract_result = ContractSearchResult(
                notice_id=result.get("notice_id", ""),
                title=metadata.get("title", ""),
                buyer_name=result.get("buyer_name", ""),
                description=metadata.get("description", metadata.get("title", "")),
                value=result.get("value"),
                region=result.get("region"),
                closing_date=metadata.get("closing_date"),
                score=result.get("score", 0.0)
            )
            
            # Add personalized match scoring
            if scorer:
                # Create Contract object from Qdrant result for scoring
                temp_contract = Contract(
                    notice_id=result.get("notice_id", ""),
                    title=metadata.get("title", ""),
                    buyer_name=result.get("buyer_name", ""),
                    description=metadata.get("description", ""),
                    contract_value=result.get("value"),
                    region=result.get("region"),
                    qdrant_id=result.get("id")  # Qdrant point ID for embedding lookup
                )

                # DEBUG: Log to see if ID is being passed
                logger.info(f"DEBUG: Contract {temp_contract.notice_id} has qdrant_id: {temp_contract.qdrant_id}")
                
                # Calculate match scores against company profile
                match_scores = scorer.score_contract(temp_contract, current_user.firm_id)
                
                # Only include contracts that pass preference filters
                if match_scores:
                    contract_result.match_scores = match_scores
                    contract_result.total_match_score = match_scores["total_score"]
                    contract_result.match_reasons = match_scores.get("match_reasons", [])  # 🔧 BUG FIX
                    search_results.append(contract_result)
                else:
                    # Contract filtered out by hard filters (value range, excluded keywords)
                    logger.debug(f"Contract {temp_contract.notice_id} filtered out by preferences")
            else:
                # No personalized scoring - include all results
                search_results.append(contract_result)
        
        # Sort by match score if available, otherwise by semantic score
        if include_match_scores and search_results:
            search_results.sort(key=lambda x: x.total_match_score or 0, reverse=True)
            logger.info(f"Ranked {len(search_results)} contracts by personalized match score")
        
        # Limit to requested amount after filtering and sorting
        search_results = search_results[:search_request.limit]
        
        return ContractSearchResponse(
            query=search_request.query,
            results=search_results,
            total_found=len(search_results),
            message=f"Found {len(search_results)} matching contracts" + 
                   (f" (personalized for {current_user.firm_id})" if include_match_scores else "")
        )
        
    except Exception as e:
        logger.error(f"Contract search failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Contract search failed: {str(e)}"
        )

# ========== CONTRACT DETAILS ROUTE ==========

@router.get("/contracts/saved", response_model=SavedContractsListResponse)
async def get_saved_contracts(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all saved contracts for the current user, optionally filtered by status"""
    try:
        query = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email
        )
        
        # Apply status filter if provided
        if status_filter:
            try:
                status_enum = ContractStatus[status_filter.upper()]
                query = query.filter(SavedContract.status == status_enum)
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status_filter}. Valid options: interested, bidding, won, lost"
                )
        
        # Order by most recently saved first
        saved_contracts = query.order_by(SavedContract.saved_at.desc()).all()
        
        return SavedContractsListResponse(
            total=len(saved_contracts),
            contracts=[SavedContractResponse.from_orm(sc) for sc in saved_contracts]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get saved contracts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve saved contracts: {str(e)}"
        )



@router.get("/contracts/{notice_id}")
async def get_contract_details(
    notice_id: str,
    current_user: User = Depends(get_current_active_user)
) -> Dict:
    """Get full details for a specific contract opportunity"""
    try:
        # Query Qdrant for this specific contract
        scroll_result = vector_store.client.scroll(
            collection_name=vector_store.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="notice_id",
                        match=MatchValue(value=notice_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False
        )
        
        if not scroll_result[0]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contract not found"
            )
        
        point = scroll_result[0][0]
        metadata = point.payload.get("metadata", {})
        
        return {
            "notice_id": notice_id,
            "title": metadata.get("title"),
            "buyer_name": point.payload.get("buyer_name"),
            "description": metadata.get("description"),
            "value": point.payload.get("value"),
            "region": point.payload.get("region"),
            "closing_date": metadata.get("closing_date"),
            "published_date": metadata.get("published_date"),
            "cpv_codes": metadata.get("cpv_codes", []),
            "contact_details": metadata.get("contact_details", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get contract details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve contract details"
        )

@router.post("/companies/{firm_id}/onboarding/complete")
async def complete_onboarding(
    firm_id: str,
    db: Session = Depends(get_db)
):
    """Mark onboarding as complete and return success"""
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Update onboarding status
    company.onboarding_completed = 2  # 2 = completed
    company.onboarding_step = 4       # All steps done
    company.onboarding_completed_at = datetime.utcnow()
    db.commit()
    
    logger.info(f"✅ Onboarding completed for {company.company_name} (firm_id: {firm_id})")
    
    return {
        "success": True,
        "message": "Onboarding completed successfully",
        "company_name": company.company_name,
        "next_step": "/contracts"
    }

# Optional: Check onboarding status endpoint
@router.get("/companies/{firm_id}/onboarding/status")
async def get_onboarding_status(
    firm_id: str,
    db: Session = Depends(get_db)
):
    """Get current onboarding status for a company"""
    company = db.query(CompanyProfile).filter(CompanyProfile.firm_id == firm_id).first()
    
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {
        "firm_id": firm_id,
        "company_name": company.company_name,
        "onboarding_completed": company.onboarding_completed,
        "onboarding_step": company.onboarding_step,
        "needs_onboarding": company.onboarding_completed < 2
    }

@router.post("/upload")  # ✅ Simplified path
async def upload_company_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),  # ✅ JWT auth
    db: Session = Depends(get_db)
):
    """Upload capability document and process in background"""
    
    # ✅ Get user_id from JWT token
    user_id = current_user.email  # Using email as user_id
    
    # Validate file type
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in ["pdf", "docx", "doc", "txt"]:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, DOCX, and TXT files are supported"
        )
    
    # Validate file size (max 10MB)
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset
    
    if file_size > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size is 10MB"
        )
    
    # Save file temporarily
    temp_dir = "/tmp/uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = f"{temp_dir}/{user_id}_{file.filename}"
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Process in background
    background_tasks.add_task(
        processor.process_and_store,
        file_path=temp_path,
        file_type=file_ext,
        user_id=user_id,  # ✅ Changed from company_id
        filename=file.filename
    )
    
    return {
        "status": "processing",
        "message": "Document uploaded successfully. Processing in background.",
        "filename": file.filename,
        "user_id": user_id,
        
    }


@router.get("/documents/matches")  # ✅ Removed firm_id from path
async def get_document_matches(
    limit: int = 10,
    current_user: User = Depends(get_current_active_user)  # ✅ JWT auth
):
    """Get contract matches based on uploaded documents"""
    
    user_id = current_user.email  # ✅ Get from JWT
    
    matches = await processor.find_matching_contracts(user_id, limit)
    
    return {
        "user_id": user_id,
        "total_matches": len(matches),
        "matches": matches
    }


@router.get("/documents")  # ✅ Removed firm_id from path
async def list_company_documents(
    current_user: User = Depends(get_current_active_user)  # ✅ JWT auth
):
    """List all documents uploaded by current user"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from app.core.config import settings
    
    user_id = current_user.email  # ✅ Get from JWT
    
    qdrant = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT
    )
    
    # Get unique documents for this user
    result = qdrant.scroll(
        collection_name="user_documents",  # ✅ Changed from company_documents
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="user_id",  # ✅ Changed from company_id
                    match=MatchValue(value=user_id)
                )
            ]
        ),
        limit=100
    )
    
    # Group by document_id
    docs = {}
    for point in result[0]:
        doc_id = point.payload["document_id"]
        if doc_id not in docs:
            docs[doc_id] = {
                "document_id": doc_id,
                "filename": point.payload["filename"],
                "uploaded_at": point.payload["uploaded_at"],
                "total_chunks": point.payload["total_chunks"],
                "file_type": point.payload["file_type"]
            }
    
    return {"documents": list(docs.values())}

@router.post("/contracts/save")
async def save_contract(
    request: SaveContractRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Save a contract to user's saved list"""
    try:
        # Check if already saved
        existing = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == request.notice_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contract already saved"
            )
        
        # Create new saved contract
        saved_contract = SavedContract(
            user_email=current_user.email,
            firm_id=current_user.firm_id,
            notice_id=request.notice_id,
            contract_title=request.contract_title,
            buyer_name=request.buyer_name,
            contract_value=request.contract_value,
            deadline=request.deadline,
            status="interested"  # Just hardcode it
        )
        
        db.add(saved_contract)
        db.commit()
        db.refresh(saved_contract)
        
        logger.info(f"User {current_user.email} saved contract {request.notice_id}")
        
        return {
            "success": True,
            "message": "Contract saved successfully",
            "id": saved_contract.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save contract: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save contract: {str(e)}"
        )


@router.delete("/contracts/save/{notice_id}")
async def unsave_contract(
    notice_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Remove a contract from user's saved list"""
    try:
        saved_contract = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == notice_id
        ).first()
        
        if not saved_contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved contract not found"
            )
        
        db.delete(saved_contract)
        db.commit()
        
        logger.info(f"User {current_user.email} unsaved contract {notice_id}")
        
        return {
            "success": True,
            "message": "Contract removed from saved list"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unsave contract: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unsave contract: {str(e)}"
        )

@router.post("/admin/setup-indexes")
async def setup_qdrant_indexes():
    """One-time setup: Create required Qdrant indexes"""
    try:
        # Create document_type index
        vector_store.client.create_payload_index(
            collection_name=vector_store.collection_name,
            field_name="document_type",
            field_schema="keyword"
        )
        
        return {
            "success": True,
            "message": "Qdrant indexes created successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Index creation: {str(e)}"
        }


@router.put("/contracts/save/{notice_id}/status")
async def update_contract_status(
    notice_id: str,
    request: UpdateContractStatusRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update the status of a saved contract"""
    try:
        saved_contract = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == notice_id
        ).first()
        
        if not saved_contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved contract not found"
            )
        
        # Update status
        saved_contract.status = ContractStatus[request.status.upper()]
        
        # Update notes if provided
        if request.notes is not None:
            saved_contract.notes = request.notes
        
        db.commit()
        
        logger.info(f"User {current_user.email} updated contract {notice_id} status to {request.status}")
        
        return {
            "success": True,
            "message": "Contract status updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update contract status: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}"
        )


@router.get("/contracts/save/{notice_id}/check")
async def check_if_saved(
    notice_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Check if a contract is saved by the current user"""
    try:
        saved_contract = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == notice_id
        ).first()
        
        return {
            "is_saved": saved_contract is not None,
            "status": saved_contract.status.value if saved_contract else None
        }
        
    except Exception as e:
        logger.error(f"Failed to check saved status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check saved status: {str(e)}"
        )