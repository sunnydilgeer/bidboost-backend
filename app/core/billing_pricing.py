"""
Founder pricing logic.

- Founders get Pro at discounted rate ($99 vs $149)
- Server-side enforcement: frontend only requests "starter" or "pro"
- Revocation on churn prevents cancel-and-return exploit
"""
from app.core.config import settings
from app.models.subscription import FirmSubscription


def select_price_id_for_plan(sub: FirmSubscription, plan_type: str) -> tuple[str, str]:
    """
    Select the appropriate Stripe price ID based on plan type and founder eligibility.
    
    Returns: (stripe_price_id, billing_price_label)
    - billing_price_label is what we store in DB (starter/pro/pro_founder)
    """
    if plan_type == "starter":
        return settings.STRIPE_STARTER_PRICE_ID, "starter"

    if plan_type == "pro":
        # Check founder eligibility (eligible + not revoked)
        if sub.founder_eligible and sub.founder_revoked_at is None:
            return settings.STRIPE_PRO_FOUNDER_PRICE_ID, "pro_founder"
        return settings.STRIPE_PRO_PRICE_ID, "pro"

    raise ValueError(f"Invalid plan_type: {plan_type}")


def map_price_id_to_plan_and_billing(price_id: str) -> tuple[str, str] | None:
    """
    Map a Stripe price ID back to (plan, billing_price).
    
    - plan: semantic tier (starter/pro) - used for entitlements
    - billing_price: actual price variant (starter/pro/pro_founder) - used for UI/tracking
    
    Returns None if price_id is unrecognized.
    """
    if price_id == settings.STRIPE_STARTER_PRICE_ID:
        return "starter", "starter"
    if price_id == settings.STRIPE_PRO_PRICE_ID:
        return "pro", "pro"
    if price_id == settings.STRIPE_PRO_FOUNDER_PRICE_ID:
        return "pro", "pro_founder"
    return None


def is_founder_pricing_active(sub: FirmSubscription) -> bool:
    """Check if subscription is currently on founder pricing."""
    return sub.billing_price == "pro_founder" and sub.plan == "pro"