"""
modbus_v3.py — Compat-Shim nach Refactor 2026-05-16.

Die monolithische Datei wurde in das Package `collector/` zerlegt
(siehe doc/llm/cards/collector-fronius-collector.card.md). Diese Datei
re-exportiert die oeffentliche API fuer bestehende Aufrufer (collector.py).
"""

from collector.buffer import flush_buffer_to_db, save_raw_data
from collector.poller import poll_once, poller_loop, cleanup_db, fetch_battery_api

__all__ = [
    'poller_loop',
    'flush_buffer_to_db',
    'save_raw_data',
    'poll_once',
    'cleanup_db',
    'fetch_battery_api',
]
