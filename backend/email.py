"""SMTP email helper. Uses Hostinger SMTP (SSL on port 465 by default).
Zero new dependencies — stdlib smtplib + email.message.
Graceful no-op when smtp_host is blank (dev mode)."""

import logging
import smtplib
from email.message import EmailMessage

from backend.config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False on failure."""
    settings = get_settings()

    if not settings.smtp_host:
        logger.info("SMTP not configured — skipping email to %s (subject: %s)", to, subject)
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_user or settings.contact_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()

        if settings.smtp_user and settings.smtp_pass:
            server.login(settings.smtp_user, settings.smtp_pass)

        server.sendmail(msg["From"], to, msg.as_string())
        server.quit()
        logger.info("Email sent to %s (subject: %s)", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s (subject: %s)", to, subject)
        return False


def send_verification_email(to: str, token: str, base_url: str = "http://localhost:5173") -> bool:
    """Send the email verification link for a new registration."""
    link = f"{base_url}?verify={token}"
    subject = "Verify your Gadgents account"
    body = f"""Welcome to Gadgents!

Please verify your email address by clicking this link:

{link}

This link will expire after you use it. If you didn't create a Gadgents account, you can safely ignore this email.

— The Gadgents team"""
    return send_email(to, subject, body)


def send_password_reset_email(to: str, token: str, base_url: str = "http://localhost:5173") -> bool:
    """Send a password reset link."""
    link = f"{base_url}?reset={token}"
    subject = "Reset your Gadgents password"
    body = f"""A password reset was requested for your Gadgents account.

Click this link to choose a new password:

{link}

If you didn't request this, you can safely ignore this email.

— The Gadgents team"""
    return send_email(to, subject, body)
