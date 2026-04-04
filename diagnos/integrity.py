#!/usr/bin/env python3
"""
diagnos/integrity.py — Phase-2 Read-only Integritaetschecks

Schicht D: strikt read-only.
Ausgabe: JSON auf stdout, Auffaelligkeiten auf stderr.

Nutzung:
    python3 -m diagnos.integrity
    python3 -m diagnos.integrity --pretty
"""

import json
import os
import sqlite3
import sys
import time
from glob import glob
from datetime import datetime, timezone
from typing import Optional

from diagnos.config import BASE_DIR, CRIT, DB_PATH, FAIL, OK, WARN

DAILY_BALANCE_WARN_WH = 300.0
DAILY_BALANCE_CRIT_WH = 1000.0
ROLLUP_WARN_KWH = 0.2
ROLLUP_CRIT_KWH = 1.0
RAW_GAP_SCAN_HOURS = 24
DATA_1MIN_GAP_SCAN_HOURS = 72
DATA_15MIN_GAP_SCAN_DAYS = 14
HOURLY_GAP_SCAN_DAYS = 30
RAW_GAP_MIN_S = 30
DATA_1MIN_GAP_MIN_S = 120
DATA_15MIN_GAP_MIN_S = 1800
HOURLY_GAP_MIN_S = 5400
CONFIG_JSON_GLOB = os.path.join(BASE_DIR, 'config', '*.json')
ATTACHMENT_STATE_FILE = os.path.join(BASE_DIR, 'config', 'fronius_attachment_state.json')


