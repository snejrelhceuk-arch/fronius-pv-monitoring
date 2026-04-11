#!/usr/bin/env python3
"""
pv-config.py — Interaktives SSH-Konfigurationstool für PV-Automation

Whiptail-basiertes Terminal-Menü für:
  - Regelkreise ein/ausschalten
  - Parameter-Matrix anzeigen & bearbeiten
  - Batterie-Scheduler-Status
  - System-Status (Collector, DB, Failover, Warnungen)
  - Forecast-Genauigkeit
  - Heizpatrone (Fritz!DECT) — Konfiguration, Test, manuelle Steuerung

Zugang: SSH → `python3 pv-config.py` oder `./pv-config.py`
Auth:   SSH-Login (Passwort/Key)
Sicher: Kein Netzwerk-Port, keine zusätzliche Angriffsfläche

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §3 (S1 Config-Schicht)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta
from typing import Optional, Tuple

# ── Projekt-Root ermitteln ─────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import config
from automation.engine.param_matrix import (
    lade_matrix, validiere_matrix, alle_regelkreise,
    get_param, DEFAULT_MATRIX_PATH,
)

# ── Konstanten ─────────────────────────────────────────────────
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


# ═══════════════════════════════════════════════════════════════
# Status-Dashboard (vor dem Menü)
# ═══════════════════════════════════════════════════════════════

def _collector_status() -> tuple[str, str]:
    """Collector-Status. Rückgabe: (status_text, farbe)."""
    pid_file = os.path.join(PROJECT_ROOT, 'collector.pid')
    if not os.path.exists(pid_file):
        return 'GESTOPPT', C_RED

    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        # Prüfe ob Prozess lebt
        os.kill(pid, 0)
    except (ValueError, ProcessLookupError, PermissionError):
        return 'PID-STALE', C_RED

    # Letzter Datensatz in raw_data (ts = Unix epoch float)
    row = _query_one("SELECT MAX(ts) FROM raw_data")
    if row and row[0]:
        try:
            age_s = time.time() - float(row[0])
            if age_s < 30:
                return f'AKTIV (PID {pid})', C_GREEN
            elif age_s < 120:
                return f'VERZÖGERT ({int(age_s)}s)', C_YELLOW
            else:
                return f'STALE ({int(age_s/60)}min)', C_RED
        except Exception:
            pass

    return f'LÄUFT (PID {pid})', C_GREEN


def _battery_status() -> dict:
    """Aktueller Batterie-Status aus DB."""
    row = _query_one("""
        SELECT SOC_Batt, U_Batt_API, I_Batt_API, ChaSt_Batt
        FROM raw_data ORDER BY ts DESC LIMIT 1
    """)
    if not row:
        return {}
    # Batterie-Leistung = U × I (positiv=Laden, negativ=Entladen)
    u = row[1] or 0
    i = row[2] or 0
    return {
        'soc': row[0],
        'power_w': u * i,
        'cha_state': row[3],
    }


def _pv_status() -> dict:
    """Aktuelle PV-Daten."""
    row = _query_one("""
        SELECT P_DC_Inv, P_Netz, P_AC_Inv
        FROM raw_data ORDER BY ts DESC LIMIT 1
    """)
    if not row:
        return {}
    p_dc = row[0] or 0       # DC-Leistung (PV gesamt)
    p_netz = row[1] or 0     # Netz: negativ = Einspeisung, positiv = Bezug
    p_ac = row[2] or 0       # AC-Leistung Inverter
    return {
        'pv_w': p_dc,
        'bezug_w': max(0, p_netz),
        'einsp_w': max(0, -p_netz),
        'haus_w': p_ac - min(0, p_netz),  # AC + Bezug (≈ Hausverbrauch)
    }


def _tagesertrag() -> Optional[float]:
    """Heutiger PV-Ertrag in kWh (Summe der Stunden-Deltas)."""
    # hourly_data.ts = Unix epoch float, W_PV_total_delta = Wh pro Stunde
    today_start = datetime.combine(date.today(), datetime.min.time()).timestamp()
    row = _query_one("""
        SELECT SUM(W_PV_total_delta) FROM hourly_data
        WHERE ts >= ?
    """, (today_start,))
    return round(row[0] / 1000, 2) if row and row[0] else None


def _automation_phase() -> str:
    """Letzte Automation-Aktion."""
    # Primaer: battery_control_log (echte Scheduler-Aktionen)
    row = _query_one("""
        SELECT datetime(ts, 'unixepoch', 'localtime'), action, param, new_value, reason
        FROM battery_control_log
        ORDER BY ts DESC LIMIT 1
    """)
    if row:
        ts, action, param, new_val, reason = row
        ts_short = ts[11:16] if ts and len(ts) > 16 else ts or '?'
        return f'{ts_short} {action}:{param}={new_val} ({(reason or "")[:40]})'
    # Fallback: automation_log
    row = _query_one("""
        SELECT ts, kommando, wert, grund
        FROM automation_log
        WHERE aktor = 'batterie'
        ORDER BY ts DESC LIMIT 1
    """)
    if not row:
        return 'Keine Aktionen'
    ts, cmd, wert, grund = row
    return f'{ts[11:16]} {cmd}={wert} ({(grund or "")[:40]})'


def _db_size() -> str:
    """DB-Größe."""
    try:
        size = os.path.getsize(config.DB_PATH)
        return f'{size / 1024 / 1024:.1f} MB'
    except OSError:
        return '?'


def _scheduler_state() -> dict:
    """Batterie-Scheduler-Status."""
    if os.path.exists(SCHEDULER_STATE_PATH):
        try:
            with open(SCHEDULER_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _status_backtitle() -> str:
    """Einzeilige Status-Zusammenfassung für whiptail backtitle."""
    pv = _pv_status()
    batt = _battery_status()
    soc = batt.get('soc', 0) or 0
    pv_w = pv.get('pv_w', 0) or 0
    haus_w = pv.get('haus_w', 0) or 0
    bezug = pv.get('bezug_w', 0) or 0
    einsp = pv.get('einsp_w', 0) or 0
    netz_str = f'Bezug {bezug:.0f}W' if bezug > 50 else f'Einsp. {einsp:.0f}W'
    batt_p = batt.get('power_w', 0) or 0
    if batt_p > 50:
        batt_str = f'Laden {batt_p:.0f}W'
    elif batt_p < -50:
        batt_str = f'Entl. {abs(batt_p):.0f}W'
    else:
        batt_str = 'Idle'
    return (f'PV: {pv_w:.0f}W | Haus: {haus_w:.0f}W | '
            f'Netz: {netz_str} | SOC: {soc:.0f}% {batt_str}')


def _status_menu_body() -> str:
    """Mehrzeiliger Status-Block als whiptail-Menü-Text."""
    now = datetime.now()
    coll_text, _ = _collector_status()
    ertrag = _tagesertrag()
    phase = _automation_phase()
    sched = _scheduler_state()
    db_sz = _db_size()

    ertrag_str = f'{ertrag:.1f} kWh' if ertrag else '--'

    lines = []
    lines.append(f'{now.strftime("%d.%m.%Y %H:%M:%S")}')
    lines.append(f'Tagesertrag: {ertrag_str}   DB: {db_sz}   Collector: {coll_text}')
    lines.append(f'Letzte Aktion: {phase}')

    if sched:
        morgen = sched.get('morgen_status', '--')
        nachm = sched.get('nachmittag_status', '--')
        lines.append(f'Scheduler: Morgen={morgen}  Nachm={nachm}')

    # Platzhalter fuer kuenftige Meldungen
    # lines.append(f'Forecast: ...')
    # lines.append(f'Meldungen: ...')

    lines.append('')
    lines.append('Funktion waehlen:')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════
# Menü 1: Regelkreise ein/ausschalten
# ═══════════════════════════════════════════════════════════════

def menu_regelkreise():
    """Regelkreise per Checklist aktivieren/deaktivieren."""
    matrix = lade_matrix()
    items = []

    for rk_name, rk in alle_regelkreise(matrix):
        prio = rk.get('prioritaet', 0)
        aktiv = rk.get('aktiv', False)
        gewicht = rk.get('score_gewicht', 0)
        label = PRIO_LABELS.get(prio, f'P{prio}')
        # Beschreibung dynamisch an Fensterbreite anpassen
        desc_max = max(20, WT_W - 40)
        desc = f'[{label}] Score={gewicht}  {rk.get("beschreibung", "")[:desc_max]}'
        items.append((rk_name, desc, aktiv))

    result = wt_checklist(
        'Regelkreise aktivieren/deaktivieren.\n'
        'Leertaste = Umschalten, Enter = Bestätigen, Esc = Abbrechen.\n\n'
        'SICHERHEIT-Regeln (P1) sollten immer aktiv bleiben!',
        items,
    )

    if result is None:
        return  # Abbruch

    # Änderungen ermitteln
    aenderungen = []
    for rk_name, rk in alle_regelkreise(matrix):
        war_aktiv = rk.get('aktiv', False)
        soll_aktiv = rk_name in result
        if war_aktiv != soll_aktiv:
            aenderungen.append((rk_name, soll_aktiv))

    if not aenderungen:
        wt_msgbox('Keine Änderungen.')
        return

    # Sicherheitscheck: P1-Regeln deaktivieren?
    p1_deaktiviert = [
        name for name, aktiv in aenderungen
        if not aktiv and matrix['regelkreise'][name].get('prioritaet') == 1
    ]
    if p1_deaktiviert:
        if not wt_yesno(
            f'⚠ WARNUNG: Sicherheitsregeln werden deaktiviert:\n\n'
            f'{", ".join(p1_deaktiviert)}\n\n'
            f'Dies kann zu Batterieschäden führen!\n'
            f'Wirklich fortfahren?'
        ):
            return

    # Zusammenfassung
    summary = 'Folgende Änderungen:\n\n'
    for name, aktiv in aenderungen:
        prio = matrix['regelkreise'][name].get('prioritaet', 0)
        if name == 'heizpatrone':
            detail = ' (HP-Steuerung, nicht die Last!)' if not aktiv else ' (HP-Automatik)'
        elif prio == 1:
            detail = ' ⚠ SICHERHEIT'
        else:
            detail = ''
        summary += f'  {"✓ Steuerung AN" if aktiv else "✗ Steuerung AUS"}: {name}{detail}\n'
    summary += '\nÄnderungen speichern?'

    if not wt_yesno(summary):
        return

    # Speichern
    for name, aktiv in aenderungen:
        matrix['regelkreise'][name]['aktiv'] = aktiv

    _speichere_matrix(matrix)
    wt_msgbox(f'{len(aenderungen)} Regelkreis(e) geändert.\n'
              f'Wirksam ab nächstem Engine-Zyklus (≤1 Min).')


# ═══════════════════════════════════════════════════════════════
# Menü 2: Parameter-Matrix anzeigen & bearbeiten
# ═══════════════════════════════════════════════════════════════

def menu_parameter():
    """Parameter-Matrix: Regelkreis wählen → Parameter bearbeiten."""
    while True:
        matrix = lade_matrix()
        items = []
        for rk_name, rk in alle_regelkreise(matrix):
            prio = rk.get('prioritaet', 0)
            aktiv = '●' if rk.get('aktiv') else '○'
            n_params = len([k for k in rk.get('parameter', {}) if not k.startswith('_')])
            desc_max = max(20, WT_W - 30)
            beschr = rk.get('beschreibung', '')[:desc_max]
            desc = f'{aktiv} P{prio} S={rk.get("score_gewicht", 0):>3} {n_params}P  {beschr}'
            items.append((rk_name, desc))

        choice = wt_menu(
            'Regelkreis wählen zum Anzeigen/Bearbeiten der Parameter.\n'
            '● = aktiv, ○ = inaktiv',
            items,
        )

        if not choice:
            return

        _menu_regelkreis_detail(choice)


def _menu_regelkreis_detail(rk_name: str):
    """Detail-Ansicht eines Regelkreises mit Parameter-Bearbeitung."""
    while True:
        matrix = lade_matrix()
        rk = matrix.get('regelkreise', {}).get(rk_name, {})
        if not rk:
            wt_msgbox(f'Regelkreis "{rk_name}" nicht gefunden.')
            return

        params = rk.get('parameter', {})
        items = []
        anzeige_zu_key = {}  # Mapping: Anzeigename → JSON-Key
        for p_name, p in params.items():
            if p_name.startswith('_'):
                continue
            wert = p.get('wert', '?')
            einheit = p.get('einheit', '')
            beschr = p.get('beschreibung', '')
            # Einheitssuffixe aus dem Namen entfernen (_pct, _kwh, _w)
            anzeige = p_name
            for suffix in ('_pct', '_kwh', '_w'):
                if anzeige.endswith(suffix):
                    anzeige = anzeige[:-len(suffix)]
                    break
            anzeige_zu_key[anzeige] = p_name
            # Beschreibung dynamisch an Fensterbreite anpassen
            desc_max = max(20, WT_W - len(anzeige) - 15)
            desc = f'{wert}{einheit}  {beschr[:desc_max]}'
            items.append((anzeige, desc))

        # Header
        prio = rk.get('prioritaet', 0)
        aktiv = 'AKTIV' if rk.get('aktiv') else 'INAKTIV'
        header = (
            f'{rk_name.upper()} — {PRIO_LABELS.get(prio, f"P{prio}")} — {aktiv}\n'
            f'{rk.get("beschreibung", "")}\n'
            f'Score: {rk.get("score_gewicht", 0)}  Zyklus: {rk.get("engine_zyklus", "?")}\n\n'
            f'Parameter wählen zum Bearbeiten:'
        )

        choice = wt_menu(header, items)
        if not choice:
            return

        # Anzeigename zurück auf echten JSON-Key mappen
        real_key = anzeige_zu_key.get(choice, choice)
        _edit_parameter(rk_name, real_key)


def _edit_parameter(rk_name: str, p_name: str):
    """Einzelnen Parameter bearbeiten."""
    matrix = lade_matrix()
    rk = matrix['regelkreise'][rk_name]
    p = rk['parameter'][p_name]

    wert = p.get('wert', 0)
    einheit = p.get('einheit', '')
    bereich = p.get('bereich', [])
    beschreibung = p.get('beschreibung', '')
    obs_feld = p.get('obs_feld', '')
    aktor = p.get('aktor_kommando', '')

    info = (
        f'Parameter: {p_name}\n'
        f'Beschreibung: {beschreibung}\n\n'
        f'Aktueller Wert: {wert}{einheit}\n'
    )
    if bereich and len(bereich) == 2:
        info += f'Gültiger Bereich: {bereich[0]} .. {bereich[1]}{einheit}\n'
    if obs_feld:
        info += f'ObsState-Feld: {obs_feld}\n'
    if aktor:
        info += f'Aktor-Kommando: {aktor}\n'
    info += '\nNeuen Wert eingeben:'

    neuer_wert_str = wt_inputbox(info, str(wert))
    if neuer_wert_str is None:
        return

    # Typ beibehalten (int oder float)
    try:
        if isinstance(wert, int) and '.' not in neuer_wert_str:
            neuer_wert = int(neuer_wert_str)
        else:
            neuer_wert = float(neuer_wert_str)
    except ValueError:
        wt_msgbox(f'Ungültiger Wert: "{neuer_wert_str}"\n\nBitte eine Zahl eingeben.')
        return

    # Bereichsprüfung
    if bereich and len(bereich) == 2:
        lo, hi = bereich
        if not (lo <= neuer_wert <= hi):
            wt_msgbox(
                f'Wert {neuer_wert}{einheit} liegt außerhalb des '
                f'gültigen Bereichs [{lo}..{hi}]{einheit}.\n\n'
                f'Änderung abgelehnt.'
            )
            return

    if neuer_wert == wert:
        wt_msgbox('Wert unverändert.')
        return

    # Bestätigung
    if not wt_yesno(
        f'Parameter: {rk_name} → {p_name}\n\n'
        f'Alt: {wert}{einheit}\n'
        f'Neu: {neuer_wert}{einheit}\n\n'
        f'Speichern?'
    ):
        return

    # Speichern
    matrix = lade_matrix()  # Frisch laden (Concurrent-Safety)
    matrix['regelkreise'][rk_name]['parameter'][p_name]['wert'] = neuer_wert
    _speichere_matrix(matrix)
    wt_msgbox(f'✓ {p_name} = {neuer_wert}{einheit} gespeichert.\n'
              f'Wirksam ab nächstem Engine-Zyklus.')


# ═══════════════════════════════════════════════════════════════
# Menü 3: Batterie-Scheduler
# ═══════════════════════════════════════════════════════════════

def menu_scheduler():
    """Batterie-Scheduler Status und Override."""
    while True:
        choice = wt_menu(
            'Batterie-Scheduler — Status & Steuerung',
            [
                ('status', 'Aktuellen Status anzeigen'),
                ('log', 'Letzte Aktionen (24h)'),
                ('soc_min', 'SOC_MIN Override → 5%'),
                ('soc_max', 'SOC_MAX Override → 100%'),
                ('reset', 'SOC auf Komfortwerte zurücksetzen'),
                ('auto', 'SOC auf auto zurücksetzen (5-100%)'),
            ],
        )

        if not choice:
            return

        if choice == 'status':
            _zeige_scheduler_status()
        elif choice == 'log':
            _zeige_scheduler_log()
        elif choice == 'soc_min':
            _soc_override('soc_min', 5)
        elif choice == 'soc_max':
            _soc_override('soc_max', 100)
        elif choice == 'reset':
            _soc_reset()
        elif choice == 'auto':
            _soc_auto()


def _zeige_scheduler_status():
    """Scheduler-Status als Textbox."""
    sched = _scheduler_state()
    batt = _battery_status()

    # battery_control.json lesen
    bc = {}
    if os.path.exists(BATTERY_CONFIG_PATH):
        try:
            with open(BATTERY_CONFIG_PATH) as f:
                bc = json.load(f)
        except Exception:
            pass

    soc = batt.get('soc', '?')
    power = batt.get('power_w', 0) or 0
    cha_state = batt.get('cha_state', '?')

    grenzen = bc.get('soc_grenzen', {})
    zellausg = bc.get('zellausgleich', {})

    text = (
        f'BATTERIE-SCHEDULER STATUS\n'
        f'{"─" * 50}\n\n'
        f'SOC aktuell:     {soc}%\n'
        f'Leistung:        {power:.0f}W {"(Laden)" if power > 0 else "(Entladen)" if power < 0 else "(Idle)"}\n'
        f'Ladestatus:      {cha_state}\n\n'
        f'SOC-Grenzen (Config):\n'
        f'  Komfort:       {grenzen.get("komfort_min", "?")}% – {grenzen.get("komfort_max", "?")}%\n'
        f'  Stress:        {grenzen.get("stress_min", "?")}% – {grenzen.get("stress_max", "?")}%\n'
        f'  Absolut Min:   {grenzen.get("absolutes_minimum", "?")}%\n\n'
        f'Zellausgleich:\n'
        f'  Modus:         {zellausg.get("modus", "?")}\n'
        f'  Letzter:       {zellausg.get("letzter_ausgleich", "nie")}\n'
        f'  Max. Tage:     {zellausg.get("max_tage_ohne_ausgleich", "?")}\n'
    )

    if sched:
        text += '\nScheduler-State:\n'
        for k, v in sorted(sched.items()):
            text += f'  {k}: {v}\n'

    wt_msgbox(text)


def _zeige_scheduler_log():
    """Letzte 20 Scheduler-Aktionen."""
    # Primaer: battery_control_log (echte Scheduler-Aktionen)
    rows = _query_all("""
        SELECT datetime(ts, 'unixepoch', 'localtime'), action, param, new_value, reason
        FROM battery_control_log
        ORDER BY ts DESC
        LIMIT 20
    """)
    source = 'battery_control_log'

    if not rows:
        # Fallback: automation_log
        rows = _query_all("""
            SELECT ts, kommando, wert, grund, ergebnis
            FROM automation_log
            WHERE aktor = 'batterie'
            ORDER BY ts DESC
            LIMIT 20
        """)
        source = 'automation_log'

    if not rows:
        wt_msgbox('Keine Scheduler-Aktionen in der DB.')
        return

    tmp = '/tmp/pv_scheduler_log.txt'
    with open(tmp, 'w') as f:
        f.write(f'BATTERIE-SCHEDULER LOG ({source})\n')
        f.write(f'{"═" * 70}\n\n')
        for row in rows:
            if source == 'battery_control_log':
                ts, action, param, new_val, reason = row
                ts_short = ts[5:16] if ts and len(ts) > 16 else ts or '?'
                f.write(f'{ts_short}  {action}:{param}={new_val}\n')
                if reason:
                    f.write(f'  {reason[:65]}\n')
            else:
                ts, cmd, wert, grund, erg = row
                ts_short = ts[5:16] if ts and len(ts) > 16 else ts or '?'
                f.write(f'{ts_short}  {cmd}={wert}  {erg or ""}\n')
                if grund:
                    f.write(f'  {grund[:65]}\n')
        f.write(f'\n{"─" * 70}\n')

    wt_textbox(tmp)
    os.unlink(tmp)


def _soc_override(param: str, wert: int):
    """SOC_MIN oder SOC_MAX sofort per Fronius-API setzen."""
    label = 'SOC_MIN' if param == 'soc_min' else 'SOC_MAX'
    if not wt_yesno(
        f'{label} sofort auf {wert}% setzen?\n\n'
        f'Dies wirkt direkt auf den Wechselrichter.\n'
        f'Der Scheduler kann den Wert im nächsten Zyklus\n'
        f'wieder überschreiben (≤15 Min).'
    ):
        return

    try:
        from fronius_api import BatteryConfig
        api = BatteryConfig()

        # Modus auf 'manual' stellen, sonst ignoriert F1 die Werte
        api.set_soc_mode('manual')

        if param == 'soc_min':
            api.set_soc_min(wert)
        else:
            api.set_soc_max(wert)

        wt_msgbox(f'SOC {label} = {wert}% gesetzt (Modus: manual).')
    except Exception as e:
        wt_msgbox(f'Fehler beim Setzen von {label}:\n\n{str(e)[:200]}')


def _soc_reset():
    """SOC auf Komfortwerte zurücksetzen."""
    matrix = lade_matrix()
    komfort_min = get_param(matrix, 'morgen_soc_min', 'komfort_min_pct', 25)
    komfort_max = get_param(matrix, 'nachmittag_soc_max', 'komfort_max_pct', 75)

    if not wt_yesno(
        f'SOC auf Komfortwerte zurücksetzen?\n\n'
        f'SOC_MIN → {komfort_min}%\n'
        f'SOC_MAX → {komfort_max}%\n\n'
        f'Der Scheduler kann die Werte im nächsten\n'
        f'Zyklus wieder überschreiben (≤15 Min).'
    ):
        return

    try:
        from fronius_api import BatteryConfig
        api = BatteryConfig()

        # Modus auf 'manual' stellen, sonst ignoriert F1 die Werte
        api.set_soc_mode('manual')

        api.set_soc_min(komfort_min)
        api.set_soc_max(komfort_max)
        wt_msgbox(f'SOC_MIN={komfort_min}%, SOC_MAX={komfort_max}% gesetzt\n(Modus: manual).')
    except Exception as e:
        wt_msgbox(f'Fehler:\n\n{str(e)[:200]}')


def _soc_auto():
    """SOC auf auto zuruecksetzen: Modus auto, 5-100%."""
    if not wt_yesno(
        'SOC auf Werkseinstellung zuruecksetzen?\n\n'
        'Modus  → auto\n'
        'SOC_MIN → 5%\n'
        'SOC_MAX → 100%\n\n'
        'Der Wechselrichter steuert die Batterie\n'
        'dann wieder selbstaendig.'
    ):
        return

    try:
        from fronius_api import BatteryConfig
        api = BatteryConfig()

        # Erst Werte setzen (im manual-Modus), dann auf auto
        api.set_soc_mode('manual')
        api.set_soc_min(5)
        api.set_soc_max(100)
        api.set_soc_mode('auto')
        wt_msgbox('SOC_MIN=5%, SOC_MAX=100%, Modus=auto gesetzt.')
    except Exception as e:
        wt_msgbox(f'Fehler:\n\n{str(e)[:200]}')


# ═══════════════════════════════════════════════════════════════
# Menü 4: System-Status
# ═══════════════════════════════════════════════════════════════

def menu_system():
    """System-Übersicht und Warnungen."""
    while True:
        choice = wt_menu(
            'System-Status & Warnungen',
            [
                ('uebersicht', 'System-Übersicht'),
                ('warnungen', 'Aktive Warnungen prüfen'),
                ('db', 'Datenbank-Status'),
                ('services', 'Service-Status'),
                ('validierung', 'Parametermatrix validieren'),
            ],
        )

        if not choice:
            return

        if choice == 'uebersicht':
            _system_uebersicht()
        elif choice == 'warnungen':
            _pruefe_warnungen()
        elif choice == 'db':
            _db_status()
        elif choice == 'services':
            _service_status()
        elif choice == 'validierung':
            _validiere_param_matrix()


def _system_uebersicht():
    """Kompakte System-Übersicht."""
    coll_text, _ = _collector_status()
    batt = _battery_status()
    pv = _pv_status()
    db_sz = _db_size()

    # Regelkreise zählen
    matrix = lade_matrix()
    rks = alle_regelkreise(matrix)
    aktiv = sum(1 for _, rk in rks if rk.get('aktiv'))

    # DB-Tabellengrößen
    tables = {}
    for tbl in ['raw_data', 'data_1min', 'data_15min', 'hourly_data',
                'daily_data', 'monthly_statistics', 'automation_log']:
        row = _query_one(f'SELECT COUNT(*) FROM {tbl}')
        tables[tbl] = row[0] if row else 0

    text = (
        f'SYSTEM-ÜBERSICHT\n'
        f'{"═" * 50}\n\n'
        f'Anlage:        {config.PV_KWP_TOTAL} kWp, BYD {config.PV_BATTERY_KWH} kWh\n'
        f'Standort:      {config.LATITUDE}°N, {config.LONGITUDE}°E, {config.ELEVATION}m\n'
        f'Collector:     {coll_text}\n'
        f'Web-API:       Port {config.WEB_API_PORT}\n'
        f'DB (tmpfs):    {db_sz}\n'
        f'Automation:    {aktiv}/{len(rks)} Regelkreise aktiv\n\n'
        f'DATENBANK-TABELLEN:\n'
        f'{"─" * 50}\n'
    )
    for tbl, count in tables.items():
        text += f'  {tbl:<25} {count:>8} Zeilen\n'

    wt_msgbox(text)


def _pruefe_warnungen():
    """Aktive Warnungen prüfen und anzeigen."""
    warnungen = []

    # 1. Collector-Status
    coll_text, coll_color = _collector_status()
    if coll_color == C_RED:
        warnungen.append(f'🔴 Collector: {coll_text}')

    # 2. Letzte Daten-Alter (ts = Unix epoch float)
    row = _query_one("SELECT MAX(ts) FROM raw_data")
    if row and row[0]:
        try:
            age_min = (time.time() - float(row[0])) / 60
            if age_min > 10:
                warnungen.append(f'🔴 Keine neuen Daten seit {int(age_min)} Minuten')
        except Exception:
            pass

    # 3. SOC-Anomalie
    batt = _battery_status()
    soc = batt.get('soc')
    if soc is not None:
        if soc < 5:
            warnungen.append(f'🔴 SOC kritisch niedrig: {soc}%')
        elif soc < 10:
            warnungen.append(f'🟡 SOC niedrig: {soc}%')

    # 4. DB-Größe
    try:
        size_mb = os.path.getsize(config.DB_PATH) / 1024 / 1024
        if size_mb > 300:
            warnungen.append(f'🟡 DB-Größe: {size_mb:.0f} MB (>300 MB)')
    except OSError:
        warnungen.append('🔴 DB nicht erreichbar')

    # 5. Parametermatrix validieren
    try:
        matrix = lade_matrix()
        fehler = validiere_matrix(matrix)
        if fehler:
            warnungen.append(f'🟡 {len(fehler)} Parameter außerhalb Bereich')
    except Exception as e:
        warnungen.append(f'🔴 Matrix nicht lesbar: {str(e)[:50]}')

    # 6. Zellausgleich überfällig?
    try:
        with open(BATTERY_CONFIG_PATH) as f:
            bc = json.load(f)
        letzter = bc.get('zellausgleich', {}).get('letzter_ausgleich', '')
        max_tage = bc.get('zellausgleich', {}).get('max_tage_ohne_ausgleich', 45)
        if letzter:
            letzte_date = date.fromisoformat(letzter)
            tage_seit = (date.today() - letzte_date).days
            if tage_seit > max_tage:
                warnungen.append(f'🟡 Zellausgleich überfällig: {tage_seit} Tage (Max: {max_tage})')
    except Exception:
        pass

    # 7. Backup-Alter prüfen
    backup_dir = os.path.join(PROJECT_ROOT, 'backup', 'db')
    if os.path.isdir(backup_dir):
        newest = 0
        for f in os.listdir(backup_dir):
            fp = os.path.join(backup_dir, f)
            if os.path.isfile(fp):
                newest = max(newest, os.path.getmtime(fp))
        if newest > 0:
            age_h = (time.time() - newest) / 3600
            if age_h > 48:
                warnungen.append(f'🟡 Backup älter als {int(age_h)}h')

    if not warnungen:
        wt_msgbox('✓ Keine aktiven Warnungen.\n\nAlle Systeme im Normalzustand.')
    else:
        text = f'AKTIVE WARNUNGEN ({len(warnungen)})\n{"═" * 50}\n\n'
        for w in warnungen:
            text += f'{w}\n\n'
        wt_msgbox(text)


def _db_status():
    """Detaillierter DB-Status."""
    # DB-Dateiinfo
    db_path = config.DB_PATH
    persist_path = config.DB_PERSIST_PATH
    db_sz = _db_size()

    text = f'DATENBANK-STATUS\n{"═" * 50}\n\n'
    text += f'RAM-DB:     {db_path}\n'
    text += f'Größe:      {db_sz}\n'
    text += f'Persist:    {persist_path}\n'

    # Persist-Alter
    if os.path.exists(persist_path):
        age_h = (time.time() - os.path.getmtime(persist_path)) / 3600
        text += f'Persist-Alter: {age_h:.1f}h\n'
    else:
        text += 'Persist: NICHT VORHANDEN\n'

    # WAL-Modus prüfen
    row = _query_one("PRAGMA journal_mode")
    text += f'Journal:    {row[0] if row else "?"}\n\n'

    # Zeitbereiche pro Tabelle (ts = Unix epoch float)
    text += f'ZEITBEREICHE:\n{"─" * 50}\n'
    for tbl in ['raw_data', 'data_1min', 'data_15min', 'hourly_data', 'daily_data']:
        row = _query_one(f'SELECT MIN(ts), MAX(ts), COUNT(*) FROM {tbl}')
        if row and row[0]:
            min_dt = datetime.fromtimestamp(float(row[0])).strftime('%Y-%m-%d')
            max_dt = datetime.fromtimestamp(float(row[1])).strftime('%Y-%m-%d')
            text += f'  {tbl:<18} {min_dt}..{max_dt}  ({row[2]} Zeilen)\n'

    wt_msgbox(text)


def _service_status():
    """systemd-Services prüfen."""
    services = [
        'pv-collector.service',
        'pv-web.service',
        'pv-steuerbox.service',
        'pv-wattpilot.service',
        'pv-backup-gfs.timer',
        'pv-backup-2d.timer',
        'pv-mirror-sync.timer',
    ]

    text = f'SERVICE-STATUS\n{"═" * 50}\n\n'

    for svc in services:
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', svc],
                capture_output=True, text=True, timeout=3,
            )
            status = result.stdout.strip()
            marker = '✓' if status == 'active' else ('⏱' if status == 'activating' else '✗')
            text += f'  {marker} {svc:<35} {status}\n'
        except Exception:
            text += f'  ? {svc:<35} unbekannt\n'

    # Cron-Jobs
    text += f'\nCRON-CHECKS:\n{"─" * 50}\n'
    try:
        result = subprocess.run(
            ['crontab', '-l'], capture_output=True, text=True, timeout=3,
        )
        crons = [l.strip() for l in result.stdout.splitlines()
                 if l.strip() and not l.startswith('#')]
        text += f'  {len(crons)} aktive Cron-Jobs\n'
        for c in crons[:8]:
            text += f'  {c[:68]}\n'
        if len(crons) > 8:
            text += f'  ... +{len(crons) - 8} weitere\n'
    except Exception:
        text += '  Crontab nicht lesbar\n'

    wt_msgbox(text)


def _validiere_param_matrix():
    """Parametermatrix vollständig validieren."""
    try:
        matrix = lade_matrix()
        fehler = validiere_matrix(matrix)

        rks = alle_regelkreise(matrix)
        aktiv = sum(1 for _, rk in rks if rk.get('aktiv'))
        total_params = sum(
            len([k for k in rk.get('parameter', {}) if not k.startswith('_')])
            for _, rk in rks
        )

        text = f'PARAMETERMATRIX-VALIDIERUNG\n{"═" * 50}\n\n'
        text += f'Regelkreise: {aktiv}/{len(rks)} aktiv\n'
        text += f'Parameter:   {total_params} gesamt\n'
        text += f'Version:     {matrix.get("_version", "?")}\n'
        text += f'Stand:       {matrix.get("_updated", "?")}\n\n'

        if fehler:
            text += f'⚠ {len(fehler)} FEHLER:\n{"─" * 50}\n'
            for f in fehler:
                text += f'  ✗ {f}\n'
        else:
            text += f'✓ Alle {total_params} Parameter im gültigen Bereich.\n'

        wt_msgbox(text)
    except Exception as e:
        wt_msgbox(f'Fehler beim Laden der Matrix:\n\n{str(e)[:200]}')


# ═══════════════════════════════════════════════════════════════
# Menü 5: Forecast
# ═══════════════════════════════════════════════════════════════

def menu_forecast():
    """Forecast-Status und Genauigkeit."""
    while True:
        choice = wt_menu(
            'Solar-Prognose',
            [
                ('heute', 'Tagesprognose heute'),
                ('genauigkeit', 'Forecast-Genauigkeit (letzte 7 Tage)'),
                ('kalibrierung', 'Letzte Kalibrierung'),
            ],
        )

        if not choice:
            return

        if choice == 'heute':
            _forecast_heute()
        elif choice == 'genauigkeit':
            _forecast_genauigkeit()
        elif choice == 'kalibrierung':
            _forecast_kalibrierung()


def _forecast_heute():
    """Tagesprognose aus DB."""
    today = date.today().isoformat()
    row = _query_one("""
        SELECT expected_kwh, quality, created_at, hourly_profile,
               weather_text, cloud_cover_avg, sunrise, sunset
        FROM forecast_daily
        WHERE date = ?
    """, (today,))

    if not row:
        wt_msgbox('Keine Tagesprognose in der DB.\n\n'
                   '(forecast_daily leer fuer heute)')
        return

    expected, quality, created, hourly_json, weather, cloud, sunrise, sunset = row
    created_str = datetime.fromtimestamp(created).strftime('%H:%M') if created else '?'

    text = f'TAGESPROGNOSE {today}\n{"═" * 50}\n\n'
    text += f'Prognose:   {expected:.1f} kWh\n'
    text += f'Qualitaet:  {quality or "?"}\n'
    text += f'Erstellt:   {created_str}\n'
    if weather:
        text += f'Wetter:     {weather}\n'
    if cloud is not None:
        text += f'Bewoelkung: {cloud:.0f}%\n'
    if sunrise and sunset:
        text += f'Sonne:      {sunrise} - {sunset}\n'

    ertrag = _tagesertrag()
    if ertrag and expected:
        pct = ertrag / expected * 100
        text += f'\nIST bisher: {ertrag:.1f} kWh ({pct:.0f}%)\n'

    # Stundenweise Prognose aus JSON-Feld
    if hourly_json:
        try:
            profile = json.loads(hourly_json) if isinstance(hourly_json, str) else hourly_json
            if isinstance(profile, list) and profile:
                text += f'\nSTUNDENWEISE:\n{"─" * 50}\n'
                for entry in profile:
                    h = entry.get('hour', 0)
                    wh = entry.get('wh', 0) or entry.get('energy_wh', 0)
                    text += f'  {h:02d}:00  {wh:>5.0f} Wh\n'
        except (json.JSONDecodeError, TypeError):
            pass

    wt_msgbox(text)


def _forecast_genauigkeit():
    """Forecast-Genauigkeit der letzten 7 Tage."""
    seven_days_ago = (datetime.now() - timedelta(days=7)).timestamp()
    rows = _query_all("""
        SELECT d.ts, d.W_PV_total,
               f.expected_kwh
        FROM daily_data d
        LEFT JOIN forecast_daily f ON date(d.ts, 'unixepoch', 'localtime') = f.date
        WHERE d.ts >= ?
        ORDER BY d.ts
    """, (seven_days_ago,))

    if not rows:
        wt_msgbox('Keine Vergleichsdaten vorhanden.\n'
                   '(daily_data oder forecast_daily leer)')
        return

    text = f'FORECAST-GENAUIGKEIT — Letzte 7 Tage\n{"═" * 50}\n\n'
    text += f'{"Datum":<12} {"IST kWh":>9} {"Prognose":>9} {"Abw.":>7}\n'
    text += f'{"─" * 12} {"─" * 9} {"─" * 9} {"─" * 7}\n'

    for row in rows:
        ist = (row[1] or 0) / 1000
        prog = row[2] or 0
        datum = datetime.fromtimestamp(float(row[0])).strftime('%Y-%m-%d') if row[0] else '?'
        if prog > 0:
            abw = (ist - prog) / prog * 100
            abw_str = f'{abw:+.1f}%'
        else:
            abw_str = '—'
        text += f'{datum:<12} {ist:>8.1f} {prog:>9.1f} {abw_str:>7}\n'

    wt_msgbox(text)


def _forecast_kalibrierung():
    """Kalibrierungs-Status."""
    cal_path = os.path.join(PROJECT_ROOT, 'config', 'solar_calibration.json')
    if not os.path.exists(cal_path):
        wt_msgbox('Keine Kalibrierungsdatei gefunden.\n\n'
                   f'Erwartet: {cal_path}')
        return

    try:
        with open(cal_path) as f:
            cal = json.load(f)

        text = f'SOLAR-KALIBRIERUNG\n{"═" * 50}\n\n'
        if isinstance(cal, dict):
            for k, v in sorted(cal.items()):
                if isinstance(v, dict):
                    text += f'\n{k}:\n'
                    for kk, vv in sorted(v.items()):
                        text += f'  {kk}: {vv}\n'
                else:
                    text += f'{k}: {v}\n'
        else:
            text += json.dumps(cal, indent=2, ensure_ascii=False)[:800]

        wt_msgbox(text)
    except Exception as e:
        wt_msgbox(f'Fehler beim Lesen:\n\n{str(e)[:200]}')


# ═══════════════════════════════════════════════════════════════
# Menü 6: Heizpatrone (HP) — Fritz!DECT
# ═══════════════════════════════════════════════════════════════

FRITZ_CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'fritz_config.json')


def _lade_fritz_config() -> dict:
    """Fritz!Box-Config laden. Credentials kommen aus .secrets (nicht JSON!)."""
    cfg = {}
    if os.path.exists(FRITZ_CONFIG_PATH):
        try:
            with open(FRITZ_CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception:
            pass
    # Credentials immer aus .secrets laden (wie FRONIUS_PASS, WATTPILOT_PASSWORD)
    cfg['fritz_user'] = config.load_secret('FRITZ_USER') or ''
    cfg['fritz_password'] = config.load_secret('FRITZ_PASSWORD') or ''
    return cfg


def _speichere_fritz_config(cfg: dict):
    """Fritz!Box-Config atomar speichern. Credentials werden NICHT in JSON geschrieben."""
    # Credentials aus dem Dict entfernen — gehören in .secrets
    save_cfg = {k: v for k, v in cfg.items()
                if k not in ('fritz_user', 'fritz_password')}
    save_cfg['_updated'] = date.today().isoformat()
    tmp = FRITZ_CONFIG_PATH + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(save_cfg, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, FRITZ_CONFIG_PATH)
        _fix_ownership(FRITZ_CONFIG_PATH)
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern:\n\n{str(e)[:200]}')
        if os.path.exists(tmp):
            os.unlink(tmp)


# Fritz!Box SID-Cache (Modul-Level, gültig ~15 Min)
_fritz_sid_cache: dict = {'sid': None, 'ts': 0, 'host': ''}
_FRITZ_SID_TTL = 900  # 15 Minuten


def _fritz_session_id(cfg: dict, force_refresh: bool = False) -> Optional[str]:
    """Fritz!Box Session-ID holen via login_sid.lua (AHA-HTTP-API).

    Cached für 15 Min — spart 2 HTTP-Requests pro Folge-Aufruf.
    """
    import hashlib
    import urllib.request
    import xml.etree.ElementTree as ET
    global _fritz_sid_cache

    host = cfg.get('fritz_ip', '192.168.178.1')
    user = cfg.get('fritz_user', '')
    passwd = cfg.get('fritz_password', '')

    if not user or not passwd:
        return None

    # Cache gültig?
    if (not force_refresh
            and _fritz_sid_cache['sid']
            and _fritz_sid_cache['host'] == host
            and (time.time() - _fritz_sid_cache['ts']) < _FRITZ_SID_TTL):
        return _fritz_sid_cache['sid']

    # Challenge holen
    url = f'http://{host}/login_sid.lua'
    resp = urllib.request.urlopen(url, timeout=8)
    xml_text = resp.read().decode('utf-8')
    root = ET.fromstring(xml_text)
    sid = root.findtext('SID')
    challenge = root.findtext('Challenge')

    if sid and sid != '0000000000000000':
        _fritz_sid_cache = {'sid': sid, 'ts': time.time(), 'host': host}
        return sid

    # Response berechnen: challenge-password (UTF-16LE, MD5)
    response = f'{challenge}-{passwd}'.encode('utf-16-le')
    md5 = hashlib.md5(response).hexdigest()
    login_response = f'{challenge}-{md5}'

    # Login
    url2 = f'http://{host}/login_sid.lua?username={user}&response={login_response}'
    resp2 = urllib.request.urlopen(url2, timeout=8)
    xml_text2 = resp2.read().decode('utf-8')
    root2 = ET.fromstring(xml_text2)
    sid = root2.findtext('SID')

    if sid == '0000000000000000':
        _fritz_sid_cache = {'sid': None, 'ts': 0, 'host': ''}
        return None

    _fritz_sid_cache = {'sid': sid, 'ts': time.time(), 'host': host}
    return sid


def _fritz_switch(cfg: dict, cmd: str) -> Optional[str]:
    """Fritz!DECT AHA-Schaltbefehl senden (setswitchon/setswitchoff/getswitchstate/...)."""
    import urllib.request
    global _fritz_sid_cache

    sid = _fritz_session_id(cfg)
    if not sid:
        return None

    host = cfg.get('fritz_ip', '192.168.178.1')
    ain = cfg.get('ain', '').replace(' ', '')

    url = (f'http://{host}/webservices/homeautoswitch.lua'
           f'?ain={ain}&switchcmd={cmd}&sid={sid}')
    try:
        resp = urllib.request.urlopen(url, timeout=8)
        return resp.read().decode('utf-8').strip()
    except Exception:
        # SID evtl. abgelaufen → Cache invalidieren für nächsten Versuch
        _fritz_sid_cache = {'sid': None, 'ts': 0, 'host': ''}
        raise


def _fritz_bulk_status(cfg: dict) -> Optional[dict]:
    """HP-Status per getdevicelistinfos in EINEM Request (statt 4 Einzelne).

    Fritz!Box ist langsam (~1-2s pro Request). Diese Bulk-Abfrage
    liefert state, power, energy, name in einem einzigen XML.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    sid = _fritz_session_id(cfg)
    if not sid:
        return None

    host = cfg.get('fritz_ip', '192.168.178.1')
    ain_norm = cfg.get('ain', '').replace(' ', '').strip()
    if not ain_norm:
        return None

    url = (f'http://{host}/webservices/homeautoswitch.lua'
           f'?switchcmd=getdevicelistinfos&sid={sid}')
    resp = urllib.request.urlopen(url, timeout=10)
    xml_text = resp.read().decode('utf-8')
    root = ET.fromstring(xml_text)

    for device in root.findall('device'):
        dev_ain = (device.get('identifier') or '').replace(' ', '').strip()
        if dev_ain != ain_norm:
            continue

        result = {'state': None, 'power_mw': None, 'energy_wh': None, 'name': None}

        name_el = device.find('name')
        if name_el is not None and name_el.text:
            result['name'] = name_el.text.strip()

        sw = device.find('switch')
        if sw is not None:
            state_el = sw.find('state')
            if state_el is not None and state_el.text is not None:
                result['state'] = state_el.text.strip()

        pm = device.find('powermeter')
        if pm is not None:
            power_el = pm.find('power')
            if power_el is not None and power_el.text:
                try:
                    result['power_mw'] = int(power_el.text)
                except ValueError:
                    pass
            energy_el = pm.find('energy')
            if energy_el is not None and energy_el.text:
                try:
                    result['energy_wh'] = int(energy_el.text)
                except ValueError:
                    pass

        return result
    return None


