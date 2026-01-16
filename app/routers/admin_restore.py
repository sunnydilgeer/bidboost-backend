from fastapi import APIRouter, HTTPException
import asyncio
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.company import CompanyProfile
from app.services.capability_store_pinecone import get_capability_store
from app.services.llm import get_llm_service

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.post("/restore-capabilities")
async def restore_capabilities_endpoint():
    """TEMPORARY: Restore capabilities to Pinecone"""
    db: Session = SessionLocal()
    capability_store = get_capability_store()
    llm_service = get_llm_service()
    
    try:
        companies = db.query(CompanyProfile).all()
        
        results = {
            "status": "success",
            "companies_total": len(companies),
            "companies_processed": 0,
            "capabilities_restored": 0,
            "companies_skipped": 0,
            "errors": [],
            "details": []
        }
        
        for company in companies:
            if not company.capabilities:
                results["companies_skipped"] += 1
                results["details"].append({
                    "company": company.company_name,
                    "status": "skipped",
                    "reason": "no capabilities"
                })
                continue
                
            try:
                vector_ids = await capability_store.add_capabilities_batch(
                    capabilities=company.capabilities,
                    llm_service=llm_service
                )
                
                for capability, vector_id in zip(company.capabilities, vector_ids):
                    capability.qdrant_id = vector_id
                
                db.commit()
                
                results["companies_processed"] += 1
                results["capabilities_restored"] += len(vector_ids)
                results["details"].append({
                    "company": company.company_name,
                    "firm_id": company.firm_id,
                    "status": "success",
                    "capabilities_restored": len(vector_ids)
                })
                
            except Exception as e:
                error_msg = f"{company.company_name}: {str(e)}"
                results["errors"].append(error_msg)
                results["details"].append({
                    "company": company.company_name,
                    "status": "error",
                    "error": str(e)
                })
                db.rollback()
        
        stats = capability_store.get_namespace_stats()
        results["pinecone_total_vectors"] = stats["total_capabilities"]
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@router.post("/rebuild-cache")
async def rebuild_cache_endpoint():
    """TEMPORARY: Rebuild contract match cache"""
    from app.services.match_cache_service import MatchCacheService
    
    try:
        service = MatchCacheService()
        result = service.run_cache_update()
        return {
            "status": "success",
            "message": "Cache rebuilt successfully",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/verify-capabilities")
async def verify_capabilities_endpoint():
    """TEMPORARY: Verify capability restoration"""
    db: Session = SessionLocal()
    capability_store = get_capability_store()
    
    try:
        companies = db.query(CompanyProfile).all()
        
        results = {
            "status": "success",
            "companies_total": len(companies),
            "capabilities_total": 0,
            "capabilities_with_vector_id": 0,
            "capabilities_verified_in_pinecone": 0,
            "missing_in_pinecone": [],
            "details": []
        }
        
        for company in companies:
            if not company.capabilities:
                continue
            
            company_result = {
                "company": company.company_name,
                "capabilities_total": len(company.capabilities),
                "capabilities_with_vector_id": 0,
                "capabilities_verified": 0
            }
            
            results["capabilities_total"] += len(company.capabilities)
            
            for cap in company.capabilities:
                if cap.qdrant_id:
                    results["capabilities_with_vector_id"] += 1
                    company_result["capabilities_with_vector_id"] += 1
                    
                    vector_data = capability_store.get_capability(cap.qdrant_id)
                    if vector_data:
                        results["capabilities_verified_in_pinecone"] += 1
                        company_result["capabilities_verified"] += 1
                    else:
                        results["missing_in_pinecone"].append({
                            "company": company.company_name,
                            "capability": cap.capability_text[:50] + "...",
                            "vector_id": cap.qdrant_id
                        })
            
            results["details"].append(company_result)
        
        stats = capability_store.get_namespace_stats()
        results["pinecone_total_vectors"] = stats["total_capabilities"]
        
        if (results["capabilities_with_vector_id"] == results["capabilities_total"] 
            and not results["missing_in_pinecone"] 
            and results["capabilities_total"] > 0):
            results["verdict"] = "✅ ALL VERIFIED"
        else:
            results["verdict"] = "⚠️ ISSUES FOUND"
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
