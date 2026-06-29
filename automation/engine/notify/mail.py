"""
automation/engine/notify/mail.py — SMTP-Transport für den EventNotifier.

Kapselt den Verbindungs-/Login-/Sende-/Schließ-Ablauf, der zuvor in
EventNotifier dreifach (Event-, Integrity-, Diagnos-Alarm) dupliziert war.
Verhalten verbatim erhalten (Refactor 2026-06-29): wirft bei Fehler, der
Aufrufer behandelt Exceptions + Logging wie bisher.
"""

from __future__ import annotations

import smtplib
from email.message import Message


def smtp_versand(host: str, port: int, user: str, password: str,
                 sender: str, empfaenger: str, msg: Message) -> None:
    """Sende eine vorbereitete Mail. Wirft bei Fehler (Aufrufer fängt ab).

    Port 465 → implizites SSL; Port 587 → STARTTLS; sonst Klartext.
    Login nur wenn user UND password gesetzt sind.
    """
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        smtp = smtplib.SMTP(host, port, timeout=15)
        if port == 587:
            smtp.starttls()
    try:
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(sender, [empfaenger], msg.as_string())
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
