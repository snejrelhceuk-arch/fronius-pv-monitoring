"""
event_notifier.py — Einmalige E-Mail-Benachrichtigung bei kritischen Events
                    + Sunset-Tagesbericht (24h-Zusammenfassung Sunset→Sunset)

Prüft ObsState gegen konfigurierte Schwellwerte und sendet einmalig
(1× pro Event-Typ pro Tag) eine E-Mail an config.NOTIFICATION_EMAIL.

Sunset-Tagesbericht:
  Eigenständige Zusammenfassung der letzten ~24h (Sunset gestern → Sunset heute).
  Wird beim Komfort-Reset (= Sunset-Erkennung) ausgelöst.
  Datenquelle: hourly_data direkt — KEINE Vermischung mit Monitoring/Analyse.

Konfiguration:
  config.py:
    NOTIFICATION_EMAIL       — Empfänger
    NOTIFICATION_SMTP_HOST   — SMTP-Server (default: localhost)
    NOTIFICATION_EVENTS      — Liste aktiver Event-Keys
    EVENT_THRESHOLDS         — Schwellwert-Definitionen

Events werden über config.NOTIFICATION_EVENTS aktiviert/deaktiviert.
Neue Events: Einfach EVENT_THRESHOLDS in config.py erweitern und
den Key in NOTIFICATION_EVENTS aufnehmen.

Sunset-Tagesbericht: 'sunset_tagesbericht' in NOTIFICATION_EVENTS aufnehmen.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md
"""

from __future__ import annotations

