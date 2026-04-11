"""
aktor_fritzdect.py — Fritz!DECT-Aktor-Plugin für die Automation-Engine

Steuert die Heizpatrone (2 kW) über eine Fritz!DECT-Steckdose via
Fritz!Box AHA-HTTP-API (Session-ID-Auth, setswitchon/off, getswitchstate).

Unterstützte Kommandos:
    hp_ein     — Heizpatrone einschalten
    hp_aus     — Heizpatrone ausschalten
    klima_ein  — Klimaanlage einschalten
    klima_aus  — Klimaanlage ausschalten

Credentials: .secrets → FRITZ_USER + FRITZ_PASSWORD (wie FRONIUS_PASS)
Config:      config/fritz_config.json → fritz_ip, ain

Siehe: automation/STRATEGIEN.md §2.6, doc/AUTOMATION_ARCHITEKTUR.md §6
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
import config
from automation.engine.aktoren.aktor_batterie import AktorBase

LOG = logging.getLogger('aktor.fritzdect')

FRITZ_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config', 'fritz_config.json')

# Session-ID Cache (gültig für ~20 Min bei Fritz!Box)
_sid_cache: dict = {'sid': None, 'ts': 0}
_SID_TTL = 900  # 15 Min — konservativ unter Fritz!Box-Timeout


def _load_fritz_config() -> dict:
    """Fritz-Config aus JSON + Credentials aus .secrets."""
    cfg = {}
    if os.path.exists(FRITZ_CONFIG_PATH):
        try:
            with open(FRITZ_CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception as e:
            LOG.warning(f"fritz_config.json nicht lesbar: {e}")
    cfg['fritz_user'] = config.load_secret('FRITZ_USER') or ''
    cfg['fritz_password'] = config.load_secret('FRITZ_PASSWORD') or ''
    return cfg


def _get_session_id(host: str, user: str, password: str) -> Optional[str]:
    """Fritz!Box Session-ID holen (AHA-HTTP-API login_sid.lua).

    Cached für _SID_TTL Sekunden.
    """
    global _sid_cache

    # Cache gültig?
    if _sid_cache['sid'] and (time.time() - _sid_cache['ts']) < _SID_TTL:
        return _sid_cache['sid']

    if not user or not password:
        LOG.error("FRITZ_USER oder FRITZ_PASSWORD nicht in .secrets gesetzt")
        return None

    try:
        # Challenge holen
        url = f'http://{host}/login_sid.lua'
        resp = urllib.request.urlopen(url, timeout=5)
        xml_text = resp.read().decode('utf-8')
        root = ET.fromstring(xml_text)
        sid = root.findtext('SID')
        challenge = root.findtext('Challenge')

        if sid and sid != '0000000000000000':
            _sid_cache = {'sid': sid, 'ts': time.time()}
            return sid

        # Response berechnen: challenge-password (UTF-16LE, MD5)
        response = f'{challenge}-{password}'.encode('utf-16-le')
        md5 = hashlib.md5(response).hexdigest()
        login_response = f'{challenge}-{md5}'

        url2 = f'http://{host}/login_sid.lua?username={user}&response={login_response}'
        resp2 = urllib.request.urlopen(url2, timeout=5)
        xml_text2 = resp2.read().decode('utf-8')
        root2 = ET.fromstring(xml_text2)
        sid = root2.findtext('SID')

        if sid == '0000000000000000':
            LOG.error("Fritz!Box Login fehlgeschlagen (falsche Credentials?)")
            return None

        _sid_cache = {'sid': sid, 'ts': time.time()}
        return sid

    except Exception as e:
        LOG.error(f"Fritz!Box Session-ID Fehler: {e}")
        _sid_cache = {'sid': None, 'ts': 0}
        return None


def _aha_command(host: str, ain: str, sid: str, cmd: str) -> Optional[str]:
    """AHA-HTTP-API Befehl senden und Antwort lesen."""
    ain_clean = ain.replace(' ', '')
    url = (f'http://{host}/webservices/homeautoswitch.lua'
           f'?ain={ain_clean}&switchcmd={cmd}&sid={sid}')
    try:
        resp = urllib.request.urlopen(url, timeout=8)
        return resp.read().decode('utf-8').strip()
    except Exception as e:
        LOG.error(f"AHA-Befehl '{cmd}' fehlgeschlagen: {e}")
        return None


def _aha_device_info(host: str, ain: str, sid: str) -> Optional[dict]:
    """Alle Infos für ein Gerät in EINEM Request via getdevicelistinfos.

    Parsed das XML und extrahiert state, power, energy, name
    für die angegebene AIN. Spart 3 Extra-Requests gegenüber
    4× getswitch*-Einzelabfragen.
    """
    url = (f'http://{host}/webservices/homeautoswitch.lua'
           f'?switchcmd=getdevicelistinfos&sid={sid}')
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        xml_text = resp.read().decode('utf-8')
        root = ET.fromstring(xml_text)
    except Exception as e:
        LOG.error(f"getdevicelistinfos fehlgeschlagen: {e}")
        return None

    # AIN normalisieren (Fritz!Box liefert mit/ohne Leerzeichen)
    ain_norm = ain.replace(' ', '').strip()

    for device in root.findall('device'):
        dev_ain = (device.get('identifier') or '').replace(' ', '').strip()
        if dev_ain != ain_norm:
            continue

        # present ist ein Kind-Element, kein Attribut!
        present_el = device.find('present')
        is_present = (present_el is not None
                      and present_el.text is not None
                      and present_el.text.strip() == '1')

        result = {
            'state': None,
            'power_mw': None,
            'energy_wh': None,
            'name': None,
            'erreichbar': is_present,
        }

        name_el = device.find('name')
        if name_el is not None and name_el.text:
            result['name'] = name_el.text.strip()

        sw = device.find('switch')
        if sw is not None:
            state_el = sw.find('state')
            if state_el is not None and state_el.text is not None:
                result['state'] = state_el.text.strip()  # '0'|'1'

        pm = device.find('powermeter')
        if pm is not None:
            power_el = pm.find('power')
            if power_el is not None and power_el.text:
                try:
                    result['power_mw'] = int(power_el.text)  # Milliwatt
                except ValueError:
                    pass
            energy_el = pm.find('energy')
            if energy_el is not None and energy_el.text:
                try:
                    result['energy_wh'] = int(energy_el.text)  # Wh
                except ValueError:
                    pass


        # Temperatur extrahieren (falls vorhanden)
        temp_el = device.find('temperature')
        if temp_el is not None:
            celsius_el = temp_el.find('celsius')
            if celsius_el is not None and celsius_el.text:
                try:
                    # Fritz!Box liefert Temperatur in 0.1°C
                    result['temperature'] = float(celsius_el.text) / 10.0
                except Exception:
                    pass

        return result

    LOG.warning(f"AIN '{ain}' nicht in getdevicelistinfos gefunden")
    return None


class AktorFritzDECT(AktorBase):
    """Heizpatrone via Fritz!DECT-Steckdose (AHA-HTTP-API).

        Kommandos:
            hp_ein     — setswitchon  (Heizpatrone EIN)
            hp_aus     — setswitchoff (Heizpatrone AUS)
            klima_ein  — setswitchon  (Klimaanlage EIN)
            klima_aus  — setswitchoff (Klimaanlage AUS)
            lueftung_ein — setswitchon  (Lueftung EIN)
            lueftung_aus — setswitchoff (Lueftung AUS)
    """

    name = 'fritzdect'
    MAX_RETRIES = 2
    RETRY_DELAY = 2.0

    _KOMMANDOS = {
        'hp_ein': ('setswitchon', 'heizpatrone'),
        'hp_aus': ('setswitchoff', 'heizpatrone'),
        'klima_ein': ('setswitchon', 'klimaanlage'),
        'klima_aus': ('setswitchoff', 'klimaanlage'),
        # Lueftung: AIN 00000 0000000 (device_id lueftung)
        'lueftung_ein': ('setswitchon', 'lueftung'),
        'lueftung_aus': ('setswitchoff', 'lueftung'),
    }

    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        self._cfg = _load_fritz_config()

    def _reload_config(self):
        """Config neu laden (z.B. nach Änderung in pv-config)."""
        self._cfg = _load_fritz_config()

    def _get_ain(self, device_id: str = 'heizpatrone') -> str:
        """AIN eines Geräts aus geraete[]-Array holen.

        Fallback auf Legacy-Top-Level 'ain' nur für Heizpatrone.
        """
        if device_id == 'heizpatrone':
            ain_legacy = self._cfg.get('ain', '')
            if ain_legacy:
                return ain_legacy

        for g in self._cfg.get('geraete', []):
            if str(g.get('id', '')).lower() == str(device_id).lower():
                return g.get('ain', '')
        return ''

    def _get_sid(self) -> Optional[str]:
        """Session-ID holen (cached)."""
        return _get_session_id(
            self._cfg.get('fritz_ip', '192.168.178.1'),
            self._cfg.get('fritz_user', ''),
            self._cfg.get('fritz_password', ''),
        )

    def _switch(self, aha_cmd: str, device_id: str = 'heizpatrone') -> Optional[str]:
        """AHA-Schaltbefehl mit Retry."""
        global _sid_cache
        host = self._cfg.get('fritz_ip', '192.168.178.1')
        ain = self._get_ain(device_id)

        if not ain:
            LOG.error(f"Keine AIN konfiguriert für Gerät '{device_id}' (config/fritz_config.json)")
            return None

        for attempt in range(self.MAX_RETRIES + 1):
            sid = self._get_sid()
            if not sid:
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"Fritz!Box Login Retry {attempt + 1}")
                    _sid_cache = {'sid': None, 'ts': 0}
                    time.sleep(self.RETRY_DELAY)
                    continue
                return None

            result = _aha_command(host, ain, sid, aha_cmd)
            if result is not None:
                return result

            # Bei Fehler: Session-Cache invalidieren, Retry
            if attempt < self.MAX_RETRIES:
                LOG.warning(f"AHA-Befehl Retry {attempt + 1}")
                _sid_cache = {'sid': None, 'ts': 0}
                time.sleep(self.RETRY_DELAY)

        return None

    # ── AktorBase Interface ──────────────────────────────────

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine Fritz!DECT-Aktion aus.

        Args:
            aktion: dict mit 'kommando' (hp_ein|hp_aus|klima_ein|klima_aus|lueftung_ein|lueftung_aus), optional 'grund'

        Returns:
            dict mit 'ok': bool, 'kommando': str, 'detail': str
        """
        kommando = aktion.get('kommando', '')
        grund = aktion.get('grund', '')

        mapping = self._KOMMANDOS.get(kommando)
        if not mapping:
            LOG.error(f"Unbekanntes Kommando: {kommando}")
            return {'ok': False, 'kommando': kommando,
                    'detail': f'Unbekanntes Kommando: {kommando}'}
        aha_cmd, device_id = mapping

        LOG.info(f"Fritz!DECT: {kommando} ({device_id}, AHA: {aha_cmd}) — {grund}")

        if self.dry_run:
            LOG.info(f"  [DRY-RUN] Würde ausführen: {aha_cmd}")
            return {'ok': True, 'kommando': kommando, 'detail': '[DRY-RUN]'}

        result = self._switch(aha_cmd, device_id=device_id)

        if result is None:
            LOG.error(f"Fritz!DECT {kommando} fehlgeschlagen")
            return {'ok': False, 'kommando': kommando,
                    'detail': f'FEHLER: {grund}'}

        # Prüfe Ergebnis: setswitchon → '1', setswitchoff → '0'
        erwartet = '1' if kommando.endswith('_ein') else '0'
        ok = result == erwartet

        if ok:
            LOG.info(f"  Fritz!DECT {kommando} OK (Antwort: {result})")
        else:
            LOG.warning(f"  Fritz!DECT {kommando} Antwort unerwartet: "
                        f"'{result}' (erwartet: '{erwartet}')")

        return {
            'ok': ok,
            'kommando': kommando,
            'wert': result,
            'detail': f"{'OK' if ok else 'UNERWARTET'}: {grund}",
        }

    def verifiziere(self, aktion: dict) -> dict:
        """Read-Back: Aktuellen Schaltzustand abfragen."""
        kommando = aktion.get('kommando', '')
        mapping = self._KOMMANDOS.get(kommando)
        if not mapping:
            return {'ok': False, 'grund': f'Unbekanntes Kommando: {kommando}'}
        _, device_id = mapping
        erwartet = '1' if kommando.endswith('_ein') else '0'

        result = self._switch('getswitchstate', device_id=device_id)
        if result is None:
            return {'ok': False, 'grund': 'Fritz!Box nicht erreichbar'}

        ok = result == erwartet
        return {
            'ok': ok,
            'ist': result,
            'soll': erwartet,
            'ist_text': 'EIN' if result == '1' else 'AUS',
        }

    def get_status(self) -> dict:
        """Aktuellen Status der Fritz!DECT-Steckdose abfragen.

        Verwendet getdevicelistinfos (1 Request statt 4 Einzelabfragen).
        Fritz!Box ist langsam (~1-2s pro Request) — Bulk spart ~6s.

        Returns:
            dict mit state, power_mw, energy_wh, name, erreichbar
        """
        host = self._cfg.get('fritz_ip', '192.168.178.1')
        ain = self._get_ain()

        if not ain:
            LOG.error("Keine AIN konfiguriert (config/fritz_config.json)")
            return {'state': None, 'power_mw': None, 'energy_wh': None,
                    'name': None, 'erreichbar': False}

        global _sid_cache
        sid = self._get_sid()
        if not sid:
            return {'state': None, 'power_mw': None, 'energy_wh': None,
                    'name': None, 'erreichbar': False}

        # 1 Bulk-Request statt 4 Einzelne
        info = _aha_device_info(host, ain, sid)
        if info is not None:
            return info

        # Fallback bei ungültiger SID: einmal Retry
        _sid_cache = {'sid': None, 'ts': 0}
        sid = self._get_sid()
        if sid:
            info = _aha_device_info(host, ain, sid)
            if info is not None:
                return info

        return {'state': None, 'power_mw': None, 'energy_wh': None,
                'name': None, 'erreichbar': False}

    def close(self):
        """Cleanup — nichts zu tun (HTTP, kein persistenter Socket)."""
        global _sid_cache
        _sid_cache = {'sid': None, 'ts': 0}