def menu_heizpatrone():
    """Heizpatrone (HP) — Konfiguration & Steuerung via Fritz!DECT."""
    while True:
        cfg = _lade_fritz_config()
        ain = cfg.get('ain') or '—'
        host = cfg.get('fritz_ip') or '—'
        has_creds = bool(cfg.get('fritz_user') and cfg.get('fritz_password'))
        konfig_ok = has_creds and ain != '—'

        # Regelkreis-Status aus Parametermatrix
        try:
            matrix = lade_matrix()
            rk = matrix.get('regelkreise', {}).get('heizpatrone', {})
            rk_aktiv = rk.get('aktiv', False)
            rk_text = 'AKTIV' if rk_aktiv else 'INAKTIV'
        except Exception:
            rk_text = '?'

        choice = wt_menu(
            f'Heizpatrone (HP) — Fritz!DECT-Steuerung\n'
            f'Fritz!Box: {host}  AIN: {ain}\n'
            f'Zugangsdaten (.secrets): {"✓" if has_creds else "✗ FRITZ_USER/FRITZ_PASSWORD fehlen"}  '
            f'Regelkreis: {rk_text}',
            [
                ('status', 'HP-Status abfragen (Fritz!Box)'),
                ('config', 'Fritz!Box-Verbindung konfigurieren'),
                ('test', 'Verbindungstest'),
                ('ein', 'HP manuell EINSCHALTEN'),
                ('aus', 'HP manuell AUSSCHALTEN'),
                ('schwellen', 'Schwellwerte (Parametermatrix)'),
            ],
        )

        if not choice:
            return

        if choice == 'status':
            _hp_status(cfg)
        elif choice == 'config':
            cfg = _hp_config(cfg)
        elif choice == 'test':
            _hp_verbindungstest(cfg)
        elif choice == 'ein':
            _hp_manuell(cfg, True)
        elif choice == 'aus':
            _hp_manuell(cfg, False)
        elif choice == 'schwellen':
            _hp_schwellen()


