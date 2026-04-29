"""
event_notifier.py — Einmalige E-Mail-Benachrichtigung bei kritischen Events
                    + Sunset-Tagesbericht (24h-Zusammenfassung Sunset→Sunset)

Prüft ObsState gegen konfigurierte Schwellwerte und sendet einmalig
(1× pro Event-Typ pro Tag) eine E-Mail an config.NOTIFICATION_EMAIL.

Sunset-Tagesbericht:
  Eigenständige Zusammenfassung der letzten ~24h (Sunset gestern → Sunset heute).
  Wird beim Komfort-Reset (= Sunset-Erkennung) ausgelöst.
    Energiedaten aus hourly_data direkt; read-only Diagnos-Snapshot optional
    als Zusatz zum Versandzeitpunkt.

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

import json
import logging
import os
import smtplib
import socket
import sqlite3
import time
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from typing import Optional

import config as app_config
from automation.engine import credential_store
from automation.engine import diagnos_alert_state
from automation.engine.obs_state import ObsState
from automation.engine.wattpilot_recovery import WattpilotRecoveryManager
from diagnos.health import run_all as run_diagnos_health
from diagnos.integrity import run_all as run_diagnos_integrity

LOG = logging.getLogger('event_notifier')


# ═══════════════════════════════════════════════════════════
# Persistenter Dedup-State
# ═══════════════════════════════════════════════════════════
# Sofortalarme und Live-Events werden 1× pro Kalendertag pro Key versandt.
# Bisher lag der Versandzustand nur in einer In-Memory-Map. Folge: Bei
# Daemon-Restart (deploy/reboot/crash) gingen die "schon gesendet"-Marker
# verloren → Doppelmails möglich. Persistierung in einer kleinen JSON-
# Datei vermeidet das. Heilung erfolgt automatisch bei Tageswechsel.

_DEDUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config',
    'event_notifier_dedup.json',
)


def _dedup_load(path: str = _DEDUP_PATH) -> dict[str, str]:
    """Lade Dedup-Map (event_key → ISO-Datum). Defekte Dateien sind kein Fehler."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning(f"Dedup-State nicht lesbar ({path}): {exc} → fresh start")
        return {}


