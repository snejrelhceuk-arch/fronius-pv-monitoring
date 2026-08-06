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
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
from typing import Optional

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

def _nq_config_path() -> str:
    return os.path.join(PROJECT_ROOT, 'config', 'nq_config.json')


def _save_nq_config(path: str, cfg: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def menu_netzkriterien():
    """Netzkriterien-Grenzwerte (NQ/PAC4200) bearbeiten -> config/nq_config.json."""
    path = _nq_config_path()
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        wt_msgbox(f'nq_config.json nicht lesbar:\n{str(e)[:200]}')
        return
    gw = cfg.setdefault('grenzwerte', {})
    lv = gw.setdefault('warning_levels', {})
    lvl = gw.setdefault('warning_levels_load', {})

    # (tag, label, container, key)
    fields = [
        ('i_max',  'Strom-Grenze i_max [A]',                 gw,  'i_max_a'),
        ('p_max',  'Leistungs-Grenze p_max [W]',             gw,  'p_max_w'),
        ('u_lo',   'Spannung L-L min [V]',                   gw,  'u_ll_min_v'),
        ('u_hi',   'Spannung L-L max [V]',                   gw,  'u_ll_max_v'),
        ('f_lo',   'Frequenz min [Hz]',                      gw,  'freq_min_hz'),
        ('f_hi',   'Frequenz max [Hz]',                      gw,  'freq_max_hz'),
        ('thd',    'THD-U max [%]',                          gw,  'thd_u_max_pct'),
        ('nw',     'Warnstufe U/f/THD  warn [%]',            lv,  'warn_pct'),
        ('nh',     'Warnstufe U/f/THD  hoch [%]',            lv,  'high_pct'),
        ('nc',     'Warnstufe U/f/THD  kritisch [%]',        lv,  'crit_pct'),
        ('lw',     'Warnstufe Strom/Leistung  warn [%]',     lvl, 'warn_pct'),
        ('lh',     'Warnstufe Strom/Leistung  hoch [%]',     lvl, 'high_pct'),
        ('lc',     'Warnstufe Strom/Leistung  kritisch [%]', lvl, 'crit_pct'),
    ]
    while True:
        items = [(tag, f'{label}  [{cont.get(key, "—")}]') for tag, label, cont, key in fields]
        choice = wt_menu(
            'Netzkriterien-Grenzwerte (PAC4200/NQ)\n\n'
            'Strom + Leistung = Anschlussgroessen (Warnstufen 80/100/120%).\n'
            'Spannung/Frequenz/THD = Norm (Warnstufen 50/70/90%).\n'
            'Wirkt sofort im Netzkriterien-Monitoring (kein Neustart noetig).',
            items,
        )
        if not choice:
            return
        _tag, label, cont, key = next(f for f in fields if f[0] == choice)
        val = wt_inputbox(f'{label}:', str(cont.get(key, '')))
        if val is None:
            continue
        try:
            num = float(val.strip().replace(',', '.'))
        except ValueError:
            wt_msgbox('Ungueltige Zahl.')
            continue
        cont[key] = num
        try:
            _save_nq_config(path, cfg)
        except Exception as e:
            wt_msgbox(f'Speichern fehlgeschlagen:\n{str(e)[:200]}')


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
