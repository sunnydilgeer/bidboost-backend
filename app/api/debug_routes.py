"""
Minimal debug endpoints to test deployment
"""
from fastapi import APIRouter

debug_router = APIRouter(prefix="/api/debug", tags=["Debug"])

@debug_router.get("/test")
async def test_endpoint():
    """Simple test endpoint"""
    return {
        "status": "working",
        "message": "Debug router is deployed!",
        "version": "minimal-v1"
    }

@debug_router.get("/qdrant/status")
async def check_qdrant_status():
    """Check Qdrant - lazy import to avoid startup issues"""
    try:
        from app.services.vector_store import VectorStoreService
        
        vector_store = VectorStoreService()
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
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Qdrant status check failed: {str(e)}")
        return {
            "qdrant_connected": False,
            "error": str(e),
            "status": "❌ Qdrant connection failed"
        }