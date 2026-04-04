"""
modbus_v3.py — Modbus-Collector für Fronius Gen24 / SmartMeter
Version 2.0 - 30.12.2025
Version 2.1 - 31.12.2024 - RAM-Buffer + Batch-Writes
Version 3.0 - 12.02.2026 - tmpfs-Architektur (DB in /dev/shm, Persist alle 5min auf NVMe)

Aktuelle Architektur:
- DB lebt in tmpfs (/dev/shm/fronius_data.db) → null Disk-I/O für Reads
- RAM-Buffer (deque) für Rohdaten, Batch-Writes alle 60s in tmpfs-DB
- Persist-Thread in db_init.py: tmpfs → SD (Stunde/Tag konfigurierbar)
- Datenverlust-Risiko: abhängig von DB_PERSIST_UNIT (Stunde/Tag)
"""

import time
import socket
import threading
import struct
import sqlite3
import sys
import os
import requests
import json
from collections import deque
import logging
import modbus_quellen
import atexit
import config
import db_init

# Logging: INFO für Produktion (DEBUG bei Bedarf temporär aktivieren)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# --- Konfiguration (aus config.py) ---
IP_ADDRESS = modbus_quellen.IP_ADDRESS
PORT = modbus_quellen.PORT
POLL_INTERVAL = config.POLL_INTERVAL
DB_FILE = config.DB_PATH
FRONIUS_API_BASE = config.FRONIUS_API_BASE
PID_FILE = config.PID_FILE
ATTACHMENT_STATE_FILE = os.path.join(config.BASE_DIR, 'config', 'fronius_attachment_state.json')

# --- PID-FILE SCHUTZ (Single Instance) ---
def _is_collector_process(pid):
    """Prüft ob der Prozess mit dieser PID tatsächlich ein Collector ist"""
    try:
        with open(f'/proc/{pid}/cmdline', 'r') as f:
            cmdline = f.read()
        return 'collector.py' in cmdline or 'modbus_v3' in cmdline
    except (FileNotFoundError, PermissionError):
        return False

def create_pid_file():
    """Erstellt PID-File und prüft auf laufende Instanz"""
    if os.path.exists(PID_FILE):
        # Prüfe ob Prozess noch läuft
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            
            # Prüfe ob Prozess existiert UND ein Collector ist
            try:
                os.kill(old_pid, 0)  # Signal 0 = Prüfe Existenz
                if _is_collector_process(old_pid):
                    print(f"[ERROR] collector.py laeuft bereits (PID {old_pid})")
                    print(f"   Beenden Sie den Prozess mit: kill {old_pid}")
                    print(f"   Oder erzwingen Sie Start mit: rm {PID_FILE}")
                    sys.exit(1)
                else:
                    print(f"[WARN] PID {old_pid} lebt, ist aber kein Collector — entferne stale PID-File")
                    os.remove(PID_FILE)
            except OSError:
                # Prozess existiert nicht mehr → Stale PID-File
                print(f"[WARN] Entferne verwaistes PID-File (PID {old_pid} existiert nicht)")
                os.remove(PID_FILE)
        except (ValueError, FileNotFoundError):
            os.remove(PID_FILE)
    
    # Erstelle neues PID-File
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    # Registriere Cleanup beim Beenden
    atexit.register(remove_pid_file)
    print(f"[OK] PID-File erstellt: {PID_FILE} (PID {os.getpid()})")

