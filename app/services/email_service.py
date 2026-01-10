"""
Email service for sending contract notifications using Resend.
✅ REFACTORED: Switched from SendGrid to Resend
✅ FIXED: FRONTEND_URL handling, improved testability
"""
from datetime import datetime
from typing import List, Optional
import os
import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

# Configure Resend
resend.api_key = os.getenv("RESEND_API_KEY")


class EmailService:
    def __init__(
        self,
        *,
        env: Optional[Environment] = None,            # 🔧 TESTABILITY
        template_dir: Optional[Path] = None,          # 🔧 TESTABILITY
    ):
        self.from_email = os.getenv("EMAIL_FROM", "noreply@bidmatch.co")

        # 🔧 TESTABILITY: inject Jinja env
        if env:
            self.env = env
        else:
            template_dir = template_dir or (Path(__file__).parent.parent / "templates")
            self.env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(["html", "xml"]),
            )

    @staticmethod
    def _frontend_url() -> str:
        """
        Get frontend URL with proper fallback handling.
        ✅ FIXED: No more "None/settings" bug
        """
        url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        
        # Handle None/empty/invalid values
        if url == "None" or not url or url.strip() == "":
            return "http://localhost:3000"
        
        # Remove trailing slash for consistency
        return url.rstrip("/")

    def send_new_contracts_email(
        self,
        to_email: str,
        user_name: str,
        contracts: List[dict],
        total_new_contracts: int,
    ) -> bool:
        """
        Send daily digest email with new matching contracts.
        
        Args:
            to_email: Recipient email address
            user_name: User's full name
            contracts: List of contract dicts (top 5 for email)
            total_new_contracts: Total count of new matches
            
        Returns:
            bool: True if email sent successfully
        """
        try:
            frontend_url = self._frontend_url()

            template = self.env.get_template("email_new_contracts.html")
            html_content = template.render(
                user_name=user_name,
                contracts=contracts,
                total_new_contracts=total_new_contracts,
                dashboard_url=frontend_url,
                unsubscribe_url=f"{frontend_url}/settings",
            )

            resend.Emails.send({
                "from": f"BidMatch <{self.from_email}>",
                "to": to_email,
                "subject": f"🎯 {total_new_contracts} new contracts match your profile",
                "html": html_content
            })

            return True

        except Exception as e:
            print(f"Error sending new contracts email to {to_email}: {e}")
            return False

    def send_deadline_reminder_email(
        self,
        to_email: str,
        user_name: str,
        contract: dict,
        days_until_deadline: int,
    ) -> bool:
        """
        Send deadline reminder for saved contracts.
        
        Args:
            to_email: Recipient email address
            user_name: User's full name
            contract: Contract dict with notice_id, title, etc.
            days_until_deadline: Days remaining (7, 3, or 1)
            
        Returns:
            bool: True if email sent successfully
        """
        try:
            frontend_url = self._frontend_url()

            template = self.env.get_template("email_deadline_reminder.html")
            html_content = template.render(
                user_name=user_name,
                contract=contract,
                days_until_deadline=days_until_deadline,
                contract_url=f"{frontend_url}/contracts/{contract['notice_id']}",
                dashboard_url=frontend_url,
                unsubscribe_url=f"{frontend_url}/settings",
            )

            urgency = "🚨" if days_until_deadline == 1 else "⏰"

            resend.Emails.send({
                "from": f"BidMatch <{self.from_email}>",
                "to": to_email,
                "subject": (
                    f"{urgency} Deadline in {days_until_deadline} "
                    f"day{'s' if days_until_deadline > 1 else ''}: "
                    f"{contract['title'][:50]}..."
                ),
                "html": html_content
            })

            return True

        except Exception as e:
            print(f"Error sending deadline reminder to {to_email}: {e}")
            return False

    def send_quickstart_report(
        self,
        to_email: str,
        company_name: str,
        website_url: str,
        capabilities_preview: str,
        pages_scraped: int,
        total_matches: int,
        contracts: List[dict],
    ) -> bool:
        """
        Send quickstart report for new users (website scraping results).
        
        Args:
            to_email: Recipient email address
            company_name: Company name
            website_url: Website that was scraped
            capabilities_preview: Preview of detected capabilities
            pages_scraped: Number of pages analyzed
            total_matches: Total contracts matched
            contracts: List of top matching contracts
            
        Returns:
            bool: True if email sent successfully
        """
        try:
            frontend_url = self._frontend_url()

            template = self.env.get_template("email_quickstart_report.html")
            html_content = template.render(
                company_name=company_name,
                website_url=website_url,
                capabilities_preview=capabilities_preview,
                pages_scraped=pages_scraped,
                total_matches=total_matches,
                contracts=contracts,
                signup_url=f"{frontend_url}/signup?from=email_report",
                frontend_url=frontend_url,
            )

            resend.Emails.send({
                "from": f"BidMatch <{self.from_email}>",
                "to": to_email,
                "subject": f"Your BidMatch Contract Report - {total_matches} Matches Found",
                "html": html_content
            })

            return True

        except Exception as e:
            print(f"Error sending quickstart report to {to_email}: {e}")
            return False

    def test_connection(self) -> bool:
        """Test if Resend is properly configured."""
        return bool(os.getenv("RESEND_API_KEY"))


# ✅ Production singleton preserved
email_service = EmailService()