#!/usr/bin/env python3
"""
tools/pv_config/common.py — Gemeinsame Basis fuer pv-config (UI + DB + Konstanten)

Extrahiert aus pv-config.py (Architektur-Refactor 2026-06-29): Whiptail-Wrapper,
read-only DB-Helfer und geteilte Konstanten. Wird von pv-config.py und den
Schwester-Modulen diagnose/service/matrix_editor importiert.
"""
from __future__ import annotations

import os
import subprocess
import sqlite3
import sys
from typing import Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config

VERSION = '1.3.0'
TITLE = 'PV-System Konfiguration'
BATTERY_CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'battery_control.json')
SCHEDULER_STATE_PATH = os.path.join(PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
HANDBUCH_PATH = os.path.join(PROJECT_ROOT, 'doc', 'automation', 'PV_CONFIG_HANDBUCH.md')

# Whiptail-Dimensionen — dynamisch ans Terminal angepasst
def _terminal_size():
    """Terminalgröße ermitteln, Fallback 24x80."""
    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        rows, cols = 24, 80
    return rows, cols

_rows, _cols = _terminal_size()
WT_H = max(20, _rows - 2)       # 2 Zeilen Rand
WT_W = max(60, _cols - 4)       # 4 Spalten Rand (≈ so breit wie blauer Hintergrund)
WT_LIST_H = max(10, WT_H - 8)   # Listenhöhe innerhalb Dialog

# ANSI-Farben für Status-Anzeige VOR dem Menü
C_RESET = '\033[0m'
C_BOLD = '\033[1m'
C_DIM = '\033[2m'
C_RED = '\033[91m'
C_GREEN = '\033[92m'
C_YELLOW = '\033[93m'
C_BLUE = '\033[94m'
C_CYAN = '\033[96m'

# Prioritäts-Labels
PRIO_LABELS = {1: 'SICHERHEIT', 2: 'STEUERUNG', 3: 'WARTUNG'}


# ═══════════════════════════════════════════════════════════════
# Whiptail-Wrapper
# ═══════════════════════════════════════════════════════════════

def _wt(args: list[str], input_text: str = '', backtitle: str = '') -> Tuple[int, str]:
    """Whiptail aufrufen. Rückgabe: (returncode, stderr-Output)."""
    bt = backtitle or f'PV-System v{VERSION} | {config.PV_KWP_TOTAL} kWp | BYD {config.PV_BATTERY_KWH} kWh'
    cmd = ['whiptail', '--title', TITLE, '--backtitle', bt] + args
    proc = subprocess.run(
        cmd,
        input=input_text.encode() if input_text else None,
        stderr=subprocess.PIPE,
    )
    # whiptail gibt Auswahl auf stderr aus
    return proc.returncode, proc.stderr.decode().strip()


def wt_menu(text: str, items: list[tuple[str, str]]) -> Optional[str]:
    """Menü anzeigen. items = [(tag, description), ...]. Rückgabe: gewählter Tag oder None."""
    args = ['--menu', text, str(WT_H), str(WT_W), str(WT_LIST_H)]
    for tag, desc in items:
        # Whiptail interpretiert '-...' am Desc-Anfang als Flag → Space-Prefix
        safe_desc = f' {desc}' if desc.startswith('-') else desc
        args.extend([tag, safe_desc])
    rc, choice = _wt(args)
    return choice if rc == 0 else None


def wt_checklist(text: str, items: list[tuple[str, str, bool]]) -> Optional[list[str]]:
    """Checklist. items = [(tag, desc, checked), ...]. Rückgabe: Liste gewählter Tags."""
    args = ['--checklist', text, str(WT_H), str(WT_W), str(WT_LIST_H)]
    for tag, desc, checked in items:
        safe_desc = f' {desc}' if desc.startswith('-') else desc
        args.extend([tag, safe_desc, 'ON' if checked else 'OFF'])
    rc, output = _wt(args)
    if rc != 0:
        return None
    # Whiptail gibt "tag1" "tag2" zurück
    return [t.strip('"') for t in output.split()] if output else []


def wt_inputbox(text: str, default: str = '') -> Optional[str]:
    """Eingabefeld. Rückgabe: eingegebener Text oder None."""
    rc, output = _wt(['--inputbox', text, str(10), str(WT_W), default])
    return output if rc == 0 else None


def wt_yesno(text: str) -> bool:
    """Ja/Nein Dialog. Rückgabe: True = Ja."""
    rc, _ = _wt(['--yesno', text, str(10), str(WT_W)])
    return rc == 0


def wt_msgbox(text: str):
    """Info-Dialog."""
    _wt(['--msgbox', text, str(WT_H), str(WT_W)])


def wt_textbox(filepath: str):
    """Datei anzeigen (scrollbar)."""
    _wt(['--textbox', filepath, str(WT_H), str(WT_W), '--scrolltext'])


# ═══════════════════════════════════════════════════════════════
# DB-Zugriff
# ═══════════════════════════════════════════════════════════════

def _get_db() -> sqlite3.Connection:
    """DB-Verbindung (read-only für Status)."""
    conn = sqlite3.connect(f'file:{config.DB_PATH}?mode=ro', uri=True, timeout=5)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _query_one(sql: str, params: tuple = ()) -> Optional[tuple]:
    """Einzelne Zeile abfragen."""
    try:
        conn = _get_db()
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row
    except Exception:
        return None


def _query_all(sql: str, params: tuple = ()) -> list:
    """Alle Zeilen abfragen."""
    try:
        conn = _get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []

