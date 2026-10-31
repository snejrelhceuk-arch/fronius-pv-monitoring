#!/usr/bin/env python3
"""Tests fuer den WP-Mode-Operator-Hold (Steuerbox wp_mode).

Hintergrund: Ein Steuerbox-`wp_mode`-Override (max/std/min) schrieb den
Heiz-/WW-Soll nur einmal; die zeitgesteuerte WP-Sollwertregel `heiz_bedarf`
ueberschrieb ihn binnen ~1 min wieder auf Standard. Fix:
  - `wp_mode` nutzt jetzt einen Respekt-Hold (Override bleibt `active`).
  - Solange der Hold aktiv ist, meldet `read_active_wp_mode_intent()` ihn und
    die Engine ueberspringt alle `aktor=='waermepumpe'`-Regeln.
  - `neutral` gibt die Automatik wieder frei (kein Hold).

Nutzung: python3 -m pytest tests/test_wp_mode_hold.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _mk_ram_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE operator_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            params_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            respekt_s INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'steuerbox',
            status TEXT NOT NULL DEFAULT 'open'
        )
        """
    )
    conn.commit()
    conn.close()


def _insert(path: str, action: str, params_json: str, status: str,
            respekt_s: int = 1800, age_s: int = 0) -> int:
    created = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    conn = sqlite3.connect(path)
    cur = conn.execute(
        "INSERT INTO operator_overrides (action, params_json, created_at, respekt_s, status) "
        "VALUES (?,?,?,?,?)",
        (action, params_json, created, respekt_s, status),
    )
    conn.commit()
    oid = int(cur.lastrowid)
    conn.close()
    return oid


def test_read_active_wp_mode_intent(tmp_path):
    from automation.engine import operator_intents as oi

    db = str(tmp_path / 'ram.db')
    _mk_ram_db(db)

    # Kein Override -> None
    assert oi.read_active_wp_mode_intent(db, force_refresh=True) is None

    # Aktiver max-Hold -> erkannt
    _insert(db, 'wp_mode', '{"mode": "max"}', 'active')
    intent = oi.read_active_wp_mode_intent(db, force_refresh=True)
    assert intent is not None
    assert intent['mode'] == 'max'
    assert intent['respekt_remaining_s'] > 0


def test_neutral_ist_kein_hold(tmp_path):
    from automation.engine import operator_intents as oi

    db = str(tmp_path / 'ram.db')
    _mk_ram_db(db)
    _insert(db, 'wp_mode', '{"mode": "neutral"}', 'active')
    assert oi.read_active_wp_mode_intent(db, force_refresh=True) is None


def test_abgelaufener_hold_ist_inaktiv(tmp_path):
    from automation.engine import operator_intents as oi

    db = str(tmp_path / 'ram.db')
    _mk_ram_db(db)
    _insert(db, 'wp_mode', '{"mode": "max"}', 'active', respekt_s=1800, age_s=3600)
    assert oi.read_active_wp_mode_intent(db, force_refresh=True) is None


def test_released_hold_ist_inaktiv(tmp_path):
    from automation.engine import operator_intents as oi

    db = str(tmp_path / 'ram.db')
    _mk_ram_db(db)
    _insert(db, 'wp_mode', '{"mode": "max"}', 'released')
    assert oi.read_active_wp_mode_intent(db, force_refresh=True) is None


def test_uses_respekt_hold_fuer_wp_mode():
    from automation.engine.operator_overrides import OperatorOverrideProcessor as P

    assert P._uses_respekt_hold('wp_mode', {'mode': 'max'}) is True
    assert P._uses_respekt_hold('wp_mode', {'mode': 'std'}) is True
    assert P._uses_respekt_hold('wp_mode', {'mode': 'min'}) is True
    # neutral haelt nicht -> einmaliger No-Op, kein Hold
    assert P._uses_respekt_hold('wp_mode', {'mode': 'neutral'}) is False


def test_wp_mode_kein_per_zyklus_reapply():
    from automation.engine.operator_overrides import OperatorOverrideProcessor as P

    # Reapply False: Sollwert wird beim Hold-Start einmal geschrieben,
    # das Engine-Gate unterdrueckt derweil die WP-Regeln.
    assert P._active_hold_needs_reapply('wp_mode', {'mode': 'max'}, {}, elapsed_s=120) is False


def test_steuerbox_card_match():
    # wp_mode muss weiterhin eine erlaubte Steuerbox-Aktion sein.
    import config
    assert 'wp_mode' in config.STEUERBOX_ALLOWED_ACTIONS


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
