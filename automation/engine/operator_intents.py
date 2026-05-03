"""Read-only helper fuer aktive Operator-Intents aus der RAM-DB."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

RAM_DB_PATH = '/dev/shm/automation_obs.db'

_CACHE_TTL_S = 5.0
_CACHE: dict[str, Any] = {
    'ts': 0.0,
    'value': None,
}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {'1', 'true', 'yes', 'on'}:
            return True
        if norm in {'0', 'false', 'no', 'off'}:
            return False
    return default


def _parse_created_at(created_at: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(created_at)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _remaining_respekt_s(created_at: str, respekt_s: int) -> int:
    ts = _parse_created_at(created_at)
    if ts is None:
        return 0
    elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
    return max(0, int(respekt_s - elapsed))


def _read_afternoon_charge_intent(db_path: str) -> dict[str, Any] | None:
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.execute('PRAGMA journal_mode=WAL')
        row = conn.execute(
            "SELECT id, params_json, created_at, respekt_s, status "
            "FROM operator_overrides "
            "WHERE action='afternoon_charge_request' "
            "AND status IN ('open','active') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except Exception:
        return None

    if not row:
        return None

    try:
        params = json.loads(row[1] or '{}')
    except Exception:
        params = {}

    remaining_s = _remaining_respekt_s(str(row[2]), int(row[3] or 0))
    if remaining_s <= 0:
        return None

    until_hour_raw = params.get('until_hour')
    until_hour = None
    if isinstance(until_hour_raw, (int, float)):
        until_hour_f = float(until_hour_raw)
        if 0.0 <= until_hour_f <= 24.0:
            until_hour = round(until_hour_f, 2)

    if until_hour is not None:
        now = datetime.now()
        now_h = now.hour + now.minute / 60.0 + now.second / 3600.0
        if now_h >= float(until_hour):
            return None

    target_soc = int(params.get('target_soc_pct', 100))
    target_soc = max(75, min(100, target_soc))

    start_earliest = float(params.get('start_earliest_h', 12.0))
    start_latest = float(params.get('start_latest_h', 15.0))
    start_earliest = max(0.0, min(24.0, start_earliest))
    start_latest = max(start_earliest, min(24.0, start_latest))

    return {
        'override_id': int(row[0]),
        'status': str(row[4]),
        'target_soc_pct': target_soc,
        'pause_hp_until_target': _parse_bool(params.get('pause_hp_until_target'), True),
        'start_earliest_h': round(start_earliest, 2),
        'start_latest_h': round(start_latest, 2),
        'until_hour': until_hour,
        'respekt_remaining_s': remaining_s,
    }


def read_active_afternoon_charge_intent(
    db_path: str = RAM_DB_PATH,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Liefert aktiven Tages-Ladewunsch (falls vorhanden)."""
    now = time.time()
    if not force_refresh and (now - float(_CACHE['ts'])) <= _CACHE_TTL_S:
        return _CACHE['value']

    value = _read_afternoon_charge_intent(db_path)
    _CACHE['ts'] = now
    _CACHE['value'] = value
    return value
