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
try:
    import config as _cfg
    DEFAULT_IP = _cfg.WATTPILOT_IP
except ImportError:
    DEFAULT_IP = "192.0.2.197"
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
    import secrets

    # Schritt 1: Passwort-Hash
    dk = hashlib.pbkdf2_hmac('sha512', password.encode(), serial.encode(), 100000, 256)
    hashed_pw = base64.b64encode(dk)[:32]  # bytes, 32 Zeichen

    # Schritt 2: token3 generieren
    token3 = secrets.token_hex(16)

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
            ip: Wattpilot IP-Adresse (Default: aus config oder neutralem Platzhalter)
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
        except ImportError as exc:
            raise ImportError("websockets nicht installiert: pip3 install websockets") from exc
        
        uri = f"ws://{self.ip}/ws"
        logger.debug("Verbinde mit %s ...", uri)
        
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
        except ConnectionRefusedError as exc:
            raise ConnectionRefusedError(
                f"WebSocket {uri} verweigert — vermutlich externe App (go-e/Fronius) aktiv") from exc
        except ConnectionResetError as exc:
            raise ConnectionResetError(
                f"WebSocket {uri} zurückgesetzt — Verbindung durch andere App verdrängt") from exc
        except OSError as e:
            if 'Connection refused' in str(e) or 'Connection reset' in str(e):
                raise ConnectionRefusedError(f"WebSocket {uri} nicht verfügbar: {e}") from e
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

    # ── Schreibzugriff (setValue) ─────────────────────────────

    async def _set_value_async(self, key: str, value, timeout_ack: float = 5.0):
        """Einzelnen Wattpilot-Parameter per WebSocket setzen.

        Protokoll (Secured):
          1. Verbinden + Auth
          2. fullStatus abwarten (für hashed_password + secured-Flag)
          3. securedMsg mit HMAC-SHA256 senden (oder plain setValue wenn unsecured)
          4. Auf 'response' mit success=true warten

        Args:
            key:   API-Key (z.B. 'amp', 'psm', 'frc')
            value: Zielwert (int/float/bool)
            timeout_ack: Max. Wartezeit auf Response [s]

        Returns:
            dict: {'ok': True/False, 'key': key, 'value': value, 'detail': ...}
        """
        import hmac as hmac_mod
        try:
            import websockets
        except ImportError as exc:
            raise ImportError("websockets nicht installiert: pip3 install websockets") from exc

        uri = f"ws://{self.ip}/ws"
        logger.info("Wattpilot setValue: %s=%s via %s", key, value, uri)

        try:
            async with websockets.connect(uri, open_timeout=self.timeout) as ws:
                # 1) Hello
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                hello = json.loads(raw)
                if hello.get('type') != 'hello':
                    return {'ok': False, 'key': key, 'detail': f'Kein hello: {hello.get("type")}'}
                serial = hello.get('serial', '')
                secured = hello.get('secured', 0)

                # 2) AuthRequired
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                auth_req = json.loads(raw)
                if auth_req.get('type') != 'authRequired':
                    return {'ok': False, 'key': key, 'detail': f'Kein authRequired: {auth_req.get("type")}'}

                # 3) Auth senden + hashed_password berechnen (für HMAC)
                password = self._get_password()
                token3, auth_hash = _compute_auth(serial, password, auth_req['token1'], auth_req['token2'])
                await ws.send(json.dumps({"type": "auth", "token3": token3, "hash": auth_hash}))

                # Hashed Password für securedMsg (gleiche PBKDF2 wie in _compute_auth)
                dk = hashlib.pbkdf2_hmac('sha512', password.encode(), serial.encode(), 100000, 256)
                hashed_pw = base64.b64encode(dk)[:32]  # 32 Bytes

                # 4) Auth-Ergebnis + fullStatus abwarten
                auth_ok = False
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    mtype = msg.get('type', '')
                    if mtype == 'authError':
                        return {'ok': False, 'key': key, 'detail': f'Auth fehlgeschlagen: {msg}'}
                    if mtype == 'authSuccess':
                        auth_ok = True
                    if mtype == 'fullStatus' and not msg.get('partial', True):
                        break

                if not auth_ok:
                    return {'ok': False, 'key': key, 'detail': 'Auth nicht bestätigt'}

                # 5) setValue senden (secured oder plain)
                req_id = int(time.time() * 1000) % 100000
                inner_msg = {
                    "type": "setValue",
                    "requestId": req_id,
                    "key": key,
                    "value": value
                }

                if secured and secured > 0:
                    # SecuredMsg: HMAC-SHA256 über JSON-Payload, Key = hashed_password
                    payload = json.dumps(inner_msg)
                    h = hmac_mod.new(
                        bytearray(hashed_pw),
                        bytearray(payload.encode()),
                        hashlib.sha256
                    )
                    outer_msg = {
                        "type": "securedMsg",
                        "data": payload,
                        "requestId": f"{req_id}sm",
                        "hmac": h.hexdigest()
                    }
                    await ws.send(json.dumps(outer_msg))
                    logger.info(f"Wattpilot securedMsg gesendet: {key}={value} (reqId={req_id})")
                else:
                    await ws.send(json.dumps(inner_msg))
                    logger.info(f"Wattpilot setValue gesendet: {key}={value} (reqId={req_id})")

                # 6) Response abwarten (type=response mit success=true/false)
                deadline = time.time() + timeout_ack
                try:
                    while time.time() < deadline:
                        remaining = max(0.1, deadline - time.time())
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                        msg = json.loads(raw)
                        # Direkte Response auf unseren Request
                        if msg.get('type') == 'response':
                            success = msg.get('success', False)
                            resp_msg = msg.get('message', '')
                            if success:
                                logger.info(f"Wattpilot bestätigt: {key}={value}")
                                return {'ok': True, 'key': key,
                                        'value': value,
                                        'detail': f'Bestätigt: {key}={value}'}
                            else:
                                logger.error(f"Wattpilot abgelehnt: {key}={value}: {resp_msg}")
                                return {'ok': False, 'key': key,
                                        'value': value,
                                        'detail': f'Abgelehnt: {resp_msg}'}
                        # deltaStatus mit unserem Key = auch eine Bestätigung
                        if msg.get('type') == 'deltaStatus':
                            st = msg.get('status', {})
                            if key in st:
                                ist_wert = st[key]
                                logger.info(f"Wattpilot deltaStatus bestätigt: {key}={ist_wert}")
                                return {'ok': True, 'key': key,
                                        'value': value, 'ist': ist_wert,
                                        'detail': f'Bestätigt via deltaStatus: {key}={ist_wert}'}
                except asyncio.TimeoutError:
                    pass
                # Kein Response erhalten
                logger.warning(f"Wattpilot setValue {key}={value}: Gesendet (kein Response innerhalb {timeout_ack}s)")
                return {'ok': True, 'key': key, 'value': value,
                        'detail': f'Gesendet, kein Response innerhalb {timeout_ack}s'}

        except ConnectionRefusedError:
            return {'ok': False, 'key': key, 'detail': f'WebSocket {uri} verweigert (App aktiv?)'}
        except ConnectionResetError:
            return {'ok': False, 'key': key, 'detail': f'WebSocket {uri} zurückgesetzt'}
        except Exception as e:
            return {'ok': False, 'key': key, 'detail': f'Fehler: {e}'}

    def _run_async(self, coro):
        """Async-Coroutine synchron ausführen (Event-Loop-sicher)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=self.timeout + 10)
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def set_value(self, key: str, value) -> dict:
        """Wattpilot-Parameter setzen (synchroner Aufruf mit Retry).

        Unterstützte Keys:
          amp  — Ladestrom [6–32 A]
          psm  — Phasenmodus (1=1-phasig, 2=3-phasig)
          frc  — Force State (0=neutral, 1=aus, 2=ein)
          lmo  — Lademodus (3=Default, 4=Eco, 5=NextTrip)

        Bei WebSocket-Kollision (Collector oder externe App belegt die
        einzige erlaubte Verbindung) wird automatisch bis zu N× wiederholt.
        Konfiguration: WATTPILOT_WRITE_RETRIES / WATTPILOT_WRITE_RETRY_PAUSE

        Returns:
            dict: {'ok': bool, 'key': str, 'value': ..., 'detail': str}
        """
        try:
            import config as cfg
            max_retries = getattr(cfg, 'WATTPILOT_WRITE_RETRIES', 3)
            retry_pause = getattr(cfg, 'WATTPILOT_WRITE_RETRY_PAUSE', 3)
        except ImportError:
            max_retries = 3
            retry_pause = 3

        last_result = None
        for attempt in range(1, max_retries + 1):
            result = self._run_async(self._set_value_async(key, value))
            last_result = result

            if result.get('ok'):
                if attempt > 1:
                    logger.info(f"Wattpilot set_value({key}={value}) erfolgreich "
                                f"nach {attempt} Versuchen")
                return result

            # Retry-fähige Fehler: WebSocket belegt (Collector/App)
            detail = result.get('detail', '')
            retriable = ('hello' in detail.lower()
                         or 'refused' in detail.lower()
                         or 'reset' in detail.lower()
                         or 'timeout' in detail.lower())

            if not retriable or attempt >= max_retries:
                break

            logger.warning(f"Wattpilot set_value({key}={value}) Versuch {attempt}/{max_retries} "
                           f"fehlgeschlagen: {detail} → Retry in {retry_pause}s")
            time.sleep(retry_pause)

        logger.error(f"Wattpilot set_value({key}={value}) endgültig fehlgeschlagen "
                     f"nach {max_retries} Versuchen: {last_result.get('detail')}")
        return last_result

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
            'amp': int(status.get('amp', 0) or 0),
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
            'lmo': int(status.get('lmo', 0) or 0),
            'force_state': status.get('frc', 0),
            'frc': int(status.get('frc', 0) or 0),
            'trx': status.get('trx', None),
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
                print("")
                print(f"  Auto-Status:   {summary['car_state_text']}")
                print(f"  Lademodus:     {summary['charge_mode']}")
                print(f"  Phasen:        {summary['phase_mode']}")
                print(f"  Strom:         {summary['charge_current_a']} A (max {summary['max_current_a']} A)")
                print(f"  Leistung:      {summary['power_w']:.0f} W")
                print("")
                print(f"  Session:       {summary['energy_session_kwh']:.3f} kWh")
                print(f"  Zählerstand:   {summary['energy_total_kwh']:.3f} kWh")
            else:
                print(f"  OFFLINE: {summary.get('error_message', 'Nicht erreichbar')}")
            print("=" * 55)
        except Exception as e:
            print(f"FEHLER: {e}")
            sys.exit(1)