def _hp_status(cfg: dict):
    """HP-Status via Fritz!Box AHA-API abfragen.

    Verwendet getdevicelistinfos (1 Request statt 4 Einzelabfragen).
    Fritz!Box ist langsam — Bulk spart ~6 Sekunden.
    """
    if not cfg.get('ain'):
        wt_msgbox('Keine AIN konfiguriert.\n\n'
                   'Bitte zuerst Fritz!Box-Verbindung einrichten.')
        return

    try:
        info = _fritz_bulk_status(cfg)
        if info is None:
            wt_msgbox('Fritz!Box nicht erreichbar oder AIN nicht gefunden.')
            return

        state = info.get('state')
        state_text = {
            '0': 'AUS', '1': 'EIN', 'inval': 'Unbekannt'
        }.get(state or '', f'? ({state})')

        power_mw = info.get('power_mw')
        power_w = power_mw / 1000 if power_mw is not None else 0
        energy_wh = info.get('energy_wh') or 0

        text = (
            f'HEIZPATRONE STATUS\n'
            f'{"═" * 50}\n\n'
            f'Gerätename:  {info.get("name") or "?"}\n'
            f'AIN:         {cfg.get("ain", "?")}\n'
            f'Schaltzustand: {state_text}\n'
            f'Leistung:    {power_w:.1f} W\n'
            f'Energie:     {energy_wh} Wh (seit Zähler-Reset)\n'
        )

        wt_msgbox(text)
    except Exception as e:
        wt_msgbox(f'Fehler bei Fritz!Box-Abfrage:\n\n{str(e)[:200]}')


