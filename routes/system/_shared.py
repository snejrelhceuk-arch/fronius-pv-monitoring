"""Geteilte Read-Helfer fuer das system-Blueprint.

Enthaelt Funktionen, die von mehreren Submodulen (``ha.py`` und
``wattpilot.py``) gemeinsam genutzt werden.
"""
import sqlite3
from datetime import datetime

from routes.helpers import get_db_connection


def _read_wattpilot_db_summary(now: float) -> dict:
    """Kompakten Wattpilot-Status aus der DB lesen (kein Live-WebSocket)."""
    conn = get_db_connection()
    if not conn:
        raise RuntimeError('DB nicht verfügbar')

    try:
        try:
            row = conn.execute(
                """
                SELECT ts, energy_total_wh, power_w, car_state, session_wh,
                       temperature_c, phase_mode, amp, trx, lmo, frc
                FROM wattpilot_readings
                ORDER BY ts DESC
                LIMIT 1
                """
            ).fetchone()
            has_extended_cols = True
        except sqlite3.OperationalError:
            row = conn.execute(
                """
                SELECT ts, energy_total_wh, power_w, car_state, session_wh,
                       temperature_c, phase_mode
                FROM wattpilot_readings
                ORDER BY ts DESC
                LIMIT 1
                """
            ).fetchone()
            has_extended_cols = False
    finally:
        conn.close()

    if not row:
        raise RuntimeError('Keine Wattpilot-Daten in DB')

    if has_extended_cols:
        ts, energy_total_wh, power_w, car_state, session_wh, temperature_c, phase_mode, amp, trx, lmo, frc = row
    else:
        ts, energy_total_wh, power_w, car_state, session_wh, temperature_c, phase_mode = row
        amp, trx, lmo, frc = 0, None, 0, 0
    age_s = round(now - float(ts))
    car_state = int(car_state or 0)
    phase_mode = int(phase_mode or 0)
    lmo_i = int(lmo or 0)
    mode_name = {
        3: 'Standard',
        4: 'Eco (PV)',
        5: 'Next Trip',
    }.get(lmo_i, '—')
    return {
        'online': age_s <= 180,
        'source': 'db',
        'age_s': age_s,
        'timestamp': datetime.now().isoformat(),
        'last_update_ts': ts,
        'energy_total_wh': energy_total_wh or 0,
        'energy_total_kwh': round((energy_total_wh or 0) / 1000.0, 3),
        'energy_session_wh': session_wh or 0,
        'energy_session_kwh': round((session_wh or 0) / 1000.0, 3),
        'power_w': float(power_w or 0),
        'power_kw': round(float(power_w or 0) / 1000.0, 2),
        'car_state': car_state,
        'car_state_text': {
            0: 'Unbekannt',
            1: 'Bereit (kein Auto)',
            2: 'Lädt',
            3: 'Warte auf Auto',
            4: 'Vollständig',
            5: 'Fehler',
        }.get(car_state, f'Unbekannt ({car_state})'),
        'charging': car_state == 2,
        'temperature_c': float(temperature_c or 0),
        # phase_mode wird vom Wattpilot nicht zuverlässig gemeldet (fast immer 0,
        # nie 3-phasig trotz >9 kW) → nicht als belastbare Info anzeigen.
        'phase_mode_raw': phase_mode,
        'amp': int(amp or 0),
        'lmo': lmo_i,
        'mode_name': mode_name,
        'trx': trx,
        'frc': int(frc or 0),
    }
