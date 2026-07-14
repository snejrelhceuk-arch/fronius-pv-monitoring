"""nq.collector.nq_limit_mail — Sofort-Alarm-Mail bei NQ-Grenzwertüberschreitung (Rolle N).

Best-effort, **defensiv**: der Tech-Collector wertet die verifiziert gelesenen
Skalare (U/I/FREQ/THD) gegen ``config/nq_config.json`` → ``grenzwerte`` aus. Bei
dauerhafter Überschreitung (>``limit_window_s``) meldet die ``LimitMonitor``-
Zustandsmaschine (``nq_poller``) einen Alarm. Diese Datei versendet ihn per Mail
über denselben SMTP-Pfad wie das Produktivsystem (``config.NOTIFICATION_*`` +
``credential_store``).

Rollen-Hinweis: Tech (Rolle N) ist read-only ggü. Produktion. Mail ist kein
Produktions-Schreibpfad. Ist der Credential-Store auf Tech nicht provisioniert
(Machine-ID-gebunden), schlägt der Versand still fehl — der Alarm bleibt in
``nq_limit_alerts`` (tmpfs) persistiert und kann Primary-seitig nachverschickt
werden. Kein Blocking des Pollers: Aufruf immer in try/except + kurzer Timeout.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

LOG = logging.getLogger("nq.limit_mail")


def send_limit_mail(subject: str, body: str, timeout: float = 8.0) -> bool:
    """Versendet eine Grenzwert-Alarm-Mail. Returns True bei Erfolg.

    Vollständig defensiv: jede Fehlerquelle (fehlende config, kein Passwort,
    SMTP nicht erreichbar) führt zu ``return False`` ohne Exception, damit der
    aufrufende Poller nie blockiert oder crasht.
    """
    try:
        import config
    except Exception:
        LOG.debug("config nicht importierbar — Limit-Mail übersprungen")
        return False

    recipient = getattr(config, "NOTIFICATION_EMAIL", "") or ""
    smtp_host = getattr(config, "NOTIFICATION_SMTP_HOST", "") or ""
    smtp_port = getattr(config, "NOTIFICATION_SMTP_PORT", 465)
    smtp_user = getattr(config, "NOTIFICATION_SMTP_USER", "") or ""
    smtp_from = getattr(config, "NOTIFICATION_FROM", smtp_user) or smtp_user
    if not recipient or not smtp_host or smtp_host.endswith(".invalid"):
        LOG.debug("SMTP nicht konfiguriert — Limit-Mail übersprungen")
        return False

    smtp_pass = None
    try:
        from automation.engine import credential_store
        smtp_pass = credential_store.lade("smtp_pass")
    except Exception:
        smtp_pass = None
    if smtp_user and not smtp_pass:
        LOG.warning("SMTP-Passwort nicht verfügbar (credential_store) — Limit-Mail übersprungen")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg["X-PV-Event"] = "nq_limit_alert"
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ctx) as srv:
            if smtp_user and smtp_pass:
                srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        LOG.info("Limit-Alarm-Mail versendet: %s", subject)
        return True
    except Exception as exc:  # pragma: no cover - infra-abhängig
        LOG.warning("Limit-Mail-Versand fehlgeschlagen: %s", exc)
        return False
