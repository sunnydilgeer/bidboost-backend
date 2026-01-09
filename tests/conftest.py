"""
Shared test fixtures for email service and scheduler tests.
✅ All dependencies mocked - no real emails, no real DB, no real Redis
"""
# tests/conftest.py - ADD THIS AT THE VERY TOP
import pytest
from datetime import datetime as real_datetime, timedelta, UTC
from unittest.mock import patch
import sys

# Patch datetime.utcnow() globally for all tests
class MockDatetime(real_datetime):
    @classmethod
    def utcnow(cls):
        return real_datetime.now(UTC).replace(tzinfo=None)  # Return naive UTC time

# Install the patch before any models are imported
sys.modules['datetime'].datetime = MockDatetime

# NOW import everything else
import os
import logging
from unittest.mock import Mock, MagicMock
import pytest
import os
import logging
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jinja2 import Environment, DictLoader

logger = logging.getLogger(__name__)

# Import models (adjust paths as needed for your project)
from app.database import Base
from app.models import User
from app.models.company import CompanyProfile, SavedContract, CompanyCapability, CompanySize
from app.services.email_service import EmailService
from app.tasks.email_scheduler import EmailScheduler


# ==================== MOCK SENDGRID ====================

@pytest.fixture
def mock_sendgrid_client():
    """
    Mock SendGrid client that records calls without sending.
    
    Usage in tests:
        assert mock_sendgrid_client.send.call_count == 1
        call_args = mock_sendgrid_client.send.call_args[0][0]
        assert call_args.subject == "Expected subject"
    """
    client = Mock()
    response = Mock()
    response.status_code = 202  # Success code
    client.send.return_value = response
    return client


# ==================== MOCK JINJA TEMPLATES ====================

@pytest.fixture
def mock_jinja_env():
    """
    In-memory Jinja templates for testing (no file system dependency).
    
    Provides minimal but functional templates for all email types.
    """
    templates = {
        "email_new_contracts.html": """
            <!DOCTYPE html>
            <html>
            <head><title>New Contracts</title></head>
            <body>
                <h1>Hi {{ user_name }}</h1>
                <p>{{ total_new_contracts }} new contracts match your profile</p>
                {% for contract in contracts %}
                <div class="contract">
                    <h2>{{ contract.title }}</h2>
                    <p>Agency: {{ contract.buyer_name }}</p>
                    <p>Value: {{ contract.value }}</p>
                    <p>Deadline: {{ contract.deadline }}</p>
                    <p>Match: {{ contract.match_score }}%</p>
                    <p>Reason: {{ contract.match_reason }}</p>
                </div>
                {% endfor %}
                <a href="{{ dashboard_url }}">View Dashboard</a>
                <a href="{{ unsubscribe_url }}">Unsubscribe</a>
            </body>
            </html>
        """,
        "email_deadline_reminder.html": """
            <!DOCTYPE html>
            <html>
            <head><title>Deadline Reminder</title></head>
            <body>
                <h1>Hi {{ user_name }}</h1>
                <p>⏰ {{ days_until_deadline }} days until deadline</p>
                <h2>{{ contract.title }}</h2>
                <p>Agency: {{ contract.buyer_name }}</p>
                <p>Value: {{ contract.value }}</p>
                <p>Deadline: {{ contract.deadline }}</p>
                <p>Status: {{ contract.status }}</p>
                <a href="{{ contract_url }}">View Contract</a>
                <a href="{{ unsubscribe_url }}">Unsubscribe</a>
            </body>
            </html>
        """,
        "email_quickstart_report.html": """
            <!DOCTYPE html>
            <html>
            <head><title>Quickstart Report</title></head>
            <body>
                <h1>Your BidMatch Contract Report</h1>
                <p>Company: {{ company_name }}</p>
                <p>Website: {{ website_url }}</p>
                <p>Capabilities: {{ capabilities_preview }}</p>
                <p>Pages Scraped: {{ pages_scraped }}</p>
                <p>Total Matches: {{ total_matches }}</p>
                {% for contract in contracts %}
                <div>{{ contract.title }}</div>
                {% endfor %}
                <a href="{{ signup_url }}">Sign Up</a>
            </body>
            </html>
        """
    }
    return Environment(loader=DictLoader(templates))


