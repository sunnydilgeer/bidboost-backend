import asyncio
from fastapi import BackgroundTasks
from app.core.config import settings
from app.core.entitlements import get_entitlements
from app.core.paywall import UpgradeRequired, require_entitlement
from app.models.subscription import FirmSubscription
from app.services.contract_fetcher import ContractFetcherService
from app.services.match_scoring import ContractMatchScorer
from app.services.past_win_store_pinecone import get_past_win_store
from app.models.contract import Contract
from app.routers import capability_recommendations
from app.models import User as DBUser
from app.api.debug_routes import debug_router  # Import the real one
from app.models.company import CompanyProfile, CompanyCapability, PastWin, SearchPreference, CachedContractMatch
from app.models.schemas import (
    ContractSyncResponse, 
    ContractSearchRequest, 
    ContractSearchResponse, 
    ContractSearchResult,
    CapabilityCreate,
    CapabilityUpdate,
    CapabilityResponse,
    PastWinCreate,
    PastWinUpdate,
    PastWinResponse,
    PreferencesUpdate,
    PreferencesResponse,
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
from app.services.document_processor import get_processor
import os 
import shutil 
from app.core.auth import User, get_current_active_user
from app.database import get_db
from sqlalchemy.orm import Session
from typing import Dict, Optional, List
import logging
from datetime import datetime
from pydantic import BaseModel

class FederalInfoUpdate(BaseModel):
    company_name: Optional[str] = None
    description: Optional[str] = None
    sba_certified: Optional[bool] = None
    sdvosb_certified: Optional[bool] = None
    wosb_certified: Optional[bool] = None
    hubzone_certified: Optional[bool] = None
    eight_a_certified: Optional[bool] = None
    naics_codes: Optional[List[str]] = None
    psc_codes: Optional[List[str]] = None
    cage_code: Optional[str] = None
    uei_number: Optional[str] = None
    sam_registered: Optional[bool] = None
    sam_expiration: Optional[str] = None


class PipelineSummary(BaseModel):
    """Pipeline-wide aggregate statistics from cached matches"""
    total_opportunities: int
    high_relevance_count: int
    avg_match_score: int
    closing_7d_count: int


class PipelineResponse(BaseModel):
    """API response wrapper"""
    pipeline: PipelineSummary

logger = logging.getLogger(__name__)
capability_embedding_cache = {}

router = APIRouter(prefix="/api", tags=["Contracts"])


def trigger_cache_refresh(firm_id: str):
    """Trigger immediate cache refresh for a firm in background"""
    from app.services.match_cache_service import MatchCacheService
    import threading
    
    def refresh_in_background():
        try:
            service = MatchCacheService()
            service.run_cache_update(firm_ids=[firm_id])
            logger.info(f"✅ Cache refreshed for {firm_id}")
        except Exception as e:
            logger.error(f"Cache refresh failed for {firm_id}: {e}")
    
    # Run in background thread
    thread = threading.Thread(target=refresh_in_background)
    thread.daemon = True  # Don't block app shutdown
    thread.start()
    logger.info(f"🔄 Triggered cache refresh for {firm_id}")

# Lazy initialization functions - only connect when called
def get_vector_store():
    """Get VectorStoreService instance - connects to Qdrant on first call"""
    return VectorStoreService()

def get_llm_service():
    """Get LLMService instance - connects on first call"""
    return LLMService()

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
        vector_store = get_vector_store()
        
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
        vector_store = get_vector_store()
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

@router.get("/billing/entitlements", tags=["Billing"])
async def billing_entitlements(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Return server-authoritative plan + entitlements for this firm."""
    
    # ✅ ADD LOGGING
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"🔍 Entitlements requested for user: {current_user.email}")
    logger.info(f"🔍 User's firm_id: {current_user.firm_id}")
    
    # Check what's in the database
    from app.models.subscription import FirmSubscription
    sub = db.query(FirmSubscription).filter(
        FirmSubscription.firm_id == current_user.firm_id
    ).first()
    
    if sub:
        logger.info(f"🔍 Database shows: firm_id={sub.firm_id}, plan={sub.plan}")
    else:
        logger.info(f"⚠️ No subscription found in database!")
    
    result = get_entitlements(db, current_user.firm_id)
    logger.info(f"🔍 Returning entitlements: {result}")
    
    return result

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
            "value": "50,000",
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
    """Get company profile with all federal fields"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        # Safely handle preferences relationship
        preferences_data = None
        if profile.search_preference:
            preferences_data = PreferencesResponse(
                min_contract_value=profile.search_preference.min_contract_value,
                max_contract_value=profile.search_preference.max_contract_value,
                preferred_regions=profile.search_preference.preferred_regions or [],
                excluded_categories=profile.search_preference.excluded_categories or [],
                keywords=profile.search_preference.keywords or []
            )
        
        # Build response with all federal fields
        return CompanyProfileResponse(
            firm_id=profile.firm_id,
            company_name=profile.company_name,
            description=profile.description,
            size=profile.size,
            founded_year=profile.founded_year,
            registration_number=profile.registration_number,
            # Federal fields with safe defaults
            sba_certified=profile.sba_certified or False,
            sdvosb_certified=profile.sdvosb_certified or False,
            wosb_certified=profile.wosb_certified or False,
            hubzone_certified=profile.hubzone_certified or False,
            eight_a_certified=profile.eight_a_certified or False,
            naics_codes=profile.naics_codes or [],
            psc_codes=profile.psc_codes or [],
            cage_code=profile.cage_code,
            uei_number=profile.uei_number,
            sam_registered=profile.sam_registered or False,
            sam_expiration=profile.sam_expiration.isoformat() if profile.sam_expiration else None,
            # Related data
            capabilities=[CapabilityResponse.from_orm(c) for c in profile.capabilities] if profile.capabilities else [],
            past_wins=[PastWinResponse.from_orm(w) for w in profile.past_wins] if profile.past_wins else [],
            preferences=preferences_data,
            created_at=profile.created_at,
            updated_at=profile.updated_at
        )
        
    except Exception as e:
        logger.error(f"Failed to get company profile: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve company profile: {str(e)}"
        )
@router.put("/company/profile")
async def update_company_profile_endpoint(
    data: FederalInfoUpdate,  # ← This receives the JSON body!
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update company profile including federal-specific fields"""
    try:
        profile = get_company_profile(db, current_user.firm_id)
        
        # Basic fields
        if data.company_name is not None:
            profile.company_name = data.company_name
        if data.description is not None:
            profile.description = data.description
        
        # Federal certification fields
        if data.sba_certified is not None:
            profile.sba_certified = data.sba_certified
        if data.sdvosb_certified is not None:
            profile.sdvosb_certified = data.sdvosb_certified
        if data.wosb_certified is not None:
            profile.wosb_certified = data.wosb_certified
        if data.hubzone_certified is not None:
            profile.hubzone_certified = data.hubzone_certified
        if data.eight_a_certified is not None:
            profile.eight_a_certified = data.eight_a_certified
        
        # Industry codes
        if data.naics_codes is not None:
            profile.naics_codes = data.naics_codes
        if data.psc_codes is not None:
            profile.psc_codes = data.psc_codes
        
        # Federal identifiers
        if data.cage_code is not None:
            profile.cage_code = data.cage_code
        if data.uei_number is not None:
            profile.uei_number = data.uei_number
        if data.sam_registered is not None:
            profile.sam_registered = data.sam_registered
        if data.sam_expiration is not None:
            from datetime import datetime
            profile.sam_expiration = datetime.fromisoformat(data.sam_expiration.replace('Z', '+00:00')).date()
        
        logger.info(f"DEBUG BEFORE COMMIT: sba={profile.sba_certified}, sdvosb={profile.sdvosb_certified}")
        
        db.commit()
        db.refresh(profile)
        
        logger.info(f"Updated profile for firm {current_user.firm_id}")
        return {"success": True, "message": "Profile updated successfully"}
        
    except Exception as e:
        logger.error(f"Failed to update profile: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update profile: {str(e)}"
        )

@router.get("/capabilities", dependencies=[Depends(require_entitlement("capability_management"))])
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

@router.post("/capabilities", dependencies=[Depends(require_entitlement("capability_management"))])
async def add_capability(
    capability: CapabilityCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Add a new capability and sync to Pinecone"""
    try:
        from app.services.capability_store_pinecone import get_capability_store
        
        llm_service = get_llm_service()
        profile = get_company_profile(db, current_user.firm_id)
        
        # Create capability in database first
        new_cap = CompanyCapability(
            company_id=profile.id,
            capability_text=capability.capability_text,
            category=capability.category
        )
        
        db.add(new_cap)
        db.flush()
        db.refresh(new_cap)
        cap_store = get_capability_store()
        pinecone_id = await cap_store.add_capability(new_cap, llm_service)
        
        # Update with pinecone_id
        new_cap.qdrant_id = pinecone_id  # Reusing same DB field
        db.commit()
        trigger_cache_refresh(current_user.firm_id)
        db.refresh(new_cap)


        
        # INVALIDATE CACHE
        keys_to_delete = [k for k in capability_embedding_cache.keys() if k.startswith(f"{current_user.firm_id}:")]
        for key in keys_to_delete:
            del capability_embedding_cache[key]
        logger.info(f"Cleared capability cache for firm {current_user.firm_id}")
        
        logger.info(f"Added capability for firm {current_user.firm_id}: {capability.capability_text[:50]}")
        
        return {
            "success": True,
            "id": new_cap.id,
            "qdrant_id": new_cap.qdrant_id,
            "message": "Capability added and synced to Pinecone"
        }
        
    except Exception as e:
        logger.error(f"Failed to add capability: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add capability: {str(e)}"
        )

@router.put("/capabilities/{capability_id}", dependencies=[Depends(require_entitlement("capability_management"))])
async def update_capability(
    capability_id: int,
    capability: CapabilityUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update an existing capability and re-sync to Pinecone"""
    try:
        from app.services.capability_store_pinecone import get_capability_store
        
        llm_service = get_llm_service()
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
        
        # Re-sync to Pinecone (delete old, add new)
        cap_store = get_capability_store()
        
        if existing_cap.qdrant_id:
            cap_store.delete_capability(existing_cap.qdrant_id)
        
        pinecone_id = await cap_store.add_capability(existing_cap, llm_service)
        existing_cap.qdrant_id = pinecone_id
        
        db.commit()
        trigger_cache_refresh(current_user.firm_id)


        
        # INVALIDATE CACHE
        keys_to_delete = [k for k in capability_embedding_cache.keys() if k.startswith(f"{current_user.firm_id}:")]
        for key in keys_to_delete:
            del capability_embedding_cache[key]
        logger.info(f"Cleared capability cache for firm {current_user.firm_id}")
        
        logger.info(f"Updated capability {capability_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Capability updated and re-synced to Pinecone"
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

@router.delete("/capabilities/{capability_id}", dependencies=[Depends(require_entitlement("capability_management"))])
async def delete_capability(
    capability_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a capability and remove from Pinecone"""
    try:
        from app.services.capability_store_pinecone import get_capability_store
        
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
        
        # Delete from Pinecone first
        if existing_cap.qdrant_id:
            cap_store = get_capability_store()
            cap_store.delete_capability(existing_cap.qdrant_id)
        
        # Delete from database
        db.delete(existing_cap)
        db.commit()
        trigger_cache_refresh(current_user.firm_id)

        # INVALIDATE CACHE
        keys_to_delete = [k for k in capability_embedding_cache.keys() if k.startswith(f"{current_user.firm_id}:")]
        for key in keys_to_delete:
            del capability_embedding_cache[key]
        logger.info(f"Cleared capability cache for firm {current_user.firm_id}")
        
        logger.info(f"Deleted capability {capability_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Capability deleted and removed from Pinecone"
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
    """Add a new past contract win and embed in Pinecone"""
    try:
        from app.services.past_win_store_pinecone import get_past_win_store
        
        llm_service = get_llm_service()
        profile = get_company_profile(db, current_user.firm_id)
        
        # Create past win in database first
        new_win = PastWin(
            company_id=profile.id,
            contract_title=win.contract_title,
            buyer_name=win.buyer_name,
            contract_value=win.contract_value,
            award_date=win.award_date,
            description=win.description
        )
        
        db.add(new_win)
        db.flush()  # Get the ID without committing
        db.refresh(new_win)
        
        # ✅ NEW: Add to Pinecone
        win_store = get_past_win_store()
        pinecone_id = await win_store.add_past_win(new_win, llm_service)
        
        # Update with pinecone_id
        new_win.pinecone_id = pinecone_id
        db.commit()
        trigger_cache_refresh(current_user.firm_id)

        db.refresh(new_win)
        
        logger.info(f"Added past win for firm {current_user.firm_id}: {win.contract_title} (Pinecone ID: {pinecone_id})")
        
        return {
            "success": True,
            "id": new_win.id,
            "pinecone_id": new_win.pinecone_id,
            "message": "Past win added and embedded in Pinecone"
        }
        
    except Exception as e:
        logger.error(f"Failed to add past win: {str(e)}", exc_info=True)
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
    """Update an existing past contract win and re-embed in Pinecone"""
    try:
        from app.services.past_win_store_pinecone import get_past_win_store
        
        llm_service = get_llm_service()
        profile = get_company_profile(db, current_user.firm_id)
        
        # Verify past win belongs to this company
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
        
        db.flush()
        
        # ✅ NEW: Re-sync to Pinecone (delete old, add new)
        win_store = get_past_win_store()
        
        if existing_win.pinecone_id:
            win_store.delete_past_win(existing_win.pinecone_id)
        
        pinecone_id = await win_store.add_past_win(existing_win, llm_service)
        existing_win.pinecone_id = pinecone_id
        
        db.commit()
        trigger_cache_refresh(current_user.firm_id)

        
        logger.info(f"Updated past win {win_id} for firm {current_user.firm_id} (Pinecone ID: {pinecone_id})")
        
        return {
            "success": True,
            "message": "Past win updated and re-embedded in Pinecone"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update past win: {str(e)}", exc_info=True)
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
    """Delete a past contract win and remove from Pinecone"""
    try:
        from app.services.past_win_store_pinecone import get_past_win_store
        
        profile = get_company_profile(db, current_user.firm_id)
        
        # Verify past win belongs to this company
        win = db.query(PastWin).filter(
            PastWin.id == win_id,
            PastWin.company_id == profile.id
        ).first()
        
        if not win:
            raise HTTPException(
                status_code=404,
                detail="Past win not found or does not belong to your company"
            )
        
        # ✅ NEW: Delete from Pinecone first
        if win.pinecone_id:
            win_store = get_past_win_store()
            win_store.delete_past_win(win.pinecone_id)
        
        # Delete from database
        db.delete(win)
        db.commit()
        trigger_cache_refresh(current_user.firm_id)

        
        logger.info(f"Deleted past win {win_id} for firm {current_user.firm_id}")
        
        return {
            "success": True,
            "message": "Past win deleted and removed from Pinecone"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete past win: {str(e)}", exc_info=True)
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
        trigger_cache_refresh(current_user.firm_id)

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
    
    vector_store = get_vector_store()
    llm_service = get_llm_service()
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

# ==========================================
# COMPLETE OPTIMIZED FUNCTION #1
# Replace the entire @router.get("/contracts/recommended") function
# Location: Around line 820-950 in routes.py
# ==========================================

@router.get("/contracts/recommended", response_model=ContractSearchResponse)
async def get_recommended_contracts(
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> ContractSearchResponse:
    """
    Get personalized contract recommendations with match scoring.
    
    OPUS PURE CAPABILITY APPROACH:
    - match_score = capability similarity only
    - No weighted average, no penalties for missing data
    - Checks cache first, falls back to real-time scoring
    """
    try:
        USE_CACHE = True  # ← Set to True after testing
        cached_matches = None  # ✅ Initialize it!
        
        if USE_CACHE:
            cached_matches = db.query(CachedContractMatch)\
                .filter(CachedContractMatch.firm_id == current_user.firm_id)\
                .order_by(CachedContractMatch.rank)\
                .limit(limit)\
                .all()
        
        if cached_matches:
            logger.info(f"⚡ CACHE HIT: Serving {len(cached_matches)} contracts from cache for {current_user.firm_id}")
            
            # Convert cached matches to API format
            results = []
            for match in cached_matches:
                match_dict = match.to_dict()
                results.append(ContractSearchResult(**match_dict))
            
            return ContractSearchResponse(
                query="",
                results=results,
                total_found=len(results),
                message=f"Found {len(results)} personalized matches (cached)"
            )
        
        # ❌ CACHE MISS - Fall back to real-time scoring
        logger.warning(f"⚠️ Cache MISS for {current_user.firm_id} - using real-time scoring")
        
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings
        from app.services.code_lookup import get_code_lookup_service, clean_naics_code
        from app.services.capability_store_pinecone import get_capability_store
        from app.services.past_win_store_pinecone import get_past_win_store
        
        llm_service = get_llm_service()
        code_service = get_code_lookup_service()

        # Get company profile
        company = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == current_user.firm_id
        ).first()
        
        if not company:
            raise HTTPException(status_code=404, detail="Company profile not found")
        
        # Get capabilities
        capabilities = db.query(CompanyCapability).filter(
            CompanyCapability.company_id == company.id
        ).all()
        
        if not capabilities:
            return ContractSearchResponse(
                query="",
                results=[],
                total_found=0,
                message="Add capabilities to see personalized matches"
            )
        
        # Create query from capabilities
        capability_texts = [cap.capability_text for cap in capabilities[:3]]
        combined_query = " ".join(capability_texts)

        # Check cache first
        capability_ids = sorted([c.id for c in capabilities])
        cache_key = f"{current_user.firm_id}:{'-'.join(map(str, capability_ids))}"

        if cache_key in capability_embedding_cache:
            query_vector = capability_embedding_cache[cache_key]
            logger.info(f"Using cached embedding for {current_user.firm_id}")
        else:
            # Generate embedding and cache it
            query_vector = await llm_service.generate_embeddings(combined_query)
            capability_embedding_cache[cache_key] = query_vector
            logger.info(f"Generated and cached new embedding for {current_user.firm_id}")
        
        # Search Pinecone - REDUCED LIMIT for faster scoring
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        results = pinecone.search_contracts(
            query_vector=query_vector,
            limit=min(limit * 2, 40),  # Cap at 40 to avoid over-fetching
            min_score=0.35,  # Higher threshold = fewer contracts to score
            namespace="contracts"
        )
        
        if not results:
            return ContractSearchResponse(
                query="",
                results=[],
                total_found=0,
                message="No matching contracts found"
            )
        
        # PERFORMANCE OPTIMIZATION: Pre-fetch all capability vectors once
        cap_store = get_capability_store()
        capability_ids_to_fetch = [cap.qdrant_id for cap in capabilities if cap.qdrant_id]
        
        # Batch fetch all capabilities from Pinecone
        capabilities_data = {}
        if capability_ids_to_fetch:
            capabilities_data = cap_store.get_capabilities_batch(capability_ids_to_fetch)
            logger.info(f"Pre-fetched {len(capabilities_data)} capability vectors")
        
        # Pre-fetch past win vectors
        past_wins_data = {}
        past_wins = company.past_wins if company.past_wins else []
        if past_wins:
            win_store = get_past_win_store()
            past_win_ids = [win.pinecone_id for win in past_wins if win.pinecone_id]
            
            if past_win_ids:
                past_wins_data = win_store.get_past_wins_batch(past_win_ids)
                logger.info(f"Pre-fetched {len(past_wins_data)} past win vectors")
        
        # PERFORMANCE OPTIMIZATION: Pre-fetch ALL contract vectors in one batch
        contract_ids = [r.get("id") for r in results if r.get("id")]
        contract_vectors = {}
        
        if contract_ids:
            try:
                # Batch fetch all contract vectors from Pinecone
                fetch_result = pinecone.index.fetch(ids=contract_ids, namespace="contracts")
                
                for vec_id, vec_data in fetch_result.vectors.items():
                    contract_vectors[vec_id] = list(vec_data.values)
                
                logger.info(f"✅ Pre-fetched {len(contract_vectors)} contract vectors in one batch")
            except Exception as e:
                logger.error(f"Failed to batch fetch contract vectors: {e}")
        
        # Initialize scorer
        scorer = ContractMatchScorer(db, pinecone.index)
        
        # Convert with scoring
        search_results = []
        for result in results:
            # Enrich with code names
            enriched_result = code_service.enrich_contract(result)
            
            # Create Contract for scoring
            temp_contract = Contract(
                notice_id=enriched_result.get("notice_id", ""),
                title=enriched_result.get("title", ""),
                buyer_name=enriched_result.get("agency", ""),
                description=enriched_result.get("description", ""),
                contract_value=enriched_result.get("contract_value"),
                region=enriched_result.get("state"),
                qdrant_id=enriched_result.get("id")
            )
            
            # Score it - pass ALL THREE pre-fetched vectors
            match_scores = scorer.score_contract(
                temp_contract, 
                current_user.firm_id, 
                capability_vectors=capabilities_data,
                contract_vectors=contract_vectors,
                past_win_vectors=past_wins_data
            )
            
            # Skip if filtered out
            if not match_scores:
                continue
            
            # Build result using enriched_result throughout
            search_results.append(ContractSearchResult(
                notice_id=enriched_result.get("notice_id", ""),
                title=enriched_result.get("title", ""),
                buyer_name=enriched_result.get("agency", ""),
                description=enriched_result.get("description", ""),
                value=float(enriched_result.get("contract_value", 0)) if enriched_result.get("contract_value") else None,
                region=enriched_result.get("state", ""),
                closing_date=enriched_result.get("response_deadline", ""),
    score=match_scores["match_score"],
                office=enriched_result.get("office"),
                naics_code=clean_naics_code(enriched_result.get("naics_code")),
                naics_name=enriched_result.get("naics_name"),
                psc_code=enriched_result.get("psc_code"),
                psc_name=enriched_result.get("psc_name"),
                set_aside=enriched_result.get("set_aside"),
                city=enriched_result.get("city"),
                posted_date=enriched_result.get("posted_date"),
                source_url=enriched_result.get("url"),
                contact_name=enriched_result.get("contact_name"),
                contact_email=enriched_result.get("contact_email"),
                contact_phone=enriched_result.get("contact_phone"),
                closing_time=None,
                start_date=None,
                end_date=None,
                value_low=None,
                value_high=None,
                postcode=None,
                notice_type=None,
                contact_address=None,
                contact_website=None,
                additional_text=None,
                attachments=None,
                links=None,
                suitable_for_sme=None,
                suitable_for_vco=None,
                match_scores=match_scores,
                total_match_score=match_scores["match_score"],  # ✅ PURE CAPABILITY SCORE
                match_reasons=match_scores.get("match_reasons", [])
            ))
            
            # Early exit if we have enough results
            if len(search_results) >= limit:
                break
        
        # Sort by match score (PURE CAPABILITY)
        search_results.sort(key=lambda x: x.total_match_score or 0, reverse=True)
        search_results = search_results[:limit]
        
        logger.info(f"✅ Recommendations complete: Returning {len(search_results)} matches")
        
        return ContractSearchResponse(
            query="",
            results=search_results,
            total_found=len(search_results),
            message=f"Found {len(search_results)} personalized matches"
        )
        
    except Exception as e:
        logger.error(f"Recommendations failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contracts/pipeline-summary", response_model=PipelineResponse)
async def get_pipeline_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get pipeline-wide aggregate statistics from match cache.
    
    ⚡ FAST: Queries CachedContractMatch table (PostgreSQL)
    🎯 ACCURATE: Uses same pre-computed scores as /recommended
    📊 SCALABLE: Aggregates only, no row data
    
    Performance: < 50ms (cached in PostgreSQL)
    """
    
    try:
        from sqlalchemy import func, and_, case
        from datetime import datetime, timedelta
        
        firm_id = current_user.firm_id
        now = datetime.utcnow()
        seven_days_from_now = now + timedelta(days=7)
        
        # Single aggregate query on CachedContractMatch
        stats = db.query(
            # Total cached opportunities
            func.count(CachedContractMatch.id).label('total_opportunities'),
            
            # High relevance count (score >= 60%)
            func.sum(
                case(
                    (CachedContractMatch.total_match_score >= 0.6, 1),
                    else_=0
                )
            ).label('high_relevance_count'),
            
            # Average match score (convert 0-1 to 0-100)
            (func.avg(CachedContractMatch.total_match_score) * 100).label('avg_match_score'),
            
            # Closing within 7 days
            func.sum(
                case(
                    (
                        and_(
                            CachedContractMatch.closing_date.isnot(None),
                            CachedContractMatch.closing_date >= now,
                            CachedContractMatch.closing_date <= seven_days_from_now
                        ), 1
                    ),
                    else_=0
                )
            ).label('closing_7d_count')
            
        ).filter(
            CachedContractMatch.firm_id == firm_id
        ).first()
        
        # Handle empty cache
        if not stats or stats.total_opportunities == 0:
            logger.warning(f"No cached matches for firm {firm_id} - cache may need refresh")
            return PipelineResponse(
                pipeline=PipelineSummary(
                    total_opportunities=0,
                    high_relevance_count=0,
                    avg_match_score=0,
                    closing_7d_count=0
                )
            )
        
        # Build response
        pipeline_summary = PipelineSummary(
            total_opportunities=int(stats.total_opportunities or 0),
            high_relevance_count=int(stats.high_relevance_count or 0),
            avg_match_score=round(float(stats.avg_match_score or 0)),
            closing_7d_count=int(stats.closing_7d_count or 0)
        )
        
        logger.info(
            f"Pipeline summary for {firm_id}: "
            f"{pipeline_summary.total_opportunities} total, "
            f"{pipeline_summary.high_relevance_count} high-relevance, "
            f"{pipeline_summary.avg_match_score}% avg score"
        )
        
        return PipelineResponse(pipeline=pipeline_summary)
        
    except Exception as e:
        logger.error(f"Pipeline summary failed for {firm_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pipeline summary"
        )



# ========== CONTRACT SEARCH ROUTE WITH PERSONALIZED MATCH SCORING ==========

# ==========================================
# COMPLETE FIXED SEARCH FUNCTION - MAIN FIX
# This removes the duplicate Pinecone initialization
# ==========================================

@router.post("/contracts/search", response_model=ContractSearchResponse)
async def search_contracts(
    search_request: ContractSearchRequest,
    include_match_scores: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
) -> ContractSearchResponse:
    """
    Search SAM.gov contracts using Pinecone semantic search.
    
    OPUS PURE CAPABILITY APPROACH:
    - match_score = capability similarity only
    - No weighted average, no boosts
    - Same scoring as dashboard and quick-start
    """
    try:
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings 
        from app.services.code_lookup import get_code_lookup_service, clean_naics_code

        llm_service = get_llm_service()
        code_service = get_code_lookup_service()
        
        logger.info(f"Contract search: '{search_request.query}'")
        
        # Generate query embedding
        query_vector = await llm_service.generate_embeddings(search_request.query)
        
        # Initialize Pinecone ONCE at the top
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        
        # Build Pinecone filters
        filters = {}
        if search_request.min_value or search_request.max_value:
            value_filter = {}
            if search_request.min_value:
                value_filter["$gte"] = float(search_request.min_value)
            if search_request.max_value:
                value_filter["$lte"] = float(search_request.max_value)
            filters["contract_value"] = value_filter
        
        if search_request.region:
            filters["state"] = {"$eq": search_request.region}
        
        # Search Pinecone
        search_limit = search_request.limit * 2 if include_match_scores else search_request.limit
        results = pinecone.search_contracts(
            query_vector=query_vector,
            limit=search_limit,
            min_score=0.3,
            namespace="contracts",
            filter_dict=filters if filters else None
        )
        
        # Initialize scorer if match scores are requested
        scorer = ContractMatchScorer(db, pinecone.index) if include_match_scores else None
        
        # PERFORMANCE OPTIMIZATION: Pre-fetch capability vectors AND contract vectors if scoring is enabled
        capabilities_data = {}
        contract_vectors = {}
        past_wins_data = {}
        
        if scorer:
            from app.services.capability_store_pinecone import get_capability_store
            from app.services.past_win_store_pinecone import get_past_win_store
            
            # Get company capabilities
            company = db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == current_user.firm_id
            ).first()
            
            if company and company.capabilities:
                cap_store = get_capability_store()
                capability_ids = [cap.qdrant_id for cap in company.capabilities if cap.qdrant_id]
                
                if capability_ids:
                    capabilities_data = cap_store.get_capabilities_batch(capability_ids)
                    logger.info(f"[/search] Pre-fetched {len(capabilities_data)} capability vectors")
            
            # Pre-fetch past win vectors
            if company and company.past_wins:
                win_store = get_past_win_store()
                past_win_ids = [win.pinecone_id for win in company.past_wins if win.pinecone_id]
                
                if past_win_ids:
                    past_wins_data = win_store.get_past_wins_batch(past_win_ids)
                    logger.info(f"[/search] Pre-fetched {len(past_wins_data)} past win vectors")
            
            # Pre-fetch all contract vectors in one batch
            contract_ids = [r.get("id") for r in results if r.get("id")]
            
            if contract_ids:
                try:
                    fetch_result = pinecone.index.fetch(ids=contract_ids, namespace="contracts")
                    
                    for vec_id, vec_data in fetch_result.vectors.items():
                        contract_vectors[vec_id] = list(vec_data.values)
                    
                    logger.info(f"[/search] Pre-fetched {len(contract_vectors)} contract vectors")
                except Exception as e:
                    logger.error(f"[/search] Failed to batch fetch contracts: {e}")
        
        # Convert results
        search_results = []
        for result in results:
            # Enrich with code names
            enriched_result = code_service.enrich_contract(result)
            
            # Build contract result using enriched_result throughout
            contract_result = ContractSearchResult(
                notice_id=enriched_result.get("notice_id", ""),
                title=enriched_result.get("title", ""),
                buyer_name=enriched_result.get("agency", ""),
                description=enriched_result.get("description", ""),
                value=enriched_result.get("contract_value"),
                region=enriched_result.get("state"),
                closing_date=enriched_result.get("response_deadline"),
                score=enriched_result.get("score", 0.0),
                office=enriched_result.get("office"),
                naics_code=clean_naics_code(enriched_result.get("naics_code")),
                psc_code=enriched_result.get("psc_code"),
                naics_name=enriched_result.get("naics_name"),
                psc_name=enriched_result.get("psc_name"),
                set_aside=enriched_result.get("set_aside"),
                city=enriched_result.get("city"),
                posted_date=enriched_result.get("posted_date"),
                source_url=enriched_result.get("url"),
                contact_name=enriched_result.get("contact_name"),
                contact_email=enriched_result.get("contact_email"),
                contact_phone=enriched_result.get("contact_phone"),
                closing_time=None,
                start_date=None,
                end_date=None,
                value_low=None,
                value_high=None,
                postcode=None,
                notice_type=None,
                contact_address=None,
                contact_website=None,
                additional_text=None,
                attachments=None,
                links=None,
                suitable_for_sme=None,
                suitable_for_vco=None
            )
            
            # Add match scoring if enabled
            if scorer:
                temp_contract = Contract(
                    notice_id=enriched_result.get("notice_id", ""),
                    title=enriched_result.get("title", ""),
                    buyer_name=enriched_result.get("agency", ""),
                    description=enriched_result.get("description", ""),
                    contract_value=enriched_result.get("contract_value"),
                    region=enriched_result.get("state"),
                    qdrant_id=enriched_result.get("id")
                )
                
                # Score with ALL THREE pre-fetched vectors
                match_scores = scorer.score_contract(
                    temp_contract, 
                    current_user.firm_id, 
                    capability_vectors=capabilities_data,
                    contract_vectors=contract_vectors,
                    past_win_vectors=past_wins_data
                )
                
                if match_scores:
                    contract_result.match_scores = match_scores
                    contract_result.total_match_score = match_scores["match_score"]  # ✅ PURE CAPABILITY SCORE
                    contract_result.match_reasons = match_scores.get("match_reasons", [])
                    search_results.append(contract_result)
            else:
                search_results.append(contract_result)
        
        # Sort by match score if enabled (PURE CAPABILITY)
        if include_match_scores:
            search_results.sort(key=lambda x: x.total_match_score or 0, reverse=True)
        
        search_results = search_results[:search_request.limit]
        
        return ContractSearchResponse(
            query=search_request.query,
            results=search_results,
            total_found=len(search_results),
            message=f"Found {len(search_results)} contracts matching '{search_request.query}'"
        )
        
    except Exception as e:
        logger.error(f"Search failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

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
            SavedContract.firm_id == current_user.firm_id
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
        # ✅ FIXED: Query Pinecone instead of Qdrant for SAM.gov contracts
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings
        
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        
        # Search for contract by notice_id in metadata
        import numpy as np
        dummy_vector = np.random.rand(768).tolist()
        
        results = pinecone.index.query(
            vector=dummy_vector,
            filter={"notice_id": {"$eq": notice_id}},
            top_k=1,
            include_metadata=True,
            namespace="contracts"
        )
        
        if not results.matches:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contract not found"
            )
        
        metadata = results.matches[0].metadata
        
        return {
            "notice_id": notice_id,
            "title": metadata.get("title"),
            "buyer_name": metadata.get("agency"),
            "description": metadata.get("description"),
            "value": metadata.get("contract_value"),
            "region": metadata.get("state"),
            "closing_date": metadata.get("response_deadline"),
            "published_date": metadata.get("posted_date"),
            "naics_code": metadata.get("naics_code"),
            "psc_code": metadata.get("psc_code"),
            "set_aside": metadata.get("set_aside"),
            "contact_details": {
                "name": metadata.get("contact_name"),
                "email": metadata.get("contact_email"),
                "phone": metadata.get("contact_phone")
            }
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
    
    processor = get_processor()
    
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
    
    processor = get_processor()
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
    """Save a contract to user's saved list (Starter capped, Pro unlimited)."""
    try:
        # ✅ Paywall: firm-level saved contract cap for Starter
        ent = get_entitlements(db, current_user.firm_id)
        limit = ent.get("saved_contract_limit")

        if limit is not None:
            firm_count = db.query(SavedContract).filter(
                SavedContract.firm_id == current_user.firm_id
            ).count()
            if firm_count >= limit:
                # Standard paywall error (handled by main.py exception handler)
                raise UpgradeRequired(
                    feature="saved_contract_limit",
                    message="Upgrade to Pro for unlimited saved contracts."
                )

        # Check if already saved (per-user unique constraint in your DB)
        existing = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == request.notice_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contract already saved"
            )

        saved_contract = SavedContract(
            user_email=current_user.email,
            firm_id=current_user.firm_id,
            notice_id=request.notice_id,
            contract_title=request.contract_title,
            buyer_name=request.buyer_name,
            contract_value=request.contract_value,
            deadline=request.deadline,
            status="interested"
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
    except UpgradeRequired:
        # let the global handler format the JSON
        raise
    except Exception as e:
        logger.error(f"Failed to save contract: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save contract: {str(e)}"
        )

@router.delete("/contracts/save/{notice_id:path}")  # ✅ Added :path to accept slashes
async def unsave_contract(
    notice_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Remove a contract from user's saved list"""
    try:
        logger.info(f"=" * 80)
        logger.info(f"🗑️ DELETE REQUEST RECEIVED")
        logger.info(f"Raw notice_id received: '{notice_id}'")
        logger.info(f"notice_id type: {type(notice_id)}")
        logger.info(f"notice_id length: {len(notice_id)}")
        logger.info(f"User email: {current_user.email}")
        logger.info(f"=" * 80)
        
        # Query for the saved contract
        saved_contract = db.query(SavedContract).filter(
            SavedContract.user_email == current_user.email,
            SavedContract.notice_id == notice_id
        ).first()
        
        if not saved_contract:
            logger.warning(f"❌ Contract NOT FOUND in database")
            
            # Debug: Show all saved contracts for this user
            all_saved = db.query(SavedContract).filter(
                SavedContract.user_email == current_user.email
            ).all()
            
            logger.info(f"📋 User has {len(all_saved)} total saved contracts:")
            for sc in all_saved:
                logger.info(f"  - ID: {sc.id}")
                logger.info(f"    notice_id: '{sc.notice_id}'")
                logger.info(f"    title: {sc.contract_title[:50]}...")
                logger.info(f"    Match? {sc.notice_id == notice_id}")
                logger.info(f"    Lengths: DB={len(sc.notice_id)}, Request={len(notice_id)}")
                
                # Character-by-character comparison
                if sc.notice_id != notice_id:
                    logger.info(f"    Character comparison:")
                    for i, (c1, c2) in enumerate(zip(sc.notice_id, notice_id)):
                        if c1 != c2:
                            logger.info(f"      Position {i}: DB='{c1}' (ord={ord(c1)}) vs Request='{c2}' (ord={ord(c2)})")
                logger.info("")
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Saved contract not found. Looking for: '{notice_id}'"
            )
        
        # Delete the contract
        logger.info(f"✅ Found saved contract ID: {saved_contract.id}")
        db.delete(saved_contract)
        db.commit()
        
        logger.info(f"✅ Successfully deleted contract {notice_id}")
        
        return {
            "success": True,
            "message": "Contract removed from saved list"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to unsave contract: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unsave contract: {str(e)}"
        )

@router.post("/admin/setup-indexes")
async def setup_qdrant_indexes():
    """One-time setup: Create required Qdrant indexes"""
    try:
        vector_store = get_vector_store()
        
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


@router.put(
    "/contracts/save/{notice_id:path}/status",
    dependencies=[Depends(require_entitlement("pipeline_tracking"))]
)
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


@router.delete("/admin/reset-contracts")
async def reset_contracts():
    """Delete all contracts and start fresh"""
    try:
        vector_store = get_vector_store()
        
        vector_store.client.delete_collection("legal_documents")
        vector_store._ensure_collection()  # Recreate
        
        return {"success": True, "message": "Collection reset. Ready to sync."}
    except Exception as e:
        return {"success": False, "message": str(e)}

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

@router.post("/contracts/sync-background")
async def sync_contracts_background_endpoint(
    background_tasks: BackgroundTasks,
    limit: int = 10000,
    days_back: int = 365,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Trigger background sync that runs on Railway without timeout.
    Returns immediately while sync continues in background.
    """
    from app.tasks.background_sync import sync_contracts_background
    
    background_tasks.add_task(sync_contracts_background, days_back)
    
    return {
    "message": f"Background sync started for ALL open contracts from last {days_back} days",
    "status": "processing",
    "note": "Check Railway logs to monitor progress. Search for 🚀 emoji."
    }

@router.post("/admin/test-email")
async def test_email_system(
    current_user: User = Depends(get_current_active_user)
):
    """Test email system - sends a test email immediately"""
    from app.tasks.email_scheduler import email_scheduler
    from app.services.email_service import email_service
    
    # Test 1: Check SendGrid connection
    if not email_service.test_connection():
        raise HTTPException(
            status_code=500,
            detail="SendGrid API key not configured"
        )
    
    # Test 2: Send test email
    test_contracts = [
        {
            "notice_id": "test-123",
            "title": "Test Contract - IT Services",
            "buyer_name": "Test Government Department",
            "value": "£50,000",
            "deadline": "2025-12-15",
            "match_score": 87,
            "match_reason": "This is a test email to verify your setup"
        }
    ]
    
    success = email_service.send_new_contracts_email(
        to_email=current_user.email,
        user_name=current_user.full_name,
        contracts=test_contracts,
        total_new_contracts=1
    )
    
    if success:
        return {
            "success": True,
            "message": f"Test email sent to {current_user.email}",
            "scheduler_status": "running" if email_scheduler.scheduler.running else "stopped"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send test email"
        )

@router.post("/admin/trigger-daily-emails")
async def trigger_daily_emails_now(
    current_user: User = Depends(get_current_active_user)
):
    """Manually trigger the daily email job (for testing)"""
    from app.tasks.email_scheduler import email_scheduler
    
    try:
        email_scheduler.run_job_now('daily_contract_emails')
        return {
            "success": True,
            "message": "Daily email job triggered - check logs for results"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/reset-last-email/{email}", tags=["Contracts"])
async def reset_last_email(email: str, db: Session = Depends(get_db)):
    """Reset last_email_sent_at to 1 day ago for testing"""
    from datetime import datetime, timedelta
    
    user = db.query(DBUser).filter(DBUser.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.last_email_sent_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    
    return {
        "success": True,
        "message": f"Reset last_email_sent_at for {email} to yesterday"
    }

@router.post("/admin/sync-fts")
async def sync_fts_manually(
    current_user: User = Depends(get_current_active_user)
):
    """Manually trigger FTS sync on production"""
    from app.tasks.fts_sync import sync_fts_contracts
    
    result = await sync_fts_contracts()
    return result

@router.get(
    "/user/match-improvement-recommendations",
    dependencies=[Depends(require_entitlement("capability_management"))]
)
async def get_match_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get personalized recommendations to improve match scores."""
    try:
        # ✅ FIXED: Use Pinecone instead of Qdrant for match recommendations
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings
        
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        
        # Initialize scorer with db and pinecone index
        scorer = ContractMatchScorer(db, pinecone.index)
        
        # Generate recommendations
        recommendations = scorer.get_improvement_recommendations(current_user.firm_id)
        
        # Get current profile counts for display
        profile = db.query(CompanyProfile).filter(
            CompanyProfile.firm_id == current_user.firm_id
        ).first()
        
        if not profile:
            raise HTTPException(status_code=404, detail="Company profile not found")
        
        return {
            "recommendations": recommendations,
            "current_profile": {
                "capabilities_count": len(profile.capabilities) if profile.capabilities else 0,
                "past_wins_count": len(profile.past_wins) if profile.past_wins else 0,
                "preferences_set": profile.search_preference is not None,
                "firm_name": profile.company_name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating match recommendations: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate recommendations: {str(e)}")

@router.delete("/admin/delete-old-contracts")
async def delete_old_uk_contracts():
    """Delete old UK contracts collection"""
    try:
        vector_store = get_vector_store()
        vector_store.client.delete_collection("legal_documents")
        logger.info("🗑️ Deleted old legal_documents collection")
        return {"success": True, "message": "Old UK data deleted"}
    except Exception as e:
        logger.error(f"Delete failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/pinecone-status")
async def check_pinecone_status():
    """Check if Pinecone has SAM.gov contracts"""
    try:
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings
        
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        count = pinecone.get_document_count()
        
        return {
            "pinecone_connected": True,
            "index_name": "contracts",
            "total_vectors": count,
            "status": "✅ Pinecone operational" if count > 0 else "⚠️ No vectors found"
        }
    except Exception as e:
        logger.error(f"Pinecone status check failed: {str(e)}")
        return {"pinecone_connected": False, "error": str(e)}

@router.post("/admin/cleanup-uk-contracts")
async def cleanup_uk_contracts_from_pinecone():
    """
    Remove UK contracts from Pinecone, keep only US SAM.gov contracts.
    
    Identifies UK contracts by:
    - Missing US federal agency names
    - UK-specific keywords in descriptions
    - Empty buyer_name or agency fields
    """
    try:
        from app.services.pinecone_store import PineconeStoreService
        from app.core.config import settings
        
        pinecone = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
        
        # US Federal agency keywords (must contain at least one)
        us_agencies = [
            "department of", "dept of", "dod", "dhs", "gsa", "nasa", 
            "usda", "va ", "hhs", "dot ", "doe ", "treasury", 
            "justice", "interior", "commerce", "labor", "hud",
            "defense", "homeland security", "veterans affairs",
            "health and human services", "transportation",
            "energy", "education", "state department"
        ]
        
        # UK-specific keywords (if found, it's UK)
        uk_keywords = [
            "uk ", "united kingdom", "england", "scotland", "wales",
            "hmrc", "nhs", "crown", "procurement", "finder",
            "£", "gbp", "utility skills", "skills group"
        ]
        
        # Get all vectors with metadata (Pinecone limitation: fetch in batches)
        # Since we can't list all IDs easily, we'll use query with a dummy vector
        import numpy as np
        dummy_vector = np.random.rand(768).tolist()
        
        # Query to get many results
        results = pinecone.index.query(
            vector=dummy_vector,
            top_k=10000,  # Get as many as possible
            include_metadata=True
        )
        
        uk_contract_ids = []
        us_contract_count = 0
        
        for match in results.matches:
            metadata = match.metadata
            
            # Check if it's a US federal contract
            agency = (metadata.get("agency") or "").lower()
            title = (metadata.get("title") or "").lower()
            description = (metadata.get("description") or "").lower()
            
            combined_text = f"{agency} {title} {description}"
            
            # Identify UK contracts
            is_uk = False
            
            # Check 1: Contains UK keywords
            if any(uk_kw in combined_text for uk_kw in uk_keywords):
                is_uk = True
            
            # Check 2: Missing US agency name AND no federal keywords
            has_us_agency = any(us_kw in combined_text for us_kw in us_agencies)
            
            if not has_us_agency and not agency:
                # No US agency and empty agency field = likely UK
                is_uk = True
            
            if is_uk:
                uk_contract_ids.append(match.id)
            else:
                us_contract_count += 1
        
        # Delete UK contracts in batches
        if uk_contract_ids:
            batch_size = 100
            for i in range(0, len(uk_contract_ids), batch_size):
                batch = uk_contract_ids[i:i + batch_size]
                pinecone.index.delete(ids=batch)
                logger.info(f"Deleted batch {i//batch_size + 1}: {len(batch)} UK contracts")
        
        logger.info(f"✅ Cleanup complete: Deleted {len(uk_contract_ids)} UK contracts, kept {us_contract_count} US contracts")
        
        return {
            "success": True,
            "uk_contracts_deleted": len(uk_contract_ids),
            "us_contracts_remaining": us_contract_count,
            "message": f"Cleaned up {len(uk_contract_ids)} UK contracts from Pinecone"
        }
        
    except Exception as e:
        logger.error(f"Cleanup failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


@router.post("/admin/resync-my-capabilities")
async def resync_my_capabilities(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Re-sync all capabilities for current user to Pinecone"""
    from app.services.capability_store_pinecone import get_capability_store
    from app.services.llm import LLMService
    
    llm_service = LLMService()
    cap_store = get_capability_store()
    
    # Get company
    company = db.query(CompanyProfile).filter(
        CompanyProfile.firm_id == current_user.firm_id
    ).first()
    
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Get all capabilities
    capabilities = db.query(CompanyCapability).filter(
        CompanyCapability.company_id == company.id
    ).all()
    
    synced = 0
    errors = []
    
    for cap in capabilities:
        try:
            # Delete old vector if exists
            if cap.qdrant_id:
                cap_store.delete_capability(cap.qdrant_id)
            
            # Add to Pinecone with new vector
            pinecone_id = await cap_store.add_capability(cap, llm_service)
            cap.qdrant_id = pinecone_id
            synced += 1
            
        except Exception as e:
            logger.error(f"Failed to sync capability {cap.id}: {e}")
            errors.append({"id": cap.id, "error": str(e)})
    
    db.commit()
    
    # Clear cache
    capability_embedding_cache.clear()
    
    return {
        "success": True,
        "total_capabilities": len(capabilities),
        "synced": synced,
        "errors": errors
    }

@router.post("/admin/migrate-past-wins-pinecone")
async def migrate_past_wins_pinecone(db: Session = Depends(get_db)):
    """
    Admin endpoint: Add pinecone_id column to past_wins table
    Run this once after deploying the updated code
    """
    try:
        from sqlalchemy import text
        
        # Check if column already exists
        check_query = text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'past_wins' 
            AND column_name = 'pinecone_id';
        """)
        
        result = db.execute(check_query).fetchone()
        
        if result:
            return {
                "success": True,
                "message": "✅ Column 'pinecone_id' already exists",
                "already_migrated": True
            }
        
        logger.info("🚀 Running migration: Adding pinecone_id to past_wins")
        
        # Add column
        db.execute(text("ALTER TABLE past_wins ADD COLUMN pinecone_id VARCHAR(100);"))
        db.commit()
        
        # Create index
        db.execute(text("CREATE INDEX idx_past_wins_pinecone_id ON past_wins(pinecone_id);"))
        db.commit()
        
        logger.info("✅ Migration completed!")
        
        return {
            "success": True,
            "message": "✅ Migration completed successfully!"
        }
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/embed-existing-past-wins")
async def embed_existing_past_wins(db: Session = Depends(get_db)):
    """
    Admin endpoint: Embed all existing past wins that don't have pinecone_id
    """
    try:
        from app.services.past_win_store_pinecone import get_past_win_store
        
        llm_service = get_llm_service()
        win_store = get_past_win_store()
        
        # Get all past wins without pinecone_id
        past_wins = db.query(PastWin).filter(
            PastWin.pinecone_id == None
        ).all()
        
        if not past_wins:
            return {
                "success": True,
                "message": "✅ All past wins already embedded",
                "migrated": 0
            }
        
        logger.info(f"Found {len(past_wins)} past wins to embed")
        
        migrated = 0
        errors = []
        
        for win in past_wins:
            try:
                logger.info(f"Embedding past win {win.id}: {win.contract_title[:50]}...")
                
                # Generate embedding and store in Pinecone
                pinecone_id = await win_store.add_past_win(win, llm_service)
                
                # Update database
                win.pinecone_id = pinecone_id
                db.flush()
                
                logger.info(f"✅ Success! Pinecone ID: {pinecone_id}")
                migrated += 1
                
            except Exception as e:
                error_msg = f"Failed win {win.id}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Commit all changes
        db.commit()
        
        return {
            "success": True,
            "migrated": migrated,
            "total": len(past_wins),
            "errors": errors if errors else None,
            "message": f"✅ Embedded {migrated}/{len(past_wins)} past wins"
        }
        
    except Exception as e:
        logger.error(f"Data migration failed: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/capabilities/extract-from-url", dependencies=[Depends(require_entitlement("capability_management"))])
async def extract_capabilities_from_url(
    company_url: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Extract capabilities from URL for review (doesn't save yet)"""
    from app.services.web_scraper import WebScraperService
    
    scraper = WebScraperService()
    llm_service = get_llm_service()
    
    # Scrape
    scrape_result = await scraper.scrape_company_website(company_url)
    if not scrape_result["success"]:
        raise HTTPException(400, detail="Failed to scrape website")
    
    # Extract capabilities
    capabilities = await llm_service.extract_capabilities(
        scrape_result["capabilities_text"]
    )
    
    return {
        "success": True,
        "capabilities": capabilities,
        "company_name": scrape_result["company_name"],
        "pages_scraped": scrape_result["pages_scraped"]
    }

@router.post("/admin/refresh-match-cache")
async def refresh_match_cache(
    firm_id: str = None,
    current_user: User = Depends(get_current_active_user)
):
    """Manually refresh contract match cache (sync, not background)"""
    from app.services.match_cache_service import MatchCacheService
    
    try:
        service = MatchCacheService()
        
        if firm_id:
            service.run_cache_update(firm_ids=[firm_id])
            return {"success": True, "message": f"Cache refreshed for {firm_id}"}
        else:
            # Refresh for current user's firm
            service.run_cache_update(firm_ids=[current_user.firm_id])
            return {"success": True, "message": f"Cache refreshed for {current_user.firm_id}"}
            
    except Exception as e:
        logger.error(f"Cache refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

class PlanUpdate(BaseModel):
    plan: str  # "starter" | "pro"

@router.post("/admin/firms/{firm_id}/plan", tags=["Admin"])
async def admin_set_plan(
    firm_id: str,
    payload: PlanUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Admin-only: flip firm plan between starter/pro for testing."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    if payload.plan not in ("starter", "pro"):
        raise HTTPException(status_code=400, detail="Invalid plan")

    sub = db.query(FirmSubscription).filter(FirmSubscription.firm_id == firm_id).first()
    if not sub:
        sub = FirmSubscription(firm_id=firm_id, plan=payload.plan)
        db.add(sub)
    else:
        sub.plan = payload.plan

    db.commit()
    return {"success": True, "firm_id": firm_id, "plan": payload.plan}
