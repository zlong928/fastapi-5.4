from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import DEBUG_EMAIL_CODE, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USERNAME

logger = logging.getLogger(__name__)


def send_password_reset_code_email(email: str, code: str) -> None:
    if not SMTP_HOST:
        if DEBUG_EMAIL_CODE:
            logger.info("Password reset verification code for %s: %s", email, code)
        else:
            logger.info("Password reset verification email queued for %s", email)
        return

    message = EmailMessage()
    message["Subject"] = "Your password reset verification code"
    message["From"] = SMTP_FROM or SMTP_USERNAME
    message["To"] = email
    message.set_content(
        "Use this 6-digit verification code to reset your password. "
        "It expires in 5 minutes.\n\n"
        f"Verification code: {code}\n"
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        if SMTP_USERNAME and SMTP_PASSWORD:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)