def _hp_config(cfg: dict) -> dict:
    """Fritz!Box-Verbindungsparameter konfigurieren."""
    while True:
        has_user = bool(cfg.get('fritz_user'))
        has_pass = bool(cfg.get('fritz_password'))
        choice = wt_menu(
            'Fritz!Box — Verbindungseinstellungen\n\n'
            f'IP:       {cfg.get("fritz_ip", "—")}\n'
            f'User:     {"✓ (aus .secrets)" if has_user else "✗ fehlt in .secrets"}\n'
            f'Passwort: {"✓ (aus .secrets)" if has_pass else "✗ fehlt in .secrets"}\n'
            f'AIN:      {cfg.get("ain", "—")}',
            [
                ('ip', f'Fritz!Box-IP  [{cfg.get("fritz_ip", "192.168.178.1")}]'),
                ('secrets', 'Zugangsdaten (.secrets bearbeiten)'),
                ('ain', f'AIN der Steckdose  [{cfg.get("ain", "")}]'),
            ],
        )

        if not choice:
            return cfg

        if choice == 'ip':
            val = wt_inputbox('Fritz!Box IP-Adresse:', cfg.get('fritz_ip', '192.168.178.1'))
            if val is not None:
                cfg['fritz_ip'] = val.strip()
                _speichere_fritz_config(cfg)

        elif choice == 'secrets':
            _hp_edit_secrets()
            # Credentials neu laden
            cfg['fritz_user'] = config.load_secret('FRITZ_USER') or ''
            cfg['fritz_password'] = config.load_secret('FRITZ_PASSWORD') or ''

        elif choice == 'ain':
            val = wt_inputbox(
                'AIN der Fritz!DECT-Steckdose.\n'
                'Zu finden in Fritz!Box → Smart Home → Geräte.\n'
                'Format z.B. "11657 0123456":',
                cfg.get('ain', ''),
            )
            if val is not None:
                cfg['ain'] = val.strip()
                _speichere_fritz_config(cfg)


