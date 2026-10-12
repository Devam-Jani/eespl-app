"""Email to our own staff. In development everything goes to the local Mailpit container (nothing
leaves the PC); real sending is switched on only at go-live with EMAIL_ENABLED=true and the SMTP
settings in .env. The settings are never logged or shown. (Microsoft 365: the sending mailbox
needs SMTP AUTH turned on.)"""

import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if settings.email_enabled:
        host, port = settings.smtp_host, settings.smtp_port
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(
                    settings.smtp_user,
                    settings.smtp_password.get_secret_value() if settings.smtp_password else "",
                )
            smtp.send_message(msg)
    else:  # development: the local Mailpit catches it
        with smtplib.SMTP(settings.mailpit_host, settings.mailpit_port, timeout=10) as smtp:
            smtp.send_message(msg)