def remove_pid_file():
    """Entfernt PID-File beim sauberen Beenden"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(PID_FILE)
                print("[OK] PID-File entfernt")
        except Exception as e:
            logging.debug(f"PID-File Cleanup: {e}")
# Speichert 20 Minuten Daten im RAM (400 Datensätze bei 3s Polling)
# Wird alle 60s in Datenbank geschrieben (Batch-Write)
ram_buffer = deque(maxlen=config.BUFFER_MAXLEN)
ram_buffer_lock = threading.Lock()

# --- ENERGIE-AKKUMULATOREN ---
energy_state = {
    'W_PV_F1': 0.0,
    'W_PV_F2': 0.0,
    'W_PV_F3': 0.0,
    'W_WR_F2_consumption': 0.0,  # Nächtlicher WR-Verbrauch F2
    'W_WR_F3_consumption': 0.0,  # Nächtlicher WR-Verbrauch F3
    'W_Imp_Grid': 0.0,
    'W_Exp_Grid': 0.0,
    'W_Batt_charge': 0.0,
    'W_Batt_discharge': 0.0,
    'last_poll_time': None
}
energy_lock = threading.Lock()

# --- MODBUS CLIENT ---
modbus_client = None
modbus_lock = threading.Lock()

# --- SUNSPEC CACHE ---
sunspec_cache = {'devices': {}, 'last_update': 0}
sunspec_cache_lock = threading.Lock()

# --- STATIC DEVICE DATA ---
static_device_data = {}
static_device_data_lock = threading.Lock()

# --- VERSION / ATTACHMENT STATE ---
attachment_state = {}
attachment_state_lock = threading.Lock()

class RawModbusClient:
    """Minimaler Modbus TCP Client ohne Abhängigkeiten"""
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
        if not self.sock: return None
        unit = kwargs.get('unit', kwargs.get('device_id', 1))
        self.tid = (self.tid + 1) & 0xFFFF
        
        # Modbus TCP: TI(2) Proto(2) Len(2) Unit(1) Func(1) Addr(2) Count(2)
        req = struct.pack('>HHHBBHH', self.tid, 0, 6, unit, 3, address, count)
        try:
            self.sock.sendall(req)
            head = self._recv(7)
            if len(head) < 7: return None
            tid, proto, length, uid = struct.unpack('>HHHB', head)
            body = self._recv(length - 1)
            if len(body) < 2: return None
            if body[0] >= 0x80: return None
            byte_count = body[1]
            if len(body) < 2 + byte_count: return None
            values = struct.unpack(f'>{byte_count//2}H', body[2:2+byte_count])
            
            class Res:
                def __init__(self, v): self.registers = list(v)
                def isError(self): return False
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
                if not chunk: break
                d += chunk
            except Exception: break
        return d

def read_registers_safe(client, addr, count, unit_id=1):
    """Sichere Lesefunktion"""
    try:
        rr = client.read_holding_registers(address=addr, count=count, unit=unit_id)
        if rr is None or rr.isError(): return None
        return rr.registers
    except Exception as e:
        logging.debug(f"Modbus Lesefehler bei Addr {addr}: {e}")
        return None


def _load_attachment_state():
    """Lade persistierten Versions-/Anknuepfungszustand."""
    global attachment_state
    try:
        if os.path.exists(ATTACHMENT_STATE_FILE):
            with open(ATTACHMENT_STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    with attachment_state_lock:
                        attachment_state = data
                    return
    except Exception as e:
        logging.warning(f"Attachment-State laden fehlgeschlagen: {e}")

    with attachment_state_lock:
        attachment_state = {}


def _save_attachment_state():
    """Speichere Versions-/Anknuepfungszustand atomar."""
    try:
        with attachment_state_lock:
            data = dict(attachment_state)

        tmp = f"{ATTACHMENT_STATE_FILE}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(tmp, ATTACHMENT_STATE_FILE)
    except Exception as e:
        logging.warning(f"Attachment-State speichern fehlgeschlagen: {e}")


def _safe_common_value(devices, key, field):
    try:
        return devices.get(key, {}).get('common', {}).get(field, {}).get('value')
    except Exception:
        return None


def _build_version_snapshot(devices):
    """Erzeuge kompakten Versions-Snapshot aus SunSpec Model 1."""
    return {
        'inverter_vr': _safe_common_value(devices, 'inverter', 'Vr'),
        'inverter_sn': _safe_common_value(devices, 'inverter', 'SN'),
        'prim_sm_vr': _safe_common_value(devices, 'prim_sm', 'Vr'),
        'prim_sm_sn': _safe_common_value(devices, 'prim_sm', 'SN'),
        'sec_sm_f2_vr': _safe_common_value(devices, 'sec_sm_F2', 'Vr'),
        'sec_sm_f2_sn': _safe_common_value(devices, 'sec_sm_F2', 'SN'),
        'sec_sm_wp_vr': _safe_common_value(devices, 'sec_sm_WP', 'Vr'),
        'sec_sm_wp_sn': _safe_common_value(devices, 'sec_sm_WP', 'SN'),
        'sec_sm_f3_vr': _safe_common_value(devices, 'sec_sm_F3', 'Vr'),
        'sec_sm_f3_sn': _safe_common_value(devices, 'sec_sm_F3', 'SN'),
    }


def _collect_models_for_unit(client, unit_id):
    models = read_device_data(client, unit_id, skip_model_ids=[])
    return [m.id for m in (models or [])]


def _discover_sunspec_units(client, max_unit=10):
    """Suche SunSpec-Geraete in kleinem Unit-ID-Bereich (nur bei Versionswechsel)."""
    found = []
    for unit in range(1, max_unit + 1):
        hdr = read_registers_safe(client, 40000, 2, unit)
        if not hdr or hdr[0] != 0x5375 or hdr[1] != 0x6e53:
            continue
        models = read_device_data(client, unit, skip_model_ids=[])
        common = _extract_device_data(models or []).get('common', {})
        found.append({
            'unit': unit,
            'models': [m.id for m in (models or [])],
            'device': common.get('Md', {}).get('value'),
            'serial': common.get('SN', {}).get('value'),
            'version': common.get('Vr', {}).get('value'),
        })
    return found


def _validate_all_attachment_points(client):
    """Feste Vollpruefung aller dokumentierten API-/Register-Anknuepfungen."""
    result = {
        'timestamp': int(time.time()),
        'modbus': {},
        'solar_api': {},
        'internal_api': {},
        'discovery': [],
    }

    modbus_points = [
        ('inverter', modbus_quellen.INVERTER, [1, 103, 124, 160]),
        ('prim_sm_f1', modbus_quellen.PRIM_SM_F1, [1, 203]),
        ('sec_sm_f2', modbus_quellen.SEC_SM_F2, [1, 203]),
        ('sec_sm_wp', modbus_quellen.SEC_SM_WP, [1, 203]),
        ('sec_sm_f3', modbus_quellen.SEC_SM_F3, [1, 203]),
    ]

    for name, unit, expected in modbus_points:
        t0 = time.time()
        hdr = read_registers_safe(client, 40000, 2, unit)
        hdr_ok = bool(hdr and hdr[0] == 0x5375 and hdr[1] == 0x6e53)
        models = _collect_models_for_unit(client, unit) if hdr_ok else []
        missing_expected = [m for m in expected if m not in models]
        result['modbus'][name] = {
            'unit': unit,
            'header_ok': hdr_ok,
            'models': models,
            'missing_expected_models': missing_expected,
            'ok': hdr_ok and not missing_expected,
            'duration_ms': int((time.time() - t0) * 1000),
        }

    solar_eps = [
        '/GetPowerFlowRealtimeData.fcgi',
        '/GetInverterRealtimeData.cgi?Scope=System',
        '/GetMeterRealtimeData.cgi?Scope=System',
        '/GetStorageRealtimeData.cgi?Scope=System',
    ]
    for ep in solar_eps:
        t0 = time.time()
        try:
            r = requests.get(f'{FRONIUS_API_BASE}{ep}', timeout=4)
            result['solar_api'][ep] = {
                'status': r.status_code,
                'ok': r.status_code == 200,
                'duration_ms': int((time.time() - t0) * 1000),
            }
        except Exception as e:
            result['solar_api'][ep] = {
                'status': None,
                'ok': False,
                'error': str(e),
                'duration_ms': int((time.time() - t0) * 1000),
            }

    internal_eps = [
        ('/status/common', 200),
        ('/api/config/batteries', 401),
        ('/api/config/common', 401),
    ]
    for ep, expected_status in internal_eps:
        t0 = time.time()
        try:
            r = requests.get(f'http://{IP_ADDRESS}{ep}', timeout=4)
            has_x_auth = 'X-WWW-Authenticate' in r.headers
            ok = (r.status_code == expected_status)
            if expected_status == 401:
                ok = ok and has_x_auth
            result['internal_api'][ep] = {
                'status': r.status_code,
                'expected_status': expected_status,
                'has_x_www_auth': has_x_auth,
                'ok': ok,
                'duration_ms': int((time.time() - t0) * 1000),
            }
        except Exception as e:
            result['internal_api'][ep] = {
                'status': None,
                'expected_status': expected_status,
                'has_x_www_auth': False,
                'ok': False,
                'error': str(e),
                'duration_ms': int((time.time() - t0) * 1000),
            }

    result['discovery'] = _discover_sunspec_units(client, max_unit=10)
    return result


def _version_change_check_and_revalidate(client, devices):
    """Trigger: Versionsaenderung erkannt -> Vollpruefung + Discovery + Persistenz."""
    snapshot = _build_version_snapshot(devices)
    now = int(time.time())

    with attachment_state_lock:
        prev_snapshot = attachment_state.get('version_snapshot')

    if not snapshot.get('inverter_vr'):
        return

    # Erstinitialisierung: Snapshot speichern, keine schwere Vollpruefung erzwingen.
    if prev_snapshot is None:
        with attachment_state_lock:
            attachment_state['version_snapshot'] = snapshot
            attachment_state['last_seen_ts'] = now
            attachment_state['initialized_ts'] = now
        _save_attachment_state()
        logging.info('Attachment-State initialisiert (kein Versionsvergleich moeglich)')
        return

    if snapshot == prev_snapshot:
        with attachment_state_lock:
            attachment_state['last_seen_ts'] = now
        return

    logging.warning('Versionsaenderung erkannt -> starte Vollpruefung aller Anknuepfungspunkte')
    validation = _validate_all_attachment_points(client)

    with attachment_state_lock:
        attachment_state['previous_version_snapshot'] = prev_snapshot
        attachment_state['version_snapshot'] = snapshot
        attachment_state['last_seen_ts'] = now
        attachment_state['last_version_change_ts'] = now
        attachment_state['last_validation'] = validation

    _save_attachment_state()
    logging.warning('Vollpruefung nach Versionsaenderung abgeschlossen und gespeichert')

def parse_sunspec_string(regs):
    """Parse SunSpec String (16-Bit Werte)"""
    try:
        data = struct.pack(f'>{len(regs)}H', *regs)
        s = data.decode('ascii', errors='ignore').rstrip('\x00 ')
        return s if s else None
    except Exception as e:
        logging.debug(f"SunSpec String Parse-Fehler: {e}")
        return None

def parse_sunspec_value(regs, dtype, sf=0):
    """Parse SunSpec Wert mit Skalierungsfaktor"""
    if not regs: return None
    
    try:
        if dtype == 'uint16':
            val = regs[0]
            if val == 0xFFFF: return None
        elif dtype == 'int16':
            val = regs[0] if regs[0] < 0x8000 else regs[0] - 0x10000
            if val == -0x8000: return None
        elif dtype == 'enum16':
            # Enum: uint16 ohne Invalid-Check (Werte können 0 sein)
            val = regs[0]
            return val  # Kein Scaling, direkt zurück
        elif dtype == 'bitfield16':
            # Bitfield: uint16 ohne Invalid-Check
            val = regs[0]
            return val  # Kein Scaling
        elif dtype == 'bitfield32':
            # Bitfield 32-bit: 2 Register, kein Invalid-Check
            val = (regs[0] << 16) | regs[1]
            return val  # Kein Scaling
        elif dtype == 'uint32' or dtype == 'acc32':
            val = (regs[0] << 16) | regs[1]
            if val == 0xFFFFFFFF: return None
        elif dtype == 'int32':
            val = (regs[0] << 16) | regs[1]
            if val >= 0x80000000: val -= 0x100000000
            if val == -0x80000000: return None
        elif dtype == 'acc64':
            val = (regs[0] << 48) | (regs[1] << 32) | (regs[2] << 16) | regs[3]
            if val == 0xFFFFFFFFFFFFFFFF: return None
        elif dtype == 'sunssf':
            val = regs[0] if regs[0] < 0x8000 else regs[0] - 0x10000
            return val  # Direkt zurück, kein Scaling
        else:
            return None
        
        # Skalierung anwenden
        if sf and sf != 0:
            val = val * (10 ** sf)
        
        return val
    except Exception as e:
        logging.debug(f"SunSpec Value Parse-Fehler: {e}")
        return None

def read_device_data(client, unit_id, skip_model_ids=None):
    """Liest SunSpec Modelle von einem Gerät"""
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
        # Modell-Header lesen
        model_header = read_registers_safe(client, addr, 2, unit_id)
        if not model_header: break
        
        model_id = model_header[0]
        model_len = model_header[1]
        
        # Ende-Marker
        if model_id == 0xFFFF or model_len == 0 or model_len > 200:
            break
        
        # Überspringe Modelle, die nicht benötigt werden
        if model_id in skip_model_ids:
            addr += 2 + model_len
            continue
        
        # Modell-Daten lesen
        model_data = read_registers_safe(client, addr + 2, model_len, unit_id)
        if not model_data:
            addr += 2 + model_len
            continue
        
        # Parse Modell basierend auf ID
        parsed = parse_model(model_id, model_data)
        if parsed:
            class Model:
                def __init__(self, mid, pdata):
                    self.id = mid
                    self.parsed = pdata
            models.append(Model(model_id, parsed))
        
        addr += 2 + model_len
    
    return models

def parse_model(model_id, data):
    """Parse ein SunSpec Modell basierend auf modbus_quellen.MODELS"""
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
            regs = data[offset:offset+length]
            sf = parse_sunspec_value(regs, ftype)
            if sf is not None:
                scale_factors[fname] = sf
    
    # Dann alle Datenfelder parsen
    for field in fields:
        fname = field['field']
        ftype = field.get('type')
        offset = field.get('offset', 0)
        
        # Skip scale factors (wurden schon verarbeitet)
        if ftype == 'sunssf' or ftype == 'pad':
            continue
        
        # String
        if ftype == 'string':
            length = field.get('length', 1)
            regs = data[offset:offset+length]
            val = parse_sunspec_string(regs)
            if val:
                parsed[fname] = {'value': val, 'unit': ''}
        # Numerisch
        else:
            length = 4 if ftype in ('uint32', 'int32', 'acc32') else (2 if ftype == 'bitfield32' else (8 if ftype == 'acc64' else 1))
            if length == 8:
                length = 4  # acc64 braucht 4 Register
            
            regs = data[offset:offset+length]
            sf_name = field.get('scale')
            sf = scale_factors.get(sf_name, 0) if sf_name else 0
            
            val = parse_sunspec_value(regs, ftype, sf)
            if val is not None:
                unit = field.get('units', '')
                parsed[fname] = {'value': val, 'unit': unit}
    
    return parsed

# --- DATENBANK ---
# Kanonische DB-Verbindung aus db_utils
from db_utils import get_db_connection

def restore_energy_state():
    """Lade Energie-Akkumulatoren aus DB"""
    try:
        conn = get_db_connection()
        if not conn: return
        c = conn.cursor()
        c.execute("SELECT key, value FROM energy_state")
        rows = c.fetchall()
        conn.close()
        
        with energy_lock:
            for key, value in rows:
                if key in energy_state:
                    energy_state[key] = float(value)
        
        print(f"[INFO] Energie-State wiederhergestellt: Batt Charge={energy_state['W_Batt_charge']:.1f}Wh")
    except Exception as e:
        print(f"[WARN] Konnte Energy-State nicht laden: {e}")

def save_energy_state():
    """Speichere Energie-Akkumulatoren in DB (mit kurzem Timeout)"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return
        c = conn.cursor()
        
        with energy_lock:
            for key in ['W_PV_F1', 'W_PV_F2', 'W_PV_F3', 'W_WR_F2_consumption', 'W_WR_F3_consumption', 'W_Imp_Grid', 'W_Exp_Grid', 'W_Batt_charge', 'W_Batt_discharge']:
                c.execute("INSERT OR REPLACE INTO energy_state (key, value) VALUES (?, ?)",
                         (key, energy_state[key]))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Energy State Save Error: {e}")
    finally:
        if conn:
            conn.close()

