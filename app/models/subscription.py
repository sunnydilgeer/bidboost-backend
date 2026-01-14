from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base


class FirmSubscription(Base):
    __tablename__ = "firm_subscriptions"

    firm_id = Column(String(255), primary_key=True, index=True)
    plan = Column(String(50), nullable=False, default="trial")
    plan_started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    plan_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Stripe integration
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    
    # Founder pricing
    founder_eligible = Column(Boolean, default=False, nullable=False)
    founder_revoked_at = Column(DateTime(timezone=True), nullable=True)
    billing_price = Column(String(50), nullable=True)  # trial/starter/pro/pro_founder