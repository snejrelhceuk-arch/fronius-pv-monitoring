"""
event_notifier.py — Einmalige E-Mail-Benachrichtigung bei kritischen Events

Prüft ObsState gegen konfigurierte Schwellwerte und sendet einmalig
(1× pro Event-Typ pro Tag) eine E-Mail an config.NOTIFICATION_EMAIL.

Konfiguration:
  config.py:
    NOTIFICATION_EMAIL       — Empfänger
    NOTIFICATION_SMTP_HOST   — SMTP-Server (default: localhost)
    NOTIFICATION_EVENTS      — Liste aktiver Event-Keys
    EVENT_THRESHOLDS         — Schwellwert-Definitionen

Events werden über config.NOTIFICATION_EVENTS aktiviert/deaktiviert.
Neue Events: Einfach EVENT_THRESHOLDS in config.py erweitern und
den Key in NOTIFICATION_EVENTS aufnehmen.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md
"""

from __future__ import annotations

import logging
import smtplib
import socket
from dataclasses import asdict
from datetime import date, datetime
from email.mime.text import MIMEText
from typing import Optional

import config as app_config
from automation.engine import credential_store
from automation.engine.obs_state import ObsState

LOG = logging.getLogger('event_notifier')


class EventNotifier:
    """Einmalige E-Mail-Benachrichtigung bei kritischen Events.

    Deduplizierung: Jeder Event-Key wird maximal 1× pro Kalendertag
    gemeldet. Reset bei Tageswechsel.
    """

    def __init__(self):
        self._gesendet: dict[str, str] = {}  # event_key → ISO-Datum des Versands
        self._email = getattr(app_config, 'NOTIFICATION_EMAIL', '')
        self._smtp_host = getattr(app_config, 'NOTIFICATION_SMTP_HOST', 'smtp.strato.de')
        self._smtp_port = getattr(app_config, 'NOTIFICATION_SMTP_PORT', 465)
        self._smtp_user = getattr(app_config, 'NOTIFICATION_SMTP_USER', '')
        self._from = getattr(app_config, 'NOTIFICATION_FROM', 'navigator@hekabe.de')
        self._events = getattr(app_config, 'NOTIFICATION_EVENTS', [])
        self._thresholds = getattr(app_config, 'EVENT_THRESHOLDS', {})

    def prüfe_und_melde(self, obs: ObsState) -> list[str]:
        """Prüfe alle konfigurierten Events gegen ObsState.

        Returns:
            Liste der gerade ausgelösten Event-Keys (für Logging).
        """
        if not self._email or not self._events:
            return []

        heute = date.today().isoformat()
        ausgeloest = []

        for event_key in self._events:
            threshold = self._thresholds.get(event_key)
            if not threshold:
                continue

            # Schon heute gemeldet?
            if self._gesendet.get(event_key) == heute:
                continue

            # Schwelle prüfen
            if self._schwelle_verletzt(obs, threshold):
                ausgeloest.append(event_key)
                self._sende_mail(event_key, threshold, obs)
                self._gesendet[event_key] = heute

        return ausgeloest

    def _schwelle_verletzt(self, obs: ObsState, threshold: dict) -> bool:
        """Prüfe ob ein ObsState-Feld eine Schwelle verletzt."""
        feld = threshold.get('obs_feld', '')
        op = threshold.get('op', '>=')
        schwelle = threshold.get('schwelle', 0)

        wert = getattr(obs, feld, None)
        if wert is None:
            return False

        if op == '>=':
            return wert >= schwelle
        elif op == '<=':
            return wert <= schwelle
        elif op == '<':
            return wert < schwelle
        elif op == '>':
            return wert > schwelle
        elif op == '==':
            return wert == schwelle
        return False

    def _sende_mail(self, event_key: str, threshold: dict, obs: ObsState):
        """E-Mail senden (best-effort, Fehler loggen aber nicht crashen)."""
        text = threshold.get('text', event_key)
        feld = threshold.get('obs_feld', '')
        wert = getattr(obs, feld, '?')
        schwelle = threshold.get('schwelle', '?')
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        hostname = socket.gethostname()

        betreff = f'[PV-Automation] {text}'
        koerper = (
            f'Automatische Meldung von {hostname}\n'
            f'Zeitpunkt: {now_str}\n'
            f'\n'
            f'Event:     {text}\n'
            f'Messwert:  {feld} = {wert}\n'
            f'Schwelle:  {threshold.get("op", ">=")} {schwelle}\n'
            f'\n'
            f'── System-Snapshot ──\n'
            f'SOC:           {obs.batt_soc_pct}%\n'
            f'Batt. Power:   {obs.batt_power_w} W\n'
            f'Batt. Temp:    {obs.batt_temp_max_c}°C\n'
            f'PV Total:      {obs.pv_total_w} W\n'
            f'Grid:          {obs.grid_power_w} W\n'
            f'House Load:    {obs.house_load_w} W\n'
            f'\n'
            f'Diese Meldung wird 1× pro Tag pro Event gesendet.\n'
            f'Konfiguration: config.py → NOTIFICATION_EVENTS\n'
        )

        msg = MIMEText(koerper, 'plain', 'utf-8')
        msg['Subject'] = betreff
        msg['From'] = self._from
        msg['To'] = self._email
        msg['X-PV-Event'] = event_key

        try:
            # Passwort zur Laufzeit aus credential_store laden
            smtp_pass = credential_store.lade('smtp_pass')
            if self._smtp_user and not smtp_pass:
                LOG.error(f"Event-Mail FEHLGESCHLAGEN: {event_key} — "
                          f"SMTP-Passwort nicht in /etc/pv-system/smtp_pass.key. "
                          f"Bitte über pv-config → Benachrichtigungen setzen.")
                return

            if self._smtp_port == 465:
                smtp = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=15)
            else:
                smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15)
                if self._smtp_port == 587:
                    smtp.starttls()

            if self._smtp_user and smtp_pass:
                smtp.login(self._smtp_user, smtp_pass)

            smtp.sendmail(self._from, [self._email], msg.as_string())
            smtp.quit()

            LOG.info(f"Event-Mail gesendet: {event_key} → {self._email} "
                     f"({text}, {feld}={wert})")
        except Exception as e:
            LOG.error(f"Event-Mail FEHLGESCHLAGEN: {event_key} → {self._email}: {e}")

    @property
    def aktive_events(self) -> list[str]:
        """Liste der konfigurierten Event-Keys."""
        return list(self._events)

    @property
    def gesendet_heute(self) -> dict[str, str]:
        """Heute gesendete Events (event_key → Datum)."""
        heute = date.today().isoformat()
        return {k: v for k, v in self._gesendet.items() if v == heute}
