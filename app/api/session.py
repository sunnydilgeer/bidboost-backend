from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.auth import get_current_active_user, User
from app.core.entitlements import get_entitlements
from app.database import get_db
from app.models import CompanyCapability, CompanyProfile
from app.core.entitlements import get_or_create_subscription  # ✅ NEW import

router = APIRouter(tags=["Session"])

@router.get("/session")
async def get_session(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get current user session with subscription info.
    This is the single source of truth for user state.
    """
    entitlements = get_entitlements(db, current_user.firm_id)
    
    # ✅ NEW: Get subscription to include expiration date
    subscription = get_or_create_subscription(db, current_user.firm_id)
    
    # Calculate profile completion based on capabilities
    capability_count = db.query(CompanyCapability).join(
        CompanyProfile, CompanyCapability.company_id == CompanyProfile.id
    ).filter(
        CompanyProfile.firm_id == current_user.firm_id
    ).count()
    
    # Profile completion: 5 capabilities = 100%, each cap = 20%
    profile_completion = min(100, capability_count * 20)
    
    return {
        "user": {
            "id": current_user.user_id,
            "email": current_user.email,
            "firm_id": current_user.firm_id,
            "full_name": current_user.full_name,
            "profile_completion": profile_completion,
            "plan_expires_at": subscription.plan_expires_at.isoformat() if subscription.plan_expires_at else None  # ✅ NEW
        },
        "subscription": {
            "plan": entitlements.get("plan", "trial"),
            "entitlements": entitlements
        }
    }