def _hp_edit_secrets():
    """Fritz-Credentials in .secrets bearbeiten (wie FRONIUS_PASS, WATTPILOT_PASSWORD)."""
    secrets_path = config.SECRETS_FILE
    existing_user = config.load_secret('FRITZ_USER') or ''
    existing_pass = bool(config.load_secret('FRITZ_PASSWORD'))

    info = (
        f'Fritz!Box-Zugangsdaten werden in .secrets gespeichert\n'
        f'(wie FRONIUS_PASS und WATTPILOT_PASSWORD).\n\n'
        f'Datei: {secrets_path}\n\n'
        f'FRITZ_USER:     {existing_user or "— nicht gesetzt"}\n'
        f'FRITZ_PASSWORD: {"✓ gesetzt" if existing_pass else "— nicht gesetzt"}\n\n'
        f'Neuen Benutzernamen eingeben (leer = beibehalten):'
    )

    new_user = wt_inputbox(info, existing_user)
    if new_user is None:
        return
    new_user = new_user.strip()

    new_pass = wt_inputbox('Fritz!Box Passwort eingeben:', '')
    if new_pass is None:
        return

    # .secrets-Datei lesen, Zeilen ersetzen/ergänzen
    lines = []
    if os.path.exists(secrets_path):
        with open(secrets_path, 'r') as f:
            lines = f.readlines()

    # Bestehende FRITZ_-Zeilen entfernen
    lines = [l for l in lines if not l.strip().startswith('FRITZ_USER=')
             and not l.strip().startswith('FRITZ_PASSWORD=')]

    # Neue Zeilen anhängen
    if lines and not lines[-1].endswith('\n'):
        lines.append('\n')

    # Kommentar nur wenn noch keiner da
    has_fritz_comment = any('Fritz' in l and l.strip().startswith('#') for l in lines)
    if not has_fritz_comment:
        lines.append('# Fritz!Box (Heizpatrone via Fritz!DECT)\n')

    if new_user:
        lines.append(f'FRITZ_USER={new_user}\n')
    if new_pass:
        lines.append(f'FRITZ_PASSWORD={new_pass}\n')

    with open(secrets_path, 'w') as f:
        f.writelines(lines)
    os.chmod(secrets_path, 0o600)

    wt_msgbox(
        f'✓ Zugangsdaten in .secrets gespeichert.\n\n'
        f'Datei: {secrets_path}\n'
        f'Rechte: 600 (nur Owner lesen/schreiben)\n'
        f'.gitignore: .secrets ist ausgeschlossen'
    )


