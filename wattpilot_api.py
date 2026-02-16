#!/usr/bin/env python3
"""
wattpilot_api.py — Fronius Wattpilot WebSocket API Client
==========================================================
Wiederverwendbares Modul für Wattpilot-Zugriff per WebSocket.

Liest Zählerstand (eto), Live-Status, Session-Daten und
Geräteinformationen über die lokale WebSocket-Schnittstelle.

Authentifizierung: PBKDF2-HMAC-SHA512 + SHA256 Challenge-Response
(identisch zur joscha82/wattpilot Library).

Nutzung:
  from wattpilot_api import WattpilotClient

  client = WattpilotClient()
  status = client.read_status()
  print(status['eto'])         # Gesamt-Energie in Wh
  print(status['car'])         # Auto-Status (1=Idle, 2=Charging, ...)
  print(status['nrg'])         # Live-Messwerte

Autor: PV-Anlage Monitoring
Datum: 2026-02-10
"""

import asyncio
import json
import hashlib
import base64
import os
import sys
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# --- Konfiguration (Defaults, überschreibbar via config.py) ---
DEFAULT_IP = "192.168.2.197"
DEFAULT_TIMEOUT = 10

# Auto-Status Mapping
CAR_STATES = {
    0: 'Unbekannt',
    1: 'Bereit (kein Auto)',
    2: 'Lädt',
    3: 'Warte auf Auto',
    4: 'Vollständig',
    5: 'Fehler'
}

# Lademodus Mapping
CHARGE_MODES = {
    3: 'Standard',
    4: 'Eco (PV-Überschuss)',
    5: 'Nächste Fahrt'
}


def _load_password():
    """Passwort aus Umgebungsvariable oder .secrets-Datei laden."""
    try:
        from config import load_secret
        pw = load_secret('WATTPILOT_PASSWORD')
    except ImportError:
        pw = os.environ.get('WATTPILOT_PASSWORD')
    if pw:
        return pw
    raise RuntimeError(
        "Kein Wattpilot-Passwort gefunden! "
        "Setze WATTPILOT_PASSWORD in Umgebungsvariable oder .secrets"
    )


def _compute_auth(serial: str, password: str, token1: str, token2: str):
    """
    Wattpilot Auth-Hash berechnen (PBKDF2 + SHA256 Challenge-Response).
    
    Exakt nach joscha82/wattpilot Library:
    1. PBKDF2-HMAC-SHA512(password, serial, 100000, 256 bytes) -> base64 -> [:32]
    2. hash1 = SHA256(token1_bytes + hashed_password_bytes)
    3. token3 = random 32 hex chars
    4. hash  = SHA256((token3 + token2 + hash1).encode())
    """
    import random

    # Schritt 1: Passwort-Hash
    dk = hashlib.pbkdf2_hmac('sha512', password.encode(), serial.encode(), 100000, 256)
    hashed_pw = base64.b64encode(dk)[:32]  # bytes, 32 Zeichen

    # Schritt 2: token3 generieren
    ran = random.randrange(10**80)
    token3 = "%064x" % ran
    token3 = token3[:32]

    # Schritt 3: hash1
    hash1 = hashlib.sha256((token1.encode() + hashed_pw)).hexdigest()

    # Schritt 4: final hash
    final_hash = hashlib.sha256((token3 + token2 + hash1).encode()).hexdigest()

    return token3, final_hash


