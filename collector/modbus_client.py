"""
collector.modbus_client — Minimaler Modbus-TCP-Client ohne Dependencies.

Bewusster Eigenbau (kein pymodbus). Wiederverwendbar fuer PAC4200/RS485,
falls dieser Pfad spaeter aufgebaut wird.
"""

import logging
import socket
import struct


class RawModbusClient:
    """Minimaler Modbus TCP Client ohne Abhaengigkeiten."""

    def __init__(self, host, port=502, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.tid = 0

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            return True
        except Exception as e:
            logging.debug(f"Connect Error: {e}")
            self.sock = None
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def read_holding_registers(self, address, count, **kwargs):
        if not self.sock:
            return None
        unit = kwargs.get('unit', kwargs.get('device_id', 1))
        self.tid = (self.tid + 1) & 0xFFFF

        # Modbus TCP: TI(2) Proto(2) Len(2) Unit(1) Func(1) Addr(2) Count(2)
        req = struct.pack('>HHHBBHH', self.tid, 0, 6, unit, 3, address, count)
        try:
            self.sock.sendall(req)
            head = self._recv(7)
            if len(head) < 7:
                return None
            tid, proto, length, uid = struct.unpack('>HHHB', head)
            body = self._recv(length - 1)
            if len(body) < 2:
                return None
            if body[0] >= 0x80:
                return None
            byte_count = body[1]
            if len(body) < 2 + byte_count:
                return None
            values = struct.unpack(f'>{byte_count//2}H', body[2:2 + byte_count])

            class Res:
                def __init__(self, v):
                    self.registers = list(v)

                def isError(self):
                    return False

            return Res(values)
        except Exception as e:
            logging.debug(f"Read Error: {e}")
            self.close()
            return None

    def _recv(self, n):
        d = b''
        while len(d) < n:
            try:
                chunk = self.sock.recv(n - len(d))
                if not chunk:
                    break
                d += chunk
            except Exception:
                break
        return d


def read_registers_safe(client, addr, count, unit_id=1):
    """Sichere Lesefunktion."""
    try:
        rr = client.read_holding_registers(address=addr, count=count, unit=unit_id)
        if rr is None or rr.isError():
            return None
        return rr.registers
    except Exception as e:
        logging.debug(f"Modbus Lesefehler bei Addr {addr}: {e}")
        return None
