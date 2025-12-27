from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base

class FirmSubscription(Base):
    __tablename__ = "firm_subscriptions"

    firm_id = Column(String(255), primary_key=True, index=True)
    plan = Column(String(50), nullable=False, default="starter")
    plan_started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    plan_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ ADD THESE TWO COLUMNS
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)