def _hp_verbindungstest(cfg: dict):
    """Fritz!Box-Verbindung und AHA-API testen."""
    text = f'VERBINDUNGSTEST\n{"═" * 50}\n\n'

    # 1. Ping?
    host = cfg.get('fritz_ip', '192.168.178.1')
    text += f'Fritz!Box: {host}\n'
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '2', host],
            capture_output=True, timeout=5,
        )
        text += f'  Ping: {"✓ OK" if result.returncode == 0 else "✗ nicht erreichbar"}\n'
    except Exception:
        text += '  Ping: ✗ Fehler\n'

    # 2. Session-ID?
    has_user = bool(cfg.get('fritz_user'))
    has_pass = bool(cfg.get('fritz_password'))
    text += f'\nLogin (.secrets): {"✓ User+Pass" if has_user and has_pass else "✗ FRITZ_USER/FRITZ_PASSWORD fehlen"}\n'
    try:
        sid = _fritz_session_id(cfg)
        if sid:
            text += f'  Session-ID: ✓ {sid[:8]}...\n'
        else:
            text += '  Session-ID: ✗ Login fehlgeschlagen\n'
            text += '  (Benutzername/Passwort korrekt?)\n'
    except Exception as e:
        text += f'  Session-ID: ✗ {str(e)[:60]}\n'

    # 3. AHA-API / Steckdose? (1 Bulk-Request statt 2 Einzelne)
    ain = cfg.get('ain', '')
    if ain and sid:
        text += f'\nFritz!DECT (AIN: {ain}):\n'
        try:
            info = _fritz_bulk_status(cfg)
            if info:
                text += f'  Gerät: ✓ "{info.get("name", "?")}"\n'
                st = info.get('state')
                text += f'  Zustand: {"EIN" if st == "1" else "AUS" if st == "0" else st or "?"}\n'
                pw = info.get('power_mw')
                if pw is not None:
                    text += f'  Leistung: {pw / 1000:.1f} W\n'
            else:
                text += '  Gerät: ✗ AIN nicht in Geräteliste gefunden\n'
        except Exception as e:
            text += f'  Gerät: ✗ {str(e)[:60]}\n'
    elif not ain:
        text += '\nFritz!DECT: — (keine AIN konfiguriert)\n'

    wt_msgbox(text)


