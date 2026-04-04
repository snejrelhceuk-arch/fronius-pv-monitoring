"""
Wärmepumpe Dimplex — Modbus RTU Reader + Writer.

Liest/schreibt ausgewählte Register über USB-RS485 Adapter.
Serielle Schnittstelle: /dev/ttyACM0, 19200 Baud, 8N1, Slave-ID 1.
Cache-TTL: 10 Sekunden.

ABCD: Nur von C-Rolle (Automation) genutzt. B (Web) liest via obs_state.
"""
import logging
import time
import threading

_WP_CACHE = {'ts': 0, 'data': None}
_WP_CACHE_TTL = 10
_WP_LOCK = threading.Lock()

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 19200
SLAVE_ID = 1

# Dimplex NWPM Holding-Register (FC=3)
# Register 1–100: Werte in 0.1 °C (signed int16)
# Register 5000+: Sollwerte in ganzen °C
_REGS_TENTH = {
    'aussen_temp':    1,
    'vorlauf':        5,
    'ruecklauf':      2,
    'ruecklauf_soll': 53,
    'ww_ist':         3,
    'quelle_ein':     6,
    'quelle_aus':     7,
}
_REGS_INT = {
    'ww_soll': 5047,
    'heiz_soll': 5037,
}


def _signed16(raw):
    return raw - 0x10000 if raw >= 0x8000 else raw


def _poll():
    """Alle WP-Register lesen, dict zurückgeben."""
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

# Zugelassene Schreib-Register (Whitelist — Sicherheit)
_WRITE_REGS = {
    'ww_soll': {'addr': 5047, 'min': 10, 'max': 85, 'einheit': '°C'},
    'heiz_soll': {'addr': 5037, 'min': 18, 'max': 60, 'einheit': '°C'},
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
