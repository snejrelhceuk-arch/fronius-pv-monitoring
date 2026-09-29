"""Read-only Fritz!DECT helpers for Collector/Web/Aggregation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

import config

LOG = logging.getLogger('fritzdect.read')

_PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
FRITZ_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config', 'fritz_config.json')

_sid_cache: dict = {'sid': None, 'ts': 0}
_SID_TTL = 900


def reset_fritz_session_cache() -> None:
    _sid_cache['sid'] = None
    _sid_cache['ts'] = 0


def load_fritz_config() -> dict:
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


def get_session_id(host: str, user: str, password: str) -> Optional[str]:
    if _sid_cache['sid'] and (time.time() - _sid_cache['ts']) < _SID_TTL:
        return _sid_cache['sid']

    if not user or not password:
        LOG.error("FRITZ_USER oder FRITZ_PASSWORD nicht in .secrets gesetzt")
        return None

    try:
        url = f'http://{host}/login_sid.lua'
        resp = urllib.request.urlopen(url, timeout=5)
        xml_text = resp.read().decode('utf-8')
        root = ET.fromstring(xml_text)
        sid = root.findtext('SID')
        challenge = root.findtext('Challenge')

        if sid and sid != '0000000000000000':
            _sid_cache['sid'] = sid
            _sid_cache['ts'] = time.time()
            return sid

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

        _sid_cache['sid'] = sid
        _sid_cache['ts'] = time.time()
        return sid

    except Exception as e:
        LOG.error(f"Fritz!Box Session-ID Fehler: {e}")
        reset_fritz_session_cache()
        return None


def aha_device_info(host: str, ain: str, sid: str) -> Optional[dict]:
    url = (f'http://{host}/webservices/homeautoswitch.lua'
           f'?switchcmd=getdevicelistinfos&sid={sid}')
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        xml_text = resp.read().decode('utf-8')
        root = ET.fromstring(xml_text)
    except Exception as e:
        LOG.error(f"getdevicelistinfos fehlgeschlagen: {e}")
        return None

    ain_norm = ain.replace(' ', '').strip()

    for device in root.findall('device'):
        dev_ain = (device.get('identifier') or '').replace(' ', '').strip()
        if dev_ain != ain_norm:
            continue

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

        temp_el = device.find('temperature')
        if temp_el is not None:
            celsius_el = temp_el.find('celsius')
            if celsius_el is not None and celsius_el.text:
                try:
                    result['temperature'] = float(celsius_el.text) / 10.0
                except Exception:
                    pass

        return result

    LOG.warning(f"AIN '{ain}' nicht in getdevicelistinfos gefunden")
    return None