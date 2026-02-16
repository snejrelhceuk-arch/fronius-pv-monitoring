#!/usr/bin/env python3
"""
Wattpilot WebSocket Reader - Liest alle Parameter vom Fronius Wattpilot.

Verbindet sich per WebSocket auf die lokale IP, authentifiziert mit V-Code
und gibt den vollstaendigen Status aus.

Usage:
  python3 tools/wattpilot_read.py              # Alles ausgeben
  python3 tools/wattpilot_read.py --raw        # Rohe JSON-Daten
  python3 tools/wattpilot_read.py --energy     # Nur Energie-Werte
  python3 tools/wattpilot_read.py --json       # Komplett als JSON-Datei speichern
"""

import asyncio
import json
import hashlib
import base64
import secrets
import sys
import os
from datetime import datetime

# --- Konfiguration ---
WATTPILOT_IP = "192.168.2.197"
WEBSOCKET_TIMEOUT = 10               # Sekunden
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_password():
    """Passwort aus Umgebungsvariable oder .secrets-Datei laden."""
    try:
        sys.path.insert(0, os.path.dirname(OUTPUT_DIR))
        from config import load_secret
        pw = load_secret('WATTPILOT_PASSWORD')
    except ImportError:
        pw = os.environ.get('WATTPILOT_PASSWORD')
    if pw:
        return pw
    print("FEHLER: Kein Wattpilot-Passwort gefunden!")
    print("  Entweder Umgebungsvariable setzen:")
    print("    export WATTPILOT_PASSWORD='...'")
    print(f"  Oder in .secrets eintragen:")
    print("    WATTPILOT_PASSWORD=dein_passwort")
    sys.exit(1)

# Bekannte Properties mit Beschreibung (Auswahl der wichtigsten)
KNOWN_PROPS = {
    # Energie-Zaehler
    'eto':  'Gesamt-Energie Lifetime [Wh]',
    'etop': 'Gesamt-Energie persistiert [Wh]',
    'wh':   'Session-Energie seit Anschluss [Wh]',
    'dwo':  'Energie-Limit fuer Session [Wh]',
    # Live-Leistung
    'nrg':  'Live-Messwerte [U_L1,U_L2,U_L3,U_N, I_L1,I_L2,I_L3, P_L1,P_L2,P_L3,P_N,P_Total, pf_L1,pf_L2,pf_L3,pf_N]',
    'tpa':  '30s-Durchschnitt Leistung [W]',
    'fhz':  'Netzfrequenz [Hz]',
    # Ladezustand
    'car':  'Auto-Status (1=Idle, 2=Charging, 3=WaitCar, 4=Complete, 5=Error)',
    'amp':  'Lade-Strom [A]',
    'ama':  'Max. erlaubter Strom [A]',
    'acs':  'Zugangskontrolle (0=Open, 1=Wait)',
    'alw':  'Laden erlaubt',
    'acu':  'Erlaubter Strom (unsolicited) [A]',
    'stp':  'Stopp-Zustand',
    'err':  'Fehlercode',
    'ust':  'Kabel-Verriegelung (0=normal, 1=auto, 2=always)',
    'frc':  'Force State (0=neutral, 1=off, 2=on)',
    # Phasen
    'psm':  'Phasen-Modus (1=1-phasig, 2=3-phasig)',
    'pnp':  'N-PE Spannung [V]',
    'pha':  'Phasen verfuegbar / aktiv',
    # Temperatur
    'tmp':  'Temperatur [°C]',
    'tma':  'Temperatur L1 [°C]',
    'tmb':  'Temperatur L2 [°C]',
    'tmc':  'Temperatur L3 [°C]',
    # WLAN / System
    'rssi': 'WLAN Signalstaerke [dBm]',
    'wss':  'WLAN SSID',
    'ccw':  'WLAN-Verbindung aktiv',
    'fwv':  'Firmware-Version',
    'oem':  'OEM-Hersteller',
    'typ':  'Geraetetyp',
    'sse':  'Seriennummer',
    'ffna': 'Friendly Name',
    'cdi':  'Verbundene Geraete-Info',
    # Zeitplan / Timers
    'lmo':  'Lademodus (3=default, 4=eco, 5=next_trip)',
    'lps':  'Letzter PV-Surplus',
    'rbc':  'Reboot-Counter',
    'rbt':  'Reboot-Timer [ms]',
    'adi':  'Adapter-In (16A, 32A)',
    'cae':  'Cloud API enabled',
    'lse':  'LED Stromspar-Modus',
    'ust':  'Kabel-Lock (0=Normal, 1=AutoLock, 2=AlwaysLock)',
    'dto':  'Daily Timer Offset [min]',
    'nmo':  'Norwegen-Modus',
}

CAR_STATES = {0: 'Unknown', 1: 'Idle', 2: 'Charging', 3: 'WaitCar', 4: 'Complete', 5: 'Error'}


