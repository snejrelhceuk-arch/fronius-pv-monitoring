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
import sys
import time
from datetime import datetime, date, timedelta

# ── UTF-8-Resilienz (host-unabhängig) ──────────────────────────
# pv-config ruft whiptail via subprocess; Python kodiert die argv mit
# sys.getfilesystemencoding(). Ist die System-Locale kaputt (z. B.
# LC_ALL=de_DE OHNE .UTF-8 → ISO-8859-1, wie auf frisch aufgesetzten
# Hosts), crasht jedes Unicode-Zeichen (→ ✗ ✓ …) beim fork_exec.
# Statt vom Host abzuhängen, erzwingen wir den UTF-8-Modus per Re-Exec.
if sys.getfilesystemencoding().lower().replace('-', '') != 'utf8':
    if os.environ.get('PYTHONUTF8') != '1':
        os.environ['PYTHONUTF8'] = '1'
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        os.execv(sys.executable, [sys.executable, *sys.argv])

# ── Projekt-Root ermitteln ─────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import config
from automation.engine.param_matrix import (
    lade_matrix, get_param, DEFAULT_MATRIX_PATH,
    classify_forecast_kwh, get_forecast_quality_thresholds,
)

from tools.pv_config.common import (
    BATTERY_CONFIG_PATH, HANDBUCH_PATH,
    WT_H, WT_W, WT_LIST_H,
    _wt, wt_menu, wt_inputbox, wt_yesno, wt_msgbox, wt_textbox,
    _query_one, _query_all,
)
from tools.pv_config.service import _fix_ownership
from tools.pv_config.diagnose import (
    _battery_status, _tagesertrag, _scheduler_state,
    _status_backtitle, _status_menu_body, menu_system,
)
from tools.pv_config.matrix_editor import (
    menu_regelkreise, menu_parameter, _menu_regelkreis_detail,
)
from tools.pv_config.heizpatrone import menu_heizpatrone
from tools.pv_config.benachrichtigung import menu_benachrichtigung
from tools.pv_config.netzkriterien import menu_netzkriterien, menu_imsys_ablesung


# ═══════════════════════════════════════════════════════════════
# Ausgelagert (Architektur-Refactor 2026-06-29) → tools/pv_config/:
#   common.py        — Whiptail-UI, DB-Helfer, Konstanten
#   diagnose.py      — Status-Dashboard, System-/DB-/Service-Status, Warnungen
#   matrix_editor.py — Regelkreise an/aus, Parameter-Matrix bearbeiten/speichern
#   service.py       — Daemon-Reload (SIGHUP), Ownership-Fix
# ═══════════════════════════════════════════════════════════════


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
    rows = _query_all("""
        SELECT ts, kommando, wert, grund, ergebnis
        FROM automation_log
        WHERE aktor = 'batterie'
        ORDER BY ts DESC
        LIMIT 20
    """)

    if not rows:
        wt_msgbox('Keine Scheduler-Aktionen in der DB.')
        return

    tmp = '/tmp/pv_scheduler_log.txt'
    with open(tmp, 'w') as f:
        f.write('BATTERIE-SCHEDULER LOG (automation_log)\n')
        f.write(f'{"═" * 70}\n\n')
        for row in rows:
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
                ('bewertung', 'Bewertungsschwellen bearbeiten'),
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
        elif choice == 'bewertung':
            _forecast_bewertung()


def _forecast_bewertung():
    """Zentrale Forecast-Bewertung anzeigen/bearbeiten."""
    matrix = lade_matrix()
    schlecht_unter, mittel_unter = get_forecast_quality_thresholds(matrix)

    text = f'FORECAST-BEWERTUNG\n{"═" * 50}\n\n'
    text += f'Schlecht:  < {schlecht_unter:.1f} kWh\n'
    text += f'Mittel:    < {mittel_unter:.1f} kWh\n'
    text += f'Gut:       >= {mittel_unter:.1f} kWh\n\n'
    text += 'Die Schwellen liegen in der Parametermatrix und wirken\n'
    text += 'auf SolarForecast, Automation und pv-config.\n\n'
    text += 'Mit OK öffnet sich der Regelkreis forecast_bewertung.'

    wt_msgbox(text)
    _menu_regelkreis_detail('forecast_bewertung')


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
    matrix = lade_matrix()
    quality_eff = classify_forecast_kwh(expected, matrix) if expected is not None else quality
    schlecht_unter, mittel_unter = get_forecast_quality_thresholds(matrix)

    text = f'TAGESPROGNOSE {today}\n{"═" * 50}\n\n'
    text += f'Prognose:   {expected:.1f} kWh\n'
    text += f'Qualitaet:  {quality_eff or quality or "?"}\n'
    text += (f'Schwellen:  schlecht < {schlecht_unter:.0f} | mittel < {mittel_unter:.0f} '
             f'| gut ab {mittel_unter:.0f} kWh\n')
    if quality and quality_eff and quality != quality_eff:
        text += f'DB-Wert:    {quality} (vor aktueller Schwellenlogik gespeichert)\n'
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
# Daemon-Reload nach Param-Änderung
# ═══════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════
# Matrix speichern (atomar)
# ═══════════════════════════════════════════════════════════════





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
            ('n', 'Netzkriterien-Grenzwerte (NQ/PAC4200)'),
            ('i', 'iMSys-Ablesung erfassen (Energievergleich)'),
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
        elif choice == 'n':
            menu_netzkriterien()
        elif choice == 'i':
            menu_imsys_ablesung()


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
