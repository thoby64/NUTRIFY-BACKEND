"""
Email Service Utility
Handles sending emails for password resets and notifications
Supports multiple providers: SMTP, SendGrid, Mailgun
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service for sending password reset and notification emails
    Configuration via environment variables
    """
    
    def __init__(self):
        self.provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()
        
        if self.provider == "smtp":
            self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
            self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
            self.sender_email = os.getenv("SENDER_EMAIL")
            self.sender_password = os.getenv("SENDER_PASSWORD")
            self.sender_name = os.getenv("SENDER_NAME", "Nutrition Analytics")
            
            if not self.sender_email or not self.sender_password:
                raise ValueError("SENDER_EMAIL and SENDER_PASSWORD must be set for SMTP provider")
        
        elif self.provider == "sendgrid":
            self.sendgrid_key = os.getenv("SENDGRID_API_KEY")
            self.sender_email = os.getenv("SENDER_EMAIL")
            self.sender_name = os.getenv("SENDER_NAME", "Nutrition Analytics")
            
            if not self.sendgrid_key or not self.sender_email:
                raise ValueError("SENDGRID_API_KEY and SENDER_EMAIL must be set for SendGrid provider")
        
        elif self.provider == "mailgun":
            self.mailgun_key = os.getenv("MAILGUN_API_KEY")
            self.mailgun_domain = os.getenv("MAILGUN_DOMAIN")
            self.sender_email = os.getenv("SENDER_EMAIL")
            self.sender_name = os.getenv("SENDER_NAME", "Nutrition Analytics")
            
            if not self.mailgun_key or not self.mailgun_domain or not self.sender_email:
                raise ValueError("MAILGUN_API_KEY, MAILGUN_DOMAIN, and SENDER_EMAIL must be set for Mailgun provider")
    
    def send_password_reset_email(
        self, 
        recipient_email: str, 
        username: str, 
        reset_link: str,
        expires_in_hours: int = 1
    ) -> bool:
        """
        Send password reset email via configured provider
        
        Args:
            recipient_email: Recipient's email address
            username: User's username
            reset_link: Full reset link (e.g., http://localhost:5000/reset-password?token=xxx)
            expires_in_hours: How long the reset link is valid for
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        
        subject = "Password Reset Request - Nutrition Analytics"
        
        # HTML email template
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
                    
                    <!-- Header -->
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px 20px; text-align: center; color: white;">
                        <h1 style="margin: 0; font-size: 28px;">Nutrition Analytics</h1>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">Password Reset Request</p>
                    </div>
                    
                    <!-- Body -->
                    <div style="padding: 30px 20px;">
                        <p>Hello <strong>{username}</strong>,</p>
                        
                        <p>We received a request to reset your password. Click the button below to create a new password:</p>
                        
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{reset_link}" 
                               style="display: inline-block; padding: 12px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
                                Reset Password
                            </a>
                        </div>
                        
                        <p>Or copy and paste this link in your browser:</p>
                        <p style="background: #f5f5f5; padding: 10px; border-radius: 4px; word-break: break-all; font-size: 12px;">
                            {reset_link}
                        </p>
                        
                        <p style="color: #e74c3c;"><strong>⚠️ Security Warning:</strong></p>
                        <ul style="color: #666;">
                            <li>This link expires in <strong>{expires_in_hours} hour(s)</strong></li>
                            <li>If you didn't request this, please ignore this email</li>
                            <li>Never share this link with anyone</li>
                        </ul>
                        
                        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                        <p style="font-size: 12px; color: #999; margin: 0;">
                            This is an automated email. Please do not reply to this address.
                        </p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        try:
            if self.provider == "smtp":
                return self._send_via_smtp(recipient_email, subject, html_body)
            elif self.provider == "sendgrid":
                return self._send_via_sendgrid(recipient_email, subject, html_body)
            elif self.provider == "mailgun":
                return self._send_via_mailgun(recipient_email, subject, html_body)
            else:
                logger.error(f"Unknown email provider: {self.provider}")
                return False
        except Exception as e:
            logger.error(f"Error sending password reset email to {recipient_email}: {str(e)}")
            return False
    
    def _send_via_smtp(self, recipient_email: str, subject: str, html_body: str) -> bool:
        """Send email via SMTP (Gmail, Outlook, custom SMTP)"""
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.sender_name} <{self.sender_email}>"
            message["To"] = recipient_email
            
            # Attach HTML
            message.attach(MIMEText(html_body, "html"))
            
            # Connect and send
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, message.as_string())
            
            logger.info(f"Password reset email sent to {recipient_email}")
            return True
        
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending to {recipient_email}: {str(e)}")
            return False
    
    def _send_via_sendgrid(self, recipient_email: str, subject: str, html_body: str) -> bool:
        """Send email via SendGrid API"""
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.sendgrid_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "personalizations": [{
                    "to": [{"email": recipient_email}]
                }],
                "from": {
                    "email": self.sender_email,
                    "name": self.sender_name
                },
                "subject": subject,
                "content": [{
                    "type": "text/html",
                    "value": html_body
                }]
            }
            
            response = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers=headers
            )
            
            if response.status_code == 202:
                logger.info(f"Password reset email sent to {recipient_email} via SendGrid")
                return True
            else:
                logger.error(f"SendGrid error: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            logger.error(f"SendGrid error sending to {recipient_email}: {str(e)}")
            return False
    
    def _send_via_mailgun(self, recipient_email: str, subject: str, html_body: str) -> bool:
        """Send email via Mailgun API"""
        try:
            import requests
            
            auth = ("api", self.mailgun_key)
            payload = {
                "from": f"{self.sender_name} <{self.sender_email}>",
                "to": recipient_email,
                "subject": subject,
                "html": html_body
            }
            
            response = requests.post(
                f"https://api.mailgun.net/v3/{self.mailgun_domain}/messages",
                auth=auth,
                data=payload
            )
            
            if response.status_code == 200:
                logger.info(f"Password reset email sent to {recipient_email} via Mailgun")
                return True
            else:
                logger.error(f"Mailgun error: {response.status_code} - {response.text}")
                return False
        
        except Exception as e:
            logger.error(f"Mailgun error sending to {recipient_email}: {str(e)}")
            return False


# Singleton instance
_email_service = None


def get_email_service() -> EmailService:
    """Get or create email service instance"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
