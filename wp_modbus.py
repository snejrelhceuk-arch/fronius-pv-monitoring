"""
Wärmepumpe Dimplex — Modbus RTU Reader.

Liest ausgewählte Register über USB-RS485 Adapter.
Serielle Schnittstelle: /dev/ttyACM0, 19200 Baud, 8N1, Slave-ID 1.
Cache-TTL: 10 Sekunden.
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
    'vorlauf':        5,
    'ruecklauf':      2,
    'ruecklauf_soll': 53,
    'ww_ist':         3,
    'quelle_ein':     6,
    'quelle_aus':     7,
}
_REGS_INT = {
    'ww_soll': 5047,
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
