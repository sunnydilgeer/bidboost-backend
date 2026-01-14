from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import stripe
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.auth import get_current_active_user, User
from app.core.billing_pricing import select_price_id_for_plan, map_price_id_to_plan_and_billing
from app.database import get_db
from app.models.subscription import FirmSubscription

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/api/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan_type: str  # "starter" or "pro" (never "founder" - that's server-side)


# ==================== CREATE CHECKOUT SESSION ====================
@router.post("/create-checkout-session")
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session for plan upgrade."""
    
    # Validate plan type
    if request.plan_type not in ("starter", "pro"):
        raise HTTPException(status_code=400, detail="Invalid plan type. Must be 'starter' or 'pro'.")
    
    # Get or create subscription record
    subscription = db.query(FirmSubscription).filter(
        FirmSubscription.firm_id == current_user.firm_id
    ).first()
    
    if not subscription:
        subscription = FirmSubscription(firm_id=current_user.firm_id, plan="trial")
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    # Check if already on requested plan
    if subscription.plan == request.plan_type:
        raise HTTPException(status_code=400, detail=f"Already on {request.plan_type.capitalize()} plan")
    
    # ✅ FOUNDER PRICING: Server-side price selection
    price_id, billing_price_label = select_price_id_for_plan(subscription, request.plan_type)
    
    # Get or create Stripe customer
    if subscription.stripe_customer_id:
        customer_id = subscription.stripe_customer_id
    else:
        customer = stripe.Customer.create(
            email=current_user.email,
            metadata={"firm_id": current_user.firm_id}
        )
        subscription.stripe_customer_id = customer.id
        db.commit()
        customer_id = customer.id
    
    # Create checkout session
    try:
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/billing",
            metadata={
                "firm_id": current_user.firm_id,
                "user_email": current_user.email,
                "plan_type": request.plan_type,
                "billing_price_label": billing_price_label,  # ✅ Track for debugging
            }
        )
        
        return {"checkout_url": checkout_session.url}
        
    except Exception as e:
        logger.exception(f"Failed to create checkout session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


# ==================== GET CURRENT SUBSCRIPTION ====================
@router.get("/subscription")
async def get_subscription(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get current subscription details."""
    subscription = db.query(FirmSubscription).filter(
        FirmSubscription.firm_id == current_user.firm_id
    ).first()
    
    if not subscription:
        subscription = FirmSubscription(firm_id=current_user.firm_id, plan="trial")
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    return {
        "plan": subscription.plan,
        "plan_started_at": subscription.plan_started_at,
        "plan_expires_at": subscription.plan_expires_at,
        "stripe_customer_id": subscription.stripe_customer_id,
        "stripe_subscription_id": subscription.stripe_subscription_id,
        "billing_price": subscription.billing_price,
    }


# ==================== STRIPE WEBHOOK ====================
@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        logger.error("Missing stripe-signature header")
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        logger.exception(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")

    logger.info(f"✅ Stripe webhook received: {event['type']} id={event['id']}")

    # ==================== HANDLE EVENTS ====================
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        firm_id = session['metadata'].get('firm_id')
        
        if not firm_id:
            logger.error(f"No firm_id in session metadata: {session['id']}")
            return {"received": True}
        
        subscription_id = session.get('subscription')
        if subscription_id:
            stripe_subscription = stripe.Subscription.retrieve(subscription_id)
            price_id = stripe_subscription["items"]["data"][0]["price"]["id"]
            
            # ✅ FOUNDER PRICING: Map price to plan + billing_price
            mapped = map_price_id_to_plan_and_billing(price_id)
            if not mapped:
                logger.error(f"Unknown price_id: {price_id}")
                return {"received": True}
            
            plan, billing_price = mapped
            
            subscription = db.query(FirmSubscription).filter(
                FirmSubscription.firm_id == firm_id
            ).first()
            
            if subscription:
                subscription.plan = plan
                subscription.billing_price = billing_price  # ✅ Track actual price
                subscription.stripe_subscription_id = subscription_id
                subscription.plan_started_at = datetime.now(timezone.utc)
                subscription.plan_expires_at = None
                db.commit()
                logger.info(f"✅ Upgraded {firm_id} to {plan} (billing: {billing_price}) via checkout.session.completed")
            else:
                logger.error(f"Subscription not found for firm_id: {firm_id}")
    
    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        
        if subscription_id:
            subscription = db.query(FirmSubscription).filter(
                FirmSubscription.stripe_subscription_id == subscription_id
            ).first()
            
            if subscription:
                subscription.plan_expires_at = None
                db.commit()
                logger.info(f"✅ Confirmed {subscription.plan} (billing: {subscription.billing_price}) for {subscription.firm_id} via invoice.paid")
    
    elif event['type'] == 'customer.subscription.updated':
        stripe_subscription = event['data']['object']
        customer_id = stripe_subscription['customer']
        
        subscription = db.query(FirmSubscription).filter(
            FirmSubscription.stripe_customer_id == customer_id
        ).first()
        
        if subscription:
            price_id = stripe_subscription["items"]["data"][0]["price"]["id"]
            
            # ✅ FOUNDER PRICING: Map price to plan + billing_price
            mapped = map_price_id_to_plan_and_billing(price_id)
            if not mapped:
                logger.error(f"Unknown price_id in subscription.updated: {price_id}")
                return {"received": True}
            
            plan, billing_price = mapped
            
            subscription.plan = plan
            subscription.billing_price = billing_price
            subscription.plan_expires_at = None
            db.commit()
            logger.info(f"✅ Updated {subscription.firm_id} to {plan} (billing: {billing_price}) via subscription.updated")
    
    elif event['type'] == 'customer.subscription.deleted':
        stripe_subscription = event['data']['object']
        subscription_id = stripe_subscription['id']
        
        subscription = db.query(FirmSubscription).filter(
            FirmSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if subscription:
            now = datetime.now(timezone.utc)
            
            # ✅ FOUNDER PRICING: Revoke founder status on churn
            if subscription.billing_price == "pro_founder":
                subscription.founder_revoked_at = now
                logger.info(f"⚠️ Revoked founder pricing for {subscription.firm_id} (churned)")
            
            subscription.plan = 'starter'
            subscription.billing_price = 'starter'
            subscription.plan_expires_at = now
            db.commit()
            logger.info(f"✅ Downgraded {subscription.firm_id} to Starter via subscription.deleted")
    
    return {"received": True}