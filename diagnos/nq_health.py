#!/usr/bin/env python3
"""
diagnos/nq_health.py — Read-only NQ-Beobachtung (Rolle N) fuer Diagnos.

Schicht D beobachtet das Netzqualitaets-Subsystem (PAC4200, Rolle N) rein
lesend: Ist die Tech->Primary-Pipeline lebendig (frische Aggregate), rollt die
Tagesenergie, sind die Primary-NQ-Timer scharf? Kein Zugriff auf die
PAC4200-Hardware (die liest ausschliesslich der Tech-Collector) und kein
Schreibpfad.

Die PAC4200-Hardware wird **indirekt** beobachtet: frische Aggregate in der
Primary-Monats-DB (nq/db/nq_YYYY-MM.db) beweisen die gesamte Kette
PAC -> Tech-Collector -> Transfer -> Aggregation. Ein Stillstand faellt als
Freshness-Alarm auf. Der Check ist rollen- und deploymentbewusst: fehlt die
NQ-DB (Modul nicht aktiv) oder laeuft der Host als Failover, bleibt er still.

Nutzung:
    python3 -m diagnos.nq_health --pretty
"""

import glob
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from diagnos.config import (
    CRIT, FAIL, OK, WARN, ROLE_FILE,
    NQ_DB_DIR, NQ_PIPELINE_WARN_S, NQ_PIPELINE_CRIT_S,
    NQ_ENERGY_WARN_DAYS, NQ_ENERGY_CRIT_DAYS, NQ_TIMERS,
)

_SEV_ORDER = {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}


def _read_role() -> str:
    try:
        if not os.path.exists(ROLE_FILE):
            return 'primary'
        with open(ROLE_FILE, encoding='utf-8') as f:
            role = f.readline().strip().lower()
        return role if role in ('primary', 'failover') else 'primary'
    except OSError:
        return 'primary'


def _newest_month_db() -> Optional[str]:
    """Neueste NQ-Monats-DB (lexikografisch = juengster Monat, Format nq_YYYY-MM.db)."""
    files = [p for p in glob.glob(os.path.join(NQ_DB_DIR, 'nq_*.db')) if os.path.isfile(p)]
    return max(files) if files else None


def _db_ro(path: str) -> Optional[sqlite3.Connection]:
    try:
        return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return None


