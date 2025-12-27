from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.subscription import FirmSubscription

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
    sub = db.query(FirmSubscription).filter(FirmSubscription.firm_id == firm_id).first()
    if not sub:
        sub = FirmSubscription(firm_id=firm_id, plan="starter")
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub

def get_entitlements(db: Session, firm_id: str) -> Dict[str, Any]:
    sub = get_or_create_subscription(db, firm_id)
    base = PRO if sub.plan == "pro" else STARTER
    return {**base, "plan": sub.plan}