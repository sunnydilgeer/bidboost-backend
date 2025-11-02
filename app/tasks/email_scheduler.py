"""
Email Scheduler - Production Version
Integrated with your actual User and SavedContract models

Location: app/tasks/email_scheduler.py
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from typing import List, Dict
import logging

from app.services.email_service import email_service
from app.database import SessionLocal
from app.models import User
from app.models.company import SavedContract
from app.services.match_scoring import ContractMatchScorer
from app.services.vector_store import VectorStoreService
from app.services.contract_fetcher import ContractFetcherService
from app.services.llm import LLMService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.vector_store = VectorStoreService()
        self.setup_jobs()
    
    def setup_jobs(self):
        """Set up scheduled jobs."""
        # Daily contract sync at 7:00 AM (before emails)
        self.scheduler.add_job(
            func=self.sync_contracts_daily,
            trigger=CronTrigger(hour=7, minute=0),
            id='sync_contracts_daily',
            name='Sync contracts from UK Contracts Finder API',
            replace_existing=True
        )
        
        # Daily new contracts email at 8:00 AM
        self.scheduler.add_job(
            func=self.send_daily_contract_emails,
            trigger=CronTrigger(hour=8, minute=0),
            id='daily_contract_emails',
            name='Send daily new contract emails',
            replace_existing=True
        )
        
        # Daily deadline reminders at 9:00 AM
        self.scheduler.add_job(
            func=self.send_deadline_reminders,
            trigger=CronTrigger(hour=9, minute=0),
            id='deadline_reminders',
            name='Send deadline reminder emails',
            replace_existing=True
        )
        
        logger.info("✅ Email scheduler jobs configured (7am sync, 8am emails, 9am reminders)")
    
    def send_daily_contract_emails(self):
        """Send daily emails with new matching contracts."""
        logger.info("🚀 Starting daily contract email job")
        
        db = SessionLocal()
        try:
            # Get users with daily notifications enabled
            users = db.query(User).filter(
                User.email_notifications_enabled == True,
                User.notification_frequency == "daily",
                User.is_active == True
            ).all()
            
            logger.info(f"📧 Found {len(users)} users with daily notifications enabled")
            
            sent_count = 0
            for user in users:
                try:
                    # Calculate time range for new contracts
                    since_date = user.last_email_sent_at or datetime.utcnow() - timedelta(days=1)
                    
                    # Get new contracts matched to this user's profile
                    new_contracts = self._get_new_contracts_for_user(
                        db=db,
                        user=user,
                        since_date=since_date
                    )
                    
                    if len(new_contracts) > 0:
                        # Format contracts for email
                        formatted_contracts = [
                            {
                                "notice_id": c["notice_id"],
                                "title": c["title"],
                                "buyer_name": c["buyer_name"],
                                "value": self._format_value(c.get("value")),
                                "deadline": self._format_date(c.get("deadline")),
                                "match_score": int(c.get("match_score", 0) * 100) if c.get("match_score") else 0,
                                "match_reason": c.get("match_reason", "Matches your profile")
                            }
                            for c in new_contracts[:5]  # Top 5 only
                        ]
                        
                        # Send email
                        success = email_service.send_new_contracts_email(
                            to_email=user.email,
                            user_name=user.full_name,
                            contracts=formatted_contracts,
                            total_new_contracts=len(new_contracts)
                        )
                        
                        if success:
                            # Update last_email_sent_at
                            user.last_email_sent_at = datetime.utcnow()
                            db.commit()
                            sent_count += 1
                            logger.info(f"✅ Sent to {user.email} ({len(new_contracts)} contracts)")
                        else:
                            logger.error(f"❌ Failed to send to {user.email}")
                    else:
                        logger.info(f"⏭️  No new contracts for {user.email}")
                
                except Exception as e:
                    logger.error(f"❌ Error processing {user.email}: {e}")
                    db.rollback()
                    continue
            
            logger.info(f"✅ Daily email job completed: {sent_count}/{len(users)} emails sent")
        
        except Exception as e:
            logger.error(f"❌ Critical error in daily email job: {e}")
        finally:
            db.close()
    
    def send_deadline_reminders(self):
        """Send deadline reminder emails for saved contracts."""
        logger.info("🚀 Starting deadline reminder job")
        
        db = SessionLocal()
        try:
            today = datetime.utcnow().date()
            
            # Target dates for reminders (7, 3, 1 days before)
            target_dates = [
                today + timedelta(days=7),
                today + timedelta(days=3),
                today + timedelta(days=1)
            ]
            
            # Query saved contracts with approaching deadlines
            # Join with User to check notification preferences
            saved_contracts = db.query(SavedContract).join(
                User, SavedContract.user_email == User.email
            ).filter(
                SavedContract.status.in_(["interested", "bidding"]),
                User.email_notifications_enabled == True,
                User.is_active == True,
                SavedContract.deadline.isnot(None)
            ).all()
            
            # Filter for contracts with deadlines on target dates
            contracts_to_remind = [
                sc for sc in saved_contracts 
                if sc.deadline and sc.deadline.date() in target_dates
            ]
            
            logger.info(f"📅 Found {len(contracts_to_remind)} contracts with approaching deadlines")
            
            sent_count = 0
            for saved_contract in contracts_to_remind:
                try:
                    days_until = (saved_contract.deadline.date() - today).days
                    
                    # Only send for 7, 3, or 1 day intervals
                    if days_until not in [7, 3, 1]:
                        continue
                    
                    # Get user
                    user = db.query(User).filter(User.email == saved_contract.user_email).first()
                    if not user:
                        continue
                    
                    # Prepare contract data
                    contract_data = {
                        "notice_id": saved_contract.notice_id,
                        "title": saved_contract.contract_title,
                        "buyer_name": saved_contract.buyer_name,
                        "value": self._format_value(saved_contract.contract_value),
                        "deadline": self._format_date(saved_contract.deadline),
                        "status": saved_contract.status.title()
                    }
                    
                    # Send reminder
                    success = email_service.send_deadline_reminder_email(
                        to_email=user.email,
                        user_name=user.full_name,
                        contract=contract_data,
                        days_until_deadline=days_until
                    )
                    
                    if success:
                        sent_count += 1
                        logger.info(f"✅ Sent {days_until}d reminder to {user.email}")
                    else:
                        logger.error(f"❌ Failed to send reminder to {user.email}")
                
                except Exception as e:
                    logger.error(f"❌ Error processing contract {saved_contract.notice_id}: {e}")
                    continue
            
            logger.info(f"✅ Deadline reminder job completed: {sent_count} reminders sent")
        
        except Exception as e:
            logger.error(f"❌ Critical error in deadline reminder job: {e}")
        finally:
            db.close()
    
    def sync_contracts_daily(self):
        """Sync new contracts from UK Contracts Finder API every morning."""
        logger.info("🔄 Starting daily contract sync job")
        
        try:
            # Initialize contract fetcher service
            contract_service = ContractFetcherService()
            llm_service = LLMService()
            vector_store = VectorStoreService()
            
            # Fetch contracts from API (last 7 days to catch any missed ones)
            import asyncio
            contracts = asyncio.run(contract_service.fetch_contracts(limit=100, days_back=7))
            
            if contracts:
                # Store in vector database
                asyncio.run(vector_store.add_contracts(contracts, llm_service))
                
            logger.info(f"✅ Daily contract sync complete: {len(contracts)} contracts processed")
            
            # Close the service
            asyncio.run(contract_service.close())
            
            return len(contracts)
            
        except Exception as e:
            logger.error(f"❌ Daily contract sync failed: {str(e)}")
            # Optional: Send alert email to admin
            
        finally:
            pass
    
    def _get_new_contracts_for_user(self, db, user: User, since_date: datetime) -> List[Dict]:
        """
        Get new contracts that match user's profile since a given date.
        
        This integrates with your existing scoring system.
        """
        try:
            from app.models.company import CompanyProfile
            from app.models.contract import Contract
            from qdrant_client.models import Filter, FieldCondition, Range
            
            # Get user's company profile
            company = db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == user.firm_id
            ).first()
            
            if not company:
                logger.warning(f"No company profile for user {user.email}")
                return []
            
            # Search for contracts published after since_date
            # Using Qdrant scroll to get recent contracts
            scroll_result = self.vector_store.client.scroll(
                collection_name="legal_documents",
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="metadata.published_date",
                            range=Range(
                                gte=since_date.isoformat()
                            )
                        )
                    ]
                ),
                limit=50,  # Get up to 50 recent contracts
                with_payload=True
            )
            
            if not scroll_result[0]:
                return []
            
            # Score each contract against user's profile
            scorer = ContractMatchScorer(db, self.vector_store.client)
            matched_contracts = []
            
            for point in scroll_result[0]:
                metadata = point.payload.get("metadata", {})
                
                # Create Contract object
                contract = Contract(
                    notice_id=point.payload.get("notice_id", ""),
                    title=metadata.get("title", ""),
                    buyer_name=point.payload.get("buyer_name", ""),
                    description=metadata.get("description", ""),
                    contract_value=point.payload.get("value"),
                    region=point.payload.get("region"),
                    qdrant_id=point.id
                )
                
                # Score contract
                match_result = scorer.score_contract(contract, user.firm_id)
                
                if match_result and match_result["total_score"] >= 0.5:  # 50% minimum match
                    matched_contracts.append({
                        "notice_id": contract.notice_id,
                        "title": contract.title,
                        "buyer_name": contract.buyer_name,
                        "value": contract.contract_value,
                        "deadline": metadata.get("closing_date"),
                        "match_score": match_result["total_score"],
                        "match_reason": match_result.get("match_reasons", ["Matches your profile"])[0] if match_result.get("match_reasons") else "Matches your profile"
                    })
            
            # Sort by match score
            matched_contracts.sort(key=lambda x: x["match_score"], reverse=True)
            
            return matched_contracts
            
        except Exception as e:
            logger.error(f"Error getting contracts for user {user.email}: {e}")
            return []
    
    def _format_value(self, value) -> str:
        """Format contract value for display"""
        if value is None:
            return "Not specified"
        try:
            return f"£{float(value):,.0f}"
        except:
            return str(value)
    
    def _format_date(self, date) -> str:
        """Format date for display"""
        if date is None:
            return "Not specified"
        if isinstance(date, str):
            try:
                date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except:
                return date
        if isinstance(date, datetime):
            return date.strftime("%d %B %Y")
        return str(date)
    
    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        logger.info("✅ Email scheduler started")
    
    def shutdown(self):
        """Shutdown the scheduler."""
        self.scheduler.shutdown()
        logger.info("✅ Email scheduler stopped")
    
    def run_job_now(self, job_id: str):
        """Manually trigger a job (useful for testing)."""
        job = self.scheduler.get_job(job_id)
        if job:
            job.modify(next_run_time=datetime.utcnow())
            logger.info(f"⚡ Job '{job_id}' scheduled to run immediately")
        else:
            logger.error(f"❌ Job '{job_id}' not found")


# Singleton instance
email_scheduler = EmailScheduler()