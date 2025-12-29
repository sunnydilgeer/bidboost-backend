"""
Email Scheduler - US Federal Version with Distributed Locking
Prevents duplicate job execution across multiple Railway instances

Location: app/tasks/email_scheduler.py
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.entitlements import get_entitlements
from datetime import datetime, timedelta
from typing import List, Dict
import logging
import redis
import os

from app.services.email_service import email_service
from app.database import SessionLocal
from app.models import User
from app.models.company import SavedContract
from app.services.match_scoring import ContractMatchScorer
from app.core.config import settings

# Import both vector stores
from app.services.vector_store import VectorStoreService
from app.services.pinecone_store import PineconeStoreService

from app.services.contract_fetcher import ContractFetcherService
from app.services.llm import LLMService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        
        # Initialize Redis for distributed locking
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Initialize the correct vector store based on environment
        if settings.USE_PINECONE:
            logger.info("🌲 Using Pinecone for vector storage")
            self.vector_store = PineconeStoreService(api_key=settings.PINECONE_API_KEY)
            self.use_pinecone = True
        else:
            logger.info("📦 Using Qdrant for vector storage")
            self.vector_store = VectorStoreService()
            self.use_pinecone = False
        
        self.setup_jobs()
    
    def _with_lock(self, func, lock_name: str, timeout: int = 300):
        """
        Execute function with distributed lock to prevent duplicate runs.
        
        Args:
            func: Function to execute
            lock_name: Unique lock identifier
            timeout: Lock timeout in seconds (default 5 minutes)
        """
        lock = self.redis_client.lock(
            f"scheduler_lock:{lock_name}",
            timeout=timeout,
            blocking_timeout=1  # Don't wait if lock is taken
        )
        
        try:
            if lock.acquire(blocking=False):
                logger.info(f"🔒 Acquired lock for {lock_name}")
                return func()
            else:
                logger.info(f"⏭️  Lock already held for {lock_name}, skipping (another instance running)")
                return None
        except redis.exceptions.LockError:
            logger.warning(f"⚠️  Could not acquire lock for {lock_name}")
            return None
        finally:
            try:
                lock.release()
                logger.info(f"🔓 Released lock for {lock_name}")
            except:
                pass  # Lock already released or expired
    
    def setup_jobs(self):
        """Set up scheduled jobs."""
        # Daily contract sync at 7:00 AM EST (before emails)
        self.scheduler.add_job(
            func=lambda: self._with_lock(self.sync_contracts_daily, "sync_contracts"),
            trigger=CronTrigger(hour=7, minute=0, timezone='America/New_York'),
            id='sync_contracts_daily',
            name='Sync contracts from SAM.gov',
            replace_existing=True
        )
        
        # Daily new contracts email at 9:00 AM EST
        self.scheduler.add_job(
            func=lambda: self._with_lock(self.send_daily_contract_emails, "daily_emails"),
            trigger=CronTrigger(hour=9, minute=0, timezone='America/New_York'),
            id='daily_contract_emails',
            name='Send daily new contract emails',
            replace_existing=True
        )
        
        # Daily deadline reminders at 10:00 AM EST
        self.scheduler.add_job(
            func=lambda: self._with_lock(self.send_deadline_reminders, "deadline_reminders"),
            trigger=CronTrigger(hour=10, minute=0, timezone='America/New_York'),
            id='deadline_reminders',
            name='Send deadline reminder emails',
            replace_existing=True
        )
        
        vector_db = "Pinecone" if self.use_pinecone else "Qdrant"
        logger.info(f"✅ Email scheduler jobs configured (7am sync, 9am emails, 10am reminders EST) using {vector_db}")
        logger.info("🔒 Distributed locking enabled via Redis")
    
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
                                "buyer_name": c.get("agency") or c.get("buyer_name", ""),
                                "value": self._format_value(c.get("contract_value") or c.get("value")),
                                "deadline": self._format_date(c.get("response_deadline") or c.get("deadline")),
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
        """Sync new contracts from SAM.gov API every morning."""
        logger.info("🔄 Starting daily contract sync job")
        
        try:
            # Initialize contract fetcher service
            contract_service = ContractFetcherService()
            llm_service = LLMService()
            
            # Fetch contracts from API (last 7 days to catch any missed ones)
            import asyncio
            contracts = asyncio.run(contract_service.fetch_contracts(limit=100, days_back=7))
            
            if contracts:
                # Store in the appropriate vector database
                if self.use_pinecone:
                    # Format for Pinecone
                    documents = []
                    for contract in contracts:
                        embedding = asyncio.run(llm_service.generate_embeddings(contract.description))
                        documents.append({
                            "id": contract.notice_id,
                            "embedding": embedding,
                            "payload": contract.__dict__
                        })
                    self.vector_store.upsert_documents(documents)
                else:
                    # Use existing Qdrant method
                    vector_store_qdrant = VectorStoreService()
                    asyncio.run(vector_store_qdrant.add_contracts(contracts, llm_service))
                
            logger.info(f"✅ Daily contract sync complete: {len(contracts)} contracts processed")
            
            # Close the service
            asyncio.run(contract_service.close())
            
            return len(contracts)
            
        except Exception as e:
            logger.error(f"❌ Daily contract sync failed: {str(e)}")
            
        finally:
            pass
    
    def _get_new_contracts_for_user(self, db, user: User, since_date: datetime) -> List[Dict]:
        """
        Get new contracts that match user's profile.
        Works with both Pinecone and Qdrant.
        ✅ NEW: Respects plan tier entitlements
        """
        try:
            from app.models.company import CompanyProfile
            from app.models.contract import Contract
            
            # Get user's company profile
            company = db.query(CompanyProfile).filter(
                CompanyProfile.firm_id == user.firm_id
            ).first()
            
            if not company:
                logger.warning(f"No company profile for user {user.email}")
                return []
            
            # ✅ NEW: Get entitlements to determine digest type
            entitlements = get_entitlements(db, user.firm_id)
            has_priority_alerts = entitlements.get('priority_alerts', False)
            
            if self.use_pinecone:
                contracts = self._get_contracts_from_pinecone(db, user, company)
            else:
                contracts = self._get_contracts_from_qdrant(db, user, company)
            
            # ✅ NEW: Apply tier-based filtering
            if has_priority_alerts:
                # PRO: Smart prioritization
                return self._generate_pro_digest(contracts)
            else:
                # STARTER: Simple top 20 by score
                return self._generate_starter_digest(contracts)
            
        except Exception as e:
            logger.error(f"Error getting contracts for user {user.email}: {e}")
            return []

    def _get_contracts_from_pinecone(self, db, user: User, company) -> List[Dict]:
        """Get contracts from Pinecone"""
        try:
            # Get all recent contracts (Pinecone returns them sorted by relevance)
            # We'll use a dummy query vector - in production you'd generate from user's capabilities
            import asyncio
            from app.services.llm import LLMService
            
            llm = LLMService()
            
            # Create search query from user's capabilities
            capabilities_text = " ".join([cap.capability_text for cap in company.capabilities[:3]])
            query_vector = asyncio.run(llm.generate_embeddings(capabilities_text or "federal contracts"))
            
            # Search Pinecone
            results = self.vector_store.search_contracts(
                query_vector=query_vector,
                limit=50,
                min_score=0.2
            )
            
            # Format for email (Pinecone returns different structure)
            matched_contracts = []
            for result in results:
                matched_contracts.append({
                    "notice_id": result.get("notice_id", ""),
                    "title": result.get("title", ""),
                    "agency": result.get("agency", ""),
                    "contract_value": result.get("contract_value", 0),
                    "response_deadline": result.get("response_deadline", ""),
                    "match_score": result.get("score", 0),
                    "match_reason": "Matches your capabilities"
                })
            
            return matched_contracts
            
        except Exception as e:
            logger.error(f"Pinecone search error: {e}")
            return []
    
    def _get_contracts_from_qdrant(self, db, user: User, company) -> List[Dict]:
        """Get contracts from Qdrant"""
        try:
            from app.models.contract import Contract
            
            # Get recent contracts from Qdrant
            scroll_result = self.vector_store.client.scroll(
                collection_name="contracts",
                limit=50,
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
                
                if match_result and match_result["total_score"] >= 0.5:
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
            logger.error(f"Qdrant search error: {e}")
            return []

    def _generate_pro_digest(self, contracts: List[Dict]) -> List[Dict]:
        """
        PRO: Priority-ranked digest with smart grouping.
        
        Prioritizes:
        1. High-scoring (70%+) opportunities closing <7 days
        2. High-scoring opportunities (70%+)
        3. Medium-scoring (50-69%) closing <7 days
        4. Medium-scoring (50-69%)
        """
        from datetime import datetime, timedelta
        
        today = datetime.utcnow()
        urgent_threshold = today + timedelta(days=7)
        
        # Categorize contracts
        high_score_urgent = []
        high_score = []
        medium_score_urgent = []
        medium_score = []
        
        for contract in contracts:
            score = contract.get('match_score', 0)
            deadline_str = contract.get('deadline') or contract.get('response_deadline')
            
            # Parse deadline
            is_urgent = False
            if deadline_str:
                try:
                    if isinstance(deadline_str, str):
                        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    else:
                        deadline = deadline_str
                    is_urgent = deadline <= urgent_threshold
                except:
                    pass
            
            # Categorize
            if score >= 0.7:
                if is_urgent:
                    high_score_urgent.append(contract)
                else:
                    high_score.append(contract)
            elif score >= 0.5:
                if is_urgent:
                    medium_score_urgent.append(contract)
                else:
                    medium_score.append(contract)
        
        # Combine in priority order (limit to 20 total)
        prioritized = (
            high_score_urgent[:5] +
            high_score[:10] +
            medium_score_urgent[:3] +
            medium_score[:2]
        )[:20]
        
        logger.info(f"📊 Pro digest: {len(high_score_urgent)} high/urgent, {len(high_score)} high, {len(medium_score_urgent)} med/urgent")
        
        return prioritized

    def _generate_starter_digest(self, contracts: List[Dict]) -> List[Dict]:
        """
        STARTER: Simple top 20 by match score.
        """
        # Sort by match score descending
        sorted_contracts = sorted(
            contracts,
            key=lambda x: x.get('match_score', 0),
            reverse=True
        )
        
        # Return top 20
        starter_digest = sorted_contracts[:20]
        
        logger.info(f"📋 Starter digest: {len(starter_digest)} contracts (top-scoring)")
        
        return starter_digest
    
    def _format_value(self, value) -> str:
        """Format contract value for display"""
        if value is None:
            return "Not specified"
        try:
            return f"${float(value):,.0f}"
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