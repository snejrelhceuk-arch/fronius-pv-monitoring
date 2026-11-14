#!/usr/bin/env python3
"""scripts/pv_notify.py — Gemeinsamer, defensiver Mail-Versand fuer Ops-Automatik.

Buendelt den Produktiv-SMTP-Pfad (``config.NOTIFICATION_*`` + verschluesselter
``credential_store``), den auch der Tagesbericht und der Wartungs-Melder nutzen.
Von den Wartungs-/Drift-/Abgleich-Timern importiert, damit der Versandcode nicht
mehrfach driftet.

Alle Funktionen sind vollstaendig defensiv: fehlende Config/Credentials fuehren
nie zu einer Exception, sondern zu ``False`` — die aufrufenden Oneshot-Timer
sollen niemals ``failed`` melden.
"""
from __future__ import annotations

import os
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Robust gegen kaputte System-Locale (LC_ALL=de_DE -> latin-1).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def host_label() -> str:
    """``hostname (rolle)`` — identisch zum Wartungs-Melder."""
    role = ""
    try:
        with open(os.path.join(REPO_ROOT, ".role")) as f:
            role = f.read().strip()
    except OSError:
        pass
    host = socket.gethostname()
    return f"{host} ({role})" if role else host


def send_mail(subject: str, body: str, event: str = "ops_automation",
              timeout: float = 12.0) -> bool:
    """Versendet ueber den Produktiv-SMTP-Pfad. Gibt Erfolg als bool zurueck."""
    try:
        import config
    except Exception:
        return False
    recipient = getattr(config, "NOTIFICATION_EMAIL", "") or ""
    smtp_host = getattr(config, "NOTIFICATION_SMTP_HOST", "") or ""
    smtp_port = getattr(config, "NOTIFICATION_SMTP_PORT", 465)
    smtp_user = getattr(config, "NOTIFICATION_SMTP_USER", "") or ""
    smtp_from = getattr(config, "NOTIFICATION_FROM", smtp_user) or smtp_user
    if not recipient or not smtp_host or smtp_host.endswith(".invalid"):
        return False
    smtp_pass = None
    try:
        from automation.engine import credential_store
        smtp_pass = credential_store.lade("smtp_pass")
    except Exception:
        smtp_pass = None
    if smtp_user and not smtp_pass:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg["X-PV-Event"] = event
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ctx) as srv:
            if smtp_user and smtp_pass:
                srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return True
    except Exception:
        return False
