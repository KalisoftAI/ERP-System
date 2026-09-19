"""Email delivery service using SMTP (Gmail by default).

Credentials come exclusively from environment variables / .env and are never
logged or returned to callers.
"""
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(value: str) -> bool:
    return bool(value and EMAIL_RE.match(value.strip()))


def mail_config_ok() -> tuple[bool, str]:
    """Validate that the minimum SMTP configuration is present."""
    if not settings.MAIL_ENABLED:
        return False, "Email is not enabled in configuration."
    if not settings.MAIL_USERNAME or not settings.MAIL_PASSWORD:
        return False, "SMTP credentials are not configured."
    if not settings.SMTP_HOST or not settings.SMTP_PORT:
        return False, "SMTP host/port are not configured."
    return True, ""


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Send a plain-text/HTML email.

    Returns (success, message_or_error). Never logs or exposes the password.
    """
    if not is_valid_email(to):
        return False, f"Invalid recipient email address: {to}"

    ok, err = mail_config_ok()
    if not ok:
        return False, err

    sender = settings.MAIL_FROM or settings.MAIL_USERNAME
    sender_name = settings.MAIL_FROM_NAME or "Kalika Enterprises"

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to.strip()
    msg["Subject"] = subject.strip()

    # Render plain text from HTML by stripping tags is too lossy; keep both.
    # We accept body as simple text and also convert newlines to <br>.
    plain = body.strip()
    html = f"<html><body style='font-family:sans-serif;line-height:1.5'>{plain.replace(chr(10), '<br>')}</body></html>"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.ehlo()
            if settings.SMTP_USE_TLS:
                server.starttls()
                server.ehlo()
            # Password is passed directly to the SMTP library; never logged.
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.sendmail(sender, [to.strip()], msg.as_string())
        logger.info("Email sent to %s (subject: %s)", to.strip(), subject.strip())
        return True, ""
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("SMTP authentication failed for %s: %s", settings.MAIL_USERNAME, exc)
        return False, "SMTP authentication failed. Please check email credentials."
    except smtplib.SMTPConnectError as exc:
        logger.warning("Could not connect to SMTP server: %s", exc)
        return False, "Could not connect to email server. Please check SMTP settings."
    except smtplib.SMTPRecipientsRefused as exc:
        logger.warning("Recipient refused: %s", exc)
        return False, f"Email server refused recipient: {to}"
    except smtplib.SMTPException as exc:
        logger.warning("SMTP error sending email: %s", exc)
        return False, "Email server error. Please try again later."
    except Exception as exc:
        logger.warning("Unexpected error sending email: %s", exc)
        return False, "Unexpected error sending email. Please try again later."
