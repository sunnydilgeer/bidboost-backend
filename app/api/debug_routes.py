"""
Debug endpoints for diagnosing match scoring issues
Add to main.py with: app.include_router(debug_router)
"""

from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db
from sqlalchemy.orm import Session
from app.core.auth import User, get_current_active_user
from app.services.match_scoring import ContractMatchScorer
from app.services.vector_store import VectorStoreService
from app.models.contract import Contract
from app.models.company import CompanyProfile, CompanyCapability
from qdrant_client.models import Filter, FieldCondition, MatchValue
import numpy as np
import logging

logger = logging.getLogger(__name__)

debug_router = APIRouter(prefix="/api/debug", tags=["Debug"])

# Lazy initialization - only connects when called
def get_vector_store():
    """Get VectorStoreService instance - connects to Qdrant on first call"""
    return VectorStoreService()


@debug_router.get("/match/{contract_id}")
async def debug_match_scoring(
    contract_id: str,
    firm_id: str = "firm-suninho",  # Default for testing - change to your firm_id
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
            CompanyProfile.firm_id == firm_id
        ).first()
        
        if not profile:
            raise HTTPException(status_code=404, detail=f"Company profile not found for firm_id: {firm_id}")
        
        capabilities = db.query(CompanyCapability).filter(
            CompanyCapability.company_id == profile.id
        ).all()
        
        # 4. Run match scoring
        scorer = ContractMatchScorer(db, vector_store.client)
        match_result = scorer.score_contract(temp_contract, firm_id)
        
        # 5. Get detailed capability breakdown
        capability_details = []
        contract_vector_norm = 0.0
        
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
                        similarity = float(np.dot(contract_vector, cap_vector) / 
                                         (np.linalg.norm(contract_vector) * np.linalg.norm(cap_vector)))
                        
                        capability_details.append({
                            "id": cap.id,
                            "text": cap.capability_text,
                            "qdrant_id": cap.qdrant_id,
                            "similarity_score": round(similarity, 4),
                            "similarity_percentage": f"{similarity * 100:.1f}%",
                            "vector_norm": round(cap_vector_norm, 4),
                            "vector_dimensions": len(cap_vector)
                        })
                    else:
                        capability_details.append({
                            "id": cap.id,
                            "text": cap.capability_text,
                            "qdrant_id": cap.qdrant_id,
                            "error": "Vector not found in Qdrant"
                        })
                else:
                    capability_details.append({
                        "id": cap.id,
                        "text": cap.capability_text,
                        "qdrant_id": None,
                        "error": "Not synced to Qdrant"
                    })
        
        # Sort by similarity score
        capability_details.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        
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
            if cap_detail.get("similarity_score", 0) == 0.0:
                issues.append(f"⚠️ Capability '{cap_detail['text'][:50]}...' has 0% similarity")
        
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
                "embedding_norm": round(contract_vector_norm, 4)
            },
            "profile": {
                "firm_id": firm_id,
                "company_name": profile.company_name,
                "capabilities_count": len(capabilities),
                "past_wins_count": len(profile.past_wins) if profile.past_wins else 0,
                "has_preferences": profile.search_preference is not None
            },
            "match_scores": match_result if match_result else {
                "total_score": 0.0,
                "capability_score": 0.0,
                "past_win_score": 0.0,
                "preference_score": 0.0,
                "reason": "Contract filtered out by preferences"
            },
            "capability_breakdown": capability_details,
            "top_3_matches": capability_details[:3] if capability_details else [],
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

@debug_router.get("/test-deployment")
async def test_deployment():
    """Test endpoint to verify debug_routes.py is actually deployed"""
    return {"message": "Debug routes ARE working!", "timestamp": "2025-11-06-v2"}
