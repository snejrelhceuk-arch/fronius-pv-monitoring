"""Intent-Handling fuer Steuerbox: Validierung, Persistenz, Audit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import config

from steuerbox.validators import validate_action

DB_PATH = '/dev/shm/automation_obs.db'


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS operator_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    respekt_s INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'steuerbox',
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS steuerbox_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    action TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    override_id INTEGER,
    note TEXT
);
"""


@dataclass
class IntentResult:
    override_id: int
    created_at: str
    respekt_s: int
    respekt_remaining_s: int
    status: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(_SCHEMA_SQL)
    return conn


def _write_audit(
    conn: sqlite3.Connection,
    *,
    client_ip: str,
    action: str,
    params: dict[str, Any],
    result: dict[str, Any],
    override_id: int | None,
    note: str = ''
) -> None:
    conn.execute(
        'INSERT INTO steuerbox_audit (ts, client_ip, action, params_json, result_json, override_id, note) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            _utc_now_iso(),
            client_ip,
            action,
            json.dumps(params, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            override_id,
            note,
        ),
    )


def _is_neutral_action(action: str, params: dict[str, Any]) -> bool:
    if action == 'wp_mode':
        return params.get('mode') == 'neutral'
    if action in {'hp_toggle', 'klima_toggle', 'lueftung_toggle'}:
        return params.get('state') == 'neutral'
    if action == 'wattpilot_mode':
        return params.get('mode') == 'neutral'
    if action == 'wattpilot_start_stop':
        return params.get('command') == 'neutral'
    if action == 'wattpilot_amp':
        return params.get('amp') == 'neutral'
    return False


def _close_live_overrides_for_action(conn: sqlite3.Connection, action: str, keep_id: int) -> int:
    cur = conn.execute(
        "UPDATE operator_overrides SET status='released' "
        "WHERE action=? AND status IN ('open','active') AND id<>?",
        (action, keep_id),
    )
    return int(cur.rowcount or 0)


def handle_intent(action: str, params: dict[str, Any], client_ip: str, respekt_s: int | None = None) -> IntentResult:
    """Validieren, in operator_overrides schreiben und Audit erfassen."""
    effektive_respekt_s = int(respekt_s or config.STEUERBOX_DEFAULT_RESPEKT_S)
    normalized = validate_action(action, params, effektive_respekt_s)

    conn = _get_conn()
    try:
        created_at = _utc_now_iso()

        cur = conn.execute(
            'INSERT INTO operator_overrides (action, params_json, created_at, respekt_s, source, status) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                action,
                json.dumps(normalized, ensure_ascii=False),
                created_at,
                effektive_respekt_s,
                'steuerbox',
                'open',
            ),
        )
        override_id = int(cur.lastrowid)

        neutral_release = _is_neutral_action(action, normalized)
        # Pro Aktion ist immer nur ein Live-Override erlaubt (open/active).
        released_count = _close_live_overrides_for_action(conn, action, override_id)
        if neutral_release:
            conn.execute(
                "UPDATE operator_overrides SET status='released' WHERE id=?",
                (override_id,),
            )

        result = {
            'ok': True,
            'override_id': override_id,
            'respekt_s': effektive_respekt_s,
            'neutral_release': neutral_release,
            'released_overrides': released_count,
        }
        _write_audit(
            conn,
            client_ip=client_ip,
            action=action,
            params=normalized,
            result=result,
            override_id=override_id,
            note='neutral release' if neutral_release else 'intent accepted',
        )
        conn.commit()

        return IntentResult(
            override_id=override_id,
            created_at=created_at,
            respekt_s=effektive_respekt_s,
            respekt_remaining_s=0 if neutral_release else effektive_respekt_s,
            status='released' if neutral_release else 'accepted',
        )
    except Exception as exc:
        _write_audit(
            conn,
            client_ip=client_ip,
            action=action,
            params=params,
            result={'ok': False, 'error': str(exc)},
            override_id=None,
            note='intent failed',
        )
        conn.commit()
        raise
    finally:
        conn.close()


def get_status(limit: int = 100) -> dict[str, Any]:
    """Liefert offene Overrides mit Restlaufzeit (Respekt-Verfahren)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            'SELECT id, action, params_json, created_at, respekt_s, status '
            'FROM operator_overrides ORDER BY id DESC LIMIT ?',
            (max(1, int(limit)),),
        ).fetchall()

        now_ts = time.time()
        items = []
        for row in rows:
            created_ts = datetime.fromisoformat(row[3]).timestamp()
            remaining = max(0, int((created_ts + int(row[4])) - now_ts))
            items.append(
                {
                    'id': int(row[0]),
                    'action': row[1],
                    'params': json.loads(row[2]),
                    'created_at': row[3],
                    'respekt_s': int(row[4]),
                    'respekt_remaining_s': remaining,
                    'status': row[5],
                }
            )

        return {'items': items, 'count': len(items)}
    finally:
        conn.close()


def get_audit(limit: int = 100) -> dict[str, Any]:
    """Liefert letzte Audit-Eintraege."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            'SELECT id, ts, client_ip, action, params_json, result_json, override_id, note '
            'FROM steuerbox_audit ORDER BY id DESC LIMIT ?',
            (max(1, int(limit)),),
        ).fetchall()

        items = []
        for row in rows:
            items.append(
                {
                    'id': int(row[0]),
                    'ts': row[1],
                    'client_ip': row[2],
                    'action': row[3],
                    'params': json.loads(row[4]),
                    'result': json.loads(row[5]),
                    'override_id': row[6],
                    'note': row[7],
                }
            )

        return {'items': items, 'count': len(items)}
    finally:
        conn.close()