# ==================== EMAIL SERVICE WITH MOCKS ====================

@pytest.fixture
def email_service_with_mocks(mock_sendgrid_client, mock_jinja_env):
    """
    EmailService with mocked dependencies.
    
    ✅ No real SendGrid calls
    ✅ No file system template loading
    ✅ Testable and deterministic
    """
    return EmailService(
        client=mock_sendgrid_client,
        env=mock_jinja_env
    )


# ==================== TEST DATABASE ====================

@pytest.fixture
def test_db_engine():
    """In-memory SQLite database engine."""
    engine = create_engine("sqlite:///:memory:")
    
    # SQLite doesn't support JSONB (PostgreSQL-only type)
    # Automatically detect and exclude ALL tables with JSONB columns
    from sqlalchemy.dialects.postgresql import JSONB
    
    tables_with_jsonb = []
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                tables_with_jsonb.append(table_name)
                break  # Only need to find one JSONB column per table
    
    if tables_with_jsonb:
        logger.info(f"📋 Excluding {len(tables_with_jsonb)} tables with JSONB: {tables_with_jsonb}")
    
    tables_to_create = [
        table for table in Base.metadata.tables.values()
        if table.name not in tables_with_jsonb
    ]
    
    # Create only compatible tables
    for table in tables_to_create:
        table.create(engine, checkfirst=True)
    
    yield engine
    
    # Cleanup
    for table in tables_to_create:
        table.drop(engine, checkfirst=True)


@pytest.fixture
def test_db_session(test_db_engine):
    """Database session factory for tests."""
    TestingSessionLocal = sessionmaker(bind=test_db_engine)
    
    def _get_session():
        return TestingSessionLocal()
    
    return _get_session


@pytest.fixture
def db_with_test_data(test_db_session):
    """
    Database session pre-populated with test users and companies.
    
    Creates:
    - 2 users with different notification preferences
    - 2 company profiles
    - Some saved contracts with approaching deadlines
    """
    db = test_db_session()
    
    try:
        # Create test company 1 (Starter tier)
        company1 = CompanyProfile(
            firm_id="FIRM001",
            company_name="Test Company 1",
            size=CompanySize.SMALL  # Use enum, not string!
        )
        db.add(company1)
        db.flush()  # Get the ID
        
        # Add capabilities to company 1 (use company_id, not firm_id!)
        cap1 = CompanyCapability(
            company_id=company1.id,  # Use the integer ID!
            capability_text="Cloud infrastructure and DevOps consulting",
            category="Technology"
        )
        db.add(cap1)
        
        # Create test company 2 (Pro tier)
        company2 = CompanyProfile(
            firm_id="FIRM002",
            company_name="Test Company 2",
            size=CompanySize.MEDIUM  # Use enum!
        )
        db.add(company2)
        db.flush()
        
        # Create test users with required id and hashed_password fields
        import uuid
        user1 = User(
            id=str(uuid.uuid4()),  # Required field
            email="daily-user@test.com",
            hashed_password="dummy_hash_for_tests",  # Required field!
            full_name="Daily User",
            firm_id="FIRM001",
            email_notifications_enabled=True,
            notification_frequency="daily",
            is_active=True,
            last_email_sent_at=datetime.now(UTC) - timedelta(days=1)
        )
        db.add(user1)
        
        user2 = User(
            id=str(uuid.uuid4()),
            email="weekly-user@test.com",
            hashed_password="dummy_hash_for_tests",  # Required field!
            full_name="Weekly User",
            firm_id="FIRM002",
            email_notifications_enabled=True,
            notification_frequency="weekly",
            is_active=True,
            last_email_sent_at=datetime.now(UTC) - timedelta(days=7)
        )
        db.add(user2)
        
        user3 = User(
            id=str(uuid.uuid4()),
            email="disabled-user@test.com",
            hashed_password="dummy_hash_for_tests",  # Required field!
            full_name="Disabled User",
            firm_id="FIRM001",
            email_notifications_enabled=False,
            notification_frequency="daily",
            is_active=True
        )
        db.add(user3)
        
        # Create saved contracts with approaching deadlines
        today = datetime.now(UTC)
        
        # 7 days away
        contract_7d = SavedContract(
            notice_id="CONTRACT-7D",
            user_email="daily-user@test.com",
            firm_id="FIRM001",
            contract_title="7 Day Deadline Contract",
            buyer_name="Department of Defense",
            contract_value=1000000,
            deadline=today + timedelta(days=7),
            status="bidding"
        )
        db.add(contract_7d)
        
        # 3 days away
        contract_3d = SavedContract(
            notice_id="CONTRACT-3D",
            user_email="daily-user@test.com",
            firm_id="FIRM001",
            contract_title="3 Day Deadline Contract",
            buyer_name="GSA",
            contract_value=500000,
            deadline=today + timedelta(days=3),
            status="interested"
        )
        db.add(contract_3d)
        
        # 1 day away
        contract_1d = SavedContract(
            notice_id="CONTRACT-1D",
            user_email="weekly-user@test.com",
            firm_id="FIRM002",
            contract_title="1 Day Deadline Contract",
            buyer_name="NASA",
            contract_value=2000000,
            deadline=today + timedelta(days=1),
            status="bidding"
        )
        db.add(contract_1d)
        
        # Already passed (should not trigger)
        contract_passed = SavedContract(
            notice_id="CONTRACT-PASSED",
            user_email="daily-user@test.com",
            firm_id="FIRM001",
            contract_title="Passed Deadline Contract",
            buyer_name="DOE",
            contract_value=750000,
            deadline=today - timedelta(days=1),
            status="bidding"
        )
        db.add(contract_passed)
        
        db.commit()
        
        yield db
        
    finally:
        db.close()


