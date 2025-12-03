"""
Email service for sending contract notifications using SendGrid.
"""
from datetime import datetime
from typing import List, Optional
import ssl
import certifi
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

os.environ['SSL_CERT_FILE'] = certifi.where()



class EmailService:
    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv("EMAIL_FROM", "noreply@contractdiscovery.com")
        self.client = SendGridAPIClient(self.api_key)
        
        # Set up Jinja2 for email templates
        template_dir = Path(__file__).parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml'])
        )
    
    def send_new_contracts_email(
        self,
        to_email: str,
        user_name: str,
        contracts: List[dict],
        total_new_contracts: int
    ) -> bool:
        """
        Send daily email with new matching contracts.
        
        Args:
            to_email: Recipient email
            user_name: User's name for personalization
            contracts: List of top 3-5 matching contracts with scores
            total_new_contracts: Total count of new matches
        
        Returns:
            True if sent successfully
        """
        try:
            # Render email template
            template = self.env.get_template("email_new_contracts.html")
            html_content = template.render(
                user_name=user_name,
                contracts=contracts,
                total_new_contracts=total_new_contracts,
                dashboard_url=os.getenv("FRONTEND_URL", "http://localhost:3000"),
                unsubscribe_url=f"{os.getenv('FRONTEND_URL')}/settings"
            )
            
            # Create email
            message = Mail(
                from_email=Email(self.from_email, "Contract Discovery"),
                to_emails=To(to_email),
                subject=f"🎯 {total_new_contracts} new contracts match your profile",
                html_content=Content("text/html", html_content)
            )
            
            # Send
            response = self.client.send(message)
            return response.status_code == 202
            
        except Exception as e:
            print(f"Error sending new contracts email to {to_email}: {e}")
            return False
    
    def send_deadline_reminder_email(
        self,
        to_email: str,
        user_name: str,
        contract: dict,
        days_until_deadline: int
    ) -> bool:
        """
        Send deadline reminder for a saved contract.
        
        Args:
            to_email: Recipient email
            user_name: User's name
            contract: Contract details (title, deadline, notice_id, etc.)
            days_until_deadline: 7, 3, or 1 days
        
        Returns:
            True if sent successfully
        """
        try:
            template = self.env.get_template("email_deadline_reminder.html")
            html_content = template.render(
                user_name=user_name,
                contract=contract,
                days_until_deadline=days_until_deadline,
                contract_url=f"{os.getenv('FRONTEND_URL')}/contracts/{contract['notice_id']}",
                unsubscribe_url=f"{os.getenv('FRONTEND_URL')}/settings"
            )
            
            # Set urgency based on days remaining
            urgency = "🚨" if days_until_deadline == 1 else "⏰"
            
            message = Mail(
                from_email=Email(self.from_email, "Contract Discovery"),
                to_emails=To(to_email),
                subject=f"{urgency} Deadline in {days_until_deadline} day{'s' if days_until_deadline > 1 else ''}: {contract['title'][:50]}...",
                html_content=Content("text/html", html_content)
            )
            
            response = self.client.send(message)
            return response.status_code == 202
            
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
        contracts: List[dict]
    ) -> bool:
        """
        Send quickstart report email with top contract matches.
        
        Args:
            to_email: Recipient email
            company_name: Extracted company name
            website_url: Company website analyzed
            capabilities_preview: Preview of capabilities (500 chars)
            pages_scraped: Number of pages analyzed
            total_matches: Total contracts found
            contracts: Top 3 contracts with match scores
        
        Returns:
            True if sent successfully
        """
        try:
            # Render email template
            template = self.env.get_template("email_quickstart_report.html")
            html_content = template.render(
                company_name=company_name,
                website_url=website_url,
                capabilities_preview=capabilities_preview,
                pages_scraped=pages_scraped,
                total_matches=total_matches,
                contracts=contracts,
                signup_url=f"{os.getenv('FRONTEND_URL')}/signup?from=email_report",
                frontend_url=os.getenv('FRONTEND_URL', 'http://localhost:3000')
            )
            
            # Create email
            message = Mail(
                from_email=Email(self.from_email, "BidMatch"),
                to_emails=To(to_email),
                subject=f"Your BidMatch Contract Report - {total_matches} Matches Found",
                html_content=Content("text/html", html_content)
            )
            
            # Send
            response = self.client.send(message)
            return response.status_code == 202
            
        except Exception as e:
            print(f"Error sending quickstart report to {to_email}: {e}")
            return False
    
    
    def test_connection(self) -> bool:
        """Test SendGrid connection."""
        try:
            # Send a test email to verify setup
            return self.api_key is not None and len(self.api_key) > 0
        except Exception as e:
            print(f"SendGrid connection test failed: {e}")
            return False


# Singleton instance
email_service = EmailService()