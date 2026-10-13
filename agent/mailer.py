"""Отправка полного отчёта на почту."""
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import markdown

from . import config


def is_configured() -> bool:
    return all((config.SMTP_HOST, config.SMTP_USER, config.SMTP_PASSWORD, config.REPORT_EMAIL_TO))


def send_report(subject: str, report_md: str, attachments: list[Path]) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = config.REPORT_EMAIL_TO
    msg.set_content(report_md)
    html = markdown.markdown(report_md, extensions=["tables"])
    msg.add_alternative(f"<html><body style='font-family:sans-serif'>{html}</body></html>",
                        subtype="html")
    for path in attachments:
        msg.add_attachment(path.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=path.name)

    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context) as s:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
            s.starttls(context=context)
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
