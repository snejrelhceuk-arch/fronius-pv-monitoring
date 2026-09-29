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

import logging
import time
import urllib.request
from typing import Optional

from automation.engine.aktoren.aktor_batterie import AktorBase
from fritzdect_read import (
    aha_device_info as _aha_device_info,
    get_session_id as _get_session_id,
    load_fritz_config as _load_fritz_config,
    reset_fritz_session_cache,
)

LOG = logging.getLogger('aktor.fritzdect')


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


class AktorFritzDECT(AktorBase):
    """Heizpatrone via Fritz!DECT-Steckdose (AHA-HTTP-API).

        Kommandos:
            hp_ein     — setswitchon  (Heizpatrone EIN)
            hp_aus     — setswitchoff (Heizpatrone AUS)
            klima_ein  — setswitchon  (Klimaanlage EIN)
            klima_aus  — setswitchoff (Klimaanlage AUS)
            lueftung_ein — setswitchon  (Lueftung EIN)
            lueftung_aus — setswitchoff (Lueftung AUS)
            fbh_ein    — setswitchon  (Fussbodenheizung EIN)
            fbh_aus    — setswitchoff (Fussbodenheizung AUS)
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
        # Fussbodenheizung (Bad-FBH-Pumpe): nur Nacht-Schaltung für Regelmäßigkeit
        'fbh_ein': ('setswitchon', 'fussbodenheizung'),
        'fbh_aus': ('setswitchoff', 'fussbodenheizung'),
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
                    reset_fritz_session_cache()
                    time.sleep(self.RETRY_DELAY)
                    continue
                return None

            result = _aha_command(host, ain, sid, aha_cmd)
            if result is not None:
                return result

            # Bei Fehler: Session-Cache invalidieren, Retry
            if attempt < self.MAX_RETRIES:
                LOG.warning(f"AHA-Befehl Retry {attempt + 1}")
                reset_fritz_session_cache()
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

        sid = self._get_sid()
        if not sid:
            return {'state': None, 'power_mw': None, 'energy_wh': None,
                    'name': None, 'erreichbar': False}

        # 1 Bulk-Request statt 4 Einzelne
        info = _aha_device_info(host, ain, sid)
        if info is not None:
            return info

        # Fallback bei ungültiger SID: einmal Retry
        reset_fritz_session_cache()
        sid = self._get_sid()
        if sid:
            info = _aha_device_info(host, ain, sid)
            if info is not None:
                return info

        return {'state': None, 'power_mw': None, 'energy_wh': None,
                'name': None, 'erreichbar': False}

    def close(self):
        """Cleanup — nichts zu tun (HTTP, kein persistenter Socket)."""
        reset_fritz_session_cache()
