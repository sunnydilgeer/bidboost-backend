from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
import stripe
import logging
from datetime import datetime

from app.core.config import settings
from app.core.auth import get_current_active_user, User
from app.database import get_db
from app.models.subscription import FirmSubscription

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/api/billing", tags=["Billing"])


# ==================== CREATE CHECKOUT SESSION ====================
@router.post("/create-checkout-session")
async def create_checkout_session(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session for Pro plan upgrade."""
    
    # Get or create subscription record
    subscription = db.query(FirmSubscription).filter(
        FirmSubscription.firm_id == current_user.firm_id
    ).first()
    
    if not subscription:
        subscription = FirmSubscription(firm_id=current_user.firm_id, plan="starter")
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    # Check if already Pro
    if subscription.plan == "pro":
        raise HTTPException(status_code=400, detail="Already on Pro plan")
    
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
                'price': settings.STRIPE_PRO_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/billing",
            metadata={
                "firm_id": current_user.firm_id,
                "user_email": current_user.email
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
        subscription = FirmSubscription(firm_id=current_user.firm_id, plan="starter")
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    
    return {
        "plan": subscription.plan,
        "plan_started_at": subscription.plan_started_at,
        "plan_expires_at": subscription.plan_expires_at,
        "stripe_customer_id": subscription.stripe_customer_id,
        "stripe_subscription_id": subscription.stripe_subscription_id
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
        
        # Upgrade to Pro
        subscription = db.query(FirmSubscription).filter(
            FirmSubscription.firm_id == firm_id
        ).first()
        
        if subscription:
            subscription.plan = 'pro'
            subscription.stripe_subscription_id = session.get('subscription')
            subscription.plan_started_at = datetime.utcnow()
            subscription.plan_expires_at = None
            db.commit()
            logger.info(f"✅ Upgraded {firm_id} to Pro via checkout.session.completed")
        else:
            logger.error(f"Subscription not found for firm_id: {firm_id}")
    
    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        
        if subscription_id:
            # Find subscription by stripe_subscription_id
            subscription = db.query(FirmSubscription).filter(
                FirmSubscription.stripe_subscription_id == subscription_id
            ).first()
            
            if subscription:
                subscription.plan = 'pro'
                subscription.plan_expires_at = None
                db.commit()
                logger.info(f"✅ Confirmed Pro for {subscription.firm_id} via invoice.paid")
    
    elif event['type'] == 'customer.subscription.deleted':
        stripe_subscription = event['data']['object']
        subscription_id = stripe_subscription['id']
        
        # Downgrade to Starter
        subscription = db.query(FirmSubscription).filter(
            FirmSubscription.stripe_subscription_id == subscription_id
        ).first()
        
        if subscription:
            subscription.plan = 'starter'
            subscription.plan_expires_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ Downgraded {subscription.firm_id} to Starter via subscription.deleted")
    
    return {"received": True}