# ==================== MOCK REDIS ====================

@pytest.fixture
def mock_redis():
    """
    Mock Redis client with fake distributed locking.
    
    Always allows lock acquisition (single-instance test behavior).
    """
    redis_mock = MagicMock()
    lock_mock = MagicMock()
    
    # Lock always succeeds
    lock_mock.acquire.return_value = True
    lock_mock.__enter__ = Mock(return_value=True)
    lock_mock.__exit__ = Mock(return_value=False)
    
    redis_mock.lock.return_value = lock_mock
    
    return redis_mock


# ==================== MOCK VECTOR STORE ====================

@pytest.fixture
def mock_vector_store():
    """
    Mock vector store (Qdrant/Pinecone).
    
    Returns empty results by default - override in tests as needed.
    """
    store = Mock()
    store.client.scroll.return_value = ([], None)  # Empty results
    store.search_contracts.return_value = []
    return store


# ==================== MOCK MATCH SCORER ====================

@pytest.fixture
def mock_contract_scorer():
    """
    Mock ContractMatchScorer.
    
    Returns configurable match scores for testing.
    """
    with patch('app.tasks.email_scheduler.ContractMatchScorer') as mock:
        scorer_instance = Mock()
        
        # Default: high score for testing
        scorer_instance.score_contract.return_value = {
            "total_score": 0.85,
            "match_reasons": ["Matches your capabilities"]
        }
        
        mock.return_value = scorer_instance
        yield scorer_instance


# ==================== MOCK ENTITLEMENTS ====================

@pytest.fixture
def mock_entitlements():
    """
    Mock entitlements service.
    
    Returns configurable entitlements for testing tier-based features.
    """
    with patch('app.tasks.email_scheduler.get_entitlements') as mock:
        # Default: Starter tier (no priority alerts)
        mock.return_value = {
            'priority_alerts': False,
            'advanced_search': False
        }
        yield mock


# ==================== EMAIL SCHEDULER WITH MOCKS ====================

@pytest.fixture
def email_scheduler_with_mocks(
    email_service_with_mocks,
    test_db_session,
    mock_redis,
    mock_vector_store,
    mock_contract_scorer,
    mock_entitlements
):
    """
    EmailScheduler with all dependencies mocked.
    
    ✅ No real emails sent
    ✅ No real database
    ✅ No real Redis
    ✅ No real vector store
    ✅ No scheduled jobs (setup_jobs=False)
    """
    return EmailScheduler(
        email_service=email_service_with_mocks,
        session_factory=test_db_session,
        redis_client=mock_redis,
        vector_store=mock_vector_store,
        use_pinecone=False,
        setup_jobs=False  # Don't start scheduler in tests
    )


