"""
Tests for EmailService - Template rendering, SendGrid payloads, URL handling
✅ No real emails sent - all SendGrid calls are mocked
"""
import pytest
from unittest.mock import patch
from sendgrid.helpers.mail import Mail


class TestEmailServiceTemplateRendering:
    """Test that Jinja templates render correctly with all variables."""
    
    def test_new_contracts_email_renders_all_variables(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """New contracts email should render user name, contracts, and counts."""
        contracts = [
            {
                "notice_id": "TEST-001",
                "title": "Cloud Infrastructure Project",
                "buyer_name": "DOD",
                "value": "$5,000,000",
                "deadline": "15 January 2026",
                "match_score": 92,
                "match_reason": "Strong capability match"
            }
        ]
        
        success = email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="John Doe",
            contracts=contracts,
            total_new_contracts=5
        )
        
        assert success is True
        assert mock_sendgrid_client.send.call_count == 1
        
        # Verify HTML content was rendered
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        assert "Hi John Doe" in html_content
        assert "5 new contracts" in html_content
        assert "Cloud Infrastructure Project" in html_content
        assert "DOD" in html_content
        assert "$5,000,000" in html_content
        assert "92%" in html_content
    
    def test_deadline_reminder_email_renders_urgency(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Deadline reminder should render contract details and urgency."""
        contract = {
            "notice_id": "TEST-002",
            "title": "Security Audit Services",
            "buyer_name": "DHS",
            "value": "$1,500,000",
            "deadline": "10 January 2026",
            "status": "Bidding"
        }
        
        success = email_service_with_mocks.send_deadline_reminder_email(
            to_email="test@example.com",
            user_name="Jane Smith",
            contract=contract,
            days_until_deadline=3
        )
        
        assert success is True
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        assert "Hi Jane Smith" in html_content
        assert "3 days until deadline" in html_content
        assert "Security Audit Services" in html_content
        assert "DHS" in html_content
        assert "Bidding" in html_content
    
    def test_quickstart_report_renders_company_info(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Quickstart report should render company and scraping results."""
        contracts = [
            {"title": "Contract 1"},
            {"title": "Contract 2"}
        ]
        
        success = email_service_with_mocks.send_quickstart_report(
            to_email="test@example.com",
            company_name="Acme Corp",
            website_url="https://acme.com",
            capabilities_preview="Cloud, DevOps, Security",
            pages_scraped=15,
            total_matches=42,
            contracts=contracts
        )
        
        assert success is True
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        assert "Acme Corp" in html_content
        assert "https://acme.com" in html_content
        assert "Cloud, DevOps, Security" in html_content
        assert "15" in html_content  # pages scraped
        assert "42" in html_content  # total matches


class TestEmailServiceSendGridPayloads:
    """Test that SendGrid receives correctly formatted Mail objects."""
    
    def test_new_contracts_email_sendgrid_payload(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Verify SendGrid Mail object has correct to/from/subject."""
        contracts = [{"title": "Test", "buyer_name": "DOD", "value": "$1M", 
                     "deadline": "Jan 15", "match_score": 90, "match_reason": "Match"}]
        
        email_service_with_mocks.send_new_contracts_email(
            to_email="recipient@example.com",
            user_name="Test User",
            contracts=contracts,
            total_new_contracts=3
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        
        # Verify Mail object structure
        assert isinstance(mail_obj, Mail)
        # Note: from_email comes from EMAIL_FROM env var (defaults to noreply@contractdiscovery.com)
        assert mail_obj.from_email.email in ["noreply@contractdiscovery.com", "noreply@bidmatch.co"]
        assert mail_obj.from_email.name == "Contract Discovery"
        
        # Check recipient
        to_emails = mail_obj.personalizations[0].tos
        assert len(to_emails) == 1
        assert to_emails[0]['email'] == "recipient@example.com"
        
        # Check subject
        assert mail_obj.subject.subject == "🎯 3 new contracts match your profile"
    
    def test_deadline_reminder_subject_varies_by_urgency(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Deadline reminder subject should show urgency emoji and day count."""
        contract = {
            "notice_id": "TEST",
            "title": "Very Long Contract Title That Should Be Truncated",
            "buyer_name": "GSA",
            "value": "$500K",
            "deadline": "Soon",
            "status": "Bidding"
        }
        
        # Test 1 day urgency
        email_service_with_mocks.send_deadline_reminder_email(
            to_email="test@example.com",
            user_name="User",
            contract=contract,
            days_until_deadline=1
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        assert mail_obj.subject.subject.startswith("🚨 Deadline in 1 day:")
        assert "day:" in mail_obj.subject.subject  # Singular "day"
        
        # Test 7 day reminder
        email_service_with_mocks.send_deadline_reminder_email(
            to_email="test@example.com",
            user_name="User",
            contract=contract,
            days_until_deadline=7
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        assert mail_obj.subject.subject.startswith("⏰ Deadline in 7 days:")
        assert "days:" in mail_obj.subject.subject  # Plural "days"
    
    def test_sendgrid_returns_202_means_success(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """EmailService should return True when SendGrid returns 202."""
        mock_sendgrid_client.send.return_value.status_code = 202
        
        result = email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=[],
            total_new_contracts=0
        )
        
        assert result is True
    
    def test_sendgrid_non_202_means_failure(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """EmailService should return False when SendGrid returns non-202."""
        mock_sendgrid_client.send.return_value.status_code = 400
        
        result = email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=[],
            total_new_contracts=0
        )
        
        assert result is False


class TestFrontendURLHandling:
    """Test FRONTEND_URL environment variable handling and fallbacks."""
    
    def test_frontend_url_from_environment(
        self,
        email_service_with_mocks,
        mock_sendgrid_client,
        mock_frontend_url
    ):
        """Should use FRONTEND_URL from environment when set."""
        contracts = [{"title": "Test", "buyer_name": "DOD", "value": "$1M",
                     "deadline": "Jan 15", "match_score": 90, "match_reason": "Match"}]
        
        email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=contracts,
            total_new_contracts=1
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        # Should use environment variable
        assert "https://test.contractdiscovery.com" in html_content
        assert "https://test.contractdiscovery.com/settings" in html_content
    
    def test_frontend_url_handles_none_value(
        self,
        email_service_with_mocks,
        mock_sendgrid_client,
        mock_frontend_url_none
    ):
        """Should use default when FRONTEND_URL is 'None' string."""
        contracts = [{"title": "Test", "buyer_name": "DOD", "value": "$1M",
                     "deadline": "Jan 15", "match_score": 90, "match_reason": "Match"}]
        
        email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=contracts,
            total_new_contracts=1
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        # Should NOT have "None/settings" - should use default
        assert "None/settings" not in html_content
        assert "http://localhost:3000/settings" in html_content
    
    def test_frontend_url_defaults_when_unset(
        self,
        email_service_with_mocks,
        mock_sendgrid_client,
        mock_frontend_url_unset
    ):
        """Should use localhost default when FRONTEND_URL is not set."""
        contracts = [{"title": "Test", "buyer_name": "DOD", "value": "$1M",
                     "deadline": "Jan 15", "match_score": 90, "match_reason": "Match"}]
        
        email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=contracts,
            total_new_contracts=1
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        assert "http://localhost:3000" in html_content
    
    def test_frontend_url_strips_trailing_slash(self, email_service_with_mocks):
        """_frontend_url should strip trailing slashes for consistency."""
        with patch.dict('os.environ', {'FRONTEND_URL': 'https://example.com/'}):
            url = email_service_with_mocks._frontend_url()
            assert url == "https://example.com"
            assert not url.endswith("/")


class TestEmailServiceErrorHandling:
    """Test error handling and edge cases."""
    
    def test_sendgrid_exception_returns_false(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Should return False and not crash when SendGrid raises exception."""
        mock_sendgrid_client.send.side_effect = Exception("SendGrid API error")
        
        result = email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=[],
            total_new_contracts=0
        )
        
        assert result is False
    
    def test_empty_contracts_list_renders(
        self,
        email_service_with_mocks,
        mock_sendgrid_client
    ):
        """Should handle empty contracts list without crashing."""
        result = email_service_with_mocks.send_new_contracts_email(
            to_email="test@example.com",
            user_name="User",
            contracts=[],  # Empty list
            total_new_contracts=0
        )
        
        assert result is True
        assert mock_sendgrid_client.send.call_count == 1
    
    def test_test_connection_with_api_key(self, email_service_with_mocks):
        """test_connection should return True when API key exists."""
        with patch.dict('os.environ', {'SENDGRID_API_KEY': 'test-key'}):
            service = type(email_service_with_mocks)(
                client=email_service_with_mocks.client,
                env=email_service_with_mocks.env
            )
            service.api_key = 'test-key'
            assert service.test_connection() is True
    
    def test_test_connection_without_api_key(self, email_service_with_mocks):
        """test_connection should return False when API key is missing."""
        service = type(email_service_with_mocks)(
            client=email_service_with_mocks.client,
            env=email_service_with_mocks.env
        )
        service.api_key = None
        assert service.test_connection() is False


class TestContractURLGeneration:
    """Test that contract URLs are generated correctly."""
    
    def test_deadline_reminder_contract_url(
        self,
        email_service_with_mocks,
        mock_sendgrid_client,
        mock_frontend_url
    ):
        """Deadline reminder should include direct link to contract."""
        contract = {
            "notice_id": "CONTRACT-12345",
            "title": "Test Contract",
            "buyer_name": "DOD",
            "value": "$1M",
            "deadline": "Jan 15",
            "status": "Bidding"
        }
        
        email_service_with_mocks.send_deadline_reminder_email(
            to_email="test@example.com",
            user_name="User",
            contract=contract,
            days_until_deadline=3
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        # Should have direct contract link
        expected_url = "https://test.contractdiscovery.com/contracts/CONTRACT-12345"
        assert expected_url in html_content
    
    def test_quickstart_report_signup_url(
        self,
        email_service_with_mocks,
        mock_sendgrid_client,
        mock_frontend_url
    ):
        """Quickstart report should include signup URL with tracking param."""
        email_service_with_mocks.send_quickstart_report(
            to_email="test@example.com",
            company_name="Test Co",
            website_url="https://test.com",
            capabilities_preview="DevOps",
            pages_scraped=10,
            total_matches=20,
            contracts=[]
        )
        
        mail_obj = mock_sendgrid_client.send.call_args[0][0]
        html_content = mail_obj.contents[0].content
        
        # Should have signup URL with tracking
        expected_url = "https://test.contractdiscovery.com/signup?from=email_report"
        assert expected_url in html_content