class WattpilotClient:
    """
    Fronius Wattpilot WebSocket Client.
    
    Verbindet sich per WebSocket, authentifiziert und liest den vollständigen Status.
    """
    
    def __init__(self, ip=None, timeout=None, password=None):
        """
        Args:
            ip: Wattpilot IP-Adresse (Default: aus config oder 192.168.2.197)
            timeout: WebSocket Timeout in Sekunden (Default: 10)
            password: Passwort (Default: aus .secrets oder Umgebungsvariable)
        """
        try:
            import config as cfg
            self.ip = ip or getattr(cfg, 'WATTPILOT_IP', DEFAULT_IP)
            self.timeout = timeout or getattr(cfg, 'WATTPILOT_TIMEOUT', DEFAULT_TIMEOUT)
        except ImportError:
            self.ip = ip or DEFAULT_IP
            self.timeout = timeout or DEFAULT_TIMEOUT
        
        self._password = password
        self._last_status = None
        self._last_hello = None
        self._last_read_time = None
    
    def _get_password(self):
        """Lazily load password."""
        if self._password is None:
            self._password = _load_password()
        return self._password
    
    async def _read_async(self):
        """Async WebSocket-Verbindung zum Wattpilot.
        
        HINWEIS: Wattpilot erlaubt nur EINE WebSocket-Verbindung gleichzeitig.
        Externe Apps (go-e App, Fronius App) können die Verbindung verdrängen.
        Bei ConnectionRefusedError/ConnectionResetError: Verbindung ist belegt.
        """
        try:
            import websockets
        except ImportError:
            raise ImportError("websockets nicht installiert: pip3 install websockets")
        
        uri = f"ws://{self.ip}/ws"
        logger.debug(f"Verbinde mit {uri} ...")
        
        try:
            async with websockets.connect(uri, open_timeout=self.timeout) as ws:
                # 1) Hello
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                hello = json.loads(raw)
                if hello.get('type') != 'hello':
                    raise RuntimeError(f"Unerwartete Antwort statt hello: {hello.get('type')}")
                
                serial = hello.get('serial', '')
                self._last_hello = hello
                
                # 2) AuthRequired
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                auth_req = json.loads(raw)
                if auth_req.get('type') != 'authRequired':
                    raise RuntimeError(f"Kein authRequired erhalten: {auth_req.get('type')}")
                
                token1 = auth_req['token1']
                token2 = auth_req['token2']
                
                # 3) Auth senden
                password = self._get_password()
                token3, auth_hash = _compute_auth(serial, password, token1, token2)
                await ws.send(json.dumps({
                    "type": "auth",
                    "token3": token3,
                    "hash": auth_hash
                }))
                
                # 4) Auth-Ergebnis + Status sammeln
                full_status = {}
                msg_count = 0
                
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        break
                    
                    msg = json.loads(raw)
                    msg_type = msg.get('type', '')
                    
                    if msg_type == 'authError':
                        raise RuntimeError(f"Authentifizierung fehlgeschlagen: {msg.get('message', '?')}")
                    elif msg_type == 'authSuccess':
                        logger.debug("Auth erfolgreich")
                    elif msg_type in ('fullStatus', 'deltaStatus'):
                        full_status.update(msg.get('status', {}))
                        msg_count += 1
                        if msg_type == 'fullStatus' and not msg.get('partial', True):
                            break
                
                logger.debug(f"{msg_count} Status-Nachrichten, {len(full_status)} Properties")
                
                self._last_status = full_status
                self._last_read_time = datetime.now()
                
                return full_status
        except ConnectionRefusedError:
            raise ConnectionRefusedError(
                f"WebSocket {uri} verweigert — vermutlich externe App (go-e/Fronius) aktiv")
        except ConnectionResetError:
            raise ConnectionResetError(
                f"WebSocket {uri} zurückgesetzt — Verbindung durch andere App verdrängt")
        except OSError as e:
            if 'Connection refused' in str(e) or 'Connection reset' in str(e):
                raise ConnectionRefusedError(f"WebSocket {uri} nicht verfügbar: {e}")
            raise
    
    def read_status(self):
        """
        Liest den vollständigen Wattpilot-Status (synchroner Aufruf).
        
        Returns:
            dict: Alle Wattpilot-Properties (eto, car, nrg, tmp, etc.)
        
        Raises:
            RuntimeError: Bei Verbindungs- oder Auth-Fehlern
            TimeoutError: Bei Timeout
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Falls bereits in async context (z.B. Flask mit async)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._read_async())
                    return future.result(timeout=self.timeout + 5)
            else:
                return loop.run_until_complete(self._read_async())
        except RuntimeError:
            # Kein Event Loop vorhanden
            return asyncio.run(self._read_async())
    
    def get_energy_total_wh(self):
        """
        Liest den Gesamt-Zählerstand in Wh.
        
        Returns:
            float: Gesamt-Energie in Wh (seit Inbetriebnahme)
        """
        status = self.read_status()
        eto = status.get('eto')
        if eto is None:
            raise RuntimeError("Zählerstand (eto) nicht verfügbar")
        return float(eto)
    
    def get_energy_total_kwh(self):
        """Gesamt-Zählerstand in kWh."""
        return self.get_energy_total_wh() / 1000.0
    
    def get_live_power_w(self):
        """
        Aktuelle Ladeleistung in Watt.
        
        Returns:
            float: Leistung in W (oder 0 wenn nicht laden)
        """
        status = self._last_status or self.read_status()
        nrg = status.get('nrg', [])
        if nrg and len(nrg) >= 12:
            return float(nrg[11])  # P_Total
        return float(status.get('tpa', 0) or 0)
    
    def get_status_summary(self):
        """
        Gibt eine kompakte Zusammenfassung des Wattpilot-Status zurück.
        
        Returns:
            dict: {
                'online': bool,
                'car_state': int,
                'car_state_text': str,
                'charging': bool,
                'power_w': float,
                'energy_total_kwh': float,
                'energy_session_kwh': float,
                'charge_current_a': float,
                'max_current_a': float,
                'phase_mode': str,
                'temperature_c': float,
                'rssi_dbm': int,
                'firmware': str,
                'friendly_name': str,
                'serial': str,
                'timestamp': str,
                'charge_mode': str,
                'phases': dict,
                'error': int
            }
        """
        try:
            status = self.read_status()
        except Exception as e:
            return {
                'online': False,
                'error_message': str(e),
                'timestamp': datetime.now().isoformat()
            }
        
        car = status.get('car', 0)
        nrg = status.get('nrg', [])
        
        # Live-Messwerte
        power_total = 0
        phases_info = {}
        if nrg and len(nrg) >= 16:
            power_total = nrg[11]
            phases_info = {
                'u_l1': nrg[0], 'u_l2': nrg[1], 'u_l3': nrg[2],
                'i_l1': nrg[4], 'i_l2': nrg[5], 'i_l3': nrg[6],
                'p_l1': nrg[7], 'p_l2': nrg[8], 'p_l3': nrg[9],
                'pf_l1': nrg[12], 'pf_l2': nrg[13], 'pf_l3': nrg[14],
            }
        
        hello = self._last_hello or {}
        eto = status.get('eto', 0) or 0
        wh = status.get('wh', 0) or 0
        psm = status.get('psm', 0)
        
        return {
            'online': True,
            'car_state': car,
            'car_state_text': CAR_STATES.get(car, f'Unbekannt ({car})'),
            'charging': car == 2,
            'power_w': float(power_total),
            'energy_total_kwh': round(eto / 1000, 3),
            'energy_total_wh': eto,
            'energy_session_kwh': round(wh / 1000, 3),
            'energy_session_wh': wh,
            'charge_current_a': float(status.get('amp', 0) or 0),
            'max_current_a': float(status.get('ama', 0) or 0),
            'phase_mode': '3-phasig' if psm == 2 else '1-phasig',
            'phase_mode_raw': psm,
            'temperature_c': float(status.get('tmp', 0) or 0),
            'rssi_dbm': status.get('rssi', 0),
            'firmware': hello.get('version', status.get('fwv', '?')),
            'friendly_name': hello.get('friendly_name', status.get('ffna', '?')),
            'serial': hello.get('serial', status.get('sse', '?')),
            'charge_mode': CHARGE_MODES.get(status.get('lmo', 0), 'Unbekannt'),
            'charge_mode_raw': status.get('lmo', 0),
            'force_state': status.get('frc', 0),
            'error_code': status.get('err', 0),
            'allow_charging': status.get('alw', False),
            'cable_lock': status.get('ust', 0),
            'phases': phases_info,
            'frequency_hz': status.get('fhz', 0),
            'reboot_counter': status.get('rbc', 0),
            'timestamp': datetime.now().isoformat()
        }


# ─── CLI-Modus ──────────────────────────────────────────────

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    args = sys.argv[1:]
    
    client = WattpilotClient()
    
    if '--energy' in args:
        try:
            kwh = client.get_energy_total_kwh()
            print(f"Zählerstand: {kwh:.3f} kWh ({kwh * 1000:.0f} Wh)")
        except Exception as e:
            print(f"FEHLER: {e}")
            sys.exit(1)
    
    elif '--json' in args:
        try:
            summary = client.get_status_summary()
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"FEHLER: {e}")
            sys.exit(1)
    
    else:
        try:
            summary = client.get_status_summary()
            print("\n" + "=" * 55)
            print("  WATTPILOT STATUS")
            print("=" * 55)
            if summary.get('online'):
                print(f"  Gerät:         {summary['friendly_name']}")
                print(f"  Serial:        {summary['serial']}")
                print(f"  Firmware:      {summary['firmware']}")
                print(f"  WLAN:          {summary['rssi_dbm']} dBm")
                print(f"  Temperatur:    {summary['temperature_c']} °C")
                print(f"")
                print(f"  Auto-Status:   {summary['car_state_text']}")
                print(f"  Lademodus:     {summary['charge_mode']}")
                print(f"  Phasen:        {summary['phase_mode']}")
                print(f"  Strom:         {summary['charge_current_a']} A (max {summary['max_current_a']} A)")
                print(f"  Leistung:      {summary['power_w']:.0f} W")
                print(f"")
                print(f"  Session:       {summary['energy_session_kwh']:.3f} kWh")
                print(f"  Zählerstand:   {summary['energy_total_kwh']:.3f} kWh")
            else:
                print(f"  OFFLINE: {summary.get('error_message', 'Nicht erreichbar')}")
            print("=" * 55)
        except Exception as e:
            print(f"FEHLER: {e}")
            sys.exit(1)
