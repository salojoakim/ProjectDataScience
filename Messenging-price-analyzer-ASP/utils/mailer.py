"""
Send the HTML summary via SMTP or save it locally in DRY_RUN mode.

Modes:
- DRY_RUN=true  → write HTML to logs/outbox/summary_*.html (no SMTP)
- DRY_RUN=false → send email via SMTP (STARTTLS optional)

Env (read by the app or this module):
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TO, SMTP_STARTTLS
- DRY_RUN

This module focuses on a tiny "send or save" contract to keep the app logic simple.
"""


import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "")
SMTP_TO = [s.strip() for s in os.getenv("SMTP_TO", "").split(",") if s.strip()]
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")


def send_email(subject: str, html_body: str, to: list[str] | None = None):
    """
    Skickar HTML-mail – eller sparar till fil om DRY_RUN=true.
    """
    if DRY_RUN or not SMTP_HOST or not (SMTP_TO or to):
        os.makedirs("logs/outbox", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"logs/outbox/summary_{ts}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"💾 DRY-RUN: sparade e-post som HTML: {path}")
        return

    recipients = to or SMTP_TO
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content("Your email client does not support HTML.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        if SMTP_STARTTLS:
            s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