def compute_auth(serial: str, password: str, token1: str, token2: str):
    """Berechne Wattpilot-Auth-Hash (PBKDF2 + SHA256 Challenge-Response).
    
    Exakt nach joscha82/wattpilot Library implementiert:
    1. PBKDF2-HMAC-SHA512(password, serial, 100000, 256 bytes) -> base64 -> [:32]
    2. hash1 = SHA256(token1_bytes + hashed_password_bytes)
    3. token3 = random 32 hex chars
    4. hash  = SHA256( (token3 + token2 + hash1).encode() )
    """
    # Schritt 1: Passwort-Hash (identisch zu wattpilot.__init__.py Zeile 139)
    dk = hashlib.pbkdf2_hmac('sha512', password.encode(), serial.encode(), 100000, 256)
    hashed_pw = base64.b64encode(dk)[:32]  # bytes, 32 Zeichen

    # Schritt 2: token3 generieren (32 hex chars, wie in __on_auth)
    import random
    ran = random.randrange(10**80)
    token3 = "%064x" % ran
    token3 = token3[:32]

    # Schritt 3: hash1 = SHA256(token1_bytes + hashed_password_bytes)
    hash1 = hashlib.sha256((token1.encode() + hashed_pw)).hexdigest()

    # Schritt 4: final hash = SHA256(string concatenation encoded)
    final_hash = hashlib.sha256((token3 + token2 + hash1).encode()).hexdigest()

    return token3, final_hash