def _hp_manuell(cfg: dict, einschalten: bool):
    """HP manuell ein-/ausschalten via Fritz!DECT."""
    if not cfg.get('ain'):
        wt_msgbox('Keine AIN konfiguriert.')
        return

    aktion = 'EINSCHALTEN' if einschalten else 'AUSSCHALTEN'
    cmd = 'setswitchon' if einschalten else 'setswitchoff'

    if not wt_yesno(
        f'Heizpatrone (2 kW) manuell {aktion}?\n\n'
        f'AIN: {cfg.get("ain")}\n\n'
        f'{"⚡ ACHTUNG: Manuelles Einschalten umgeht " if einschalten else ""}'
        f'{"die Automatik. HP bleibt EIN bis manuell " if einschalten else ""}'
        f'{"ausgeschaltet oder Automation übernimmt!" if einschalten else ""}'
    ):
        return

    try:
        result = _fritz_switch(cfg, cmd)
        state_ok = (result == '1') if einschalten else (result == '0')
        if state_ok:
            wt_msgbox(f'✓ Heizpatrone {aktion}.\n\n'
                       f'Antwort: {result}')
        else:
            wt_msgbox(f'Heizpatrone {cmd} gesendet.\n\n'
                       f'Antwort: {result}\n'
                       f'(Erwartet: {"1" if einschalten else "0"})')
    except Exception as e:
        wt_msgbox(f'Fehler:\n\n{str(e)[:200]}')


def _hp_schwellen():
    """HP-Schwellwerte aus Parametermatrix anzeigen/bearbeiten — leitet zu Regelkreis-Detail."""
    try:
        matrix = lade_matrix()
        rk = matrix.get('regelkreise', {}).get('heizpatrone')
        if not rk:
            wt_msgbox('Regelkreis "heizpatrone" nicht in der Parametermatrix.\n\n'
                       'Bitte config/soc_param_matrix.json prüfen.')
            return
        _menu_regelkreis_detail('heizpatrone')
    except Exception as e:
        wt_msgbox(f'Fehler:\n\n{str(e)[:200]}')


# ═══════════════════════════════════════════════════════════════
# Daemon-Reload nach Param-Änderung
# ═══════════════════════════════════════════════════════════════

_DAEMON_PID_FILE = os.path.join(PROJECT_ROOT, 'automation_daemon.pid')

def _notify_daemon_reload():
    """SIGHUP an Automation-Daemon senden → Matrix-Reload."""
    try:
        if not os.path.exists(_DAEMON_PID_FILE):
            return
        with open(_DAEMON_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGHUP)
    except (ValueError, ProcessLookupError, PermissionError):
        pass


# ═══════════════════════════════════════════════════════════════
# Matrix speichern (atomar)
# ═══════════════════════════════════════════════════════════════

def _fix_ownership(path: str):
    """Datei-Owner auf SUDO_USER zurücksetzen wenn unter sudo gelaufen.

    Verhindert root:root-Ownership bei Config-Dateien die mit
    sudo python3 pv-config.py geschrieben werden.
    """
    sudo_uid = os.environ.get('SUDO_UID')
    sudo_gid = os.environ.get('SUDO_GID')
    if sudo_uid and sudo_gid:
        try:
            os.chown(path, int(sudo_uid), int(sudo_gid))
        except OSError:
            pass


def _speichere_matrix(matrix: dict):
    """Matrix atomar speichern (write-to-temp + rename)."""
    # Zeitstempel aktualisieren
    matrix['_updated'] = date.today().isoformat()

    # Validieren vor Speichern
    fehler = validiere_matrix(matrix)
    if fehler:
        wt_msgbox(
            '⚠ VALIDIERUNGSFEHLER — Speichern abgebrochen!\n\n'
            + '\n'.join(f'• {f}' for f in fehler[:5])
        )
        return

    tmp_path = DEFAULT_MATRIX_PATH + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(matrix, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp_path, DEFAULT_MATRIX_PATH)
        _fix_ownership(DEFAULT_MATRIX_PATH)
        _notify_daemon_reload()
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern:\n\n{str(e)[:200]}')
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════
# Schalt-Logbuch
# ═══════════════════════════════════════════════════════════════

def menu_schaltlog():
    """Zentrales Schalt-Logbuch anzeigen (scrollbar).

    Zeigt alle Schaltvorgänge:
      • ENGINE: eigene Aktionen (exakter Zeitstempel)
      • EXTERN: extern erkannte Änderungen (~ungefährer Zeitpunkt)
    """
    from automation.engine.schaltlog import lese_log, SCHALTLOG_PATH

    while True:
        choice = wt_menu('Schalt-Logbuch — Alle Schaltvorgänge', [
            ('1', 'Logbuch anzeigen (neueste zuerst)'),
            ('2', 'Logbuch anzeigen (letzte 100)'),
            ('3', 'Logbuch anzeigen (alle)'),
            ('4', 'Status & Dateigröße'),
        ])
        if not choice:
            return

        if choice in ('1', '2', '3'):
            if choice == '2':
                text = lese_log(max_zeilen=100)
            elif choice == '3':
                text = lese_log(max_zeilen=2000)
            else:
                text = lese_log(max_zeilen=500)

            tmp = '/tmp/pv_schaltlog.txt'
            with open(tmp, 'w') as f:
                f.write(text)
            wt_textbox(tmp)
            try:
                os.unlink(tmp)
            except OSError:
                pass

        elif choice == '4':
            info = f'Schaltlog-Datei: {SCHALTLOG_PATH}\n\n'
            if os.path.exists(SCHALTLOG_PATH):
                size = os.path.getsize(SCHALTLOG_PATH)
                with open(SCHALTLOG_PATH, 'r') as f:
                    n_lines = sum(1 for _ in f)
                info += (f'Dateigröße: {size:,} Bytes\n'
                         f'Einträge:   {n_lines}\n'
                         f'Max:        2000 (ältere werden automatisch entfernt)\n')
            else:
                info += 'Datei existiert noch nicht.\nSie wird beim ersten Schaltvorgang angelegt.\n'
            wt_msgbox(info)


# ═══════════════════════════════════════════════════════════════
# Benachrichtigungen (E-Mail)
# ═══════════════════════════════════════════════════════════════

def menu_benachrichtigung():
    """E-Mail-Benachrichtigungen konfigurieren.

    Zeigt aktive Events, erlaubt Ein/Ausschalten und Test-Mail.
    SMTP-Passwort wird verschlüsselt in /etc/pv-system/smtp_pass.key gespeichert.
    """
    from automation.engine import credential_store

    while True:
        # Aktuelle Config
        email = getattr(config, 'NOTIFICATION_EMAIL', '(nicht konfiguriert)')
        smtp_host = getattr(config, 'NOTIFICATION_SMTP_HOST', 'smtp.example.invalid')
        smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', '')
        events = getattr(config, 'NOTIFICATION_EVENTS', [])
        thresholds = getattr(config, 'EVENT_THRESHOLDS', {})

        # Passwort-Status
        pw_status = '✓ gesetzt' if credential_store.existiert('smtp_pass') else '✗ FEHLT'

        # Status-Text
        lines = [f'Empfänger:  {email}',
                 f'SMTP:       {smtp_host}:{getattr(config, "NOTIFICATION_SMTP_PORT", 465)}',
                 f'Benutzer:   {smtp_user}',
                 f'Passwort:   {pw_status} (verschlüsselt in /etc/pv-system/)',
                 '',
                 'Aktive Events:']
        if events:
            for ev in events:
                t = thresholds.get(ev, {})
                text = t.get('text', ev)
                feld = t.get('obs_feld', '?')
                op = t.get('op', '?')
                sw = t.get('schwelle', '?')
                lines.append(f'  ✓ {ev}: {text} ({feld} {op} {sw})')
        else:
            lines.append('  (keine)')
        lines.append('')
        lines.append('Verfügbare Events:')
        for key, t in thresholds.items():
            marker = '✓' if key in events else '○'
            lines.append(f'  {marker} {key}: {t.get("text", key)}')

        body = '\n'.join(lines)

        choice = wt_menu(body, [
            ('1', 'Events ein/ausschalten'),
            ('2', 'Test-Mail senden'),
            ('3', 'Empfänger ändern'),
            ('4', 'SMTP-Passwort setzen'),
            ('z', 'Zurück'),
        ])

        if choice is None or choice == 'z':
            break

        elif choice == '1':
            _menu_benachrichtigung_events(thresholds, events)

        elif choice == '2':
            _menu_benachrichtigung_test(email, smtp_host)

        elif choice == '3':
            _menu_benachrichtigung_email()

        elif choice == '4':
            _menu_benachrichtigung_password()


