"""
Pre-signup lead capture for quickstart email reports
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import logging

from app.database import get_db
from app.models.lead import PreSignupLead
from app.services.email_service import email_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["Leads"])

# ========== REQUEST/RESPONSE MODELS ==========

class PreSignupLeadRequest(BaseModel):
    """Request to capture pre-signup lead"""
    email: EmailStr = Field(..., description="User's email address")
    website_url: str = Field(..., description="Company website that was analyzed")
    quickstart_id: str = Field(..., description="Quickstart session ID from analysis")
    source: str = Field(default="quickstart_report", description="Lead source")
    quickstart_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Summary data from quickstart (company_name, total_matches, etc.)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "website_url": "https://acmedefense.com",
                "quickstart_id": "qs_abc123",
                "source": "quickstart_report",
                "quickstart_summary": {
                    "company_name": "Acme Defense",
                    "total_matches": 12,
                    "pages_scraped": 5,
                    "average_match_score": 73
                }
            }
        }


class PreSignupLeadResponse(BaseModel):
    """Response after lead capture"""
    success: bool
    message: str
    email_sent: bool


# ========== RATE LIMITING HELPER ==========

def check_rate_limit(email: str, ip: str, db: Session) -> bool:
    """
    Check if email/IP has exceeded rate limit (5 per hour)
    Returns True if within limit, False if exceeded
    """
    from datetime import datetime, timedelta
    
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    # Count recent submissions from this email
    email_count = db.query(PreSignupLead).filter(
        PreSignupLead.email == email,
        PreSignupLead.created_at >= one_hour_ago
    ).count()
    
    # Count recent submissions from this IP
    ip_count = db.query(PreSignupLead).filter(
        PreSignupLead.ip_address == ip,
        PreSignupLead.created_at >= one_hour_ago
    ).count()
    
    return email_count < 5 and ip_count < 5


# ========== ENDPOINT ==========

@router.post("/pre-signup", response_model=PreSignupLeadResponse)
async def capture_pre_signup_lead(
    request_data: PreSignupLeadRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Capture pre-signup lead and send quickstart report email.
    
    This endpoint:
    1. Validates email format
    2. Checks rate limits (5 per hour per email/IP)
    3. Stores lead in database
    4. Sends HTML email with quickstart summary
    
    Rate limit: 5 requests per hour per email or IP address
    """
    try:
        logger.info(f"📧 Pre-signup lead capture: {request_data.email}")
        
        # Get IP address for rate limiting
        client_ip = request.client.host if request.client else "unknown"
        
        # STEP 1: Check rate limit
        if not check_rate_limit(request_data.email, client_ip, db):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again in an hour."
            )
        
        # STEP 2: Check if email already exists (optional: prevent duplicates)
        existing_lead = db.query(PreSignupLead).filter(
            PreSignupLead.email == request_data.email,
            PreSignupLead.quickstart_id == request_data.quickstart_id
        ).first()
        
        if existing_lead:
            logger.info(f"Duplicate lead submission: {request_data.email}")
            return PreSignupLeadResponse(
                success=True,
                message="Report already sent to this email",
                email_sent=False
            )
        
        # STEP 3: Store lead in database
        new_lead = PreSignupLead(
            email=request_data.email,
            website_url=request_data.website_url,
            quickstart_id=request_data.quickstart_id,
            source=request_data.source,
            quickstart_summary=request_data.quickstart_summary,
            ip_address=client_ip
        )
        
        db.add(new_lead)
        db.commit()
        
        logger.info(f"✅ Lead stored: {request_data.email}")
        
        # STEP 4: Send email report
        email_sent = await send_quickstart_report_email(
            email=request_data.email,
            quickstart_data=request_data.quickstart_summary,
            website_url=request_data.website_url
        )
        
        if not email_sent:
            logger.warning(f"⚠️ Email send failed for {request_data.email}")
        
        return PreSignupLeadResponse(
            success=True,
            message="Report sent successfully" if email_sent else "Lead captured but email failed",
            email_sent=email_sent
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Pre-signup lead capture failed: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process lead: {str(e)}"
        )


# ========== EMAIL HELPER ==========

async def send_quickstart_report_email(
    email: str,
    quickstart_data: Optional[Dict[str, Any]],
    website_url: str
) -> bool:
    """
    Send HTML email with quickstart report.
    
    This uses the existing email_service but adds a new method.
    """
    try:
        # Extract data from quickstart summary
        company_name = quickstart_data.get("company_name", "Your Company") if quickstart_data else "Your Company"
        total_matches = quickstart_data.get("total_matches", 0) if quickstart_data else 0
        pages_scraped = quickstart_data.get("pages_scraped", 0) if quickstart_data else 0
        capabilities_preview = quickstart_data.get("capabilities_preview", "") if quickstart_data else ""
        contracts = quickstart_data.get("top_contracts", []) if quickstart_data else []
        
        # Use email service to send
        success = email_service.send_quickstart_report(
            to_email=email,
            company_name=company_name,
            website_url=website_url,
            capabilities_preview=capabilities_preview,
            pages_scraped=pages_scraped,
            total_matches=total_matches,
            contracts=contracts
        )
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send quickstart email to {email}: {e}")
        return False