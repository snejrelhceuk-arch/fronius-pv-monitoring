"""Read-only Rollup-Konsistenzchecks fuer Diagnos-Integritaet.

Vergleicht ``monthly_statistics`` gegen die Tagessummen aus ``daily_data`` und
``yearly_statistics`` gegen die Monatssummen aus ``monthly_statistics``.

Feld-Differenzierung (entscheidend gegen Fehlalarme):
- **Fluss-Felder** (Solar/Bezug/Einspeisung/Gesamtverbrauch) sind eichgenaue
  Counter-Summen und muessen eng zusammenpassen -> relative Toleranz, alarmtreibend.
- **Methoden-Felder** (Batterieladung/-entladung, Direktverbrauch) nutzen bewusst
  zwei Methoden: der Monatswert stammt aus der eichgenauen Counter-Differenz
  (``data_monthly``) bzw. wird daraus abgeleitet, die Tagessumme aus
  BMS-Checkpoints (``collector/aggregate/daily.py``) bzw. direkt gemessenem
  ``W_PV_Direct_total``. Beide divergieren systematisch (~2-13 %). Diese Differenz
  wird berichtet, treibt aber KEINE Alarmschwere (sonst Dauer-CRIT ohne realen
  Datenfehler).
"""

import os
import sqlite3
from typing import Optional

from diagnos.config import CRIT, DB_PATH, FAIL, OK, WARN

# Fluss-Felder: relative Toleranz (Prozent des Monats-/Jahreswerts) + Absolut-Boden.
ROLLUP_FLOW_WARN_PCT = 1.5
ROLLUP_FLOW_CRIT_PCT = 3.0
ROLLUP_FLOW_ABS_FLOOR_KWH = 2.0   # darunter kein Alarm (Rundungsrauschen)

_FLOW_FIELDS = ('solar', 'bezug', 'einspeisung', 'gesamtverbrauch')
_METHOD_FIELDS = ('batt_ladung', 'batt_entladung', 'direktverbrauch')


def _db_readonly() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB_PATH):
        return None
    try:
        return sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _flow_severity(pct: float, abs_kwh: float) -> str:
    if abs_kwh < ROLLUP_FLOW_ABS_FLOOR_KWH:
        return OK
    if pct >= ROLLUP_FLOW_CRIT_PCT:
        return CRIT
    if pct >= ROLLUP_FLOW_WARN_PCT:
        return WARN
    return OK


_SEV_RANK = {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}


def _assess(check_name: str, period_key: str, records: list) -> dict:
    """Bewerte eine Liste vergleichbarer Perioden (Monat/Jahr).

    Jeder Record: ``{'period': str, 'count': int,
    'flow': {feld: (referenz, vergleich)}, 'method': {feld: (referenz, vergleich)}}``.
    """
    worst = OK
    max_flow_pct = 0.0
    max_flow_diff = 0.0
    max_method_pct = 0.0
    issues = []

    for rec in records:
        flow_diffs = {}
        row_sev = OK
        for field, (ref, cmp) in rec['flow'].items():
            ref = float(ref or 0.0)
            cmp = float(cmp or 0.0)
            diff = abs(ref - cmp)
            pct = 100.0 * diff / max(abs(ref), 1e-9)
            sev = _flow_severity(pct, diff)
            if _SEV_RANK[sev] > _SEV_RANK[row_sev]:
                row_sev = sev
            max_flow_pct = max(max_flow_pct, pct if diff >= ROLLUP_FLOW_ABS_FLOOR_KWH else 0.0)
            max_flow_diff = max(max_flow_diff, diff)
            if sev != OK:
                flow_diffs[field] = {'diff_kwh': round(diff, 2), 'pct': round(pct, 2)}

        method_diffs = {}
        for field, (ref, cmp) in rec['method'].items():
            ref = float(ref or 0.0)
            cmp = float(cmp or 0.0)
            diff = abs(ref - cmp)
            pct = 100.0 * diff / max(abs(ref), 1e-9)
            max_method_pct = max(max_method_pct, pct)
            method_diffs[field] = {'diff_kwh': round(diff, 2), 'pct': round(pct, 1)}

        if _SEV_RANK[row_sev] > _SEV_RANK[worst]:
            worst = row_sev
        if row_sev != OK:
            issues.append({
                period_key: rec['period'],
                'count': rec['count'],
                'max_flow_pct': round(max((d['pct'] for d in flow_diffs.values()), default=0.0), 2),
                'flow_diffs': flow_diffs,
                'method_diffs_kwh': method_diffs,
            })

    return {
        'check': check_name,
        'severity': worst,
        'periods_checked': len(records),
        'periods_with_diff': len(issues),
        'max_flow_diff_pct': round(max_flow_pct, 2),
        'max_diff_kwh': round(max_flow_diff, 2),   # Fingerprint-Kompat (Fluss-Felder)
        'max_method_diff_pct': round(max_method_pct, 1),
        'method_note': (
            'Methoden-Divergenz (Monat=eichgenaue Counter-Diff data_monthly, '
            'Tag=BMS-Checkpoints/W_PV_Direct) ist methodisch bedingt und nicht alarmtreibend.'
        ),
        'samples': issues[:5],
    }


