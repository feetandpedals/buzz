"""Mail slot (optional): sends password-reset codes by email through an SMTP mailbox you own
(for example a Gmail address with an app password). The settings are kept in Windows Credential Manager
(service ai-reel-studio, entry smtp), never in a file. Without them, resets go through the owner in Settings."""
import json
import smtplib
import ssl
from email.message import EmailMessage

import keyring

SERVICE, ENTRY = "ai-reel-studio", "smtp"


def config():
    try:
        raw = keyring.get_password(SERVICE, ENTRY)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def available():
    return bool(config())


def save(host, port, user, password, sender=None):
    keyring.set_password(SERVICE, ENTRY, json.dumps({"host": host.strip(), "port": int(port), "user": user.strip(),
                                                      "password": password, "from": (sender or user).strip()}))


def clear():
    try:
        keyring.delete_password(SERVICE, ENTRY)
    except Exception:
        pass


def send(to, subject, body):
    c = config()
    if not c:
        raise RuntimeError("Email sending is not set up.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = c["from"], to, subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if c["port"] == 465:
        with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=30) as s:
            s.login(c["user"], c["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(c["host"], c["port"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(c["user"], c["password"])
            s.send_message(msg)