import logging
import smtplib
import socket
import sqlite3
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
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
        self._smtp_host = getattr(app_config, 'NOTIFICATION_SMTP_HOST', 'smtp.example.invalid')
        self._smtp_port = getattr(app_config, 'NOTIFICATION_SMTP_PORT', 465)
        self._smtp_user = getattr(app_config, 'NOTIFICATION_SMTP_USER', '')
        self._from = getattr(app_config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
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

    # ═════════════════════════════════════════════════════════
    # Sunset-Tagesbericht (24h Sunset→Sunset)
    # ═════════════════════════════════════════════════════════

    def sende_sunset_bericht(self, obs: ObsState) -> bool:
        """Sende Sunset-Tagesbericht: 24h-Zusammenfassung Sunset→Sunset.

        Eigenständiges Überwachungstool — NICHT Teil von Monitoring/Analyse.
        Datenquelle: hourly_data direkt (kein daily_data, kein Aggregate).

        Args:
            obs: Aktueller ObsState (für Sunset-Zeit und aktuelle Werte)

        Returns:
            True wenn erfolgreich gesendet.
        """
        event_key = 'sunset_tagesbericht'

        if event_key not in self._events:
            return False
        if not self._email:
            return False

        # Deduplizierung: 1× pro Tag
        heute = date.today().isoformat()
        if self._gesendet.get(event_key) == heute:
            LOG.debug("Sunset-Bericht: heute bereits gesendet")
            return False

        try:
            daten = self._sammle_sunset_daten(obs)
            if daten is None:
                LOG.warning("Sunset-Bericht: Keine Daten verfügbar")
                return False

            koerper = self._formatiere_sunset_bericht(daten, obs)
            self._sende_sunset_mail(koerper)
            self._gesendet[event_key] = heute
            LOG.info(f"Sunset-Tagesbericht gesendet → {self._email}")
            return True
        except Exception as e:
            LOG.error(f"Sunset-Bericht FEHLGESCHLAGEN: {e}")
            return False

    def _sammle_sunset_daten(self, obs: ObsState) -> Optional[dict]:
        """Lese 24h-Daten aus hourly_data (Sunset gestern → jetzt).

        Zeitfenster: Sunset gestern (≈ selbe Uhrzeit) bis jetzt.
        Fallback: letzte 24h wenn kein Sunset-Zeitpunkt verfügbar.
        """
        db_path = app_config.DB_PATH
        try:
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
        except Exception as e:
            LOG.error(f"Sunset-Bericht: DB nicht erreichbar: {e}")
            return None

        try:
            now_ts = time.time()

            # Sunset-Zeitpunkt: obs.sunset als Dezimalstunde heute
            # Fenster-Start: gestern selbe Sunset-Uhrzeit
            if obs.sunset:
                sunset_h = obs.sunset
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                sunset_today = today + timedelta(hours=sunset_h)
                sunset_yesterday = sunset_today - timedelta(days=1)
                start_ts = sunset_yesterday.timestamp()
                end_ts = sunset_today.timestamp()
            else:
                # Fallback: letzte 24h
                start_ts = now_ts - 86400
                end_ts = now_ts

            # ── hourly_data aggregieren ──
            row = conn.execute("""
                SELECT
                    SUM(W_PV_total_delta),
                    SUM(W_Exp_Netz_delta),
                    SUM(W_Imp_Netz_delta),
                    SUM(W_Batt_Charge_total),
                    SUM(W_Batt_Discharge_total),
                    SUM(W_PV_Direct_total),
                    SUM(W_WP_total),
                    MIN(SOC_Batt_min),
                    MAX(SOC_Batt_max),
                    AVG(SOC_Batt_avg),
                    COUNT(*)
                FROM hourly_data
                WHERE ts >= ? AND ts < ?
            """, (start_ts, end_ts)).fetchone()

            if not row or row[10] == 0:
                return None

            (pv_wh, exp_wh, imp_wh, batt_ch_wh, batt_dis_wh,
             pv_direct_wh, wp_wh, soc_min, soc_max, soc_avg,
             stunden_count) = row

            # ── SOC am Fenster-Start (erste Stunde) ──
            soc_start_row = conn.execute("""
                SELECT SOC_Batt_avg FROM hourly_data
                WHERE ts >= ? AND ts < ?
                ORDER BY ts ASC LIMIT 1
            """, (start_ts, end_ts)).fetchone()
            soc_start = soc_start_row[0] if soc_start_row else None

            # ── SOC am Fenster-Ende (letzte Stunde) ──
            soc_end_row = conn.execute("""
                SELECT SOC_Batt_avg FROM hourly_data
                WHERE ts >= ? AND ts < ?
                ORDER BY ts DESC LIMIT 1
            """, (start_ts, end_ts)).fetchone()
            soc_end = soc_end_row[0] if soc_end_row else None

            # ── Wattpilot (falls vorhanden) ──
            wattpilot_wh = None
            today_midnight = int(now_ts) // 86400 * 86400
            try:
                wtp_row = conn.execute("""
                    SELECT energy_wh FROM wattpilot_daily
                    WHERE ts = ?
                """, (today_midnight,)).fetchone()
                if wtp_row:
                    wattpilot_wh = wtp_row[0]
            except Exception:
                pass  # Tabelle existiert evtl. nicht

            return {
                'start_ts': start_ts,
                'end_ts': end_ts,
                'stunden': stunden_count,
                'pv_kwh': (pv_wh or 0) / 1000,
                'einspeisung_kwh': (exp_wh or 0) / 1000,
                'netzbezug_kwh': (imp_wh or 0) / 1000,
                'batt_ladung_kwh': (batt_ch_wh or 0) / 1000,
                'batt_entladung_kwh': (batt_dis_wh or 0) / 1000,
                'pv_direkt_kwh': (pv_direct_wh or 0) / 1000,
                'wp_kwh': (wp_wh or 0) / 1000,
                'soc_start': soc_start,
                'soc_end': soc_end,
                'soc_min': soc_min,
                'soc_max': soc_max,
                'soc_avg': soc_avg,
                'wattpilot_kwh': (wattpilot_wh / 1000) if wattpilot_wh else None,
                'sunrise_h': obs.sunrise,
                'sunset_h': obs.sunset,
            }
        except Exception as e:
            LOG.error(f"Sunset-Daten Abfrage: {e}")
            return None
        finally:
            conn.close()

    def _formatiere_sunset_bericht(self, d: dict, obs: ObsState) -> str:
        """Formatiere den Sunset-Bericht als E-Mail-Text."""
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        hostname = socket.gethostname()
        start_str = datetime.fromtimestamp(d['start_ts']).strftime('%d.%m. %H:%M')
        end_str = datetime.fromtimestamp(d['end_ts']).strftime('%d.%m. %H:%M')

        def _fmt(val, einheit='kWh', dez=1):
            if val is None:
                return '—'
            return f"{val:.{dez}f} {einheit}"

        def _pct(val):
            if val is None:
                return '—'
            return f"{val:.1f}%"

        sunrise_str = f"{d['sunrise_h']:.1f}h" if d.get('sunrise_h') else '?'
        sunset_str = f"{d['sunset_h']:.1f}h" if d.get('sunset_h') else '?'

        # Verbrauch = PV + Bezug - Einspeisung
        verbrauch = d['pv_kwh'] + d['netzbezug_kwh'] - d['einspeisung_kwh']
        # Autarkie
        if verbrauch > 0:
            autarkie = max(0, (1 - d['netzbezug_kwh'] / verbrauch)) * 100
        else:
            autarkie = 0

        zeilen = [
            f'PV-System Sunset-Tagesbericht',
            f'',
            f'{start_str}  →  {end_str}  ({d["stunden"]}h Daten)',
            f'  SOC:   {_pct(d["soc_start"])} / {_pct(d["soc_end"])}',
            f'  (min/max  {_pct(d["soc_min"])} / {_pct(d["soc_max"])})',
            f'  Batt. Ladung:         {_fmt(d["batt_ladung_kwh"])}',
            f'  Batt. Entladung:      {_fmt(d["batt_entladung_kwh"])}',
            f'',
            f'  PV-Erzeug.:           {_fmt(d["pv_kwh"])}',
            f'  Verbrauch:            {_fmt(verbrauch)}',
            f'  Netzbezug:            {_fmt(d["netzbezug_kwh"])}',
            f'  Einspeisung:          {_fmt(d["einspeisung_kwh"])}',
            f'  Autarkie:             {autarkie:.0f}%',
            f'',
            f'  Wärmepumpe:           {_fmt(d["wp_kwh"])}',
        ]

        if d.get('wattpilot_kwh') is not None:
            zeilen.append(
                f'  Wattpilot (EV):       {_fmt(d["wattpilot_kwh"])}'
            )

        zeilen += [
            f'',
            f'Automatisch generiert bei Sonnenuntergang.',
            f'Konfiguration: config.py → NOTIFICATION_EVENTS',
        ]

        return '\n'.join(zeilen)

    def _sende_sunset_mail(self, koerper: str):
        """Sunset-Bericht per E-Mail senden."""
        datum_str = datetime.now().strftime('%d.%m.%Y')
        betreff = f'[PV-System] Tagesbericht {datum_str}'

        msg = MIMEText(koerper, 'plain', 'utf-8')
        msg['Subject'] = betreff
        msg['From'] = self._from
        msg['To'] = self._email
        msg['X-PV-Event'] = 'sunset_tagesbericht'

        smtp_pass = credential_store.lade('smtp_pass')
        if self._smtp_user and not smtp_pass:
            raise RuntimeError("SMTP-Passwort nicht gesetzt (credential_store)")

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
