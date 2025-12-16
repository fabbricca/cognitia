"""Email notification service for subscription events."""

import logging
import os
from typing import Optional
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)

# Email configuration
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "console")  # console, sendgrid, smtp
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@cognitia.ai")
FROM_NAME = os.getenv("FROM_NAME", "Cognitia")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@cognitia.ai")


class EmailService:
    """
    Service for sending transactional emails.

    Supports multiple backends:
    - console: Print to console (development)
    - sendgrid: SendGrid API
    - smtp: Standard SMTP
    """

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """
        Send an email using the configured backend.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email body
            text_content: Plain text email body (optional)

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if EMAIL_BACKEND == "sendgrid":
                return await EmailService._send_sendgrid(
                    to_email, subject, html_content, text_content
                )
            elif EMAIL_BACKEND == "smtp":
                return await EmailService._send_smtp(
                    to_email, subject, html_content, text_content
                )
            else:  # console
                return await EmailService._send_console(
                    to_email, subject, html_content
                )
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)
            return False

    @staticmethod
    async def _send_console(to_email: str, subject: str, html_content: str) -> bool:
        """Print email to console (development)."""
        logger.info(f"""
========== EMAIL ==========
To: {to_email}
Subject: {subject}
---
{html_content}
===========================
        """)
        return True

    @staticmethod
    async def _send_sendgrid(
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str]
    ) -> bool:
        """Send email via SendGrid API."""
        if not SENDGRID_API_KEY:
            logger.warning("SendGrid API key not configured")
            return False

        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Email, To, Content

            sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)

            message = Mail(
                from_email=Email(FROM_EMAIL, FROM_NAME),
                to_emails=To(to_email),
                subject=subject,
                html_content=Content("text/html", html_content)
            )

            if text_content:
                message.plain_text_content = Content("text/plain", text_content)

            # Send in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, sg.send, message)

            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"Email sent to {to_email} via SendGrid")
                return True
            else:
                logger.error(f"SendGrid error {response.status_code}: {response.body}")
                return False

        except ImportError:
            logger.error("sendgrid package not installed. Run: pip install sendgrid")
            return False
        except Exception as e:
            logger.error(f"SendGrid send failed: {e}", exc_info=True)
            return False

    @staticmethod
    async def _send_smtp(
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str]
    ) -> bool:
        """Send email via SMTP."""
        if not SMTP_USER or not SMTP_PASSWORD:
            logger.warning("SMTP credentials not configured")
            return False

        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
            msg['To'] = to_email

            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            # Send in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                EmailService._smtp_send_sync,
                msg,
                to_email
            )

            logger.info(f"Email sent to {to_email} via SMTP")
            return True

        except Exception as e:
            logger.error(f"SMTP send failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _smtp_send_sync(msg, to_email: str):
        """Synchronous SMTP send for executor."""
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

    # ===================
    # Email Templates
    # ===================

    @staticmethod
    async def send_usage_warning(
        to_email: str,
        user_name: str,
        resource_type: str,  # "messages" or "audio"
        used: int,
        limit: int,
        percentage: float,
        plan_name: str
    ) -> bool:
        """Send usage warning email (80%, 90%, or 100%)."""
        if percentage >= 100:
            level = "Limit Reached"
            message = f"You've used all {limit} {resource_type} for today."
            color = "#ef4444"
        elif percentage >= 90:
            level = "90% Used"
            message = f"You've used {used} of {limit} {resource_type} today."
            color = "#f59e0b"
        else:
            level = "80% Used"
            message = f"You've used {used} of {limit} {resource_type} today."
            color = "#fbbf24"

        subject = f"Cognitia: {level} - {resource_type.capitalize()}"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .warning-box {{ background: {color}15; border-left: 4px solid {color}; padding: 16px; margin: 20px 0; border-radius: 8px; }}
        .progress-bar {{ background: #e4e9f2; height: 12px; border-radius: 6px; overflow: hidden; margin: 12px 0; }}
        .progress-fill {{ background: {color}; height: 100%; width: {percentage}%; transition: width 0.3s; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Usage Alert</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <div class="warning-box">
                <strong>{level}</strong> - {message}
            </div>

            <div class="progress-bar">
                <div class="progress-fill"></div>
            </div>

            <p>You're currently on the <strong>{plan_name}</strong> plan. Your usage resets at midnight UTC.</p>

            <p>Need more? Upgrade to get higher limits and unlock premium features:</p>

            <a href="https://cognitia.ai/pricing.html" class="btn">View Upgrade Options</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                Your current plan limits:
                <br>• Messages per day: Available in your dashboard
                <br>• Audio minutes per day: Available in your dashboard
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
            <p>You're receiving this because you have a Cognitia account.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)

    @staticmethod
    async def send_payment_success(
        to_email: str,
        user_name: str,
        plan_name: str,
        amount: float,
        transaction_id: str
    ) -> bool:
        """Send payment success confirmation email."""
        subject = "Cognitia: Payment Successful"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .success-box {{ background: #10b98115; border-left: 4px solid #10b981; padding: 16px; margin: 20px 0; border-radius: 8px; }}
        .invoice {{ background: #f7f9fc; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .invoice-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e4e9f2; }}
        .invoice-row:last-child {{ border-bottom: none; font-weight: 600; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Payment Successful! 🎉</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <div class="success-box">
                Thank you for your payment! Your subscription has been activated.
            </div>

            <div class="invoice">
                <div class="invoice-row">
                    <span>Plan:</span>
                    <span>{plan_name}</span>
                </div>
                <div class="invoice-row">
                    <span>Amount Paid:</span>
                    <span>${amount:.2f}</span>
                </div>
                <div class="invoice-row">
                    <span>Transaction ID:</span>
                    <span>{transaction_id}</span>
                </div>
                <div class="invoice-row">
                    <span>Date:</span>
                    <span>{datetime.utcnow().strftime('%B %d, %Y')}</span>
                </div>
            </div>

            <p>You now have access to all {plan_name} features. Start creating amazing AI characters today!</p>

            <a href="https://cognitia.ai" class="btn">Go to Dashboard</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                Questions about your subscription? Contact us at support@cognitia.ai
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
            <p>This is a receipt for your payment.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)

    @staticmethod
    async def send_payment_failed(
        to_email: str,
        user_name: str,
        plan_name: str,
        reason: Optional[str] = None
    ) -> bool:
        """Send payment failed notification."""
        subject = "Cognitia: Payment Failed"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .error-box {{ background: #ef444415; border-left: 4px solid #ef4444; padding: 16px; margin: 20px 0; border-radius: 8px; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Payment Issue</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <div class="error-box">
                We were unable to process your payment for the {plan_name} plan.
                {f'<br><br><strong>Reason:</strong> {reason}' if reason else ''}
            </div>

            <p>To continue enjoying your subscription benefits, please update your payment method.</p>

            <a href="https://cognitia.ai/billing" class="btn">Update Payment Method</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                Common reasons for payment failures:
                <br>• Insufficient funds
                <br>• Expired card
                <br>• Incorrect billing information
            </p>

            <p style="color: #6f767e; font-size: 14px;">
                Need help? Contact support@cognitia.ai
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)

    @staticmethod
    async def send_subscription_canceled(
        to_email: str,
        user_name: str,
        plan_name: str,
        end_date: str
    ) -> bool:
        """Send subscription cancellation confirmation."""
        subject = "Cognitia: Subscription Canceled"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .info-box {{ background: #fbbf2415; border-left: 4px solid #fbbf24; padding: 16px; margin: 20px 0; border-radius: 8px; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Subscription Canceled</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <p>We're sorry to see you go. Your {plan_name} subscription has been canceled.</p>

            <div class="info-box">
                <strong>Important:</strong> You'll continue to have access to {plan_name} features until <strong>{end_date}</strong>.
            </div>

            <p>After that date, your account will be downgraded to the Free plan.</p>

            <p>Changed your mind? You can reactivate your subscription anytime.</p>

            <a href="https://cognitia.ai/pricing.html" class="btn">Reactivate Subscription</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                We'd love to hear your feedback. What could we improve?
                <br>Reply to this email or contact support@cognitia.ai
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)

    @staticmethod
    async def send_admin_new_subscription(
        plan_name: str,
        user_email: str,
        amount: float
    ) -> bool:
        """Notify admin of new paid subscription."""
        subject = f"New {plan_name} Subscription - {user_email}"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: monospace; line-height: 1.6; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .content {{ background: white; padding: 20px; border-radius: 8px; }}
        .data {{ background: #f9f9f9; padding: 12px; margin: 12px 0; border-left: 3px solid #10b981; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <h2>🎉 New Subscription</h2>

            <div class="data">
                <strong>User:</strong> {user_email}<br>
                <strong>Plan:</strong> {plan_name}<br>
                <strong>Amount:</strong> ${amount:.2f}<br>
                <strong>Date:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
            </div>

            <p><a href="https://cognitia.ai/admin.html">View Admin Dashboard</a></p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(ADMIN_EMAIL, subject, html)

    @staticmethod
    async def send_verification_email(
        to_email: str,
        user_name: str,
        verification_token: str
    ) -> bool:
        """Send email verification link."""
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")
        verification_url = f"{frontend_url}/verify-email?token={verification_token}"

        subject = "Cognitia: Verify Your Email"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .code-box {{ background: #f7f9fc; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 18px; text-align: center; margin: 20px 0; letter-spacing: 2px; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome to Cognitia! 🎉</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <p>Thank you for signing up! Please verify your email address to activate your account.</p>

            <a href="{verification_url}" class="btn">Verify Email Address</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                Or copy and paste this link into your browser:
                <br><a href="{verification_url}" style="color: #667eea; word-break: break-all;">{verification_url}</a>
            </p>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                This verification link will expire in 24 hours.
            </p>

            <p style="margin-top: 20px; color: #6f767e; font-size: 14px;">
                If you didn't create a Cognitia account, you can safely ignore this email.
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)

    @staticmethod
    async def send_password_reset_email(
        to_email: str,
        user_name: str,
        reset_token: str
    ) -> bool:
        """Send password reset link."""
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")
        reset_url = f"{frontend_url}/reset-password?token={reset_token}"

        subject = "Cognitia: Reset Your Password"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1a1d1f; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
        .content {{ background: #ffffff; padding: 30px; border: 1px solid #e4e9f2; border-radius: 0 0 12px 12px; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 16px 0; }}
        .warning-box {{ background: #fbbf2415; border-left: 4px solid #fbbf24; padding: 16px; margin: 20px 0; border-radius: 8px; }}
        .footer {{ text-align: center; color: #6f767e; font-size: 13px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Password Reset Request</h1>
        </div>
        <div class="content">
            <p>Hi {user_name},</p>

            <p>We received a request to reset your Cognitia password. Click the button below to create a new password:</p>

            <a href="{reset_url}" class="btn">Reset Password</a>

            <p style="margin-top: 30px; color: #6f767e; font-size: 14px;">
                Or copy and paste this link into your browser:
                <br><a href="{reset_url}" style="color: #667eea; word-break: break-all;">{reset_url}</a>
            </p>

            <div class="warning-box">
                <strong>Security Notice:</strong> This password reset link will expire in 1 hour.
            </div>

            <p style="color: #6f767e; font-size: 14px;">
                If you didn't request a password reset, please ignore this email. Your password will remain unchanged.
            </p>

            <p style="margin-top: 20px; color: #6f767e; font-size: 14px;">
                For security reasons, never share this link with anyone.
            </p>
        </div>
        <div class="footer">
            <p>© 2025 Cognitia. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
        """

        return await EmailService.send_email(to_email, subject, html)


# Singleton instance
email_service = EmailService()