# ==================== SAMPLE TEST DATA ====================

@pytest.fixture
def sample_contracts():
    """Sample contract data for testing digest generation."""
    today = datetime.now(UTC)
    
    return [
        # High score, urgent
        {
            "notice_id": "CONTRACT-001",
            "title": "Cloud Infrastructure Modernization",
            "agency": "DOD",
            "buyer_name": "Department of Defense",
            "contract_value": 5000000,
            "value": 5000000,
            "response_deadline": (today + timedelta(days=5)).isoformat(),
            "deadline": (today + timedelta(days=5)).isoformat(),
            "match_score": 0.92,
            "match_reason": "Strong capability match"
        },
        # High score, not urgent
        {
            "notice_id": "CONTRACT-002",
            "title": "DevOps Platform Development",
            "agency": "GSA",
            "buyer_name": "General Services Administration",
            "contract_value": 3000000,
            "value": 3000000,
            "response_deadline": (today + timedelta(days=30)).isoformat(),
            "deadline": (today + timedelta(days=30)).isoformat(),
            "match_score": 0.88,
            "match_reason": "Past performance alignment"
        },
        # Medium score, urgent
        {
            "notice_id": "CONTRACT-003",
            "title": "IT Security Audit Services",
            "agency": "DHS",
            "buyer_name": "Department of Homeland Security",
            "contract_value": 1500000,
            "value": 1500000,
            "response_deadline": (today + timedelta(days=4)).isoformat(),
            "deadline": (today + timedelta(days=4)).isoformat(),
            "match_score": 0.65,
            "match_reason": "Location match"
        },
        # Medium score, not urgent
        {
            "notice_id": "CONTRACT-004",
            "title": "Network Infrastructure Support",
            "agency": "VA",
            "buyer_name": "Veterans Affairs",
            "contract_value": 2000000,
            "value": 2000000,
            "response_deadline": (today + timedelta(days=45)).isoformat(),
            "deadline": (today + timedelta(days=45)).isoformat(),
            "match_score": 0.58,
            "match_reason": "Industry alignment"
        },
        # Low score (should be filtered out at 0.5 threshold)
        {
            "notice_id": "CONTRACT-005",
            "title": "Landscaping Services",
            "agency": "DOI",
            "buyer_name": "Department of Interior",
            "contract_value": 100000,
            "value": 100000,
            "response_deadline": (today + timedelta(days=20)).isoformat(),
            "deadline": (today + timedelta(days=20)).isoformat(),
            "match_score": 0.35,
            "match_reason": "No match"
        }
    ]


# ==================== ENVIRONMENT VARIABLE MOCKING ====================

@pytest.fixture
def mock_frontend_url():
    """Mock FRONTEND_URL environment variable."""
    with patch.dict('os.environ', {'FRONTEND_URL': 'https://test.contractdiscovery.com'}):
        yield


@pytest.fixture
def mock_frontend_url_none():
    """Mock FRONTEND_URL as None (test fallback behavior)."""
    with patch.dict('os.environ', {'FRONTEND_URL': 'None'}, clear=False):
        yield


@pytest.fixture
def mock_frontend_url_unset():
    """Mock FRONTEND_URL as unset (test default behavior)."""
    with patch.dict('os.environ', {}, clear=True):
        # Remove FRONTEND_URL if it exists
        if 'FRONTEND_URL' in os.environ:
            del os.environ['FRONTEND_URL']
        yield
# Monkey-patch for tests only: make User model use timezone-aware defaults
import app.models
original_user_init = app.models.User.__init__

def patched_user_init(self, **kwargs):
    # Set timezone-aware defaults for test users
    if 'created_at' not in kwargs:
        kwargs['created_at'] = datetime.now(UTC)
    if 'updated_at' not in kwargs:
        kwargs['updated_at'] = datetime.now(UTC)
    original_user_init(self, **kwargs)

app.models.User.__init__ = patched_user_init
