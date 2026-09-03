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
import socket
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

import config as app_config
from automation.engine import credential_store
from automation.engine.obs_state import ObsState
from automation.engine.wattpilot_recovery import WattpilotRecoveryManager
from automation.engine.notify import dedup, thresholds, mail, report_format
from diagnos.health import run_all as run_diagnos_health
from diagnos.integrity import run_all as run_diagnos_integrity
from diagnos.nq_health import run_all as run_diagnos_nq

LOG = logging.getLogger('event_notifier')

# Deutsche Monatsnamen für die Tagesbericht-Kopfzeilen.
MONATE = ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
          'August', 'September', 'Oktober', 'November', 'Dezember')

# Energie-Kernwerte (5 Werte): daily_data-Spalte (Wh) → Report-Schlüssel (kWh).
_DD_COLS = ('W_PV_total', 'W_Consumption_total', 'W_Imp_Netz_total',
            'W_Exp_Netz_total', 'W_Batt_Charge_total', 'W_Batt_Discharge_total')
_DD_KEYS = ('erzeugung', 'verbrauch', 'netzbezug', 'einspeisung',
            'batt_ladung', 'batt_entladung')


# Persistenter Dedup-State (1×/Tag pro Key) → automation/engine/notify/dedup.py

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
        self._gesendet: dict[str, str] = dedup.load()
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
            dedup.save(self._gesendet)

    def _dedup_mark(self, event_key: str) -> None:
        """Markiere einen Event-Key als heute versandt und persistiere."""
        self._gesendet[event_key] = date.today().isoformat()
        dedup.save(self._gesendet)

    def _dedup_already_sent(self, event_key: str) -> bool:
        """True, wenn der Key heute bereits markiert ist."""
        return self._gesendet.get(event_key) == date.today().isoformat()

    def pruefe_und_melde(self, obs: ObsState) -> list[str]:
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
        """Prüfe ob ein ObsState-Feld eine Schwelle verletzt (→ notify.thresholds)."""
        return thresholds.schwelle_verletzt(obs, threshold)

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

            mail.smtp_versand(self._smtp_host, self._smtp_port, self._smtp_user,
                              smtp_pass, self._from, self._email, msg)

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

    def sende_tagesbericht(self) -> bool:
        """Sende den täglichen Energiebericht (00:00 für den abgelaufenen Kalendertag).

        Reiner Energie-Auszug in vier Abschnitten — Tag / Monat / Jahr / Gesamt
        (je 5 Kernwerte; im Tag zusätzlich Stresszeit-% und Verbraucher). **Keine**
        Diagnos-/Warn-Inhalte: Systemfehler laufen über die separaten Sofort-Alarme.

        Datenquelle: ``daily_data`` (Counter-nah) + ``yearly_statistics`` (historische
        Jahre). Der abgelaufene Tag wird erst gemeldet, sobald seine daily_data-Zeile
        vorliegt (Tagesaggregation kurz nach Mitternacht) — vorher ist der Aufruf ein
        No-Op und wird im nächsten Zyklus wiederholt.

        Returns:
            True wenn gesendet; False wenn (noch) nicht fällig.
        """
        event_key = 'tagesbericht'

        if event_key not in self._events:
            return False
        if not self._email:
            return False
        if self._dedup_already_sent(event_key):
            return False

        try:
            daten = self._sammle_tagesdaten()
            if daten is None:
                # daily_data des Vortags noch nicht bereit → nächster Zyklus.
                return False

            koerper = report_format.tagesbericht(daten)
            self._sende_tagesbericht_mail(koerper)
            self._dedup_mark(event_key)
            LOG.info(f"Tagesbericht gesendet → {self._email} "
                     f"(Tag {daten['tag']['datum']})")
            # Status-Markdown best-effort aktualisieren (entkoppelt vom Mailtext).
            self._aktualisiere_statusdateien()
            return True
        except Exception as e:
            LOG.error(f"Tagesbericht FEHLGESCHLAGEN: {e}")
            return False

    def _sammle_tagesdaten(self) -> Optional[dict]:
        """Sammle Tag/Monat/Jahr/Gesamt-Energiewerte für den abgelaufenen Tag.

        Der Tag (00:00→00:00) kommt aus der ``daily_data``-Zeile des Vortags
        (Counter-nah); Monat/Jahr summieren ``daily_data`` bis einschließlich
        gestern; Gesamt ergänzt die historischen Jahre aus ``yearly_statistics``.

        Gibt None zurück, solange die daily_data-Zeile des Vortags fehlt und die
        Karenzzeit (1 h nach Mitternacht) nicht überschritten ist — der Versand
        wird dann auf den nächsten Zyklus verschoben. Danach greift ein
        ``hourly_data``-Fallback für den Tag.
        """
        heute = date.today()
        gestern = heute - timedelta(days=1)
        key_gestern = self._utc_midnight_ts(gestern)
        monatsanfang = self._utc_midnight_ts(date(gestern.year, gestern.month, 1))
        jahresanfang = self._utc_midnight_ts(date(gestern.year, 1, 1))

        # Lokale Tagesgrenzen für hourly_data-Fallback + Stresszeit.
        lokal_heute = datetime(heute.year, heute.month, heute.day).timestamp()
        lokal_gestern = datetime(gestern.year, gestern.month, gestern.day).timestamp()

        try:
            conn = sqlite3.connect(
                f'file:{app_config.DB_PATH}?mode=ro', uri=True, timeout=5)
        except Exception as e:
            LOG.error(f"Tagesbericht: DB nicht erreichbar: {e}")
            return None
        try:
            # ── Tag (abgelaufener Kalendertag) ──
            # Der Tages-Aggregator (collector.aggregate.daily, Cron :05) finalisiert
            # den Vortag erst mit dem ersten Lauf nach lokaler Mitternacht (00:05).
            # Vorher existiert die daily_data-Zeile zwar, ist aber partiell — daher
            # frühestens 10 min nach Mitternacht melden. Ist die Aggregation nach
            # 60 min noch nicht durch (Cron gestört), greift der hourly_data-Fallback.
            sek_seit_mitternacht = time.time() - lokal_heute
            if sek_seit_mitternacht < 600:
                return None
            has_day = conn.execute(
                'SELECT 1 FROM daily_data WHERE ts = ? LIMIT 1',
                (key_gestern,)).fetchone()
            fallback = False
            if has_day:
                tag = self._dd_bilanz(conn, 'ts = ?', (key_gestern,))
                wp_kwh = self._dd_scalar(conn, 'W_WP_total', 'ts = ?', (key_gestern,))
            elif sek_seit_mitternacht >= 3600:
                fallback = True
                tag, wp_kwh = self._tag_aus_hourly(conn, lokal_gestern, lokal_heute)
            else:
                return None  # daily_data[gestern] fehlt noch → später erneut versuchen

            # ── Monat / Jahr: Tage strikt vor gestern + Tag ──
            monat = self._add_bilanz(
                self._dd_bilanz(conn, 'ts >= ? AND ts < ?', (monatsanfang, key_gestern)),
                tag)
            jahr = self._add_bilanz(
                self._dd_bilanz(conn, 'ts >= ? AND ts < ?', (jahresanfang, key_gestern)),
                tag)

            # ── Gesamt: historische Jahre + laufendes Jahr ──
            gesamt = self._gesamt_bilanz(conn, gestern.year, jahr)

            # ── Verbraucher (nur Tag) ──
            hp_wh = self._scalar(
                conn, 'SELECT energy_wh FROM heizpatrone_daily WHERE ts = ?', (key_gestern,))
            wtp_wh = self._scalar(
                conn, 'SELECT energy_wh FROM wattpilot_daily WHERE ts = ?', (key_gestern,))
            hp_kwh = (hp_wh / 1000.0) if hp_wh else 0.0
            wtp_kwh = (wtp_wh / 1000.0) if wtp_wh else 0.0
            haushalt = max(0.0, tag['verbrauch'] - wp_kwh - hp_kwh - wtp_kwh)

            # ── Stresszeit (nur Tag) ──
            k_min, k_max = self._komfort_grenzen()
            stress_pct = self._stresszeit_pct(conn, lokal_gestern, lokal_heute, k_min, k_max)
        finally:
            conn.close()

        bis_str = gestern.strftime('%d.%m.')
        tag.update({
            'datum': gestern.strftime('%d.%m.%Y'),
            'fallback': fallback,
            'wp_kwh': wp_kwh, 'hp_kwh': hp_kwh,
            'wattpilot_kwh': wtp_kwh, 'haushalt_kwh': haushalt,
            'stresszeit_pct': stress_pct, 'stress_low': k_min, 'stress_high': k_max,
        })
        monat['label'] = f'{MONATE[gestern.month - 1]} {gestern.year}'
        monat['bis'] = bis_str
        jahr['label'] = str(gestern.year)
        jahr['bis'] = bis_str
        gesamt['label'] = 'seit Inbetriebnahme'
        gesamt['bis'] = gestern.strftime('%d.%m.%Y')
        return {'tag': tag, 'monat': monat, 'jahr': jahr, 'gesamt': gesamt}

    @staticmethod
    def _utc_midnight_ts(d: date) -> int:
        """UTC-Mitternacht des Datums — Schlüsselkonvention von daily_data."""
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())

    @staticmethod
    def _komfort_grenzen() -> tuple:
        """SOC-Komfortband (komfort_min/komfort_max) aus battery_control.json."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'config', 'battery_control.json')
        try:
            with open(path, encoding='utf-8') as f:
                g = json.load(f).get('soc_grenzen', {})
            return int(g.get('komfort_min', 25)), int(g.get('komfort_max', 75))
        except Exception:
            return 25, 75

    def _dd_bilanz(self, conn, where: str, params: tuple) -> dict:
        """Die 5 Energie-Kernwerte (kWh) aus daily_data für ein ts-Fenster."""
        sel = ', '.join(f'COALESCE(SUM({c}), 0)' for c in _DD_COLS)
        row = conn.execute(
            f'SELECT {sel} FROM daily_data WHERE {where}', params).fetchone()
        return {k: (row[i] or 0) / 1000.0 for i, k in enumerate(_DD_KEYS)}

    def _dd_scalar(self, conn, col: str, where: str, params: tuple) -> float:
        row = conn.execute(
            f'SELECT COALESCE(SUM({col}), 0) FROM daily_data WHERE {where}',
            params).fetchone()
        return (row[0] or 0) / 1000.0 if row else 0.0

    @staticmethod
    def _add_bilanz(basis: dict, tag: dict) -> dict:
        return {k: basis.get(k, 0) + tag.get(k, 0) for k in _DD_KEYS}

    @staticmethod
    def _scalar(conn, sql: str, params: tuple):
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row and row[0] is not None else None
        except sqlite3.Error:
            return None

    def _tag_aus_hourly(self, conn, start_ts, end_ts) -> tuple:
        """Fallback-Tagesbilanz aus hourly_data (lokales Tagesfenster)."""
        row = conn.execute("""
            SELECT COALESCE(SUM(W_PV_total_delta), 0),
                   COALESCE(SUM(W_Imp_Netz_delta), 0),
                   COALESCE(SUM(W_Exp_Netz_delta), 0),
                   COALESCE(SUM(W_Batt_Charge_total), 0),
                   COALESCE(SUM(W_Batt_Discharge_total), 0),
                   COALESCE(SUM(W_WP_total), 0)
            FROM hourly_data WHERE ts >= ? AND ts < ?
        """, (start_ts, end_ts)).fetchone()
        pv, imp, exp, bch, bdis, wp = [(v or 0) / 1000.0 for v in row]
        tag = {'erzeugung': pv, 'verbrauch': max(0.0, pv + imp - exp),
               'netzbezug': imp, 'einspeisung': exp,
               'batt_ladung': bch, 'batt_entladung': bdis}
        return tag, wp

    def _gesamt_bilanz(self, conn, jahr_aktuell: int, jahr_bilanz: dict) -> dict:
        """Gesamt = historische Jahre (yearly_statistics, year<aktuell) + laufendes Jahr."""
        gesamt = dict(jahr_bilanz)
        try:
            row = conn.execute("""
                SELECT COALESCE(SUM(solar_erzeugung_kwh), 0),
                       COALESCE(SUM(gesamt_verbrauch_kwh), 0),
                       COALESCE(SUM(netz_bezug_kwh), 0),
                       COALESCE(SUM(netz_einspeisung_kwh), 0),
                       COALESCE(SUM(batt_ladung_kwh), 0),
                       COALESCE(SUM(batt_entladung_kwh), 0)
                FROM yearly_statistics WHERE year < ?
            """, (jahr_aktuell,)).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            for i, k in enumerate(_DD_KEYS):
                gesamt[k] = gesamt.get(k, 0) + (row[i] or 0)
        return gesamt

    @staticmethod
    def _stresszeit_pct(conn, start_ts, end_ts, k_min: int, k_max: int):
        """Anteil der Tagesminuten mit SOC außerhalb des Komfortbands [k_min, k_max]."""
        try:
            row = conn.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN SOC_Batt_avg < ? OR SOC_Batt_avg > ? THEN 1 ELSE 0 END)
                FROM data_1min
                WHERE ts >= ? AND ts < ? AND SOC_Batt_avg IS NOT NULL
            """, (k_min, k_max, start_ts, end_ts)).fetchone()
        except sqlite3.Error:
            return None
        if not row or not row[0]:
            return None
        return 100.0 * (row[1] or 0) / row[0]

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

            mail.smtp_versand(self._smtp_host, self._smtp_port, self._smtp_user,
                              smtp_pass, self._from, self._email, msg)

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

            mail.smtp_versand(self._smtp_host, self._smtp_port, self._smtp_user,
                              smtp_pass, self._from, self._email, msg)

            self._dedup_mark(alarm_key)
            LOG.warning(f"Integrity-Alarm gesendet: {alarm_key} → {self._email}")
            return True
        except Exception as e:
            LOG.error(f"Integrity-Alarm FEHLGESCHLAGEN: {alarm_key}: {e}")
            return False

    def _aktualisiere_statusdateien(self) -> None:
        """Aktualisiere die Status-Markdown-Dateien (RAW-/System-/Netz-Status.md).

        Best-effort und **entkoppelt** vom Tagesbericht: Fehler hier berühren die
        bereits versandte Energie-Mail nicht. Liefert die read-only Diagnos-
        Snapshots an ``diagnos.status_report`` — einmal pro Tag zum Berichtszeitpunkt.
        """
        try:
            health_data = self._hole_diagnos_snapshot()
            integrity_data = self._hole_integrity_snapshot()
            nq_data = self._hole_nq_snapshot()
            self._write_status_files(health_data, integrity_data, nq_data)
        except Exception as e:
            LOG.debug(f"Statusdateien-Update übersprungen: {e}")

    def _hole_nq_snapshot(self) -> Optional[dict]:
        """Read-only NQ-Snapshot (Rolle N) zum Versandzeitpunkt."""
        try:
            return run_diagnos_nq()
        except Exception as e:
            LOG.warning(f"Sunset-Bericht: NQ-Snapshot nicht verfügbar: {e}")
            return None

    def _write_status_files(
        self,
        health_data: Optional[dict],
        integrity_data: Optional[dict],
        nq_data: Optional[dict],
    ) -> dict:
        """Schreibt RAW-/System-/Netz-Status.md (Beiwerk; Fehler nicht fatal)."""
        try:
            from diagnos import status_report
            return status_report.write_status_reports(
                integrity_data, health_data, nq_data=nq_data)
        except Exception:
            return {}


    def _sende_tagesbericht_mail(self, koerper: str) -> None:
        """Tagesbericht per E-Mail senden — reiner Energiebericht, kein Severity-Suffix."""
        datum_str = datetime.now().strftime('%d.%m.%Y')
        betreff = f'[PV-System] Tagesbericht {datum_str}'

        msg = MIMEText(koerper, 'plain', 'utf-8')
        msg['Subject'] = betreff
        msg['From'] = self._from
        msg['To'] = self._email
        msg['X-PV-Event'] = 'tagesbericht'

        smtp_pass = credential_store.lade('smtp_pass')
        if self._smtp_user and not smtp_pass:
            raise RuntimeError("SMTP-Passwort nicht gesetzt (credential_store)")

        mail.smtp_versand(self._smtp_host, self._smtp_port, self._smtp_user,
                          smtp_pass, self._from, self._email, msg)