def check_nq_pipeline_freshness() -> dict:
    """Frische der 5-min-Aggregate — beweist die PAC->Tech->Primary-Kette."""
    db = _newest_month_db()
    if db is None:
        return {'check': 'nq:pipeline_freshness', 'severity': OK, 'skipped': True,
                'detail': 'keine NQ-Monats-DB (Modul nicht aktiv)'}
    conn = _db_ro(db)
    if conn is None:
        return {'check': 'nq:pipeline_freshness', 'severity': FAIL,
                'error': f'{os.path.basename(db)} nicht lesbar'}
    try:
        row = conn.execute('SELECT MAX(ts) FROM nq_5min').fetchone()
        if not row or row[0] is None:
            return {'check': 'nq:pipeline_freshness', 'severity': WARN,
                    'db': os.path.basename(db), 'error': 'nq_5min leer'}
        age_s = time.time() - float(row[0])
        severity = OK
        if age_s > NQ_PIPELINE_CRIT_S:
            severity = CRIT
        elif age_s > NQ_PIPELINE_WARN_S:
            severity = WARN
        return {
            'check': 'nq:pipeline_freshness',
            'severity': severity,
            'db': os.path.basename(db),
            'last_utc': datetime.fromtimestamp(float(row[0]), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'age_s': round(age_s),
        }
    except sqlite3.Error as exc:
        return {'check': 'nq:pipeline_freshness', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_nq_energy_freshness() -> dict:
    """Alter des juengsten Tages in nq_energy_daily (Rollup laeuft taeglich)."""
    db = _newest_month_db()
    if db is None:
        return {'check': 'nq:energy_freshness', 'severity': OK, 'skipped': True,
                'detail': 'keine NQ-Monats-DB (Modul nicht aktiv)'}
    conn = _db_ro(db)
    if conn is None:
        return {'check': 'nq:energy_freshness', 'severity': FAIL,
                'error': f'{os.path.basename(db)} nicht lesbar'}
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nq_energy_daily'")
        if not cur.fetchone():
            return {'check': 'nq:energy_freshness', 'severity': OK, 'skipped': True,
                    'detail': 'nq_energy_daily nicht vorhanden'}
        row = conn.execute('SELECT MAX(day) FROM nq_energy_daily').fetchone()
        if not row or row[0] is None:
            return {'check': 'nq:energy_freshness', 'severity': WARN,
                    'db': os.path.basename(db), 'error': 'nq_energy_daily leer'}
        day = str(row[0])
        try:
            last = datetime.strptime(day, '%Y-%m-%d').date()
        except ValueError:
            return {'check': 'nq:energy_freshness', 'severity': WARN,
                    'error': f'ungueltiges Datum {day}'}
        days_behind = (datetime.now().date() - last).days
        severity = OK
        if days_behind >= NQ_ENERGY_CRIT_DAYS:
            severity = CRIT
        elif days_behind >= NQ_ENERGY_WARN_DAYS:
            severity = WARN
        return {'check': 'nq:energy_freshness', 'severity': severity,
                'db': os.path.basename(db), 'last_day': day, 'days_behind': days_behind}
    except sqlite3.Error as exc:
        return {'check': 'nq:energy_freshness', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_nq_events_recent(hours: int = 24) -> dict:
    """Netzereignis-Zusammenfassung der letzten Stunden (informativ, kein Alarm).

    Netzereignisse (HF/NF/VLF) sind ueberwiegend netzseitig und werden nicht
    alarmiert; die Zahl/Baender erscheinen zur Einordnung im Netz-Status.
    """
    db = _newest_month_db()
    if db is None:
        return {'check': 'nq:events_recent', 'severity': OK, 'skipped': True,
                'detail': 'keine NQ-Monats-DB (Modul nicht aktiv)'}
    conn = _db_ro(db)
    if conn is None:
        return {'check': 'nq:events_recent', 'severity': OK, 'skipped': True,
                'detail': f'{os.path.basename(db)} nicht lesbar'}
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nq_events'")
        if not cur.fetchone():
            return {'check': 'nq:events_recent', 'severity': OK, 'skipped': True,
                    'detail': 'nq_events nicht vorhanden'}
        cutoff = time.time() - hours * 3600
        rows = conn.execute(
            'SELECT band, COUNT(*), MAX(severity) FROM nq_events '
            'WHERE ts_start >= ? GROUP BY band', (cutoff,)).fetchall()
        bands = {str(r[0]): int(r[1]) for r in rows}
        total = sum(bands.values())
        worst = max((float(r[2] or 0.0) for r in rows), default=0.0)
        return {'check': 'nq:events_recent', 'severity': OK, 'window_h': hours,
                'count': total, 'bands': bands, 'max_severity': round(worst, 2)}
    except sqlite3.Error as exc:
        return {'check': 'nq:events_recent', 'severity': OK, 'skipped': True, 'detail': str(exc)}
    finally:
        conn.close()


def _timer_status(unit: str) -> tuple:
    """(LoadState, ActiveState) oder (None, None), wenn systemctl fehlt."""
    try:
        r = subprocess.run(
            ['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'ActiveState'],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, None
    load = active = ''
    for line in r.stdout.splitlines():
        if line.startswith('LoadState='):
            load = line.split('=', 1)[1].strip()
        elif line.startswith('ActiveState='):
            active = line.split('=', 1)[1].strip()
    return load, active


def check_nq_services() -> dict:
    """Primary-NQ-Timer scharf? Nur installierte (loaded) Units werden bewertet."""
    states = {}
    problems = []
    for unit in NQ_TIMERS:
        load, active = _timer_status(unit)
        if load is None:
            return {'check': 'nq:services', 'severity': OK, 'skipped': True,
                    'detail': 'systemctl nicht verfuegbar'}
        if load != 'loaded':
            continue  # auf diesem Host nicht ausgerollt -> ignorieren
        states[unit] = active
        if active in ('failed', 'inactive'):
            problems.append(f'{unit}={active}')
    if not states:
        return {'check': 'nq:services', 'severity': OK, 'skipped': True,
                'detail': 'keine NQ-Timer installiert'}
    severity = WARN if problems else OK
    out = {'check': 'nq:services', 'severity': severity, 'states': states}
    if problems:
        out['error'] = 'NQ-Timer nicht scharf: ' + ', '.join(problems)
    return out


def run_all() -> dict:
    """Alle NQ-Checks ausfuehren (rollen-/deploymentbewusst)."""
    role = _read_role()
    if role == 'failover':
        checks = [{'check': 'nq:module', 'severity': OK, 'skipped': True,
                   'role': role, 'detail': 'NQ-Aggregation laeuft nur auf primary'}]
    else:
        checks = [
            check_nq_pipeline_freshness(),
            check_nq_energy_freshness(),
            check_nq_services(),
            check_nq_events_recent(),
        ]
    worst = max(checks, key=lambda c: _SEV_ORDER.get(c.get('severity', OK), 0))
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
    for c in result['checks']:
        if c.get('severity') in (WARN, CRIT, FAIL):
            print(f"[{c['severity'].upper()}] {c['check']}: {c}", file=sys.stderr)
    if result['overall'] in (CRIT, FAIL):
        sys.exit(2)
    if result['overall'] == WARN:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
