from typing import Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.models.subscription import FirmSubscription

# -----------------------------
# Founder pricing config
# -----------------------------
FOUNDER_LIMIT = 30  # first 30 firms get founder eligibility

# ✅ Trial entitlements (full Pro features)
TRIAL: Dict[str, Any] = {
    "search_contracts": True,
    "save_contracts": True,
    "saved_contract_limit": None,  # Unlimited during trial
    "capability_management": True,
    "capability_wizard": True,  # AI feature
    "dashboard_kpis": True,
    "deadline_prioritization": True,
    "pipeline_tracking": True,
    "opportunity_notes": True,
    "positioning_insights": True,
    "priority_alerts": True,
}

# ✅ Starter entitlements (kept for backward compatibility)
STARTER: Dict[str, Any] = {
    "search_contracts": True,
    "save_contracts": True,
    "saved_contract_limit": 50,
    "capability_management": True,
    "capability_wizard": False,
    "dashboard_kpis": False,
    "deadline_prioritization": False,
    "pipeline_tracking": False,
    "opportunity_notes": False,
    "positioning_insights": False,
    "priority_alerts": False,
}

PRO: Dict[str, Any] = {
    "search_contracts": True,
    "save_contracts": True,
    "saved_contract_limit": None,  # Unlimited
    "capability_management": True,
    "capability_wizard": True,  # AI feature
    "dashboard_kpis": True,
    "deadline_prioritization": True,
    "pipeline_tracking": True,
    "opportunity_notes": True,
    "positioning_insights": True,
    "priority_alerts": True,
}

# ✅ Free entitlements (post-trial limited access)
FREE: Dict[str, Any] = {
    "search_contracts": False,
    "save_contracts": False,
    "saved_contract_limit": 0,
    "capability_management": False,
    "capability_wizard": False,
    "dashboard_kpis": False,
    "deadline_prioritization": False,
    "pipeline_tracking": False,
    "opportunity_notes": False,
    "positioning_insights": False,
    "priority_alerts": False,
}

UPGRADE_MESSAGES: Dict[str, str] = {
    "search_contracts": "Upgrade to Starter to search contracts.",
    "save_contracts": "Upgrade to Starter to save contracts.",
    "dashboard_kpis": "Upgrade to Pro to unlock dashboard insights & KPIs.",
    "deadline_prioritization": "Upgrade to Pro to unlock deadline prioritization.",
    "pipeline_tracking": "Upgrade to Pro to manage your contract pipeline.",
    "opportunity_notes": "Upgrade to Pro to add notes on opportunities.",
    "capability_management": "Upgrade to Starter to manage capabilities.",
    "capability_wizard": "Upgrade to Pro to unlock the AI Capability Wizard.",
    "positioning_insights": "Upgrade to Pro to unlock Federal Positioning Insights.",
    "priority_alerts": "Upgrade to Pro for priority-aware alerts and digests.",
    "saved_contract_limit": "Upgrade to Pro for unlimited saved contracts.",
}


def _should_grant_founder(db: Session) -> bool:
    """
    Returns True if founder slots remain.
    NOTE: This is a simple beta-safe implementation (not race-condition hardened).
    """
    founder_count = (
        db.query(FirmSubscription)
        .filter(FirmSubscription.founder_eligible == True)  # noqa: E712
        .count()
    )
    return founder_count < FOUNDER_LIMIT


def get_or_create_subscription(db: Session, firm_id: str) -> FirmSubscription:
    """Get or create subscription for a firm."""
    sub = db.query(FirmSubscription).filter(FirmSubscription.firm_id == firm_id).first()
    if sub:
        return sub

    # ✅ Start all users on 14-day trial
    now = datetime.now(timezone.utc)
    sub = FirmSubscription(
        firm_id=firm_id,
        plan="trial",
        plan_started_at=now,
        plan_expires_at=now + timedelta(days=14),
    )

    # ✅ Founder pricing: grant eligibility for first 30 firms (unless later revoked)
    # This sets the persistent flag used by select_price_id_for_plan().
    if _should_grant_founder(db):
        sub.founder_eligible = True

    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_effective_plan(sub: FirmSubscription) -> str:
    """
    Return the *effective* plan considering trial expiry.
    - trial (not expired) -> trial
    - trial (expired) -> free
    - otherwise -> sub.plan (starter/pro/free)
    """
    if sub.plan == "trial" and sub.plan_expires_at:
        if datetime.now(timezone.utc) > sub.plan_expires_at:
            return "free"
    return sub.plan


def get_entitlements_for_plan(plan: str) -> Dict[str, Any]:
    """Map a plan to its entitlement flags (no billing state)."""
    if plan == "trial":
        return TRIAL
    if plan == "pro":
        return PRO
    if plan == "starter":
        return STARTER
    if plan == "free":
        return FREE
    # Fallback: treat unknown as starter
    return STARTER


def get_entitlements(db: Session, firm_id: str) -> Dict[str, Any]:
    """
    Get entitlement flags for a firm.
    IMPORTANT: This returns *entitlements only* (no 'plan' key).
    Billing state ('plan') should be sourced from subscription/session.
    """
    sub = get_or_create_subscription(db, firm_id)
    effective_plan = get_effective_plan(sub)
    return get_entitlements_for_plan(effective_plan)