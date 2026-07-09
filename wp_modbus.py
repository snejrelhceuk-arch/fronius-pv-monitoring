"""
Wärmepumpe Dimplex — Modbus RTU Reader + Writer.

Liest/schreibt ausgewählte Register über USB-RS485 Adapter.
Serielle Schnittstelle: /dev/ttyACM0, 19200 Baud, 8N1, Slave-ID 1.
Cache-TTL: 10 Sekunden.

ABCD: Nur von C-Rolle (Automation) genutzt. B (Web) liest via obs_state.

Transport-Backend (config.WP_BACKEND_MODE):
  local  — direktes RS485/tty auf diesem Host (Bridge-Host Pi4-Tech).
  remote — HTTP an die Pi4-Tech Bridge (Primary ohne WP-Hardware).
Die öffentlichen Signaturen get_wp_status()/write_register() bleiben unverändert.
"""
import logging
import time
import threading

import config

_WP_CACHE = {'ts': 0, 'data': None}
_WP_CACHE_TTL = 10
_WP_LOCK = threading.Lock()

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 19200
SLAVE_ID = 1

# ── Zentrale Dimplex-NWPM-Modbus-Register-Map (Holding-Register, FC=3) ──
# Single-Source für Adressen + Skalierung + Schreibrechte. Register 1–100:
# Werte in 0.1 °C (signed int16). Register 5000+: Sollwerte in ganzen °C.
#   scale     — Anzeige = roh * scale (0.1 = Zehntelgrad-Register, 1.0 = Ganzzahl)
#   writable  — über write_register() schreibbar (Whitelist, mit min/max)
# Rolle C (Automation). KEINE Cross-Role-Nutzung: die A-Rolle (collector/)
# hat ihre eigene Fronius-Register-Map (collector/quellen.py:MODELS).
WP_REGISTERS = {
    'aussen_temp':    {'addr': 1,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'ruecklauf':      {'addr': 2,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'ww_ist':         {'addr': 3,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'vorlauf':        {'addr': 5,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'quelle_ein':     {'addr': 6,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'quelle_aus':     {'addr': 7,    'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'ruecklauf_soll': {'addr': 53,   'scale': 0.1, 'writable': False, 'einheit': '°C'},
    'heiz_soll':      {'addr': 5037, 'scale': 1.0, 'writable': True,  'min': 18, 'max': 60, 'einheit': '°C'},
    'ww_soll':        {'addr': 5047, 'scale': 1.0, 'writable': True,  'min': 10, 'max': 85, 'einheit': '°C'},
}

# Abgeleitete Lese-Sichten (Register werden einzeln gelesen → Reihenfolge irrelevant)
_REGS_TENTH = {k: v['addr'] for k, v in WP_REGISTERS.items() if v['scale'] == 0.1}
_REGS_INT = {k: v['addr'] for k, v in WP_REGISTERS.items() if v['scale'] == 1.0}


def _signed16(raw):
    return raw - 0x10000 if raw >= 0x8000 else raw


def _remote_headers():
    headers = {'Content-Type': 'application/json'}
    token = config.WP_REMOTE_TOKEN
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _poll_remote():
    """WP-Status über die Pi4-Tech Bridge (HTTP) lesen. Fail-safe → None."""
    if not config.WP_REMOTE_BASE_URL:
        logging.error("WP remote: PV_WP_REMOTE_BASE_URL nicht gesetzt")
        return None
    try:
        import requests
    except ImportError:
        logging.error("WP remote: requests nicht installiert")
        return None
    url = f"{config.WP_REMOTE_BASE_URL}/api/wp/status"
    try:
        resp = requests.get(url, headers=_remote_headers(),
                            timeout=config.WP_REMOTE_TIMEOUT_S)
    except Exception as e:
        logging.warning("WP remote status Verbindungsfehler: %s", e)
        return None
    if resp.status_code != 200:
        logging.warning("WP remote status HTTP %s", resp.status_code)
        return None
    try:
        payload = resp.json()
    except Exception as e:
        logging.warning("WP remote status JSON-Fehler: %s", e)
        return None
    if isinstance(payload, dict) and 'data' in payload:
        return payload['data']
    return payload


def _poll_local():
    """Alle WP-Register über RS485/tty lesen, dict zurückgeben."""
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        logging.error("WP Modbus: pymodbus nicht installiert")
        return None

    client = ModbusSerialClient(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=1.5,
    )

    if not client.connect():
        logging.warning("WP Modbus: Verbindung zu %s fehlgeschlagen", SERIAL_PORT)
        return None

    try:
        data = {}

        for key, addr in _REGS_TENTH.items():
            rr = client.read_holding_registers(address=addr, count=1, slave=SLAVE_ID)
            if rr.isError():
                data[key] = None
            else:
                data[key] = round(_signed16(rr.registers[0]) / 10.0, 1)

        for key, addr in _REGS_INT.items():
            rr = client.read_holding_registers(address=addr, count=1, slave=SLAVE_ID)
            if rr.isError():
                data[key] = None
            else:
                data[key] = _signed16(rr.registers[0])

        data['ts'] = time.strftime('%H:%M:%S')
        return data

    except Exception as e:
        logging.warning("WP Modbus Lesefehler: %s", e)
        return None
    finally:
        client.close()


def _poll():
    """Dispatcher: liest WP-Status je nach Backend (local/remote)."""
    if config.WP_BACKEND_MODE == 'remote':
        return _poll_remote()
    return _poll_local()


def get_wp_status():
    """Gecachte WP-Daten (max. 10 s alt). Thread-safe."""
    now = time.time()

    with _WP_LOCK:
        if _WP_CACHE['data'] and (now - _WP_CACHE['ts']) < _WP_CACHE_TTL:
            return dict(_WP_CACHE['data'])

    data = _poll()

    with _WP_LOCK:
        if data:
            _WP_CACHE['data'] = data
            _WP_CACHE['ts'] = now
        return dict(_WP_CACHE['data']) if _WP_CACHE['data'] else None


# ── Schreib-Funktionen (ABCD: nur C-Rolle) ──────────────────

# Zugelassene Schreib-Register (Whitelist — Sicherheit), abgeleitet aus WP_REGISTERS
_WRITE_REGS = {
    k: {'addr': v['addr'], 'min': v['min'], 'max': v['max'], 'einheit': v['einheit']}
    for k, v in WP_REGISTERS.items() if v['writable']
}


def write_register(name: str, value: int) -> bool:
    """Einzelnes WP-Register schreiben (Whitelist-geschützt).

    Args:
        name: Register-Name aus _WRITE_REGS (z.B. 'ww_soll')
        value: Ganzzahliger Wert im erlaubten Bereich

    Returns:
        True bei Erfolg, False bei Fehler
    """
    reg = _WRITE_REGS.get(name)
    if not reg:
        logging.error("WP Modbus write: '%s' nicht in Whitelist %s",
                       name, list(_WRITE_REGS.keys()))
        return False

    value = int(value)
    if not reg['min'] <= value <= reg['max']:
        logging.error("WP Modbus write: %s=%d außerhalb [%d, %d] %s",
                       name, value, reg['min'], reg['max'], reg['einheit'])
        return False

    if config.WP_BACKEND_MODE == 'remote':
        return _write_register_remote(name, value)
    return _write_register_local(reg, name, value)


def _write_register_remote(name: str, value: int) -> bool:
    """Schreibbefehl an die Pi4-Tech Bridge (HTTP). Fail-safe → False."""
    if not config.WP_REMOTE_BASE_URL:
        logging.error("WP remote write: PV_WP_REMOTE_BASE_URL nicht gesetzt")
        return False
    try:
        import requests
    except ImportError:
        logging.error("WP remote write: requests nicht installiert")
        return False
    url = f"{config.WP_REMOTE_BASE_URL}/api/wp/write"
    try:
        resp = requests.post(url, json={'name': name, 'value': int(value)},
                             headers=_remote_headers(),
                             timeout=config.WP_REMOTE_TIMEOUT_S)
    except Exception as e:
        logging.error("WP remote write Verbindungsfehler: %s", e)
        return False
    if resp.status_code != 200:
        logging.error("WP remote write HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    try:
        ok = bool(resp.json().get('ok'))
    except Exception as e:
        logging.error("WP remote write JSON-Fehler: %s", e)
        return False
    if ok:
        logging.info("WP remote write: %s=%d OK (Bridge)", name, value)
        with _WP_LOCK:
            _WP_CACHE['ts'] = 0
    return ok


def _write_register_local(reg: dict, name: str, value: int) -> bool:
    """Einzelnes WP-Register lokal über RS485/tty schreiben."""
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        logging.error("WP Modbus: pymodbus nicht installiert")
        return False

    client = ModbusSerialClient(
        port=SERIAL_PORT, baudrate=BAUD_RATE,
        bytesize=8, parity='N', stopbits=1, timeout=1.5,
    )
    if not client.connect():
        logging.warning("WP Modbus write: Verbindung fehlgeschlagen")
        return False

    try:
        rr = client.write_register(address=reg['addr'], value=value, slave=SLAVE_ID)
        if rr.isError():
            logging.error("WP Modbus write: %s=%d → Fehler: %s", name, value, rr)
            return False
        logging.info("WP Modbus write: %s=%d%s (Reg %d) OK",
                      name, value, reg['einheit'], reg['addr'])
        # Cache invalidieren
        with _WP_LOCK:
            _WP_CACHE['ts'] = 0
        return True
    except Exception as e:
        logging.error("WP Modbus write Fehler: %s", e)
        return False
    finally:
        client.close()
