"""
SAM.gov Direct Link Resolver
Fetches UUID-based direct links on-demand (lazy lookup)

Instead of bulk-fetching 24k UUIDs (rate limited), this fetches
the direct SAM.gov link only when a user actually clicks "View on SAM.gov".

Usage:
    Add this router to your FastAPI app:
    
    from sam_link_resolver import router as sam_link_router
    app.include_router(sam_link_router, prefix="/api")
"""

import os
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(tags=["SAM.gov Links"])

# Configuration
SAM_API_KEY = os.getenv("SAM_API_KEY")
SAM_API_BASE = "https://api.sam.gov/opportunities/v2/search"

# Simple in-memory cache (TTL: 24 hours)
# In production, you might want Redis or cache in Pinecone metadata
_link_cache: dict[str, tuple[str, datetime]] = {}
CACHE_TTL_HOURS = 24


class SAMLinkResponse(BaseModel):
    notice_id: str
    url: str
    cached: bool = False


class SAMLinkError(BaseModel):
    notice_id: str
    error: str
    fallback_url: str


def get_cached_link(notice_id: str) -> Optional[str]:
    """Get link from cache if not expired."""
    if notice_id in _link_cache:
        url, cached_at = _link_cache[notice_id]
        if datetime.now() - cached_at < timedelta(hours=CACHE_TTL_HOURS):
            return url
        else:
            # Expired, remove from cache
            del _link_cache[notice_id]
    return None


def cache_link(notice_id: str, url: str):
    """Store link in cache."""
    _link_cache[notice_id] = (url, datetime.now())


def get_google_fallback(notice_id: str) -> str:
    """Generate Google search fallback URL."""
    return f"https://www.google.com/search?q=site:sam.gov+%22{notice_id}%22"


@router.get(
    "/contracts/{notice_id}/sam-link",
    response_model=SAMLinkResponse,
    responses={
        200: {"description": "Direct SAM.gov link"},
        404: {"description": "Contract not found, fallback URL provided"},
        503: {"description": "SAM.gov API unavailable, fallback URL provided"},
    }
)
async def get_sam_link(notice_id: str):
    """
    Get direct SAM.gov link for a contract.
    
    Makes a single API call to SAM.gov to fetch the UUID-based direct link.
    Results are cached for 24 hours to minimize API calls.
    
    If the API fails, returns a Google search fallback URL.
    """
    
    # Check cache first
    cached_url = get_cached_link(notice_id)
    if cached_url:
        return SAMLinkResponse(
            notice_id=notice_id,
            url=cached_url,
            cached=True
        )
    
    # Validate API key
    if not SAM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={
                "notice_id": notice_id,
                "error": "SAM_API_KEY not configured",
                "fallback_url": get_google_fallback(notice_id)
            }
        )
    
    # Query SAM.gov API
    try:
        params = {
            "api_key": SAM_API_KEY,
            "solnum": notice_id,  # Search by solicitation number
            "limit": 1,
        }
        
        response = requests.get(SAM_API_BASE, params=params, timeout=10)
        
        if response.status_code == 429:
            # Rate limited - return fallback
            raise HTTPException(
                status_code=503,
                detail={
                    "notice_id": notice_id,
                    "error": "SAM.gov rate limit exceeded",
                    "fallback_url": get_google_fallback(notice_id)
                }
            )
        
        response.raise_for_status()
        data = response.json()
        
        opportunities = data.get("opportunitiesData", [])
        
        if not opportunities:
            # Not found - return fallback
            raise HTTPException(
                status_code=404,
                detail={
                    "notice_id": notice_id,
                    "error": "Contract not found in SAM.gov",
                    "fallback_url": get_google_fallback(notice_id)
                }
            )
        
        # Get the direct link (uiLink contains the UUID)
        opp = opportunities[0]
        ui_link = opp.get("uiLink", "")
        
        if not ui_link:
            # No uiLink in response - construct fallback
            raise HTTPException(
                status_code=404,
                detail={
                    "notice_id": notice_id,
                    "error": "No direct link available",
                    "fallback_url": get_google_fallback(notice_id)
                }
            )
        
        # Cache the result
        cache_link(notice_id, ui_link)
        
        return SAMLinkResponse(
            notice_id=notice_id,
            url=ui_link,
            cached=False
        )
        
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=503,
            detail={
                "notice_id": notice_id,
                "error": "SAM.gov API timeout",
                "fallback_url": get_google_fallback(notice_id)
            }
        )
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=503,
            detail={
                "notice_id": notice_id,
                "error": f"SAM.gov API error: {str(e)}",
                "fallback_url": get_google_fallback(notice_id)
            }
        )


@router.get("/contracts/sam-link/cache-stats")
async def get_cache_stats():
    """Get cache statistics (for debugging)."""
    now = datetime.now()
    valid_count = sum(
        1 for _, (_, cached_at) in _link_cache.items()
        if now - cached_at < timedelta(hours=CACHE_TTL_HOURS)
    )
    return {
        "total_cached": len(_link_cache),
        "valid_entries": valid_count,
        "cache_ttl_hours": CACHE_TTL_HOURS
    }