def _db_readonly() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB_PATH):
        return None
    try:
        return sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _severity_from_delta(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return CRIT
    if value >= warn:
        return WARN
    return OK


def _load_attachment_state() -> Optional[dict]:
    try:
        if not os.path.exists(ATTACHMENT_STATE_FILE):
            return None
        with open(ATTACHMENT_STATE_FILE, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _format_ts_utc(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def check_fronius_attachment_state() -> dict:
    """Prüft den gespeicherten WR-/Schnittstellenzustand aus dem Attachment-State."""
    state = _load_attachment_state()
    if not state:
        return {
            'check': 'integrity:fronius_attachment_state',
            'severity': WARN,
            'error': 'Attachment-State fehlt oder ist nicht lesbar',
        }

    snapshot = state.get('version_snapshot') or {}
    validation = state.get('last_validation') or {}
    modbus = validation.get('modbus') or {}
    solar_api = validation.get('solar_api') or {}
    internal_api = validation.get('internal_api') or {}

    modbus_ok = bool(modbus) and all(bool(item.get('ok')) for item in modbus.values())
    solar_api_ok = bool(solar_api) and all(bool(item.get('ok')) for item in solar_api.values())
    internal_api_ok = bool(internal_api) and all(bool(item.get('ok')) for item in internal_api.values())
    battery_api = internal_api.get('/api/config/batteries') or {}
    battery_api_ok = bool(battery_api.get('ok'))

    severity = OK
    if validation:
        if not (modbus_ok and solar_api_ok and internal_api_ok and battery_api_ok):
            severity = CRIT
    else:
        severity = WARN

    # --- Collector-Liveness aus neuen Feldern ---
    last_poll_ts = state.get('last_successful_poll_ts')
    consecutive_errors = state.get('consecutive_errors', 0)
    reconnect = state.get('last_reconnect_event') or {}

    poll_age_s = None
    collector_live = None
    if last_poll_ts:
        poll_age_s = int(time.time()) - int(last_poll_ts)
        collector_live = poll_age_s <= 300  # 5 min Toleranz
        if poll_age_s > 300:
            severity = CRIT
        elif poll_age_s > 60:
            severity = max(severity, WARN, key=lambda s: {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}.get(s, 0))

    if consecutive_errors >= 5:
        severity = CRIT
    elif consecutive_errors >= 3:
        severity = max(severity, WARN, key=lambda s: {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}.get(s, 0))

    # Assessment-Text
    parts = []
    if validation and modbus_ok and solar_api_ok and internal_api_ok and battery_api_ok:
        parts.append('Schnittstellenprüfung erfolgreich.')
    elif validation:
        parts.append('Schnittstellenprüfung mit Fehlern.')
    else:
        parts.append('Keine Vollprüfung gespeichert.')

    if collector_live is True:
        parts.append(f'Collector aktiv (letzter Poll vor {poll_age_s}s).')
    elif collector_live is False:
        parts.append(f'Collector inaktiv seit {poll_age_s}s!')
    # else: Feld noch nicht vorhanden (alter Collector-Code)

    if consecutive_errors > 0:
        parts.append(f'{consecutive_errors} Fehler in Folge.')

    if reconnect.get('ts'):
        rc_age = int(time.time()) - int(reconnect['ts'])
        rc_ok = reconnect.get('success', False)
        if rc_age < 3600:
            parts.append(
                f'Reconnect vor {rc_age}s ({reconnect.get("trigger", "?")}): '
                f'{"OK" if rc_ok else "FEHLGESCHLAGEN"}.'
            )

    return {
        'check': 'integrity:fronius_attachment_state',
        'severity': severity,
        'inverter_vr': snapshot.get('inverter_vr'),
        'inverter_sn': snapshot.get('inverter_sn'),
        'last_seen_utc': _format_ts_utc(state.get('last_seen_ts')),
        'last_version_change_utc': _format_ts_utc(state.get('last_version_change_ts')),
        'validation_available': bool(validation),
        'modbus_ok': modbus_ok,
        'solar_api_ok': solar_api_ok,
        'internal_api_ok': internal_api_ok,
        'battery_api_ok': battery_api_ok,
        'collector_live': collector_live,
        'last_poll_age_s': poll_age_s,
        'consecutive_errors': consecutive_errors,
        'last_reconnect': reconnect if reconnect.get('ts') else None,
        'assessment': ' '.join(parts),
    }


def check_daily_energy_balance(days: int = 14) -> dict:
    """Prüft Verbrauch = PV + Bezug - Einspeisung für die letzten vollen Tage."""
    conn = _db_readonly()
    if conn is None:
        return {'check': 'integrity:daily_energy_balance', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        current_day = (int(time.time()) // 86400) * 86400
        rows = conn.execute(
            """
            SELECT
                ts,
                ABS(COALESCE(W_Consumption_total, 0) - (
                    COALESCE(W_PV_total, 0) + COALESCE(W_Imp_Netz_total, 0) - COALESCE(W_Exp_Netz_total, 0)
                )) AS diff_wh,
                W_Consumption_total,
                W_PV_total,
                W_Imp_Netz_total,
                W_Exp_Netz_total
            FROM daily_data
            WHERE ts < ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (current_day, days),
        ).fetchall()

        if not rows:
            return {
                'check': 'integrity:daily_energy_balance',
                'severity': WARN,
                'error': 'Keine daily_data-Vergleichsdaten',
            }

        max_diff = max(float(row[1] or 0) for row in rows)
        bad_rows = [row for row in rows if float(row[1] or 0) >= DAILY_BALANCE_WARN_WH]

        samples = []
        for row in bad_rows[:5]:
            day = datetime.fromtimestamp(float(row[0]), tz=timezone.utc).strftime('%Y-%m-%d')
            samples.append({
                'day': day,
                'diff_wh': round(float(row[1] or 0), 1),
                'consumption_wh': round(float(row[2] or 0), 1),
                'formula_wh': round(float((row[3] or 0) + (row[4] or 0) - (row[5] or 0)), 1),
            })

        return {
            'check': 'integrity:daily_energy_balance',
            'days_checked': len(rows),
            'bad_days': len(bad_rows),
            'max_diff_wh': round(max_diff, 1),
            'severity': _severity_from_delta(max_diff, DAILY_BALANCE_WARN_WH, DAILY_BALANCE_CRIT_WH),
            'samples': samples,
        }
    except sqlite3.Error as exc:
        return {'check': 'integrity:daily_energy_balance', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_monthly_rollup(months: int = 3) -> dict:
    """Vergleicht monthly_statistics mit Summen aus daily_data fuer die letzten Monate."""
    conn = _db_readonly()
    if conn is None:
        return {'check': 'integrity:monthly_rollup', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        rows = conn.execute(
            """
            WITH recent_months AS (
                SELECT year, month
                FROM monthly_statistics
                ORDER BY year DESC, month DESC
                LIMIT ?
            ),
            daily_rollup AS (
                SELECT
                    CAST(strftime('%Y', ts, 'unixepoch', 'localtime') AS INTEGER) AS year,
                    CAST(strftime('%m', ts, 'unixepoch', 'localtime') AS INTEGER) AS month,
                    ROUND(COALESCE(SUM(W_PV_total), 0) / 1000.0, 2) AS solar_kwh,
                    ROUND(COALESCE(SUM(W_Imp_Netz_total), 0) / 1000.0, 2) AS bezug_kwh,
                    ROUND(COALESCE(SUM(W_Exp_Netz_total), 0) / 1000.0, 2) AS einspeisung_kwh,
                    ROUND(COALESCE(SUM(W_Batt_Charge_total), 0) / 1000.0, 2) AS batt_ladung_kwh,
                    ROUND(COALESCE(SUM(W_Batt_Discharge_total), 0) / 1000.0, 2) AS batt_entladung_kwh,
                    ROUND(COALESCE(SUM(W_PV_Direct_total), 0) / 1000.0, 2) AS direkt_kwh,
                    ROUND(COALESCE(SUM(W_Consumption_total), 0) / 1000.0, 2) AS verbrauch_kwh,
                    COUNT(*) AS day_count
                FROM daily_data
                GROUP BY 1, 2
            )
            SELECT
                m.year, m.month,
                d.day_count,
                ABS(COALESCE(m.solar_erzeugung_kwh, 0) - COALESCE(d.solar_kwh, 0)) AS diff_solar,
                ABS(COALESCE(m.netz_bezug_kwh, 0) - COALESCE(d.bezug_kwh, 0)) AS diff_bezug,
                ABS(COALESCE(m.netz_einspeisung_kwh, 0) - COALESCE(d.einspeisung_kwh, 0)) AS diff_einsp,
                ABS(COALESCE(m.batt_ladung_kwh, 0) - COALESCE(d.batt_ladung_kwh, 0)) AS diff_batt_lad,
                ABS(COALESCE(m.batt_entladung_kwh, 0) - COALESCE(d.batt_entladung_kwh, 0)) AS diff_batt_entl,
                ABS(COALESCE(m.direktverbrauch_kwh, 0) - COALESCE(d.direkt_kwh, 0)) AS diff_direkt,
                ABS(COALESCE(m.gesamt_verbrauch_kwh, 0) - COALESCE(d.verbrauch_kwh, 0)) AS diff_verbrauch
            FROM monthly_statistics m
            JOIN recent_months r ON r.year = m.year AND r.month = m.month
            LEFT JOIN daily_rollup d ON d.year = m.year AND d.month = m.month
            ORDER BY m.year DESC, m.month DESC
            """,
            (months,),
        ).fetchall()

        comparable = [row for row in rows if row[2] and row[2] > 0]
        if not comparable:
            return {
                'check': 'integrity:monthly_rollup',
                'severity': WARN,
                'error': 'Keine vergleichbaren Monatsdaten',
            }

        issues = []
        max_diff = 0.0
        for row in comparable:
            year, month, day_count = int(row[0]), int(row[1]), int(row[2])
            field_diffs = {
                'solar': float(row[3] or 0),
                'bezug': float(row[4] or 0),
                'einspeisung': float(row[5] or 0),
                'batt_ladung': float(row[6] or 0),
                'batt_entladung': float(row[7] or 0),
                'direktverbrauch': float(row[8] or 0),
                'gesamtverbrauch': float(row[9] or 0),
            }
            row_max = max(field_diffs.values())
            max_diff = max(max_diff, row_max)
            if row_max >= ROLLUP_WARN_KWH:
                issues.append({
                    'month': f'{year:04d}-{month:02d}',
                    'day_count': day_count,
                    'max_diff_kwh': round(row_max, 2),
                    'diffs_kwh': {k: round(v, 2) for k, v in field_diffs.items() if v >= ROLLUP_WARN_KWH},
                })

        return {
            'check': 'integrity:monthly_rollup',
            'months_checked': len(comparable),
            'months_with_diff': len(issues),
            'max_diff_kwh': round(max_diff, 2),
            'severity': _severity_from_delta(max_diff, ROLLUP_WARN_KWH, ROLLUP_CRIT_KWH),
            'samples': issues[:5],
        }
    except sqlite3.Error as exc:
        return {'check': 'integrity:monthly_rollup', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_yearly_rollup(years: int = 2) -> dict:
    """Vergleicht yearly_statistics mit Summen aus monthly_statistics fuer die letzten Jahre."""
    conn = _db_readonly()
    if conn is None:
        return {'check': 'integrity:yearly_rollup', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        rows = conn.execute(
            """
            WITH recent_years AS (
                SELECT year
                FROM yearly_statistics
                ORDER BY year DESC
                LIMIT ?
            ),
            monthly_rollup AS (
                SELECT
                    year,
                    ROUND(COALESCE(SUM(solar_erzeugung_kwh), 0), 2) AS solar_kwh,
                    ROUND(COALESCE(SUM(netz_bezug_kwh), 0), 2) AS bezug_kwh,
                    ROUND(COALESCE(SUM(netz_einspeisung_kwh), 0), 2) AS einspeisung_kwh,
                    ROUND(COALESCE(SUM(batt_ladung_kwh), 0), 2) AS batt_ladung_kwh,
                    ROUND(COALESCE(SUM(batt_entladung_kwh), 0), 2) AS batt_entladung_kwh,
                    ROUND(COALESCE(SUM(direktverbrauch_kwh), 0), 2) AS direkt_kwh,
                    ROUND(COALESCE(SUM(gesamt_verbrauch_kwh), 0), 2) AS verbrauch_kwh,
                    COUNT(*) AS month_count
                FROM monthly_statistics
                GROUP BY year
            )
            SELECT
                y.year,
                m.month_count,
                ABS(COALESCE(y.solar_erzeugung_kwh, 0) - COALESCE(m.solar_kwh, 0)) AS diff_solar,
                ABS(COALESCE(y.netz_bezug_kwh, 0) - COALESCE(m.bezug_kwh, 0)) AS diff_bezug,
                ABS(COALESCE(y.netz_einspeisung_kwh, 0) - COALESCE(m.einspeisung_kwh, 0)) AS diff_einsp,
                ABS(COALESCE(y.batt_ladung_kwh, 0) - COALESCE(m.batt_ladung_kwh, 0)) AS diff_batt_lad,
                ABS(COALESCE(y.batt_entladung_kwh, 0) - COALESCE(m.batt_entladung_kwh, 0)) AS diff_batt_entl,
                ABS(COALESCE(y.direktverbrauch_kwh, 0) - COALESCE(m.direkt_kwh, 0)) AS diff_direkt,
                ABS(COALESCE(y.gesamt_verbrauch_kwh, 0) - COALESCE(m.verbrauch_kwh, 0)) AS diff_verbrauch
            FROM yearly_statistics y
            JOIN recent_years r ON r.year = y.year
            LEFT JOIN monthly_rollup m ON m.year = y.year
            ORDER BY y.year DESC
            """,
            (years,),
        ).fetchall()

        comparable = [row for row in rows if row[1] and row[1] > 0]
        if not comparable:
            return {
                'check': 'integrity:yearly_rollup',
                'severity': WARN,
                'error': 'Keine vergleichbaren Jahresdaten',
            }

        issues = []
        max_diff = 0.0
        for row in comparable:
            year, month_count = int(row[0]), int(row[1])
            field_diffs = {
                'solar': float(row[2] or 0),
                'bezug': float(row[3] or 0),
                'einspeisung': float(row[4] or 0),
                'batt_ladung': float(row[5] or 0),
                'batt_entladung': float(row[6] or 0),
                'direktverbrauch': float(row[7] or 0),
                'gesamtverbrauch': float(row[8] or 0),
            }
            row_max = max(field_diffs.values())
            max_diff = max(max_diff, row_max)
            if row_max >= ROLLUP_WARN_KWH:
                issues.append({
                    'year': year,
                    'month_count': month_count,
                    'max_diff_kwh': round(row_max, 2),
                    'diffs_kwh': {k: round(v, 2) for k, v in field_diffs.items() if v >= ROLLUP_WARN_KWH},
                })

        return {
            'check': 'integrity:yearly_rollup',
            'years_checked': len(comparable),
            'years_with_diff': len(issues),
            'max_diff_kwh': round(max_diff, 2),
            'severity': _severity_from_delta(max_diff, ROLLUP_WARN_KWH, ROLLUP_CRIT_KWH),
            'samples': issues[:5],
        }
    except sqlite3.Error as exc:
        return {'check': 'integrity:yearly_rollup', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def _gap_class(age_s: float) -> str:
    if age_s < 120:
        return 'micro'
    if age_s < 1800:
        return 'short'
    if age_s < 21600:
        return 'medium'
    return 'long'


def _gap_severity(category_counts: dict) -> str:
    if category_counts.get('long', 0) or category_counts.get('medium', 0):
        return CRIT
    if category_counts.get('short', 0) or category_counts.get('micro', 0):
        return WARN
    return OK


def _run_gap_scan(table: str, hours: int, min_gap_s: int) -> dict:
    conn = _db_readonly()
    if conn is None:
        return {'check': f'integrity:gaps:{table}', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        cutoff = time.time() - (hours * 3600)
        rows = conn.execute(
            f"""
            WITH ordered AS (
                SELECT
                    ts,
                    LEAD(ts) OVER (ORDER BY ts) AS next_ts
                FROM {table}
                WHERE ts >= ?
            )
            SELECT
                ts,
                next_ts,
                CAST(next_ts - ts AS REAL) AS gap_s
            FROM ordered
            WHERE next_ts IS NOT NULL
              AND (next_ts - ts) > ?
            ORDER BY gap_s DESC, ts DESC
            """,
            (cutoff, min_gap_s),
        ).fetchall()

        category_counts = {'micro': 0, 'short': 0, 'medium': 0, 'long': 0}
        samples = []
        max_gap = 0.0
        for row in rows:
            start_ts = float(row[0])
            end_ts = float(row[1])
            gap_s = float(row[2])
            gap_type = _gap_class(gap_s)
            category_counts[gap_type] += 1
            max_gap = max(max_gap, gap_s)
            if len(samples) < 5:
                samples.append({
                    'start_utc': datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'end_utc': datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'gap_s': round(gap_s, 1),
                    'class': gap_type,
                })

        return {
            'check': f'integrity:gaps:{table}',
            'window_hours': hours,
            'min_gap_s': min_gap_s,
            'gap_count': len(rows),
            'max_gap_s': round(max_gap, 1),
            'classes': category_counts,
            'severity': _gap_severity(category_counts),
            'samples': samples,
        }
    except sqlite3.Error as exc:
        return {'check': f'integrity:gaps:{table}', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_raw_data_gaps(hours: int = RAW_GAP_SCAN_HOURS) -> dict:
    """Prüft raw_data auf Lücken > 30s im jüngeren Verlauf."""
    return _run_gap_scan('raw_data', hours, RAW_GAP_MIN_S)


def check_data_1min_gaps(hours: int = DATA_1MIN_GAP_SCAN_HOURS) -> dict:
    """Prüft data_1min auf Lücken > 120s im jüngeren Verlauf."""
    return _run_gap_scan('data_1min', hours, DATA_1MIN_GAP_MIN_S)


def check_data_15min_gaps(days: int = DATA_15MIN_GAP_SCAN_DAYS) -> dict:
    """Prüft data_15min auf Lücken > 30min im jüngeren Verlauf."""
    result = _run_gap_scan('data_15min', days * 24, DATA_15MIN_GAP_MIN_S)
    result['window_days'] = days
    return result


def check_hourly_gaps(days: int = HOURLY_GAP_SCAN_DAYS) -> dict:
    """Prüft hourly_data auf Lücken > 90min im jüngeren Verlauf."""
    result = _run_gap_scan('hourly_data', days * 24, HOURLY_GAP_MIN_S)
    result['window_days'] = days
    return result


def check_config_json_parse() -> dict:
    """Prüft, ob alle JSON-Dateien unter config/ syntaktisch lesbar sind."""
    files = sorted(path for path in glob(CONFIG_JSON_GLOB) if os.path.isfile(path))
    if not files:
        return {
            'check': 'integrity:config_json_parse',
            'severity': WARN,
            'error': 'Keine JSON-Dateien unter config/ gefunden',
        }

    invalid = []
    for path in files:
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            invalid.append({
                'file': os.path.relpath(path, BASE_DIR),
                'error': str(exc),
            })

    severity = CRIT if invalid else OK
    return {
        'check': 'integrity:config_json_parse',
        'files_checked': len(files),
        'invalid_files': len(invalid),
        'severity': severity,
        'samples': invalid[:5],
    }


def _find_check(checks: list, name: str) -> Optional[dict]:
    for check in checks:
        if check.get('check') == name:
            return check
    return None


def _version_change_near_gap(gap_check: dict, attachment_check: Optional[dict]) -> Optional[bool]:
    if not attachment_check:
        return None
    version_change_utc = attachment_check.get('last_version_change_utc')
    if not version_change_utc or not gap_check.get('samples'):
        return None
    try:
        version_change_ts = datetime.strptime(version_change_utc, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
        gap_start_ts = datetime.strptime(gap_check['samples'][0]['start_utc'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
        return abs(version_change_ts - gap_start_ts) <= 86400
    except (KeyError, ValueError, TypeError):
        return None


def _annotate_gap_checks(checks: list) -> None:
    attachment_check = _find_check(checks, 'integrity:fronius_attachment_state')
    daily_balance_ok = (_find_check(checks, 'integrity:daily_energy_balance') or {}).get('severity') == OK
    monthly_ok = (_find_check(checks, 'integrity:monthly_rollup') or {}).get('severity') == OK
    yearly_ok = (_find_check(checks, 'integrity:yearly_rollup') or {}).get('severity') == OK

    gap_notes = {
        'integrity:gaps:raw_data': [
            'Collector verwirft fehlerhafte Polls statt NULL-/0-Datensätze in raw_data zu schreiben.',
            'Folgedaten aktuell positiv: data_1min/raw_data im Kurzfenster konsistent.',
        ],
        'integrity:gaps:data_1min': [
            'aggregate_1min.py prüft die letzten 10 Minuten auf fehlende Buckets und backfillt aus raw_data.',
            'data_1min nutzt Leistungsintegration statt instabiler Zählerdifferenzen.',
        ],
        'integrity:gaps:data_15min': [
            'aggregate.py füllt fehlende 15min-Fenster bei Bedarf aus data_1min nach.',
            'NULLIF(0) und Plausibilitätsgrenzen neutralisieren Reset-/Init-Artefakte.',
        ],
        'integrity:gaps:hourly_data': [
            'aggregate_daily.py nutzt Counter-vs-SUM(Δ)-Fallback mit Reset-Erkennung und Restgrößen.',
            'BMS-Checkpoints und Protected Days stabilisieren Tages-/Monatswerte trotz technischer Lücken.',
        ],
    }

    for check in checks:
        if not str(check.get('check', '')).startswith('integrity:gaps:'):
            continue

        if check.get('gap_count', 0) <= 0:
            check['assessment'] = 'Keine Lücken im Prüffenster erkannt.'
            continue

        near_change = _version_change_near_gap(check, attachment_check)
        check['neutralization_notes'] = list(gap_notes.get(check['check'], []))
        check['followup_assessment'] = (
            'Folgedaten aktuell positiv: Tagesbilanz sowie Monats-/Jahresrollups sind konsistent.'
            if daily_balance_ok and monthly_ok and yearly_ok
            else 'Folgedaten nicht vollständig positiv belegbar; Konsistenzchecks gesondert prüfen.'
        )
        check['version_change_near_gap'] = near_change

        if attachment_check:
            check['attachment_context'] = {
                'inverter_vr': attachment_check.get('inverter_vr'),
                'last_version_change_utc': attachment_check.get('last_version_change_utc'),
                'validation_available': attachment_check.get('validation_available'),
                'modbus_ok': attachment_check.get('modbus_ok'),
                'solar_api_ok': attachment_check.get('solar_api_ok'),
                'internal_api_ok': attachment_check.get('internal_api_ok'),
                'battery_api_ok': attachment_check.get('battery_api_ok'),
            }

        if near_change is True:
            check['neutralization_notes'].append('Zeitliche Nähe zu dokumentiertem Versionswechsel vorhanden.')
        elif near_change is False:
            check['neutralization_notes'].append('Kein dokumentierter Versionswechsel im 24h-Umfeld der Lücke.')
        else:
            check['neutralization_notes'].append('Versionswechsel im Lückenumfeld nicht belegbar (kein Change-Timestamp).')

        if attachment_check and attachment_check.get('validation_available'):
            if attachment_check.get('modbus_ok') and attachment_check.get('solar_api_ok') and attachment_check.get('internal_api_ok') and attachment_check.get('battery_api_ok'):
                check['neutralization_notes'].append('WR-Schnittstellenprüfung erfolgreich, inkl. F1 /api/config/batteries.')
            else:
                check['neutralization_notes'].append('WR-Schnittstellenprüfung nicht vollständig erfolgreich gespeichert.')
        else:
            check['neutralization_notes'].append('Keine gespeicherte Vollprüfung der WR-Schnittstellen vorhanden.')


def run_all() -> dict:
    checks = [
        check_daily_energy_balance(),
        check_fronius_attachment_state(),
        check_raw_data_gaps(),
        check_data_1min_gaps(),
        check_data_15min_gaps(),
        check_hourly_gaps(),
        check_config_json_parse(),
        check_monthly_rollup(),
        check_yearly_rollup(),
    ]
    _annotate_gap_checks(checks)
    severity_order = {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}
    worst = max(checks, key=lambda c: severity_order.get(c.get('severity', OK), 0))
    return {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'host': os.uname().nodename,
        'overall': worst['severity'],
        'checks': checks,
    }


def main():
    pretty = '--pretty' in sys.argv
    result = run_all()
    print(json.dumps(result, indent=2 if pretty else None, ensure_ascii=False))

    for check in result['checks']:
        severity = check.get('severity', OK)
        if severity in (WARN, CRIT, FAIL):
            print(f'[{severity.upper()}] {check["check"]}: {check}', file=sys.stderr)

    if result['overall'] in (CRIT, FAIL):
        sys.exit(2)
    if result['overall'] == WARN:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()