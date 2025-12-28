from typing import Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.models.subscription import FirmSubscription

# ✅ NEW: Trial entitlements (full Pro features)
TRIAL: Dict[str, Any] = {
    "saved_contract_limit": None,  # Unlimited during trial
    "dashboard_kpis": True,
    "deadline_prioritization": True,
    "pipeline_tracking": True,
    "opportunity_notes": True,
    "capability_management": True,
    "positioning_insights": True,
    "priority_alerts": True,
}

STARTER: Dict[str, Any] = {
    "saved_contract_limit": 50,
    "dashboard_kpis": False,
    "deadline_prioritization": False,
    "pipeline_tracking": False,
    "opportunity_notes": False,
    "capability_management": False,
    "positioning_insights": False,
    "priority_alerts": False,
}

PRO: Dict[str, Any] = {
    "saved_contract_limit": None,  # unlimited
    "dashboard_kpis": True,
    "deadline_prioritization": True,
    "pipeline_tracking": True,
    "opportunity_notes": True,
    "capability_management": True,
    "positioning_insights": True,
    "priority_alerts": True,
}

# ✅ NEW: Expired entitlements (everything locked)
EXPIRED: Dict[str, Any] = {
    "saved_contract_limit": 0,
    "dashboard_kpis": False,
    "deadline_prioritization": False,
    "pipeline_tracking": False,
    "opportunity_notes": False,
    "capability_management": False,
    "positioning_insights": False,
    "priority_alerts": False,
}

UPGRADE_MESSAGES: Dict[str, str] = {
    "dashboard_kpis": "Upgrade to Pro to unlock dashboard insights & KPIs.",
    "deadline_prioritization": "Upgrade to Pro to unlock deadline prioritization.",
    "pipeline_tracking": "Upgrade to Pro to manage your contract pipeline.",
    "opportunity_notes": "Upgrade to Pro to add notes on opportunities.",
    "capability_management": "Upgrade to Pro to manage and refine capabilities.",
    "positioning_insights": "Upgrade to Pro to unlock Federal Positioning Insights.",
    "priority_alerts": "Upgrade to Pro for priority-aware alerts and digests.",
    "saved_contract_limit": "Upgrade to Pro for unlimited saved contracts.",
}

def get_or_create_subscription(db: Session, firm_id: str) -> FirmSubscription:
    """Get or create subscription for a firm."""
    sub = db.query(FirmSubscription).filter(FirmSubscription.firm_id == firm_id).first()
    
    if not sub:
        # ✅ NEW: Start all users on 14-day trial
        now = datetime.utcnow()
        sub = FirmSubscription(
            firm_id=firm_id,
            plan="trial",  # Changed from "starter"
            plan_started_at=now,
            plan_expires_at=now + timedelta(days=14)  # 14-day trial
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    
    return sub

def get_entitlements(db: Session, firm_id: str) -> Dict[str, Any]:
    """Get entitlements for a firm based on their subscription plan."""
    sub = get_or_create_subscription(db, firm_id)
    
    # ✅ NEW: Check if trial expired
    if sub.plan == "trial" and sub.plan_expires_at:
        if datetime.utcnow() > sub.plan_expires_at:
            # Trial expired - lock everything
            return {**EXPIRED, "plan": "expired"}
    
    # Return entitlements based on plan
    if sub.plan == "trial":
        base = TRIAL
    elif sub.plan == "starter":
        base = STARTER
    elif sub.plan == "pro":
        base = PRO
    else:
        # Fallback to starter if unknown plan
        base = STARTER
    
    return {**base, "plan": sub.plan}