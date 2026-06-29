#!/usr/bin/env python3
"""
tools/pv_config/diagnose.py — Diagnose-/Status-Reader fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-06-29): Status-Dashboard,
System-Uebersicht, Warnungen, DB-/Service-Status, Matrix-Validierung (read-only).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, date
from typing import Optional

import config
from automation.engine.param_matrix import (
    lade_matrix, validiere_matrix, alle_regelkreise,
)
from tools.pv_config.common import (
    PROJECT_ROOT, BATTERY_CONFIG_PATH, SCHEDULER_STATE_PATH,
    C_RED, C_GREEN, C_YELLOW,
    wt_menu, wt_msgbox,
    _query_one,
)


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