def check_monthly_rollup(months: int = 3) -> dict:
    """Vergleicht monthly_statistics mit den Tagessummen aus daily_data."""
    conn = _db_readonly()
    if conn is None:
        return {'check': 'integrity:monthly_rollup', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        rows = conn.execute(
            """
            WITH recent_months AS (
                SELECT year, month FROM monthly_statistics
                ORDER BY year DESC, month DESC LIMIT ?
            ),
            daily_rollup AS (
                SELECT
                    CAST(strftime('%Y', ts, 'unixepoch', 'localtime') AS INTEGER) AS year,
                    CAST(strftime('%m', ts, 'unixepoch', 'localtime') AS INTEGER) AS month,
                    COALESCE(SUM(W_PV_total), 0) / 1000.0 AS solar,
                    COALESCE(SUM(W_Imp_Netz_total), 0) / 1000.0 AS bezug,
                    COALESCE(SUM(W_Exp_Netz_total), 0) / 1000.0 AS einspeisung,
                    COALESCE(SUM(W_PV_Direct_total), 0) / 1000.0 AS direktverbrauch,
                    COALESCE(SUM(W_Consumption_total), 0) / 1000.0 AS gesamtverbrauch,
                    COALESCE(SUM(W_Batt_Charge_total), 0) / 1000.0 AS batt_ladung,
                    COALESCE(SUM(W_Batt_Discharge_total), 0) / 1000.0 AS batt_entladung,
                    COUNT(*) AS day_count
                FROM daily_data GROUP BY 1, 2
            )
            SELECT m.year, m.month, d.day_count,
                m.solar_erzeugung_kwh, d.solar,
                m.netz_bezug_kwh, d.bezug,
                m.netz_einspeisung_kwh, d.einspeisung,
                m.direktverbrauch_kwh, d.direktverbrauch,
                m.gesamt_verbrauch_kwh, d.gesamtverbrauch,
                m.batt_ladung_kwh, d.batt_ladung,
                m.batt_entladung_kwh, d.batt_entladung
            FROM monthly_statistics m
            JOIN recent_months r ON r.year = m.year AND r.month = m.month
            LEFT JOIN daily_rollup d ON d.year = m.year AND d.month = m.month
            ORDER BY m.year DESC, m.month DESC
            """,
            (months,),
        ).fetchall()

        records = []
        for row in rows:
            if not row[2] or int(row[2]) <= 0:
                continue
            records.append({
                'period': f'{int(row[0]):04d}-{int(row[1]):02d}',
                'count': int(row[2]),
                'flow': {
                    'solar': (row[3], row[4]),
                    'bezug': (row[5], row[6]),
                    'einspeisung': (row[7], row[8]),
                    'gesamtverbrauch': (row[11], row[12]),
                },
                'method': {
                    'direktverbrauch': (row[9], row[10]),
                    'batt_ladung': (row[13], row[14]),
                    'batt_entladung': (row[15], row[16]),
                },
            })

        if not records:
            return {'check': 'integrity:monthly_rollup', 'severity': WARN,
                    'error': 'Keine vergleichbaren Monatsdaten'}
        return _assess('integrity:monthly_rollup', 'month', records)
    except sqlite3.Error as exc:
        return {'check': 'integrity:monthly_rollup', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_yearly_rollup(years: int = 2) -> dict:
    """Vergleicht yearly_statistics mit den Monatssummen aus monthly_statistics."""
    conn = _db_readonly()
    if conn is None:
        return {'check': 'integrity:yearly_rollup', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        rows = conn.execute(
            """
            WITH recent_years AS (
                SELECT year FROM yearly_statistics ORDER BY year DESC LIMIT ?
            ),
            monthly_rollup AS (
                SELECT
                    year,
                    COALESCE(SUM(solar_erzeugung_kwh), 0) AS solar,
                    COALESCE(SUM(netz_bezug_kwh), 0) AS bezug,
                    COALESCE(SUM(netz_einspeisung_kwh), 0) AS einspeisung,
                    COALESCE(SUM(direktverbrauch_kwh), 0) AS direktverbrauch,
                    COALESCE(SUM(gesamt_verbrauch_kwh), 0) AS gesamtverbrauch,
                    COALESCE(SUM(batt_ladung_kwh), 0) AS batt_ladung,
                    COALESCE(SUM(batt_entladung_kwh), 0) AS batt_entladung,
                    COUNT(*) AS month_count
                FROM monthly_statistics GROUP BY year
            )
            SELECT y.year, mr.month_count,
                y.solar_erzeugung_kwh, mr.solar,
                y.netz_bezug_kwh, mr.bezug,
                y.netz_einspeisung_kwh, mr.einspeisung,
                y.direktverbrauch_kwh, mr.direktverbrauch,
                y.gesamt_verbrauch_kwh, mr.gesamtverbrauch,
                y.batt_ladung_kwh, mr.batt_ladung,
                y.batt_entladung_kwh, mr.batt_entladung
            FROM yearly_statistics y
            JOIN recent_years r ON r.year = y.year
            LEFT JOIN monthly_rollup mr ON mr.year = y.year
            ORDER BY y.year DESC
            """,
            (years,),
        ).fetchall()

        records = []
        for row in rows:
            if not row[1] or int(row[1]) <= 0:
                continue
            records.append({
                'period': str(int(row[0])),
                'count': int(row[1]),
                'flow': {
                    'solar': (row[2], row[3]),
                    'bezug': (row[4], row[5]),
                    'einspeisung': (row[6], row[7]),
                    'gesamtverbrauch': (row[10], row[11]),
                },
                'method': {
                    'direktverbrauch': (row[8], row[9]),
                    'batt_ladung': (row[12], row[13]),
                    'batt_entladung': (row[14], row[15]),
                },
            })

        if not records:
            return {'check': 'integrity:yearly_rollup', 'severity': WARN,
                    'error': 'Keine vergleichbaren Jahresdaten'}
        return _assess('integrity:yearly_rollup', 'year', records)
    except sqlite3.Error as exc:
        return {'check': 'integrity:yearly_rollup', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()