def _dedup_save(state: dict[str, str], path: str = _DEDUP_PATH) -> None:
    """Speichere Dedup-Map atomar. Tagesalte Einträge werden mitgenommen,
    Aufräumen erfolgt im EventNotifier (entfernt Einträge < heute)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        LOG.error(f"Dedup-State nicht schreibbar ({path}): {exc}")


class EventNotifier:
    """Einmalige E-Mail-Benachrichtigung bei kritischen Events.

    Deduplizierung: Jeder Event-Key wird maximal 1× pro Kalendertag
    gemeldet. Reset bei Tageswechsel.

    Persistenz: Versandmarker werden in ``config/event_notifier_dedup.json``
    geschrieben, sodass ein Daemon-Restart keine Doppelmails verursacht.
    """

    def __init__(self):
        # event_key → ISO-Datum des Versands. Wird beim Start aus
        # config/event_notifier_dedup.json geladen, alte Einträge (< heute)
        # werden gleich entrümpelt.
        self._gesendet: dict[str, str] = _dedup_load()
        self._dedup_cleanup()
        self._email = getattr(app_config, 'NOTIFICATION_EMAIL', '')
        self._smtp_host = getattr(app_config, 'NOTIFICATION_SMTP_HOST', 'smtp.example.invalid')
        self._smtp_port = getattr(app_config, 'NOTIFICATION_SMTP_PORT', 465)
        self._smtp_user = getattr(app_config, 'NOTIFICATION_SMTP_USER', '')
        self._from = getattr(app_config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
        self._events = getattr(app_config, 'NOTIFICATION_EVENTS', [])
        self._thresholds = getattr(app_config, 'EVENT_THRESHOLDS', {})
        self._wattpilot_recovery = WattpilotRecoveryManager()

    # ── Persistenter Dedup ──────────────────────────────────
    def _dedup_cleanup(self) -> None:
        """Entferne Marker, die nicht zum heutigen Datum gehören."""
        heute = date.today().isoformat()
        before = len(self._gesendet)
        self._gesendet = {k: v for k, v in self._gesendet.items() if v == heute}
        if len(self._gesendet) != before:
            _dedup_save(self._gesendet)

    def _dedup_mark(self, event_key: str) -> None:
        """Markiere einen Event-Key als heute versandt und persistiere."""
        self._gesendet[event_key] = date.today().isoformat()
        _dedup_save(self._gesendet)

    def _dedup_already_sent(self, event_key: str) -> bool:
        """True, wenn der Key heute bereits markiert ist."""
        return self._gesendet.get(event_key) == date.today().isoformat()

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
            if self._dedup_already_sent(event_key):
                continue

            # Schwelle prüfen
            if self._schwelle_verletzt(obs, threshold):
                ausgeloest.append(event_key)
                self._sende_mail(event_key, threshold, obs)
                self._dedup_mark(event_key)

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

            try:
                if self._smtp_user and smtp_pass:
                    smtp.login(self._smtp_user, smtp_pass)

                smtp.sendmail(self._from, [self._email], msg.as_string())
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass

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
        if self._dedup_already_sent(event_key):
            LOG.debug("Sunset-Bericht: heute bereits gesendet")
            return False

        try:
            daten = self._sammle_sunset_daten(obs)
            if daten is None:
                LOG.warning("Sunset-Bericht: Keine Daten verfügbar")
                return False

            health_data = self._hole_diagnos_snapshot()
            integrity_data = self._hole_integrity_snapshot()

            # Diff-Filter: nur neue/eskalierte/heartbeat-fällige Befunde
            # erscheinen als "Auffälligkeit". Stabile Wiederholungen werden
            # unterdrückt (verfallen lassen). Heilung wird via State-Reset
            # selbsttätig gelöscht.
            reportable_names, alert_summary, severity_counts = (
                self._diff_diagnos_alerts(health_data, integrity_data)
            )

            koerper = self._formatiere_sunset_bericht(
                daten, obs, health_data, integrity_data,
                reportable_names=reportable_names,
                alert_summary=alert_summary,
            )
            self._sende_sunset_mail(koerper, severity_counts)
            self._dedup_mark(event_key)
            LOG.info(
                f"Sunset-Tagesbericht gesendet → {self._email} "
                f"(neu={alert_summary.get('new', 0)}, "
                f"changed={alert_summary.get('changed', 0)}, "
                f"reminder={alert_summary.get('reminder', 0)}, "
                f"suppressed={alert_summary.get('suppressed', 0)}, "
                f"healed={alert_summary.get('healed', 0)})"
            )
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

    def _diff_diagnos_alerts(
        self,
        health_data: Optional[dict],
        integrity_data: Optional[dict],
    ) -> tuple[set[str], dict, dict]:
        """Filtere Diagnos-Befunde gegen den persistenten Alert-State.

        Stabil-wiederkehrende Befunde (= gleicher Fingerprint) werden
        unterdrückt; nur neue, eskalierte oder Reminder-fällige Befunde
        landen in der Mail. Severity-Counts dieses gefilterten Sets dienen
        als Subject-Suffix.

        Returns:
            (reportable_check_names, alert_summary, severity_counts)
        """
        try:
            state = diagnos_alert_state.load_state()
        except Exception as exc:
            LOG.warning(f"Alert-State Laden fehlgeschlagen: {exc}")
            state = {}

        all_checks: list = []
        for snapshot in (health_data, integrity_data):
            if snapshot:
                all_checks.extend(snapshot.get('checks', []) or [])

        try:
            reportable, new_state, summary = diagnos_alert_state.filter_reportable(
                all_checks, state
            )
        except Exception as exc:
            LOG.error(f"Alert-Filter fehlgeschlagen, zeige alle Bad-Checks: {exc}")
            reportable = [
                c for c in all_checks
                if (c.get('severity') or '').lower() in ('warn', 'crit', 'fail')
            ]
            new_state = state
            summary = {'new': 0, 'changed': 0, 'reminder': 0, 'suppressed': 0, 'healed': 0}

        try:
            diagnos_alert_state.save_state(new_state)
        except Exception as exc:
            LOG.warning(f"Alert-State Speichern fehlgeschlagen: {exc}")

        reportable_names = {c.get('check') for c in reportable if c.get('check')}
        severity_counts = diagnos_alert_state.severity_counts(reportable)
        return reportable_names, summary, severity_counts

    def _hole_diagnos_snapshot(self) -> Optional[dict]:
        """Lese einen kompakten read-only Diagnos-Snapshot zum Versandzeitpunkt."""
        try:
            return run_diagnos_health()
        except Exception as e:
            LOG.warning(f"Sunset-Bericht: Diagnos-Snapshot nicht verfügbar: {e}")
            return None

    def _hole_integrity_snapshot(self) -> Optional[dict]:
        """Lese einen kompakten read-only Diagnos-Integritätssnapshot zum Versandzeitpunkt."""
        try:
            return run_diagnos_integrity()
        except Exception as e:
            LOG.warning(f"Sunset-Bericht: Integritäts-Snapshot nicht verfügbar: {e}")
            return None

    def pruefe_integrity_alarme(self) -> list[str]:
        """Prüfe Integrity-Daten auf sofortige Warn-Bedingungen.

        Sofort-Alarme (1× pro Tag pro Alarm-Key):
          - collector_inaktiv: last_poll_age_s > 300
          - collector_fehlerstrang: consecutive_errors >= 5
          - reconnect_fehlgeschlagen: last_reconnect.success == False

        Returns: Liste ausgelöster Alarm-Keys.
        """
        if not self._email:
            return []

        try:
            integrity = run_diagnos_integrity()
        except Exception as e:
            LOG.debug(f"Integrity-Alarm-Check fehlgeschlagen: {e}")
            return []

        checks = integrity.get('checks', [])
        attachment = next(
            (c for c in checks if c.get('check') == 'integrity:fronius_attachment_state'),
            {},
        )

        ausgeloest = []

        # Alarm 1: Collector inaktiv
        poll_age = attachment.get('last_poll_age_s')
        if poll_age is not None and poll_age > 300:
            alarm_key = 'integrity:collector_inaktiv'
            if self._sende_integrity_alarm(
                alarm_key,
                f'Collector seit {poll_age}s inaktiv (>300s)',
                attachment,
            ):
                ausgeloest.append(alarm_key)

        # Alarm 2: Fehlerstrang
        consec = attachment.get('consecutive_errors', 0)
        if consec >= 5:
            alarm_key = 'integrity:collector_fehlerstrang'
            if self._sende_integrity_alarm(
                alarm_key,
                f'{consec} aufeinanderfolgende Poll-Fehler',
                attachment,
            ):
                ausgeloest.append(alarm_key)

        # Alarm 3: Reconnect fehlgeschlagen
        # Nur alarmieren wenn der fehlgeschlagene Reconnect NACH dem letzten
        # erfolgreichen Poll liegt — sonst hat sich das System bereits erholt.
        reconnect = attachment.get('last_reconnect')
        if reconnect and not reconnect.get('success', True):
            rc_ts = reconnect.get('ts', 0)
            poll_age = attachment.get('last_poll_age_s')
            # poll_age = Sekunden seit letztem OK-Poll → last_poll_ts ≈ now - poll_age
            # Wenn last_poll_ts > rc_ts → System hat sich erholt → kein Alarm
            poll_ts = (time.time() - poll_age) if poll_age is not None else 0
            if not poll_ts or rc_ts > poll_ts:
                alarm_key = 'integrity:reconnect_fehlgeschlagen'
                if self._sende_integrity_alarm(
                    alarm_key,
                    f'Reconnect-Retry fehlgeschlagen (Trigger: {reconnect.get("trigger", "?")})',
                    attachment,
                ):
                    ausgeloest.append(alarm_key)

        # Optionale Auto-Recovery fuer anhaltende Wattpilot-Stoerung.
        # Erfolgt nur bei explizit aktivierter Konfiguration.
        try:
            recovery_info = self._wattpilot_recovery.evaluate_and_recover(attachment)
            if recovery_info:
                LOG.warning(f"Integrity-Recovery: {recovery_info}")
                ausgeloest.append('integrity:wattpilot_auto_recovery')
        except Exception as e:
            LOG.error(f"Integrity-Recovery Fehler: {e}")

        return ausgeloest

    def pruefe_health_alarme(self) -> list[str]:
        """Prüfe Diagnos-Health-Snapshot auf akute Sofortbedingungen.

        Sofortpfad analog zu pruefe_integrity_alarme(): wenn ein Health-Check
        eine kritische Schwelle (severity == crit / fail) reißt, wird sofort
        eine Mail abgesetzt — 1× pro Tag pro Alarm-Key (persistiert).

        Aktuell überwachte Sofort-Kandidaten:
          - cpu_temp           (CRIT/FAIL)
          - throttle           (CRIT — Unterspannung aktiv)
          - disk_root          (CRIT — kein Platz)
          - service:*          (CRIT/FAIL — wichtige Dienste tot)

        WARN-Stufen kommen weiter via Sunset-Mail mit Diff-Filter — die
        sind nicht zeitkritisch genug für einen Sofortalarm.

        Returns: Liste ausgelöster Alarm-Keys.
        """
        if not self._email:
            return []

        try:
            health = run_diagnos_health()
        except Exception as exc:
            LOG.debug(f"Health-Alarm-Check fehlgeschlagen: {exc}")
            return []

        checks = health.get('checks', []) or []
        ausgeloest: list[str] = []

        # Schwere Severities, die sofort gemeldet werden sollen.
        # WARN bleibt bewusst draußen → Sunset-Mail.
        akute = {'crit', 'fail'}

        for check in checks:
            name = check.get('check') or ''
            sev = (check.get('severity') or '').lower()
            if sev not in akute:
                continue

            # Whitelist: nur die Checks, deren Sofortpfad fachlich
            # gerechtfertigt ist (Hardware-/Hostprobleme, tote Services).
            if not (
                name in ('cpu_temp', 'throttle', 'disk_root')
                or name.startswith('service:')
            ):
                continue

            alarm_key = f'health:{name}:{sev}'
            text, details = self._format_health_alarm(name, sev, check)
            if self._sende_diagnos_alarm(alarm_key, text, details, kategorie='HEALTH'):
                ausgeloest.append(alarm_key)

        return ausgeloest

    @staticmethod
    def _format_health_alarm(name: str, sev: str, check: dict) -> tuple[str, dict]:
        """Baue Alarm-Text + Detaildict für eine Health-Check-Sofortmeldung."""
        sev_label = {'crit': 'KRIT', 'fail': 'FAIL'}.get(sev, sev.upper())
        if name == 'cpu_temp':
            text = f"CPU-Temperatur {sev_label}: {check.get('value_c')}°C"
        elif name == 'throttle':
            flags = check.get('hex') or '?'
            text = f"Pi-Throttle/Unterspannung {sev_label}: {flags}"
        elif name == 'disk_root':
            text = f"Disk root {sev_label}: belegt {check.get('used_pct')}%"
        elif name.startswith('service:'):
            unit = name.split(':', 1)[1]
            state = check.get('active_state') or check.get('error') or '?'
            text = f"Service {unit} {sev_label}: {state}"
        else:
            text = f"{name} {sev_label}"

        # Schmales Detail-Dict, damit der Alarm-Body kompakt bleibt.
        details = {k: v for k, v in check.items() if k != 'check'}
        return text, details

    def _sende_diagnos_alarm(
        self,
        alarm_key: str,
        text: str,
        details: dict,
        kategorie: str = 'WARN',
    ) -> bool:
        """Generischer Sofort-Alarm-Versand mit persistenter 1×/Tag-Dedup.

        Wird sowohl von ``pruefe_health_alarme`` als auch perspektivisch von
        NQ-/anderen Sofortpfaden genutzt. ``kategorie`` landet im Subject
        (z. B. ``[PV-System KRIT]``).
        """
        if self._dedup_already_sent(alarm_key):
            return False

        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        hostname = socket.gethostname()
        detail_lines = '\n'.join(
            f'  {k:20s} {v}' for k, v in sorted(details.items())
            if not isinstance(v, (dict, list))
        )

        koerper = (
            f'Sofort-Alarm von {hostname}\n'
            f'Zeitpunkt: {now_str}\n'
            f'\n'
            f'Alarm:     {text}\n'
            f'\n'
            f'── Details ──\n'
            f'{detail_lines}\n'
            f'\n'
            f'Diese Meldung wird 1× pro Tag pro Alarm gesendet (persistent).\n'
        )

        betreff = f'[PV-System {kategorie}] {text}'
        msg = MIMEText(koerper, 'plain', 'utf-8')
        msg['Subject'] = betreff
        msg['From'] = self._from
        msg['To'] = self._email
        msg['X-PV-Event'] = alarm_key

        try:
            smtp_pass = credential_store.lade('smtp_pass')
            if self._smtp_user and not smtp_pass:
                LOG.error(f"Sofort-Alarm FEHLGESCHLAGEN: {alarm_key} — SMTP-Passwort fehlt")
                return False

            if self._smtp_port == 465:
                smtp = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=15)
            else:
                smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15)
                if self._smtp_port == 587:
                    smtp.starttls()

            try:
                if self._smtp_user and smtp_pass:
                    smtp.login(self._smtp_user, smtp_pass)
                smtp.sendmail(self._from, [self._email], msg.as_string())
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass

            self._dedup_mark(alarm_key)
            LOG.warning(f"Sofort-Alarm gesendet: {alarm_key} → {self._email}")
            return True
        except Exception as exc:
            LOG.error(f"Sofort-Alarm FEHLGESCHLAGEN: {alarm_key}: {exc}")
            return False

    def _sende_integrity_alarm(self, alarm_key: str, text: str, attachment: dict) -> bool:
        """Sende Integrity-Warn-Mail (dedupliziert 1× pro Tag pro Alarm-Key)."""
        if self._dedup_already_sent(alarm_key):
            return False

        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        hostname = socket.gethostname()

        koerper = (
            f'Integrity-Alarm von {hostname}\n'
            f'Zeitpunkt: {now_str}\n'
            f'\n'
            f'Alarm:     {text}\n'
            f'\n'
            f'── Attachment-State ──\n'
            f'WR-Version F1:     {attachment.get("inverter_vr", "—")}\n'
            f'Collector live:    {attachment.get("collector_live", "—")}\n'
            f'Letzter Poll:      {attachment.get("last_poll_age_s", "—")}s\n'
            f'Fehler in Folge:   {attachment.get("consecutive_errors", 0)}\n'
            f'Reconnect:         {attachment.get("last_reconnect") or "—"}\n'
            f'Assessment:        {attachment.get("assessment", "—")}\n'
            f'\n'
            f'Diese Meldung wird 1× pro Tag pro Alarm gesendet.\n'
        )

        betreff = f'[PV-System WARN] {text}'
        msg = MIMEText(koerper, 'plain', 'utf-8')
        msg['Subject'] = betreff
        msg['From'] = self._from
        msg['To'] = self._email
        msg['X-PV-Event'] = alarm_key

        try:
            smtp_pass = credential_store.lade('smtp_pass')
            if self._smtp_user and not smtp_pass:
                LOG.error(f"Integrity-Alarm FEHLGESCHLAGEN: {alarm_key} — SMTP-Passwort fehlt")
                return False

            if self._smtp_port == 465:
                smtp = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=15)
            else:
                smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15)
                if self._smtp_port == 587:
                    smtp.starttls()

            try:
                if self._smtp_user and smtp_pass:
                    smtp.login(self._smtp_user, smtp_pass)
                smtp.sendmail(self._from, [self._email], msg.as_string())
            finally:
                try:
                    smtp.quit()
                except Exception:
                    pass

            self._dedup_mark(alarm_key)
            LOG.warning(f"Integrity-Alarm gesendet: {alarm_key} → {self._email}")
            return True
        except Exception as e:
            LOG.error(f"Integrity-Alarm FEHLGESCHLAGEN: {alarm_key}: {e}")
            return False

    def _format_diagnos_summary(
        self,
        health_data: Optional[dict],
        reportable_names: Optional[set] = None,
    ) -> list[str]:
        """Formatiere Diagnos-Daten kompakt für den Tagesbericht.

        ``reportable_names`` enthält die Check-Namen, die diesmal gemeldet
        werden sollen (Diff gegen Alert-State). Stabil-wiederholte Befunde
        sind nicht enthalten und werden in der Mail unterdrückt.
        """
        if not health_data:
            return [
                '',
                'Systemgesundheit (Diagnos D)',
                '  Snapshot:            nicht verfügbar',
            ]

        severity_map = {'ok': 'OK', 'warn': 'WARN', 'crit': 'KRIT', 'fail': 'FAIL'}
        checks = health_data.get('checks', [])
        by_name = {c.get('check'): c for c in checks}
        bad_checks = [c for c in checks if c.get('severity') in ('warn', 'crit', 'fail')]
        if reportable_names is not None:
            shown_bad = [c for c in bad_checks if c.get('check') in reportable_names]
            stale_bad_count = len(bad_checks) - len(shown_bad)
        else:
            shown_bad = bad_checks
            stale_bad_count = 0

        def _fmt_sev(value: Optional[str]) -> str:
            return severity_map.get(value or '', value or '—')

        def _fmt_age_s(check_name: str) -> str:
            check = by_name.get(check_name, {})
            age_s = check.get('age_s')
            if age_s is None:
                return '—'
            if age_s < 3600:
                return f'{int(age_s // 60)} min'
            return f'{age_s / 3600:.1f} h'

        def _fmt_value(check_name: str, key: str, unit: str = '') -> str:
            check = by_name.get(check_name, {})
            value = check.get(key)
            if value is None:
                return '—'
            return f'{value}{unit}'

        lines = [
            '',
            'Systemgesundheit (Diagnos D)',
            f'  Gesamt:              {_fmt_sev(health_data.get("overall"))}',
            f'  CPU / RAM / Disk:    {_fmt_value("cpu_temp", "value_c", "°C")} / '
            f'{_fmt_value("ram", "used_pct", "%")} / {_fmt_value("disk_root", "used_pct", "%")}',
            f'  Freshness raw/1m:    {_fmt_age_s("freshness:raw_data")} / {_fmt_age_s("freshness:data_1min")}',
            f'  Freshness 15m/day:   {_fmt_age_s("freshness:data_15min")} / {_fmt_age_s("freshness:daily_data")}',
            f'  Lokales GFS-Backup:  {_fmt_value("backup_local_gfs_daily", "age_h", " h")}',
        ]

        mirror_check = by_name.get('mirror_sync_age')
        if mirror_check and not mirror_check.get('skipped'):
            lines.append(
                f'  Mirror-Sync:         {_fmt_value("mirror_sync_age", "age_s", " s")} '
                f'({_fmt_sev(mirror_check.get("severity"))})'
            )

        if shown_bad:
            lines.append('')
            lines.append('Auffaelligkeiten (neu/eskaliert)')
            for check in shown_bad[:6]:
                detail = check.get('error')
                if detail is None and 'age_s' in check:
                    detail = f'age={check.get("age_s")}s'
                elif detail is None and 'age_h' in check:
                    detail = f'age={check.get("age_h")}h'
                elif detail is None and 'state' in check:
                    detail = f'state={check.get("state")}'
                elif detail is None:
                    detail = 'siehe Diagnos-Report'
                reason = check.get('_alert_reason')
                tag = f' [{reason}]' if reason and reason != 'new' else ''
                lines.append(
                    f'  [{_fmt_sev(check.get("severity"))}] {check.get("check")}: {detail}{tag}'
                )
        if stale_bad_count > 0:
            lines.append(
                f'  ({stale_bad_count} stabile Befund(e) unterdrueckt — siehe diagnos.health)'
            )

        return lines

    def _format_integrity_summary(
        self,
        integrity_data: Optional[dict],
        reportable_names: Optional[set] = None,
    ) -> list[str]:
        """Formatiere Diagnos-Integritätsdaten kompakt für den Tagesbericht.

        ``reportable_names`` selektiert, welche Befunde diesmal als neu/
        geändert/heartbeat gemeldet werden. Stabil-wiederholte werden
        unterdrückt — Fehler bleiben in den Logs erhalten.
        """
        if not integrity_data:
            return [
                '',
                'Datenintegritaet (Diagnos D)',
                '  Snapshot:            nicht verfügbar',
            ]

        severity_map = {'ok': 'OK', 'warn': 'WARN', 'crit': 'KRIT', 'fail': 'FAIL'}
        checks = integrity_data.get('checks', [])
        by_name = {c.get('check'): c for c in checks}
        bad_checks = [c for c in checks if c.get('severity') in ('warn', 'crit', 'fail')]
        if reportable_names is not None:
            stale_bad_count = sum(
                1 for c in bad_checks if c.get('check') not in reportable_names
            )
        else:
            stale_bad_count = 0

        def _fmt_sev(value: Optional[str]) -> str:
            return severity_map.get(value or '', value or '—')

        attachment = by_name.get('integrity:fronius_attachment_state', {})

        # Collector-Liveness
        poll_age = attachment.get('last_poll_age_s')
        if poll_age is not None:
            collector_str = f'aktiv (Poll vor {poll_age}s)' if attachment.get('collector_live') else f'INAKTIV seit {poll_age}s!'
        else:
            collector_str = '—'

        consec = attachment.get('consecutive_errors', 0)
        reconnect = attachment.get('last_reconnect')

        lines = [
            '',
            'Datenintegritaet (Diagnos D)',
            f'  Gesamt:              {_fmt_sev(integrity_data.get("overall"))}',
            f'  Tagesbilanz:         {_fmt_sev((by_name.get("integrity:daily_energy_balance") or {}).get("severity"))}',
            f'  Monats-/Jahresrolle: {_fmt_sev((by_name.get("integrity:monthly_rollup") or {}).get("severity"))} / '
            f'{_fmt_sev((by_name.get("integrity:yearly_rollup") or {}).get("severity"))}',
            f'  WR-Version F1:       {attachment.get("inverter_vr") or "—"}',
            f'  WR-Anknuepfungen:    {attachment.get("assessment") or "—"}',
            f'  WR-API / Batt-API:   '
            f'{"OK" if attachment.get("internal_api_ok") else "—"} / '
            f'{"OK" if attachment.get("battery_api_ok") else "—"}',
            f'  Collector:           {collector_str}',
        ]

        if consec > 0:
            lines.append(f'  Fehlerstrang:        {consec} Polls in Folge')

        if reconnect:
            rc_ok = 'OK' if reconnect.get('success') else 'FEHLER'
            lines.append(
                f'  Letzter Reconnect:   {reconnect.get("trigger", "?")} → {rc_ok}'
            )

        gap_checks = [
            by_name.get('integrity:gaps:raw_data'),
            by_name.get('integrity:gaps:data_1min'),
            by_name.get('integrity:gaps:data_15min'),
            by_name.get('integrity:gaps:hourly_data'),
        ]
        gap_shown = 0
        for gap_check in [c for c in gap_checks if c]:
            if gap_check.get('gap_count', 0) <= 0:
                continue
            # Diff-Filter: stabile Lückenberichte unterdrücken.
            if reportable_names is not None and gap_check.get('check') not in reportable_names:
                continue
            gap_shown += 1
            lines.append('')
            lines.append(
                f'  [{_fmt_sev(gap_check.get("severity"))}] {gap_check.get("check")}: '
                f'{gap_check.get("gap_count")} Lücke(n), max {gap_check.get("max_gap_s")} s'
            )
            if gap_check.get('followup_assessment'):
                lines.append(f'    Folge: {gap_check.get("followup_assessment")}')
            notes = gap_check.get('neutralization_notes') or []
            for note in notes[:3]:
                lines.append(f'    Kontext: {note}')

        if not bad_checks:
            lines.append('')
            lines.append('  Keine Integritätsabweichungen im aktuellen Prüffenster.')
        elif stale_bad_count > 0 and gap_shown == 0:
            lines.append('')
            lines.append(
                f'  Keine NEUEN Integritätsabweichungen ({stale_bad_count} stabile unterdrueckt).'
            )

        lines += [
            '',
            '  Referenzbetrieb: Regelmäßiger Solarweb-Abgleich bis 31.12.2026 vorgesehen.',
        ]

        return lines

    def _formatiere_sunset_bericht(
        self,
        d: dict,
        obs: ObsState,
        health_data: Optional[dict] = None,
        integrity_data: Optional[dict] = None,
        reportable_names: Optional[set] = None,
        alert_summary: Optional[dict] = None,
    ) -> str:
        """Formatiere den Sunset-Bericht als E-Mail-Text."""
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

        # Verbrauch = PV + Bezug - Einspeisung
        verbrauch = d['pv_kwh'] + d['netzbezug_kwh'] - d['einspeisung_kwh']
        # Autarkie
        if verbrauch > 0:
            autarkie = max(0, (1 - d['netzbezug_kwh'] / verbrauch)) * 100
        else:
            autarkie = 0

        zeilen = [
            'PV-System Sunset-Tagesbericht',
            '',
            f'{start_str}  →  {end_str}  ({d["stunden"]}h Daten)',
            f'  SOC:   {_pct(d["soc_start"])} / {_pct(d["soc_end"])}',
            f'  (min/max  {_pct(d["soc_min"])} / {_pct(d["soc_max"])})',
            f'  Batt. Ladung:         {_fmt(d["batt_ladung_kwh"])}',
            f'  Batt. Entladung:      {_fmt(d["batt_entladung_kwh"])}',
            '',
            f'  PV-Erzeug.:           {_fmt(d["pv_kwh"])}',
            f'  Verbrauch:            {_fmt(verbrauch)}',
            f'  Netzbezug:            {_fmt(d["netzbezug_kwh"])}',
            f'  Einspeisung:          {_fmt(d["einspeisung_kwh"])}',
            f'  Autarkie:             {autarkie:.0f}%',
            '',
            f'  Wärmepumpe:           {_fmt(d["wp_kwh"])}',
        ]

        if d.get('wattpilot_kwh') is not None:
            zeilen.append(
                f'  Wattpilot (EV):       {_fmt(d["wattpilot_kwh"])}'
            )

        zeilen += self._format_diagnos_summary(health_data, reportable_names)
        zeilen += self._format_integrity_summary(integrity_data, reportable_names)

        if alert_summary:
            zeilen += [
                '',
                'Diagnos-Filter (Diff zur letzten Mail)',
                f'  neu={alert_summary.get("new", 0)}  '
                f'changed={alert_summary.get("changed", 0)}  '
                f'reminder={alert_summary.get("reminder", 0)}  '
                f'unterdrueckt={alert_summary.get("suppressed", 0)}  '
                f'geheilt={alert_summary.get("healed", 0)}',
                '  (stabile Wiederholungen werden unterdrueckt; Reminder nach 7 Tagen,',
                '   Heilung beim Rueckfall auf OK; Voll-Status: python3 -m diagnos.integrity)',
            ]

        zeilen += [
            '',
            'Automatisch generiert bei Sonnenuntergang.',
            'Konfiguration: config.py → NOTIFICATION_EVENTS',
        ]

        return '\n'.join(zeilen)

    def _sende_sunset_mail(self, koerper: str, severity_counts: Optional[dict] = None):
        """Sunset-Bericht per E-Mail senden.

        ``severity_counts`` zählt die Severities der diesmal frisch zu
        meldenden Diagnos-Befunde (nicht aller). Sind alle Counts 0,
        bleibt der Betreff sauber — sonst wird ein Suffix wie
        ``— FAIL(1) KRIT(2) WARN(1)`` angehängt.
        """
        datum_str = datetime.now().strftime('%d.%m.%Y')
        betreff = f'[PV-System] Tagesbericht {datum_str}'
        if severity_counts:
            parts = []
            # Reihenfolge: schwerste Stufe zuerst → beim Sortieren der
            # Inbox bleibt der Suffix gut lesbar.
            for label_key, label in (('fail', 'FAIL'), ('crit', 'KRIT'), ('warn', 'WARN')):
                n = severity_counts.get(label_key, 0)
                if n:
                    parts.append(f'{label}({n})')
            if parts:
                betreff = f'{betreff} \u2014 {" ".join(parts)}'

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

        try:
            if self._smtp_user and smtp_pass:
                smtp.login(self._smtp_user, smtp_pass)

            smtp.sendmail(self._from, [self._email], msg.as_string())
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
