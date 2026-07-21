from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def password_reset_email_configured() -> bool:
    return settings.password_reset_email_configured


def build_password_reset_url(token: str) -> str:
    base_url = settings.password_reset_base_url.strip().rstrip("/")
    query = urlencode({"resetToken": token})
    return f"{base_url}/?{query}"


def send_password_reset_email(
    *,
    to_email: str,
    display_name: str,
    reset_token: str,
) -> bool:
    """Send a password-reset email when SMTP has been configured."""

    if not password_reset_email_configured():
        return False

    reset_url = build_password_reset_url(reset_token)
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = "HY-chat 密码重置"
    message.set_content(
        "\n".join(
            [
                f"{display_name}，你好：",
                "",
                "我们收到了你的 HY-chat 密码找回请求。",
                f"请在 {settings.password_reset_token_minutes} 分钟内打开下面的链接重置密码：",
                reset_url,
                "",
                "如果不是你本人操作，可以忽略这封邮件。",
            ]
        )
    )

    smtp_client = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    try:
        with smtp_client(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout,
        ) as smtp:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception:
        logger.warning(
            "Failed to send password reset email to=%s", to_email, exc_info=True
        )
        return False

    logger.info("Password reset email sent to=%s", to_email)
    return True
