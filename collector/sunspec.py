"""
collector.sunspec — SunSpec-Parser + Discovery.

Reine Datenparser-Schicht ueber dem Modbus-Client. Unit-test-bar mit
Register-Dump-Fixtures.
"""

import logging
import struct

from collector import quellen as modbus_quellen

from .modbus_client import read_registers_safe


def parse_sunspec_string(regs):
    """Parse SunSpec String (16-Bit Werte)."""
    try:
        data = struct.pack(f'>{len(regs)}H', *regs)
        s = data.decode('ascii', errors='ignore').rstrip('\x00 ')
        return s if s else None
    except Exception as e:
        logging.debug(f"SunSpec String Parse-Fehler: {e}")
        return None


def parse_sunspec_value(regs, dtype, sf=0):
    """Parse SunSpec Wert mit Skalierungsfaktor."""
    if not regs:
        return None

    try:
        if dtype == 'uint16':
            val = regs[0]
            if val == 0xFFFF:
                return None
        elif dtype == 'int16':
            val = regs[0] if regs[0] < 0x8000 else regs[0] - 0x10000
            if val == -0x8000:
                return None
        elif dtype == 'enum16':
            val = regs[0]
            return val
        elif dtype == 'bitfield16':
            val = regs[0]
            return val
        elif dtype == 'bitfield32':
            val = (regs[0] << 16) | regs[1]
            return val
        elif dtype == 'uint32' or dtype == 'acc32':
            val = (regs[0] << 16) | regs[1]
            if val == 0xFFFFFFFF:
                return None
        elif dtype == 'int32':
            val = (regs[0] << 16) | regs[1]
            if val >= 0x80000000:
                val -= 0x100000000
            if val == -0x80000000:
                return None
        elif dtype == 'acc64':
            val = (regs[0] << 48) | (regs[1] << 32) | (regs[2] << 16) | regs[3]
            if val == 0xFFFFFFFFFFFFFFFF:
                return None
        elif dtype == 'sunssf':
            val = regs[0] if regs[0] < 0x8000 else regs[0] - 0x10000
            return val
        else:
            return None

        if sf and sf != 0:
            val = val * (10 ** sf)

        return val
    except Exception as e:
        logging.debug(f"SunSpec Value Parse-Fehler: {e}")
        return None


def parse_model(model_id, data):
    """Parse ein SunSpec Modell basierend auf modbus_quellen.MODELS."""
    if model_id not in modbus_quellen.MODELS:
        return None

    fields = modbus_quellen.MODELS[model_id]
    parsed = {}
    scale_factors = {}

    # Erst alle Scale Factors sammeln
    for field in fields:
        fname = field['field']
        ftype = field.get('type')
        offset = field.get('offset', 0)

        if ftype == 'sunssf':
            length = field.get('length', 1)
            regs = data[offset:offset + length]
            sf = parse_sunspec_value(regs, ftype)
            if sf is not None:
                scale_factors[fname] = sf

    # Dann alle Datenfelder parsen
    for field in fields:
        fname = field['field']
        ftype = field.get('type')
        offset = field.get('offset', 0)

        if ftype == 'sunssf' or ftype == 'pad':
            continue

        if ftype == 'string':
            length = field.get('length', 1)
            regs = data[offset:offset + length]
            val = parse_sunspec_string(regs)
            if val:
                parsed[fname] = {'value': val, 'unit': ''}
        else:
            length = 4 if ftype in ('uint32', 'int32', 'acc32') else (2 if ftype == 'bitfield32' else (8 if ftype == 'acc64' else 1))
            if length == 8:
                length = 4  # acc64 braucht 4 Register

            regs = data[offset:offset + length]
            sf_name = field.get('scale')
            sf = scale_factors.get(sf_name, 0) if sf_name else 0

            val = parse_sunspec_value(regs, ftype, sf)
            if val is not None:
                unit = field.get('units', '')
                parsed[fname] = {'value': val, 'unit': unit}

    return parsed


def read_device_data(client, unit_id, skip_model_ids=None):
    """Liest SunSpec Modelle von einem Geraet."""
    if skip_model_ids is None:
        skip_model_ids = []

    # SunSpec Header lesen (40000-40002)
    header = read_registers_safe(client, 40000, 2, unit_id)
    if not header or header[0] != 0x5375 or header[1] != 0x6e53:  # 'SunS'
        logging.warning(f"Kein SunSpec Header bei Unit {unit_id}")
        return []

    models = []
    addr = 40002

    while addr < 65000:
        model_header = read_registers_safe(client, addr, 2, unit_id)
        if not model_header:
            break

        model_id = model_header[0]
        model_len = model_header[1]

        if model_id == 0xFFFF or model_len == 0 or model_len > 200:
            break

        if model_id in skip_model_ids:
            addr += 2 + model_len
            continue

        model_data = read_registers_safe(client, addr + 2, model_len, unit_id)
        if not model_data:
            addr += 2 + model_len
            continue

        parsed = parse_model(model_id, model_data)
        if parsed:
            class Model:
                def __init__(self, mid, pdata):
                    self.id = mid
                    self.parsed = pdata
            models.append(Model(model_id, parsed))

        addr += 2 + model_len

    return models


def extract_device_data(models):
    """Extrahiert geparste Daten aus SunSpec-Modellen."""
    data = {}
    for m in models:
        if m.id == 1:
            data['common'] = m.parsed
        if m.id == 124:
            data['storage'] = m.parsed
        if m.id in (103, 113):
            data['inverter_data'] = m.parsed
        if m.id == 160:
            data['mppt'] = m.parsed
        if m.id in (201, 202, 203):
            data['meter_data'] = m.parsed
    return data
