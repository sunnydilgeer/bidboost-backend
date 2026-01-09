"""
Tests for EmailScheduler - Scheduling logic, preference gating, tier filtering
✅ No real emails sent - all dependencies mocked
✅ No APScheduler jobs running - setup_jobs=False in tests
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace

from app.models import User
from app.models.company import SavedContract, CompanySize


class TestSchedulerPreferenceGating:
    """Test that emails only go to users with correct notification preferences."""

    def test_daily_emails_only_to_daily_users(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """Daily job should only email users with daily frequency."""

        # ✅ Make Qdrant return one contract point so an email is sent
        point = SimpleNamespace(
            id="QDRANT-1",
            payload={
                "notice_id": "TEST-NOTICE-1",
                "buyer_name": "GSA",
                "value": 100000,
                "region": "US",
                "metadata": {
                    "title": "Test Contract Title",
                    "description": "Test description",
                    "closing_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
            },
        )

        # Scheduler uses: self.vector_store.client.scroll(...)
        mock_vector_store.client.scroll.return_value = ([point], None)

        # Run the daily email job
        email_scheduler_with_mocks.send_daily_contract_emails()

        # Should send to daily-user@test.com (1 call)
        # Should NOT send to weekly-user@test.com
        # Should NOT send to disabled-user@test.com
        assert mock_sendgrid_client.send.call_count == 1

        # Verify it was sent to the daily user
        call_args = mock_sendgrid_client.send.call_args[0][0]
        recipient = call_args.personalizations[0].tos[0]["email"]
        assert recipient == "daily-user@test.com"

    def test_disabled_notifications_never_send(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """Users with email_notifications_enabled=False should never receive emails."""
        db = db_with_test_data

        # Verify disabled-user exists and is configured correctly
        disabled_user = db.query(User).filter(User.email == "disabled-user@test.com").first()
        assert disabled_user is not None
        assert disabled_user.email_notifications_enabled is False

        # Even if there are contracts, disabled users should not be emailed.
        point = SimpleNamespace(
            id="QDRANT-1",
            payload={
                "notice_id": "TEST-NOTICE-1",
                "buyer_name": "GSA",
                "value": 100000,
                "region": "US",
                "metadata": {
                    "title": "Test Contract Title",
                    "description": "Test description",
                    "closing_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
            },
        )
        mock_vector_store.client.scroll.return_value = ([point], None)

        # Run daily job
        email_scheduler_with_mocks.send_daily_contract_emails()

        # Check that disabled user was NOT emailed
        if mock_sendgrid_client.send.call_count > 0:
            for call in mock_sendgrid_client.send.call_args_list:
                mail_obj = call[0][0]
                recipient = mail_obj.personalizations[0].tos[0]["email"]
                assert recipient != "disabled-user@test.com"

    def test_inactive_users_never_send(
        self,
        email_scheduler_with_mocks,
        test_db_session,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """Users with is_active=False should never receive emails."""
        import uuid

        db = test_db_session()

        # Create inactive user
        inactive_user = User(
            id=str(uuid.uuid4()),
            email="inactive@test.com",
            hashed_password="dummy_hash_for_tests",
            full_name="Inactive User",
            firm_id="FIRM001",
            email_notifications_enabled=True,
            notification_frequency="daily",
            is_active=False,
        )
        db.add(inactive_user)
        db.commit()

        # Even if there are contracts, inactive users should not be emailed.
        point = SimpleNamespace(
            id="QDRANT-1",
            payload={
                "notice_id": "TEST-NOTICE-1",
                "buyer_name": "GSA",
                "value": 100000,
                "region": "US",
                "metadata": {
                    "title": "Test Contract Title",
                    "description": "Test description",
                    "closing_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
            },
        )
        mock_vector_store.client.scroll.return_value = ([point], None)

        scheduler = email_scheduler_with_mocks
        scheduler.session_factory = lambda: db
        scheduler.send_daily_contract_emails()

        # Inactive user should not receive email
        if mock_sendgrid_client.send.call_count > 0:
            for call in mock_sendgrid_client.send.call_args_list:
                mail_obj = call[0][0]
                recipient = mail_obj.personalizations[0].tos[0]["email"]
                assert recipient != "inactive@test.com"

        db.close()


class TestLastEmailSentAtUpdates:
    """Test that last_email_sent_at is updated after successful sends."""

    def test_last_email_sent_at_updates_on_success(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """After successful email send, last_email_sent_at should be updated."""
        db = db_with_test_data

        # Get initial timestamp
        user = db.query(User).filter(User.email == "daily-user@test.com").first()
        initial_timestamp = user.last_email_sent_at
        assert initial_timestamp is not None

        # ✅ Ensure there is at least one matching contract so an email is sent
        point = SimpleNamespace(
            id="QDRANT-1",
            payload={
                "notice_id": "TEST-NOTICE-1",
                "buyer_name": "GSA",
                "value": 100000,
                "region": "US",
                "metadata": {
                    "title": "Test Contract Title",
                    "description": "Test description",
                    "closing_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
            },
        )
        mock_vector_store.client.scroll.return_value = ([point], None)

        # Run daily job
        email_scheduler_with_mocks.send_daily_contract_emails()

        # Should actually have sent one email
        assert mock_sendgrid_client.send.call_count == 1

        # Refresh user from DB
        db.expire_all()
        user = db.query(User).filter(User.email == "daily-user@test.com").first()

        # last_email_sent_at should be updated
        assert user.last_email_sent_at is not None
        assert user.last_email_sent_at > initial_timestamp

    def test_last_email_sent_at_not_updated_on_failure(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """If email send fails, last_email_sent_at should not update."""
        db = db_with_test_data

        # Make SendGrid fail
        mock_sendgrid_client.send.return_value.status_code = 500

        user = db.query(User).filter(User.email == "daily-user@test.com").first()
        initial_timestamp = user.last_email_sent_at

        # Ensure there is a contract, but send will fail
        point = SimpleNamespace(
            id="QDRANT-1",
            payload={
                "notice_id": "TEST-NOTICE-1",
                "buyer_name": "GSA",
                "value": 100000,
                "region": "US",
                "metadata": {
                    "title": "Test Contract Title",
                    "description": "Test description",
                    "closing_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                },
            },
        )
        mock_vector_store.client.scroll.return_value = ([point], None)

        # Run daily job
        email_scheduler_with_mocks.send_daily_contract_emails()

        # Refresh user
        db.expire_all()
        user = db.query(User).filter(User.email == "daily-user@test.com").first()

        # Timestamp should NOT change
        assert user.last_email_sent_at == initial_timestamp


class TestDeadlineReminders:
    """Test deadline reminder logic for 7, 3, and 1 day intervals."""

    def test_deadline_reminders_sent_for_7_3_1_days(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
    ):
        """Should send reminders for contracts due in 7, 3, or 1 day."""
        email_scheduler_with_mocks.send_deadline_reminders()

        # Should send 3 emails (7d, 3d, 1d contracts)
        assert mock_sendgrid_client.send.call_count == 3

        subjects = [call[0][0].subject.subject for call in mock_sendgrid_client.send.call_args_list]
        assert any("7 days" in s for s in subjects)
        assert any("3 days" in s for s in subjects)
        assert any("1 day" in s for s in subjects)

    def test_1_day_deadline_gets_urgent_emoji(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
    ):
        """1-day deadline should have 🚨 urgent emoji in subject."""
        email_scheduler_with_mocks.send_deadline_reminders()

        for call in mock_sendgrid_client.send.call_args_list:
            subject = call[0][0].subject.subject
            if "1 day" in subject:
                assert "🚨" in subject
                break
        else:
            pytest.fail("No 1-day reminder found")

    def test_7_day_deadline_gets_clock_emoji(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
    ):
        """7-day deadline should have ⏰ clock emoji in subject."""
        email_scheduler_with_mocks.send_deadline_reminders()

        for call in mock_sendgrid_client.send.call_args_list:
            subject = call[0][0].subject.subject
            if "7 days" in subject:
                assert "⏰" in subject
                break
        else:
            pytest.fail("No 7-day reminder found")

    def test_passed_deadlines_ignored(
        self,
        email_scheduler_with_mocks,
        db_with_test_data,
        mock_sendgrid_client,
    ):
        """Contracts with passed deadlines should not trigger reminders."""
        email_scheduler_with_mocks.send_deadline_reminders()

        for call in mock_sendgrid_client.send.call_args_list:
            mail_obj = call[0][0]
            html = mail_obj.contents[0].content
            assert "Passed Deadline Contract" not in html

    def test_only_interested_and_bidding_status(
        self,
        email_scheduler_with_mocks,
        test_db_session,
        mock_sendgrid_client,
    ):
        """Only contracts with 'interested' or 'bidding' status should send reminders."""
        db = test_db_session()

        today = datetime.now(UTC)
        won_contract = SavedContract(
            notice_id="CONTRACT-WON",
            user_email="daily-user@test.com",
            firm_id="FIRM001",
            contract_title="Won Contract",
            buyer_name="DOD",
            deadline=today + timedelta(days=7),
            status="won",
        )
        db.add(won_contract)
        db.commit()

        scheduler = email_scheduler_with_mocks
        scheduler.session_factory = lambda: db
        scheduler.send_deadline_reminders()

        for call in mock_sendgrid_client.send.call_args_list:
            mail_obj = call[0][0]
            html = mail_obj.contents[0].content
            assert "Won Contract" not in html

        db.close()


class TestTierBasedDigestGeneration:
    """Test PRO vs STARTER tier digest differences."""

    def test_starter_tier_gets_top_20_by_score(
        self,
        email_scheduler_with_mocks,
        sample_contracts,
        mock_entitlements,
    ):
        """STARTER tier should get simple top 20 sorted by match score."""
        mock_entitlements.return_value = {"priority_alerts": False}

        digest = email_scheduler_with_mocks._generate_starter_digest(sample_contracts)

        assert len(digest) <= 20
        scores = [c.get("match_score", 0) for c in digest]
        assert scores == sorted(scores, reverse=True)

    def test_pro_tier_prioritizes_urgent_high_score(
        self,
        email_scheduler_with_mocks,
        sample_contracts,
        mock_entitlements,
    ):
        """PRO tier should prioritize high-score + urgent contracts first."""
        mock_entitlements.return_value = {"priority_alerts": True}

        digest = email_scheduler_with_mocks._generate_pro_digest(sample_contracts)

        first_contract = digest[0]
        assert first_contract["match_score"] >= 0.7
        assert first_contract["notice_id"] == "CONTRACT-001"

    def test_pro_digest_smart_grouping(
        self,
        email_scheduler_with_mocks,
        sample_contracts,
        mock_entitlements,
    ):
        """PRO digest should group by priority: high/urgent, high, med/urgent, med."""
        mock_entitlements.return_value = {"priority_alerts": True}

        digest = email_scheduler_with_mocks._generate_pro_digest(sample_contracts)

        notice_ids = [c["notice_id"] for c in digest]
        assert notice_ids.index("CONTRACT-001") < notice_ids.index("CONTRACT-002")

    @pytest.mark.skip(reason="Score filtering not yet implemented in digest methods")
    def test_low_score_contracts_filtered_out(
        self,
        email_scheduler_with_mocks,
        sample_contracts,
    ):
        """Contracts with match_score < 0.5 should be filtered out."""
        starter = email_scheduler_with_mocks._generate_starter_digest(sample_contracts)
        pro = email_scheduler_with_mocks._generate_pro_digest(sample_contracts)

        starter_ids = [c["notice_id"] for c in starter]
        pro_ids = [c["notice_id"] for c in pro]

        assert "CONTRACT-005" not in starter_ids
        assert "CONTRACT-005" not in pro_ids


class TestContractFormatting:
    """Test helper methods that format contract data for emails."""

    def test_format_value_with_number(self, email_scheduler_with_mocks):
        result = email_scheduler_with_mocks._format_value(5000000)
        assert result == "$5,000,000"

    def test_format_value_with_none(self, email_scheduler_with_mocks):
        result = email_scheduler_with_mocks._format_value(None)
        assert result == "Not specified"

    def test_format_value_with_invalid(self, email_scheduler_with_mocks):
        result = email_scheduler_with_mocks._format_value("invalid")
        assert result == "invalid"

    def test_format_date_with_datetime(self, email_scheduler_with_mocks):
        test_date = datetime(2026, 1, 15, 12, 0, 0)
        result = email_scheduler_with_mocks._format_date(test_date)
        assert result == "15 January 2026"

    def test_format_date_with_iso_string(self, email_scheduler_with_mocks):
        result = email_scheduler_with_mocks._format_date("2026-01-15T12:00:00Z")
        assert "January 2026" in result

    def test_format_date_with_none(self, email_scheduler_with_mocks):
        result = email_scheduler_with_mocks._format_date(None)
        assert result == "Not specified"


class TestRedisDistributedLocking:
    """Test Redis-based distributed locking for multi-instance deployments."""

    def test_with_lock_acquires_and_releases(
        self,
        email_scheduler_with_mocks,
        mock_redis,
    ):
        executed = []

        def test_func():
            executed.append(True)
            return "success"

        result = email_scheduler_with_mocks._with_lock(test_func, lock_name="test_lock")

        assert len(executed) == 1
        assert result == "success"

        assert mock_redis.lock.called
        lock = mock_redis.lock.return_value
        assert lock.acquire.called
        assert lock.release.called

    def test_with_lock_skips_if_held(
        self,
        email_scheduler_with_mocks,
        mock_redis,
    ):
        mock_redis.lock.return_value.acquire.return_value = False

        executed = []

        def test_func():
            executed.append(True)
            return "success"

        result = email_scheduler_with_mocks._with_lock(test_func, lock_name="held_lock")

        assert len(executed) == 0
        assert result is None

    def test_lock_timeout_configurable(
        self,
        email_scheduler_with_mocks,
        mock_redis,
    ):
        def test_func():
            return "done"

        email_scheduler_with_mocks._with_lock(test_func, lock_name="test", timeout=600)

        mock_redis.lock.assert_called_with(
            "scheduler_lock:test",
            timeout=600,
            blocking_timeout=1,
        )


class TestNoContractsScenario:
    """Test behavior when no contracts match user profile."""

    def test_no_contracts_no_email_sent(
        self,
        email_scheduler_with_mocks,
        test_db_session,
        mock_sendgrid_client,
        mock_vector_store,
    ):
        """If no contracts match, no email should be sent."""
        db = test_db_session()

        from app.models.company import CompanyProfile

        company = CompanyProfile(
            firm_id="FIRM-NOCONTRACTS",
            company_name="No Contracts Co",
            size=CompanySize.SMALL,
        )
        db.add(company)
        db.flush()

        import uuid

        user = User(
            id=str(uuid.uuid4()),
            email="nocontracts@test.com",
            hashed_password="dummy_hash_for_tests",
            full_name="No Contracts User",
            firm_id="FIRM-NOCONTRACTS",
            email_notifications_enabled=True,
            notification_frequency="daily",
            is_active=True,
        )
        db.add(user)
        db.commit()

        mock_vector_store.client.scroll.return_value = ([], None)

        scheduler = email_scheduler_with_mocks
        scheduler.session_factory = lambda: db
        scheduler.send_daily_contract_emails()

        assert mock_sendgrid_client.send.call_count == 0

        db.close()


class TestEmailSchedulerJobSetup:
    """Test that scheduler jobs are configured correctly."""

    def test_setup_jobs_disabled_in_tests(self, email_scheduler_with_mocks):
        assert not email_scheduler_with_mocks.scheduler.running

    def test_setup_jobs_enabled_in_production(
        self,
        email_service_with_mocks,
        test_db_session,
        mock_redis,
        mock_vector_store,
    ):
        from app.tasks.email_scheduler import EmailScheduler

        scheduler = EmailScheduler(
            email_service=email_service_with_mocks,
            session_factory=test_db_session,
            redis_client=mock_redis,
            vector_store=mock_vector_store,
            setup_jobs=True,
        )

        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) == 3

        job_ids = [job.id for job in jobs]
        assert "sync_contracts_daily" in job_ids
        assert "daily_contract_emails" in job_ids
        assert "deadline_reminders" in job_ids


class TestVectorStoreIntegration:
    """Test integration with both Qdrant and Pinecone vector stores."""

    def test_qdrant_contract_retrieval(
        self,
        email_scheduler_with_mocks,
        test_db_session,
        mock_vector_store,
        mock_contract_scorer,
    ):
        """Should retrieve contracts from Qdrant when use_pinecone=False."""
        db = test_db_session()

        from app.models.company import CompanyProfile

        company = CompanyProfile(
            firm_id="FIRM-QDRANT",
            company_name="Qdrant Test Co",
            size=CompanySize.SMALL,
        )
        db.add(company)
        db.flush()

        import uuid

        user = User(
            id=str(uuid.uuid4()),
            email="qdrant@test.com",
            hashed_password="dummy_hash_for_tests",
            full_name="Qdrant User",
            firm_id="FIRM-QDRANT",
            is_active=True,
        )
        db.add(user)
        db.commit()

        mock_point = Mock()
        mock_point.id = "point-1"
        mock_point.payload = {
            "notice_id": "QDRANT-001",
            "buyer_name": "DOD",
            "value": 1000000,
            "metadata": {
                "title": "Qdrant Contract",
                "description": "Test",
                "closing_date": "2026-01-15",
            },
        }
        mock_vector_store.client.scroll.return_value = ([mock_point], None)

        contracts = email_scheduler_with_mocks._get_contracts_from_qdrant(db, user, company)

        assert len(contracts) > 0
        assert contracts[0]["notice_id"] == "QDRANT-001"

        db.close()

    def test_pinecone_contract_retrieval(
        self,
        email_service_with_mocks,
        test_db_session,
        mock_redis,
    ):
        """Should retrieve contracts from Pinecone when use_pinecone=True."""
        db = test_db_session()

        mock_pinecone = Mock()
        mock_pinecone.search_contracts.return_value = [
            {
                "notice_id": "PINECONE-001",
                "title": "Pinecone Contract",
                "agency": "NASA",
                "contract_value": 2000000,
                "response_deadline": "2026-02-01",
                "score": 0.88,
            }
        ]

        from app.tasks.email_scheduler import EmailScheduler

        scheduler = EmailScheduler(
            email_service=email_service_with_mocks,
            session_factory=test_db_session,
            redis_client=mock_redis,
            vector_store=mock_pinecone,
            use_pinecone=True,
            setup_jobs=False,
        )

        from app.models.company import CompanyProfile, CompanyCapability

        company = CompanyProfile(
            firm_id="FIRM-PINECONE",
            company_name="Pinecone Test Co",
            size=CompanySize.MEDIUM,
        )
        db.add(company)
        db.flush()

        cap = CompanyCapability(
            company_id=company.id,
            capability_text="Space systems",
            category="Technology",
        )
        db.add(cap)

        import uuid

        user = User(
            id=str(uuid.uuid4()),
            email="pinecone@test.com",
            hashed_password="dummy_hash_for_tests",
            full_name="Pinecone User",
            firm_id="FIRM-PINECONE",
            is_active=True,
        )
        db.add(user)
        db.commit()

        with patch("app.tasks.email_scheduler.LLMService") as mock_llm:
            mock_llm_instance = Mock()
            mock_llm_instance.generate_embeddings = Mock(return_value=[0.1] * 768)
            mock_llm.return_value = mock_llm_instance

            contracts = scheduler._get_contracts_from_pinecone(db, user, company)

        assert len(contracts) > 0
        assert contracts[0]["notice_id"] == "PINECONE-001"

        db.close()