async def read_all_properties():
    """Verbinde zum Wattpilot und lese alle Properties."""
    try:
        import websockets
    except ImportError:
        print("ERROR: 'websockets' nicht installiert.")
        print("  → pip3 install websockets")
        sys.exit(1)

    uri = f"ws://{WATTPILOT_IP}/ws"
    print(f"Verbinde mit {uri} ...")

    try:
        async with websockets.connect(uri, open_timeout=WEBSOCKET_TIMEOUT) as ws:
            # 1) Hello empfangen
            raw = await asyncio.wait_for(ws.recv(), timeout=WEBSOCKET_TIMEOUT)
            hello = json.loads(raw)
            if hello.get('type') != 'hello':
                print(f"Unerwartete Antwort: {hello}")
                return None

            serial = hello.get('serial', '?')
            friendly = hello.get('friendly_name', hello.get('hostname', '?'))
            fw = hello.get('version', '?')
            mfg = hello.get('manufacturer', '?')
            protocol = hello.get('protocol', '?')
            secured = hello.get('secured', '?')
            print(f"  Geraet: {friendly}")
            print(f"  Serial: {serial}")
            print(f"  Firmware: {fw}")
            print(f"  Hersteller: {mfg}")

            # 2) AuthRequired empfangen
            raw = await asyncio.wait_for(ws.recv(), timeout=WEBSOCKET_TIMEOUT)
            auth_req = json.loads(raw)
            if auth_req.get('type') != 'authRequired':
                print(f"Kein authRequired erhalten: {auth_req}")
                return None

            token1 = auth_req['token1']
            token2 = auth_req['token2']

            # 3) Auth senden
            password = _load_password()
            token3, auth_hash = compute_auth(serial, password, token1, token2)
            await ws.send(json.dumps({
                "type": "auth",
                "token3": token3,
                "hash": auth_hash
            }))

            # 4) Auth-Ergebnis
            raw = await asyncio.wait_for(ws.recv(), timeout=WEBSOCKET_TIMEOUT)
            auth_resp = json.loads(raw)
            if auth_resp.get('type') == 'authError':
                print(f"\n  AUTHENTIFIZIERUNG FEHLGESCHLAGEN: {auth_resp.get('message', '?')}")
                print(f"  Auth-Response: {json.dumps(auth_resp, indent=2)}")
                return None
            elif auth_resp.get('type') == 'authSuccess':
                print(f"  [OK] Authentifizierung erfolgreich")
            elif auth_resp.get('type') in ('fullStatus', 'deltaStatus'):
                # Manche FW-Versionen senden direkt Status ohne explizites authSuccess
                print(f"  [OK] Auth implizit erfolgreich (direkt Status erhalten)")
                # Diese Nachricht gleich verarbeiten
                status = auth_resp.get('status', {})
                full_status = dict(status)
                msg_count = 1
                # Weiter mit Status-Empfang
                print(f"  Empfange Status-Daten ...")
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    msg_type = msg.get('type', '')
                    if msg_type in ('fullStatus', 'deltaStatus'):
                        full_status.update(msg.get('status', {}))
                        msg_count += 1
                        if msg_type == 'fullStatus' and not msg.get('partial', True):
                            break
                print(f"  {msg_count} Status-Nachrichten empfangen, "
                      f"{len(full_status)} Properties gelesen")
                return {
                    'hello': hello,
                    'status': full_status,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                print(f"  ? Unerwartete Auth-Antwort: {auth_resp}")

            # 5) fullStatus sammeln
            full_status = {}
            print(f"\n  Empfange Status-Daten ...")
            msg_count = 0

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    break

                msg = json.loads(raw)
                msg_type = msg.get('type', '')

                if msg_type in ('fullStatus', 'deltaStatus'):
                    status = msg.get('status', {})
                    full_status.update(status)
                    msg_count += 1

                    # fullStatus mit partial=false → fertig
                    if msg_type == 'fullStatus' and not msg.get('partial', True):
                        break

            print(f"  {msg_count} Status-Nachrichten empfangen, "
                  f"{len(full_status)} Properties gelesen")

            return {
                'hello': hello,
                'status': full_status,
                'timestamp': datetime.now().isoformat()
            }

    except ConnectionRefusedError:
        print(f"\n  FEHLER: Verbindung abgelehnt auf {uri}")
        print(f"  -> Ist der Wattpilot eingeschaltet und im Netzwerk?")
        return None
    except asyncio.TimeoutError:
        print(f"\n  FEHLER: Timeout -- keine Antwort von {WATTPILOT_IP}")
        return None
    except Exception as e:
        print(f"\n  FEHLER: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_energy(status):
    """Energie-relevante Werte formatiert ausgeben."""
    print("\n" + "=" * 65)
    print("  WATTPILOT - Energie-Daten")
    print("=" * 65)

    eto = status.get('eto')
    etop = status.get('etop')
    wh = status.get('wh')
    tpa = status.get('tpa')
    car = status.get('car')
    nrg = status.get('nrg')

    print(f"\n  Gesamt-Zaehler (eto):    {eto} Wh  =  {eto/1000:.3f} kWh" if eto else
          "  Gesamt-Zaehler (eto):    N/A")
    print(f"  Persistiert (etop):     {etop} Wh  =  {etop/1000:.3f} kWh" if etop else
          "  Persistiert (etop):     N/A")
    print(f"  Session (wh):           {wh} Wh  =  {wh/1000:.3f} kWh" if wh is not None else
          "  Session (wh):           N/A")
    print(f"  Leistung O30s (tpa):    {tpa} W" if tpa is not None else
          "  Leistung O30s (tpa):    N/A")
    print(f"  Auto-Status:            {CAR_STATES.get(car, car)}")

    if nrg and len(nrg) >= 16:
        print(f"\n  Live-Messwerte (nrg):")
        print(f"    Spannung:   L1={nrg[0]}V  L2={nrg[1]}V  L3={nrg[2]}V  N={nrg[3]}V")
        print(f"    Strom:      L1={nrg[4]}A  L2={nrg[5]}A  L3={nrg[6]}A")
        print(f"    Leistung:   L1={nrg[7]}W  L2={nrg[8]}W  L3={nrg[9]}W  "
              f"N={nrg[10]}W  Total={nrg[11]}W")
        print(f"    cos phi:    L1={nrg[12]}  L2={nrg[13]}  L3={nrg[14]}  N={nrg[15]}")

    print("\n" + "=" * 65)


def print_all(data):
    """Alle Properties kategorisiert ausgeben."""
    status = data['status']

    print("\n" + "=" * 65)
    print(f"  WATTPILOT - Vollstaendiger Status ({len(status)} Properties)")
    print(f"  Zeitpunkt: {data['timestamp']}")
    print("=" * 65)

    # Zuerst bekannte Properties sortiert nach Kategorie
    known_found = {}
    unknown = {}

    for key, val in sorted(status.items()):
        if key in KNOWN_PROPS:
            known_found[key] = val
        else:
            unknown[key] = val

    if known_found:
        print(f"\n  -- Bekannte Properties ({len(known_found)}) --")
        for key, val in sorted(known_found.items()):
            desc = KNOWN_PROPS.get(key, '')
            val_str = format_value(key, val)
            print(f"  {key:8s} = {val_str:30s}  # {desc}")

    if unknown:
        print(f"\n  -- Weitere Properties ({len(unknown)}) --")
        for key, val in sorted(unknown.items()):
            val_str = str(val)
            if len(val_str) > 60:
                val_str = val_str[:57] + '...'
            print(f"  {key:8s} = {val_str}")

    print(f"\n  Total: {len(status)} Properties")
    print("=" * 65)


def format_value(key, val):
    """Formatierten Wert fuer bekannte Properties."""
    if key == 'car':
        return f"{val} ({CAR_STATES.get(val, '?')})"
    if key in ('eto', 'etop', 'wh') and isinstance(val, (int, float)):
        return f"{val} Wh ({val/1000:.3f} kWh)"
    if key == 'nrg' and isinstance(val, list):
        if len(val) >= 12:
            return f"Total={val[11]}W, L1={val[0]}V/{val[4]}A"
        return str(val)
    if isinstance(val, bool):
        return 'True' if val else 'False'
    return str(val)


def save_json(data, filename=None):
    """Speichere vollstaendigen Dump als JSON."""
    if not filename:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(OUTPUT_DIR, f'wattpilot_dump_{ts}.json')
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Gespeichert: {filename}")
    return filename


async def main():
    args = sys.argv[1:]
    raw_mode = '--raw' in args
    energy_only = '--energy' in args
    save_mode = '--json' in args

    data = await read_all_properties()
    if not data:
        sys.exit(1)

    status = data['status']

    if raw_mode:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif energy_only:
        print_energy(status)
    else:
        print_energy(status)
        print_all(data)

    if save_mode:
        save_json(data)


if __name__ == '__main__':
    asyncio.run(main())
