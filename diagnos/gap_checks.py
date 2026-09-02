"""Read-only Gap-Scans fuer Diagnos-Integritaet."""

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from diagnos.config import CRIT, DB_PATH, FAIL, OK, WARN
from diagnos import gap_accept

RAW_GAP_SCAN_HOURS = 24
DATA_1MIN_GAP_SCAN_HOURS = 72
DATA_15MIN_GAP_SCAN_DAYS = 14
HOURLY_GAP_SCAN_DAYS = 30
RAW_GAP_MIN_S = 30
DATA_1MIN_GAP_MIN_S = 120
DATA_15MIN_GAP_MIN_S = 1800
HOURLY_GAP_MIN_S = 5400


def _db_readonly() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB_PATH):
        return None
    try:
        return sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _gap_class(age_s: float) -> str:
    if age_s < 120:
        return 'micro'
    if age_s < 1800:
        return 'short'
    if age_s < 21600:
        return 'medium'
    return 'long'


# Sonnenstand-Schwelle, unter der WR-Standby/Offline betrieblich erwartet ist.
# Solche Luecken (Tagesende, Nacht) sollen keine Warnung/Crit ausloesen,
# bleiben aber in der Luecken-/Ausfallliste sichtbar.
_NIGHT_ELEV_DEG = 1.0


def _gap_in_darkness(start_ts: float, end_ts: float) -> bool:
    """True, wenn die Luecke vollstaendig bei Dunkelheit/Daemmerung liegt."""
    try:
        from solar_geometry import sun_position
    except Exception:
        return False
    try:
        for ts in (start_ts, (start_ts + end_ts) / 2.0, end_ts):
            dt = datetime.utcfromtimestamp(ts)
            elev, _ = sun_position(dt)
            if elev >= _NIGHT_ELEV_DEG:
                return False
        return True
    except Exception:
        return False


def _gap_severity(category_counts: dict) -> str:
    if category_counts.get('long', 0) or category_counts.get('medium', 0):
        return CRIT
    if category_counts.get('short', 0) or category_counts.get('micro', 0):
        return WARN
    return OK


# Eine Luecke, deren Ende laenger als diese Spanne zurueckliegt, gilt als
# "gesetzt": der Tag ist vorbei, die Aggregationen (1min->15min->daily->monthly)
# haben den Stand uebernommen. Solche historischen Luecken treiben keine
# Alarmschwere mehr, bleiben aber dokumentiert.
GAP_SETTLE_S = 25 * 3600


def _run_gap_scan(table: str, hours: int, min_gap_s: int, daylight_aware: bool = False) -> dict:
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
        sev_counts = {'micro': 0, 'short': 0, 'medium': 0, 'long': 0}
        samples = []
        max_gap = 0.0
        night_gaps = 0
        settled_gaps = 0
        accepted_gaps = 0
        acceptances = gap_accept.load_acceptances()
        now_ts = time.time()
        for row in rows:
            start_ts = float(row[0])
            end_ts = float(row[1])
            gap_s = float(row[2])
            gap_type = _gap_class(gap_s)
            category_counts[gap_type] += 1
            max_gap = max(max_gap, gap_s)
            is_night = daylight_aware and _gap_in_darkness(start_ts, end_ts)
            is_settled = end_ts < (now_ts - GAP_SETTLE_S)
            accepted = gap_accept.is_accepted(table, start_ts, end_ts, acceptances)
            # Akzeptierte (bestätigte/rekonstruierte) Lücken treiben keine Schwere,
            # ebenso Nacht-Standby und historisch gesetzte Lücken.
            if accepted:
                accepted_gaps += 1
            elif is_night:
                night_gaps += 1
            elif is_settled:
                settled_gaps += 1
            else:
                sev_counts[gap_type] += 1
            if len(samples) < 5:
                samples.append({
                    'start_utc': datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'end_utc': datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    'gap_s': round(gap_s, 1),
                    'class': gap_type,
                    'expected_night': is_night,
                    'settled': is_settled,
                    'accepted': bool(accepted),
                })

        result = {
            'check': f'integrity:gaps:{table}',
            'window_hours': hours,
            'min_gap_s': min_gap_s,
            'gap_count': len(rows),
            'fresh_gap_count': sum(sev_counts.values()),
            'settled_gap_count': settled_gaps,
            'accepted_gap_count': accepted_gaps,
            'max_gap_s': round(max_gap, 1),
            'classes': category_counts,
            'severity': _gap_severity(sev_counts),
            'samples': samples,
        }
        if daylight_aware:
            result['night_gap_count'] = night_gaps
            result['daylight_gap_classes'] = sev_counts
        return result
    except sqlite3.Error as exc:
        return {'check': f'integrity:gaps:{table}', 'severity': FAIL, 'error': str(exc)}
    finally:
        conn.close()


def check_raw_data_gaps(hours: int = RAW_GAP_SCAN_HOURS) -> dict:
    return _run_gap_scan('raw_data', hours, RAW_GAP_MIN_S, daylight_aware=True)


def check_data_1min_gaps(hours: int = DATA_1MIN_GAP_SCAN_HOURS) -> dict:
    return _run_gap_scan('data_1min', hours, DATA_1MIN_GAP_MIN_S, daylight_aware=True)


def check_data_15min_gaps(days: int = DATA_15MIN_GAP_SCAN_DAYS) -> dict:
    result = _run_gap_scan('data_15min', days * 24, DATA_15MIN_GAP_MIN_S)
    result['window_days'] = days
    return result


def check_hourly_gaps(days: int = HOURLY_GAP_SCAN_DAYS) -> dict:
    result = _run_gap_scan('hourly_data', days * 24, HOURLY_GAP_MIN_S)
    result['window_days'] = days
    return result