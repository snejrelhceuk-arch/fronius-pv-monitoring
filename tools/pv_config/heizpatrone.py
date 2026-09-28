#!/usr/bin/env python3
"""
tools/pv_config/heizpatrone.py — Heizpatrone-/Fritz!DECT-Menue fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-09-28): Fritz!Box-Config
(Credentials aus .secrets), AHA-HTTP-API (SID-Cache, Schalten, Bulk-Status) und
das HP-Menue (Status, Verbindungstest, manuelles EIN/AUS, Schwellwerte).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import date
from typing import Optional

import config
from automation.engine.param_matrix import lade_matrix
from tools.pv_config.common import (
    PROJECT_ROOT,
    wt_menu, wt_inputbox, wt_yesno, wt_msgbox,
)
from tools.pv_config.service import _fix_ownership
from tools.pv_config.matrix_editor import _menu_regelkreis_detail


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
