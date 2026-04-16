import logging
from email.message import EmailMessage
import aiosmtplib
from bot.notifications.config import load_channel

logger = logging.getLogger(__name__)


async def send_email(subject: str, body: str):
    config = await load_channel("email")
    host = config.get("smtp_host", "")
    to = config.get("email_to", "")
    if not host or not to:
        return
    await _send_with(
        host, config.get("smtp_port", 587),
        config.get("smtp_user", ""), config.get("smtp_pass", ""),
        to, subject, body,
    )


async def _send_with(host, port, user, password, to, subject, body):
    msg = EmailMessage()
    msg["From"] = user or "cryptobot@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    await aiosmtplib.send(
        msg, hostname=host, port=port,
        username=user or None, password=password or None,
        start_tls=True,
    )
    logger.info(f"Email sent: {subject}")


async def send_email_test(config: dict, subject: str, body: str) -> tuple[bool, str]:
    """Test email send with explicit config."""
    try:
        await _send_with(
            config.get("smtp_host", ""), config.get("smtp_port", 587),
            config.get("smtp_user", ""), config.get("smtp_pass", ""),
            config.get("email_to", ""), subject, body,
        )
        return True, ""
    except Exception as e:
        return False, str(e)[:300]