def _menu_benachrichtigung_events(thresholds: dict, aktive: list):
    """Events ein/ausschalten (Checklist)."""
    args = ['--checklist', 'Events ein/ausschalten:',
            str(WT_H), str(WT_W), str(WT_LIST_H)]
    for key, t in thresholds.items():
        text = t.get('text', key)
        status = 'ON' if key in aktive else 'OFF'
        args.extend([key, text, status])
    rc, selected = _wt(args)
    if rc != 0:
        return
    # Ergebnis: "key1" "key2" ... → parsen
    neue_events = [s.strip('"') for s in selected.split() if s.strip('"')]
    # config.py aktualisieren
    _update_config_line('NOTIFICATION_EVENTS', repr(neue_events))
    # Live-Objekt aktualisieren
    config.NOTIFICATION_EVENTS = neue_events
    wt_msgbox(f'Events aktualisiert:\n\n{", ".join(neue_events) or "(keine)"}')


def _menu_benachrichtigung_test(email: str, smtp_host: str):
    """Test-Mail senden — über konfigurierten SMTP-Server mit verschlüsseltem Passwort."""
    if not email:
        wt_msgbox('Kein Empfänger konfiguriert.\n\nBitte zuerst Empfänger setzen.')
        return

    from automation.engine import credential_store
    smtp_pass = credential_store.lade('smtp_pass')
    smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', '')

    if smtp_user and not smtp_pass:
        wt_msgbox('SMTP-Passwort nicht gesetzt.\n\n'
                   'Bitte zuerst über Menüpunkt 4 setzen.')
        return

    try:
        import smtplib
        from email.mime.text import MIMEText
        import socket

        hostname = socket.gethostname()
        sender = getattr(config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
        port = getattr(config, 'NOTIFICATION_SMTP_PORT', 465)

        msg = MIMEText(
            f'Test-Mail von {hostname}\n\n'
            f'E-Mail-Versand funktioniert.\n'
            f'Konfiguriert für: {email}\n'
            f'SMTP: {smtp_host}:{port} (User: {smtp_user})\n',
            'plain', 'utf-8'
        )
        msg['Subject'] = '[PV-Automation] Test-Mail'
        msg['From'] = sender
        msg['To'] = email

        if port == 465:
            smtp = smtplib.SMTP_SSL(smtp_host, port, timeout=15)
        else:
            smtp = smtplib.SMTP(smtp_host, port, timeout=15)
            if port == 587:
                smtp.starttls()

        if smtp_user and smtp_pass:
            smtp.login(smtp_user, smtp_pass)

        smtp.sendmail(sender, [email], msg.as_string())
        smtp.quit()
        wt_msgbox(f'Test-Mail gesendet an:\n{email}\n\nSMTP: {smtp_host}:{port}')
    except Exception as e:
        wt_msgbox(f'Fehler beim Senden:\n\n{str(e)[:300]}')


def _menu_benachrichtigung_email():
    """Empfänger-Adresse ändern."""
    aktuell = getattr(config, 'NOTIFICATION_EMAIL', '')
    rc, neue = _wt(['--inputbox', 'E-Mail-Adresse für Benachrichtigungen:',
                     '10', str(WT_W), aktuell])
    if rc != 0 or not neue.strip():
        return
    neue = neue.strip()
    _update_config_line('NOTIFICATION_EMAIL', repr(neue))
    config.NOTIFICATION_EMAIL = neue
    wt_msgbox(f'Empfänger gesetzt:\n{neue}')


def _menu_benachrichtigung_password():
    """SMTP-Passwort verschlüsselt speichern (Machine-ID-gebunden).

    Das Passwort wird NICHT in config.py abgelegt, sondern
    AES-verschlüsselt in /etc/pv-system/smtp_pass.key.
    Entschlüsselung nur auf diesem Pi möglich.
    """
    from automation.engine import credential_store

    aktuell_status = 'gesetzt' if credential_store.existiert('smtp_pass') else 'nicht gesetzt'
    smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', 'alerts@example.invalid')

    rc, passwort = _wt([
        '--passwordbox',
        f'SMTP-Passwort für {smtp_user}\n'
        f'(aktuell: {aktuell_status})\n\n'
        f'Das Passwort wird AES-verschlüsselt in\n'
        f'/etc/pv-system/smtp_pass.key gespeichert.\n'
        f'Entschlüsselung nur auf diesem Pi möglich.',
        '16', str(WT_W),
    ])
    if rc != 0 or not passwort.strip():
        return

    passwort = passwort.strip()

    try:
        pfad = credential_store.speichere('smtp_pass', passwort)
        wt_msgbox(
            f'SMTP-Passwort verschlüsselt gespeichert:\n'
            f'{pfad}\n\n'
            f'Verschlüsselung: AES-128 (Fernet)\n'
            f'Schlüssel: Machine-ID-gebunden (PBKDF2)\n\n'
            f'Tipp: Test-Mail senden um Zustellung zu prüfen.'
        )
    except PermissionError:
        wt_msgbox(
            'Fehler: Keine Schreibrechte auf /etc/pv-system/.\n\n'
            'pv-config muss als root laufen:\n'
            '  sudo python3 pv-config.py'
        )
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern:\n\n{str(e)[:300]}')


def _update_config_line(key: str, new_value: str):
    """Einzelne Zeile in config.py aktualisieren (Key = Value)."""
    config_path = os.path.join(PROJECT_ROOT, 'config.py')
    try:
        with open(config_path, 'r') as f:
            lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key} ') or line.startswith(f'{key}='):
                lines[i] = f'{key} = {new_value}\n'
                found = True
                break
        if not found:
            lines.append(f'{key} = {new_value}\n')
        with open(config_path, 'w') as f:
            f.writelines(lines)
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern von config.py:\n\n{str(e)[:200]}')


def menu_handbuch():
    """PV-Config-Handbuch im Scroll-Dialog anzeigen."""
    if not os.path.exists(HANDBUCH_PATH):
        wt_msgbox(
            'Handbuch nicht gefunden:\n\n'
            f'{HANDBUCH_PATH}\n\n'
            'Bitte prüfen, ob die Datei im Repository vorhanden ist.'
        )
        return
    wt_textbox(HANDBUCH_PATH)


# ═══════════════════════════════════════════════════════════════
# Hauptmenü
# ═══════════════════════════════════════════════════════════════

def hauptmenu():
    """Hauptmenü-Loop."""
    while True:
        backtitle = _status_backtitle()
        body = _status_menu_body()

        args = ['--menu', body, str(WT_H), str(WT_W), str(WT_LIST_H)]
        for tag, desc in [
            ('1', 'Regelkreise ein/ausschalten'),
            ('2', 'Parameter-Matrix bearbeiten'),
            ('3', 'Batterie-Scheduler'),
            ('4', 'System-Status & Warnungen'),
            ('5', 'Solar-Prognose'),
            ('6', 'Heizpatrone (Fritz!DECT)'),
            ('7', 'Schalt-Logbuch'),
            ('8', 'Benachrichtigungen (E-Mail)'),
            ('9', 'Handbuch anzeigen'),
            ('q', 'Beenden'),
        ]:
            args.extend([tag, desc])
        rc, choice = _wt(args, backtitle=backtitle)

        if rc != 0 or choice == 'q':
            print('\npv-config beendet.\n')
            break

        if choice == '1':
            menu_regelkreise()
        elif choice == '2':
            menu_parameter()
        elif choice == '3':
            menu_scheduler()
        elif choice == '4':
            menu_system()
        elif choice == '5':
            menu_forecast()
        elif choice == '6':
            menu_heizpatrone()
        elif choice == '7':
            menu_schaltlog()
        elif choice == '8':
            menu_benachrichtigung()
        elif choice == '9':
            menu_handbuch()


# ═══════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════

def main():
    """Einstiegspunkt mit Vorprüfungen."""
    # Whiptail vorhanden?
    if not os.path.exists('/usr/bin/whiptail'):
        print('Fehler: whiptail nicht installiert.')
        print('  sudo apt install whiptail')
        sys.exit(1)

    # Terminal-Check
    if not sys.stdout.isatty():
        print('Fehler: pv-config benötigt ein interaktives Terminal.')
        print('  ssh user@host → python3 pv-config.py')
        sys.exit(1)

    # DB erreichbar?
    if not os.path.exists(config.DB_PATH):
        print(f'Warnung: DB nicht gefunden ({config.DB_PATH})')
        print('Status-Anzeige eingeschränkt.\n')

    # Matrix lesbar?
    try:
        lade_matrix()
    except FileNotFoundError:
        print('Fehler: Parametermatrix nicht gefunden.')
        print(f'  Erwartet: {DEFAULT_MATRIX_PATH}')
        sys.exit(1)

    hauptmenu()


if __name__ == '__main__':
    main()