def fetch_battery_api():
    """Hole Batterie U/I/T aus Fronius Storage API (zur Überwachung)"""
    try:
        url = f'{FRONIUS_API_BASE}/GetStorageRealtimeData.cgi?Scope=System'
        resp = requests.get(url, timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            controller = data.get('Body', {}).get('Data', {}).get('0', {}).get('Controller', {})
            return {
                'voltage': controller.get('Voltage_DC'),      # V
                'current': controller.get('Current_DC'),      # A
                'temperature': controller.get('Temperature_Cell'), # °C
                'soc': controller.get('StateOfCharge_Relative')  # %
            }
    except Exception as e:
        logging.debug(f"Battery API fetch failed: {e}")
    return {'voltage': None, 'current': None, 'temperature': None, 'soc': None}

def save_raw_data(timestamp, inv_data, sm_netz_data, sm_f2_data, sm_f3_data, sm_wp_data, p_batt, poll_dur_ms, batt_api):
    """Speichere Rohdaten in RAM-Buffer (wird alle 60s als Batch in DB geschrieben)
    
    Hinweis: p_batt wird NICHT in raw_data gespeichert (kann aus P_DC_Inv - mppt_sum berechnet werden),
             sondern nur für energy_state Akkumulation verwendet.
             batt_api liefert U_Batt_API und I_Batt_API zur Überwachung.
    """
    try:
        # Helper: Wert extrahieren
        def val(data, key, default=None):
            v = data.get(key, {}).get('value')
            return v if v is not None else default
        
        # Helper: Power Factor normalisieren (von -100..100 zu 0.0..1.0, immer positiv)
        def safe_pf(pf_val):
            if pf_val is None:
                return None
            return round(abs(pf_val) / 100.0, 3)
        
        # Daten sammeln
        inv = inv_data.get('inverter_data', {})
        mppt = inv_data.get('mppt', {})
        storage = inv_data.get('storage', {})
        sm_netz = sm_netz_data.get('meter_data', {})
        sm_f2 = sm_f2_data.get('meter_data', {})
        sm_f3 = sm_f3_data.get('meter_data', {})
        sm_wp = sm_wp_data.get('meter_data', {})
        
        # Tuple für RAM-Buffer erstellen
        record = (
            timestamp,
            # Inverter
            val(inv, 'AphA'), val(inv, 'AphB'), val(inv, 'AphC'),
            val(inv, 'PPVphAB'), val(inv, 'PPVphBC'), val(inv, 'PPVphCA'),
            val(inv, 'PhVphA'), val(inv, 'PhVphB'), val(inv, 'PhVphC'),
            val(inv, 'W'), val(inv, 'VA'), val(inv, 'VAr'), safe_pf(val(inv, 'PF')), val(inv, 'WH'),
            val(inv, 'DCW'),
            # MPPT
            val(mppt, '1_DCA'), val(mppt, '1_DCV'), val(mppt, '1_DCW'), val(mppt, '1_DCWH'),
            val(mppt, '2_DCA'), val(mppt, '2_DCV'), val(mppt, '2_DCW'), val(mppt, '2_DCWH'),
            # Battery
            val(storage, 'ChaState'), val(storage, 'ChaSt'),
            batt_api.get('voltage'), batt_api.get('current'),
            # SM Netz
            val(sm_netz, 'A'), val(sm_netz, 'AphA'), val(sm_netz, 'AphB'), val(sm_netz, 'AphC'),
            val(sm_netz, 'PhV'), val(sm_netz, 'PhVphA'), val(sm_netz, 'PhVphB'), val(sm_netz, 'PhVphC'),
            val(sm_netz, 'PPVphAB'), val(sm_netz, 'PPVphBC'), val(sm_netz, 'PPVphCA'),
            val(sm_netz, 'Hz'), val(sm_netz, 'W'), val(sm_netz, 'WphA'), val(sm_netz, 'WphB'), val(sm_netz, 'WphC'),
            val(sm_netz, 'VA'), val(sm_netz, 'VAR'), safe_pf(val(sm_netz, 'PF')),
            val(sm_netz, 'TotWhExp'), val(sm_netz, 'TotWhImp'),
            # SM F2
            val(sm_f2, 'W'), val(sm_f2, 'WphA'), val(sm_f2, 'WphB'), val(sm_f2, 'WphC'),
            val(sm_f2, 'VA'), val(sm_f2, 'VAR'), safe_pf(val(sm_f2, 'PF')),
            val(sm_f2, 'TotWhExp'), val(sm_f2, 'TotWhImp'),
            # SM WP
            val(sm_wp, 'W'), val(sm_wp, 'WphA'), val(sm_wp, 'WphB'), val(sm_wp, 'WphC'),
            val(sm_wp, 'VA'), val(sm_wp, 'VAR'), safe_pf(val(sm_wp, 'PF')),
            val(sm_wp, 'TotWhImp'),
            # SM F3
            val(sm_f3, 'W'), val(sm_f3, 'WphA'), val(sm_f3, 'WphB'), val(sm_f3, 'WphC'),
            val(sm_f3, 'VA'), val(sm_f3, 'VAR'), safe_pf(val(sm_f3, 'PF')),
            val(sm_f3, 'TotWhExp'), val(sm_f3, 'TotWhImp'),
            # Meta
            poll_dur_ms
        )
        
        # In RAM-Buffer speichern (Thread-Safe)
        with ram_buffer_lock:
            if len(ram_buffer) >= ram_buffer.maxlen:
                logging.warning(f"RAM-Buffer voll ({len(ram_buffer)}/{ram_buffer.maxlen}) — älteste Daten gehen verloren! DB-Flush hängt?")
            ram_buffer.append(record)
        
    except Exception as e:
        logging.error(f"Save Raw Data Error: {e}")

def flush_buffer_to_db():
    """Schreibt alle Daten aus RAM-Buffer in Datenbank (Batch-Write für SD Card Protection).
    Non-blocking: Bei DB-Lock schnell abbrechen → Daten bleiben im RAM-Buffer.
    """
    try:
        with ram_buffer_lock:
            if not ram_buffer:
                return  # Nichts zu schreiben
            
            # Kopiere Buffer-Inhalt für DB-Schreibvorgang
            records_to_write = list(ram_buffer)
            # Buffer wird ERST nach erfolgreichem Write geleert (s.u.)
        
        # Jetzt außerhalb des Locks in DB schreiben
        # Kurzer Timeout (1s statt 10s): Bei Lock durch Cron-Jobs schnell abbrechen
        # statt 88s die Polling-Loop zu blockieren!
        t0 = time.time()
        conn = sqlite3.connect(DB_FILE, timeout=1.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        
        c = conn.cursor()
        
        # Batch INSERT mit executemany
        c.executemany("""
            INSERT INTO raw_data (
                ts,
                -- Inverter
                I_L1_Inv, I_L2_Inv, I_L3_Inv,
                U_L1_L2_Inv, U_L2_L3_Inv, U_L3_L1_Inv,
                U_L1_N_Inv, U_L2_N_Inv, U_L3_N_Inv,
                P_AC_Inv, S_Inv, Q_Inv, PF_Inv, W_AC_Inv,
                P_DC_Inv,
                -- MPPT
                I_DC1, U_DC1, P_DC1, W_DC1,
                I_DC2, U_DC2, P_DC2, W_DC2,
                -- Battery
                SOC_Batt, ChaSt_Batt,
                U_Batt_API, I_Batt_API,
                -- SM Netz
                I_Netz, I_L1_Netz, I_L2_Netz, I_L3_Netz,
                U_Netz, U_L1_N_Netz, U_L2_N_Netz, U_L3_N_Netz,
                U_L1_L2_Netz, U_L2_L3_Netz, U_L3_L1_Netz,
                f_Netz, P_Netz, P_L1_Netz, P_L2_Netz, P_L3_Netz,
                S_Netz, Q_Netz, PF_Netz,
                W_Exp_Netz, W_Imp_Netz,
                -- SM F2
                P_F2, P_L1_F2, P_L2_F2, P_L3_F2,
                S_F2, Q_F2, PF_F2,
                W_Exp_F2, W_Imp_F2,
                -- SM WP
                P_WP, P_L1_WP, P_L2_WP, P_L3_WP,
                S_WP, Q_WP, PF_WP,
                W_Imp_WP,
                -- SM F3
                P_F3, P_L1_F3, P_L2_F3, P_L3_F3,
                S_F3, Q_F3, PF_F3,
                W_Exp_F3, W_Imp_F3,
                -- Meta
                t_poll_ms
            ) VALUES (
                ?, -- ts
                -- Inverter (15)
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                -- MPPT (8)
                ?, ?, ?, ?, ?, ?, ?, ?,
                -- Battery (4)
                ?, ?, ?, ?,
                -- SM Netz (21)
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                -- SM F2 (9)
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                -- SM WP (8)
                ?, ?, ?, ?, ?, ?, ?, ?,
                -- SM F3 (9)
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                -- Meta
                ?
            )
        """, records_to_write)
        
        conn.commit()
        conn.close()
        
        # Erst NACH erfolgreichem Write den Buffer leeren
        # (Audit 2026-02-27: vorher wurde vor dem Write geleert → Datenverlust)
        with ram_buffer_lock:
            # Entferne nur die geschriebenen Records (neue könnten hinzugekommen sein)
            for _ in range(len(records_to_write)):
                if ram_buffer:
                    ram_buffer.popleft()
        
        logging.info(f"[FLUSH] {len(records_to_write)} Datensätze in DB geschrieben")
        
    except Exception as e:
        logging.error(f"Buffer Flush Error: {e}")
        # Daten bleiben im Buffer (nicht geleert bei Fehler)

def _extract_device_data(models):
    """Extrahiert geparste Daten aus SunSpec-Modellen."""
    data = {}
    for m in models:
        if m.id == 1: data['common'] = m.parsed
        if m.id == 124: data['storage'] = m.parsed
        if m.id in (103, 113): data['inverter_data'] = m.parsed
        if m.id == 160: data['mppt'] = m.parsed
        if m.id in (201, 202, 203): data['meter_data'] = m.parsed
    return data


# --- POLLING ---
def poll_once():
    """Einmaliges Polling aller Geräte"""
    global modbus_client
    
    poll_start = time.time()
    client = None
    
    try:
        # WICHTIG: Verbindung NUR für diesen Lesezyklus öffnen!
        # Damit Modbus-Bus für WR-Kommunikation (F1<->F2<->F3) frei bleibt
        with modbus_lock:
            client = RawModbusClient(IP_ADDRESS, port=PORT, timeout=5.0)
            if not client.connect():
                logging.error("Modbus Connect Failed")
                return False
        
        time.sleep(0.1)  # Kurze Stabilisierung
        
        # Alle Geräte in Reihenfolge lesen
        POLL_DEVICES = [
            ('inverter',  modbus_quellen.INVERTER),
            ('prim_sm',   modbus_quellen.PRIM_SM_F1),
            ('sec_sm_F2', modbus_quellen.SEC_SM_F2),
            ('sec_sm_WP', modbus_quellen.SEC_SM_WP),
            ('sec_sm_F3', modbus_quellen.SEC_SM_F3),
        ]

        def _read_poll_devices(active_client):
            devices = {}
            missing_critical = []

            for dev_key, unit_id in POLL_DEVICES:
                skip_ids = [1] if dev_key in static_device_data else []
                models = read_device_data(active_client, unit_id, skip_ids)
                if dev_key == 'inverter' and not models:
                    logging.error("Inverter read failed")
                    return None, ['inverter']

                data = _extract_device_data(models or [])
                if data.get('common'):
                    with static_device_data_lock:
                        static_device_data[dev_key] = data['common']

                # F1/F2 sind kritisch fuer Gesamtfluss + Aggregation.
                # Bei Firmware-Updates kann kurzzeitig Header-Read scheitern;
                # dann erzwingen wir einen Reconnect-Retry statt NULL-Zeilen.
                if dev_key in ('prim_sm', 'sec_sm_F2') and not data.get('meter_data'):
                    missing_critical.append(dev_key)

                devices[dev_key] = data

            return devices, missing_critical

        devices, missing_critical = _read_poll_devices(client)
        if devices is None:
            return False

        if missing_critical:
            logging.warning(
                "Kritische SunSpec-Daten fehlen (%s) - Reconnect-Retry",
                ','.join(missing_critical)
            )
            with modbus_lock:
                client.close()
                client = RawModbusClient(IP_ADDRESS, port=PORT, timeout=5.0)
                if not client.connect():
                    logging.error("Modbus Reconnect Failed nach fehlendem Header")
                    return False

            time.sleep(0.1)
            devices, missing_critical_retry = _read_poll_devices(client)
            if devices is None:
                return False
            if missing_critical_retry:
                logging.error(
                    "Kritische SunSpec-Daten weiterhin fehlend (%s) - Poll verworfen",
                    ','.join(missing_critical_retry)
                )
                return False
        
        # Batterieleistung berechnen
        def get_val(dev_key, model_key, field_key, default=0):
            try:
                return devices.get(dev_key, {}).get(model_key, {}).get(field_key, {}).get('value', default)
            except Exception:
                return default
        
        dcw = get_val('inverter', 'inverter_data', 'DCW')
        dcw_1 = get_val('inverter', 'mppt', '1_DCW')
        dcw_2 = get_val('inverter', 'mppt', '2_DCW')
        p_batt = dcw - (dcw_1 + dcw_2)
        
        # Batterie U/I aus Fronius Storage API (zur Überwachung, nicht zur Berechnung)
        batt_api = fetch_battery_api()
        
        # Energie-Integration mit ECHTEM Zeitintervall
        # WICHTIG: Nicht POLL_INTERVAL (3s) annehmen! Realer Durchlauf variiert:
        # - CPU-Throttling bei Hitze: 3s → 5-10s
        # - Modbus-Timeouts: bis 57s gemessen
        # - Fronius Firmware-Updates: Antwortzeiten ändern sich
        # - Parallele battery_control.py Modbus-Writes: +0.2-0.5s
        last_poll = energy_state.get('last_poll_time')
        now = time.time()
        if last_poll and (now - last_poll) < 30:  # Max 30s, sonst war Pause/Restart
            dt_hours = (now - last_poll) / 3600.0
        else:
            dt_hours = POLL_INTERVAL / 3600.0  # Fallback beim ersten Poll / nach Restart
        
        with energy_lock:
            # PV F1 (MPPT1 + MPPT2) - DC-Leistung mit Wirkungsgrad-Korrektur + WR-Eigenverbrauch
            # Typischer WR-Wirkungsgrad: 97% (DC->AC Verluste)
            # WR-Eigenverbrauch: 40W im Betrieb, 10W Standby (nachts)
            pv_f1_dc_w = dcw_1 + dcw_2
            wr_f1_consumption = 40 if pv_f1_dc_w > 50 else 10  # Betrieb vs. Standby
            pv_f1_w = max(0, pv_f1_dc_w * 0.97 - wr_f1_consumption)  # AC-äquivalent nach Verlusten & WR-Eigenverbrauch
            energy_state['W_PV_F1'] += pv_f1_w * dt_hours
            
            # PV F2 - Erzeugung positiv zählen, Verbrauch (nachts) separat tracken
            pv_f2_w = get_val('sec_sm_F2', 'meter_data', 'W')
            if pv_f2_w > 0:
                energy_state['W_PV_F2'] += pv_f2_w * dt_hours
            else:
                # Negativer Wert = WR-Verbrauch (nachts)
                energy_state['W_WR_F2_consumption'] += abs(pv_f2_w) * dt_hours
            
            # PV F3 - Erzeugung positiv zählen, Verbrauch (nachts) separat tracken
            pv_f3_w = get_val('sec_sm_F3', 'meter_data', 'W')
            if pv_f3_w > 0:
                energy_state['W_PV_F3'] += pv_f3_w * dt_hours
            else:
                # Negativer Wert = WR-Verbrauch (nachts)
                energy_state['W_WR_F3_consumption'] += abs(pv_f3_w) * dt_hours
            
            # Grid
            grid_w = get_val('prim_sm', 'meter_data', 'W')
            if grid_w > 0:
                energy_state['W_Imp_Grid'] += grid_w * dt_hours
            else:
                energy_state['W_Exp_Grid'] += abs(grid_w) * dt_hours
            
            # Batterie - gesteuert über ChaSt (Charge State)
            # ChaSt=3: Entladung, ChaSt=4: Ladung
            batt_charge_state = get_val('inverter', 'storage', 'ChaSt')
            w_batt = abs(p_batt) * dt_hours  # Absolute Energie
            
            if batt_charge_state == 3:
                # Entladung (ChaSt=3)
                energy_state['W_Batt_discharge'] += w_batt
            elif batt_charge_state == 4:
                # Ladung (ChaSt=4)
                energy_state['W_Batt_charge'] += w_batt
            
            energy_state['last_poll_time'] = time.time()
        
        # WICHTIG: Verbindung schließen BEVOR Zeitmessung!
        # Damit Connect+Read+Close in t_poll_ms erfasst wird
        if client:
            with modbus_lock:
                client.close()
        
        # Speichern (poll_dur_ms enthält jetzt kompletten Zyklus)
        poll_end = time.time()
        poll_dur_ms = int((poll_end - poll_start) * 1000)
        
        save_raw_data(
            poll_end,
            devices['inverter'],
            devices['prim_sm'],
            devices['sec_sm_F2'],
            devices['sec_sm_F3'],
            devices['sec_sm_WP'],
            p_batt,
            poll_dur_ms,
            batt_api
        )
        
        # Cache aktualisieren
        with sunspec_cache_lock:
            sunspec_cache['devices'] = devices
            sunspec_cache['last_update'] = poll_end

        # Versionswechsel-Trigger: feste Vollpruefung + Discovery + Persistenz
        _version_change_check_and_revalidate(client, devices)
        
        # Energy State alle 60s speichern
        if int(poll_end) % 60 < POLL_INTERVAL:
            save_energy_state()
        
        return True
        
    except Exception as e:
        logging.error(f"Poll Error: {e}")
        return False
    
    finally:
        # Sicherheitsnetz: Falls Exception vor normalem close()
        if client:
            try:
                with modbus_lock:
                    # Nur schließen falls noch verbunden
                    if hasattr(client, 'sock') and client.sock:
                        client.close()
            except Exception:
                pass

def cleanup_db():
    """Lösche alte Daten gemäß Retention-Policies aus config.py"""
    conn = None
    try:
        now = time.time()
        
        conn = get_db_connection()
        if not conn: return
        c = conn.cursor()
        
        # Retention-Policies (monthly/yearly: PERMANENT)
        RETENTION = [
            ('raw_data',    config.RAW_DATA_RETENTION_DAYS),
            ('data_1min',   config.DATA_1MIN_RETENTION_DAYS),
            ('data_15min',  config.DATA_15MIN_RETENTION_DAYS),
            ('hourly_data', config.HOURLY_RETENTION_DAYS),
            ('daily_data',  config.DAILY_RETENTION_DAYS),
        ]
        
        deleted = {}
        for table, days in RETENTION:
            limit = now - (days * 86400)
            c.execute(f"DELETE FROM {table} WHERE ts < ?", (limit,))
            deleted[table] = c.rowcount
        
        conn.commit()
        
        # WAL-Checkpoint statt VACUUM (VACUUM blockiert auf tmpfs alles, ist sinnlos im RAM)
        total_deleted = sum(deleted.values())
        if total_deleted > 1000:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        
        if total_deleted > 0:
            parts = ', '.join(f"{t}={n}" for t, n in deleted.items() if n > 0)
            print(f"[INFO] Cleanup: {parts}")
    except Exception as e:
        logging.error(f"Cleanup Error: {e}")
    finally:
        if conn:
            conn.close()

def poller_loop():
    """Haupt-Polling-Schleife"""
    print("[INFO] Poller gestartet")
    
    # tmpfs-DB sicherstellen (NVMe → RAM beim Boot)
    if not db_init.ensure_tmpfs_db():
        logging.error("tmpfs-DB konnte nicht initialisiert werden!")
        return
    
    # Persist-Thread: tmpfs → SD-Card alle 5min (Crash-Sicherheit)
    db_init.start_persist_thread()
    
    # PID-File-Schutz: Nur eine Instanz erlaubt
    create_pid_file()

    # Persistierten Versions-/Anknuepfungszustand laden
    _load_attachment_state()
    
    restore_energy_state()
    
    poll_errors = 0
    last_flush = time.time()
    last_cleanup = time.time()
    
    while True:
        try:
            loop_start = time.time()
            
            if not poll_once():
                poll_errors += 1
                if poll_errors > 5:
                    logging.error("Zu viele Fehler hintereinander")
                    poll_errors = 0
                    time.sleep(10)  # Längere Pause bei wiederholten Fehlern
            else:
                poll_errors = 0
            
            # Zeitbasierte Trigger
            now = time.time()
            
            # Flush Buffer (SD Card Protection)
            if now - last_flush >= config.FLUSH_INTERVAL:
                t0 = time.time()
                flush_buffer_to_db()
                flush_dur = time.time() - t0
                if flush_dur > 5.0:
                    logging.warning(f"[TIMING] flush_buffer_to_db dauerte {flush_dur:.1f}s!")
                last_flush = now
            
            # ENTFERNT: Aggregation aus Collector entfernt (verursacht 88s-Lücken in raw_data).
            # 15min + hourly Aggregation laufen via Cron:
            #   aggregate.py      → 0,15,30,45 * * * *
            #   aggregate_1min.py → * * * * * (inkl. Backfill)
            
            # Cleanup alle 1h
            if now - last_cleanup >= 3600:
                cleanup_db()
                last_cleanup = now
            
            # Loop-Timing überwachen (Lücken-Diagnose)
            loop_dur = time.time() - loop_start
            if loop_dur > 10.0:
                logging.warning(f"[TIMING] Polling-Loop dauerte {loop_dur:.1f}s (>10s)!")
            
            time.sleep(POLL_INTERVAL)
            
        except KeyboardInterrupt:
            # Bei Programmende noch ausstehende Daten schreiben
            print("[INFO] Schreibe verbleibende Daten...")
            flush_buffer_to_db()
            break
        except Exception as e:
            logging.error(f"Poller Error: {e}")
            time.sleep(5)

