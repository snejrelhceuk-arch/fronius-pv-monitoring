#!/usr/bin/env python3
"""
battery_control.py — Batterie-Diagnose und -Steuerung via SunSpec Model 124

Liest und schreibt Storage-Register des Fronius Symo Hybrid / Gen24.
BYD HVS 10,2 kWh (LFP-Chemie, Hochvolt).

Basiert auf: Fronius Register Map Int&SF v1.0 with SYMOHYBRID MODEL 124
Quelle: ~/Downloads/SM 1.0/SE_EI_Modbus_Sunspec_Maps_State_Codes_Events/

Absolute Register-Adressen (Model 124, Unit 1):
  40304  ID           R   = 124
  40305  L            R   = 24
  40306  WChaMax      R   Max. Ladeleistung [W]
  40307  WChaGra      R   Max. Ladegeschwindigkeit [% WChaMax/sec]
  40308  WDisChaGra   R   Max. Entladegeschwindigkeit [% WChaMax/sec]
  40309  StorCtl_Mod  RW  Steuerungsmodus (Bit 0=CHARGE, Bit 1=DISCHARGE)
  40310  VAChaMax     R   Max. Lade-VA (not supported)
  40311  MinRsvPct    RW  Minimale Reserve [% AhrRtg]
  40312  ChaState     R   Verfügbare Energie [% AhrRtg]  (= SOC)
  40313  StorAval     R   SOC minus Reserve (not supported)
  40314  InBatV       R   Batterie-Spannung [V] (not supported)
  40315  ChaSt        R   Ladestatus (1=OFF,2=EMPTY,3=DISCHARGE,4=CHARGE,5=FULL,6=HOLD,7=TEST)
  40316  OutWRte      RW  Entladerate [% WChaMax]  (-10000..+10000, SF=-2)
  40317  InWRte       RW  Laderate [% WChaMax]  (-10000..+10000, SF=-2)
  40318  InOutWRte_WinTms   R   (not supported)
  40319  InOutWRte_RvrtTms  R   (not supported)
  40320  InOutWRte_RmpTms   R   (not supported)
  40321  ChaGriSet    RW  Netzladung (0=PV only, 1=Grid erlaubt)
  40322  WChaMax_SF   R   Scale Factor
  40323  WChaDisChaGra_SF R Scale Factor
  40324  VAChaMax_SF  R   (not supported)
  40325  MinRsvPct_SF R   = -2
  40326  ChaState_SF  R   = -2
  40327  StorAval_SF  R   (not supported)
  40328  InBatV_SF    R   (not supported)
  40329  InOutWRte_SF R   = -2

Schreibbare Register (Function Codes 0x03 Read, 0x06 Write Single, 0x10 Write Multiple):
  40309  StorCtl_Mod  — Hauptschalter: Bit 0 = Charge-Limit aktiv, Bit 1 = Discharge-Limit aktiv
  40311  MinRsvPct    — Minimale Reserve (SOC-Untergrenze)
  40316  OutWRte      — Entladerate begrenzen
  40317  InWRte       — Laderate begrenzen
  40321  ChaGriSet    — Netzladung ein/aus

Nutzung:
  python3 battery_control.py                     # Status anzeigen
  python3 battery_control.py --set-min-soc 15    # Min-Reserve auf 15% setzen
  python3 battery_control.py --set-charge 50     # Laderate auf 50% begrenzen
  python3 battery_control.py --set-discharge 80  # Entladerate auf 80% begrenzen
  python3 battery_control.py --hold               # Batterie halten (kein Laden/Entladen)
  python3 battery_control.py --auto               # Zurück auf Automatik
  python3 battery_control.py --grid-charge on     # Netzladung erlauben
  python3 battery_control.py --grid-charge off    # Netzladung verbieten
"""

import struct
import socket
import sys
import argparse
import time

# Sicherstellen dass UTF-8 Ausgabe funktioniert (RPi5 hat manchmal latin-1 locale)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# --- Konfiguration (aus zentraler config.py) ---
IP_ADDRESS = config.INVERTER_IP    # Alias für Rückwärtskompatibilität
PORT = config.MODBUS_PORT          # (battery_scheduler importiert IP_ADDRESS, PORT)
UNIT_ID = 1

# --- Model-Adressen (aus SunSpec Model Chain Scan) ---
# Gescannt am Live-Inverter, Unit 1:
#   40002  Model   1 (Common)       Len=65   Data@40004
#   40069  Model 103 (Inverter 3Ph) Len=50   Data@40071
#   40121  Model 120 (Nameplate)    Len=26   Data@40123
#   40149  Model 121 (Basic Set.)   Len=30   Data@40151
#   40181  Model 122 (Extended)     Len=44   Data@40183
#   40227  Model 123 (Immediate)    Len=24   Data@40229
#   40253  Model 160 (MultiMPPT)    Len=88   Data@40255
#   40343  Model 124 (STORAGE)      Len=24   Data@40345
#   40369  END MARKER (0xFFFF)

MODEL_124_ID   = 40343   # ID-Register von Model 124
MODEL_124_DATA = 40345   # Erstes Datenregister (nach ID + Len)

# Absolute Adressen = MODEL_124_DATA + offset aus modbus_quellen.py
REG = {
    'ID':              40343,
    'L':               40344,
    'WChaMax':         40345,   # offset 0
    'WChaGra':         40346,   # offset 1
    'WDisChaGra':      40347,   # offset 2
    'StorCtl_Mod':     40348,   # offset 3, RW bitfield16
    'VAChaMax':        40349,   # offset 4
    'MinRsvPct':       40350,   # offset 5, RW uint16
    'ChaState':        40351,   # offset 6, SOC
    'StorAval':        40352,   # offset 7
    'InBatV':          40353,   # offset 8
    'ChaSt':           40354,   # offset 9, Ladestatus enum
    'OutWRte':         40355,   # offset 10, RW int16 (Entladerate)
    'InWRte':          40356,   # offset 11, RW int16 (Laderate)
    'InOutWRte_WinTms':  40357, # offset 12
    'InOutWRte_RvrtTms': 40358, # offset 13
    'InOutWRte_RmpTms':  40359, # offset 14
    'ChaGriSet':       40360,   # offset 15, RW enum16
    'WChaMax_SF':      40361,   # offset 16
    'WChaDisChaGra_SF': 40362,  # offset 17
    'VAChaMax_SF':     40363,   # offset 18
    'MinRsvPct_SF':    40364,   # offset 19, = -2
    'ChaState_SF':     40365,   # offset 20, = -2
    'StorAval_SF':     40366,   # offset 21
    'InBatV_SF':       40367,   # offset 22
    'InOutWRte_SF':    40368,   # offset 23, = -2
}

# Model 120 Nameplate: Data@40123 (Len=26)
# Offsets aus modbus_quellen.py: WHRtg=17, AhrRtg=19, MaxChaRte=21, MaxDisChaRte=23
REG_120 = {
    'WHRtg':           40140,   # offset 17: Nominale Energiekapazitaet [Wh]
    'WHRtg_SF':        40141,   # offset 18
    'AhrRtg':          40142,   # offset 19: Nutzbare Kapazitaet [Ah]
    'AhrRtg_SF':       40143,   # offset 20
    'MaxChaRte':       40144,   # offset 21: Max. Laderate [W]
    'MaxChaRte_SF':    40145,   # offset 22
    'MaxDisChaRte':    40146,   # offset 23: Max. Entladerate [W]
    'MaxDisChaRte_SF': 40147,   # offset 24
}

# Fronius-spezifische Register (relative Offsets, nicht in SunSpec Chain)
# Zugriff auf diese muss noch verifiziert werden
REG_FRONIUS = {
    'F_Storage_Restrictions_View_Mode': 217,  # RW: 0=Total, 1=Inverter only
}

# Ladestatus-Bezeichnungen
CHAST_NAMES = {
    1: 'OFF',
    2: 'EMPTY',
    3: 'DISCHARGING',
    4: 'CHARGING',
    5: 'FULL',
    6: 'HOLDING',
    7: 'TESTING',
}

# StorCtl_Mod Bits
STORCTL_CHARGE    = 0x01  # Bit 0: Charge-Limit aktiv
STORCTL_DISCHARGE = 0x02  # Bit 1: Discharge-Limit aktiv


class ModbusClient:
    """Minimaler Modbus TCP Client mit Lese- und Schreibfunktion"""

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
            print(f"[FEHLER] Verbindung fehlgeschlagen: {e}")
            self.sock = None
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

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

    def read_holding_registers(self, address, count):
        """Modbus Function Code 0x03 — Read Holding Registers"""
        if not self.sock:
            return None
        self.tid = (self.tid + 1) & 0xFFFF

        req = struct.pack('>HHHBBHH', self.tid, 0, 6, UNIT_ID, 3, address, count)
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
                err_code = body[1] if len(body) > 1 else '?'
                print(f"[FEHLER] Modbus Exception bei Reg {address}: Code {err_code}")
                return None
            byte_count = body[1]
            if len(body) < 2 + byte_count:
                return None
            values = struct.unpack(f'>{byte_count // 2}H', body[2:2 + byte_count])
            return list(values)
        except Exception as e:
            print(f"[FEHLER] Lesen fehlgeschlagen Reg {address}: {e}")
            self.close()
            return None

    def write_single_register(self, address, value):
        """Modbus Function Code 0x06 — Write Single Register"""
        if not self.sock:
            return False
        self.tid = (self.tid + 1) & 0xFFFF

        # Für signed int16: Konvertiere negative Werte
        if value < 0:
            value = value & 0xFFFF

        req = struct.pack('>HHHBBHH', self.tid, 0, 6, UNIT_ID, 6, address, value)
        try:
            self.sock.sendall(req)
            resp = self._recv(12)
            if len(resp) < 12:
                print(f"[FEHLER] Keine gültige Antwort beim Schreiben Reg {address}")
                return False
            # Parse response
            r_tid, r_proto, r_len, r_uid, r_func, r_addr, r_val = struct.unpack('>HHHBBHH', resp)
            if r_func >= 0x80:
                print(f"[FEHLER] Modbus Exception beim Schreiben Reg {address}: Code {r_func}")
                return False
            if r_addr == address and r_val == (value & 0xFFFF):
                return True
            else:
                print(f"[WARN] Unerwartete Antwort: Addr={r_addr}, Val={r_val}")
                return True  # Trotzdem OK, manche Inverter antworten anders
        except Exception as e:
            print(f"[FEHLER] Schreiben fehlgeschlagen Reg {address}: {e}")
            self.close()
            return False


def read_raw(client, addr):
    """Liest ein einzelnes Register (raw uint16)"""
    result = client.read_holding_registers(addr, 1)
    return result[0] if result else None


def read_int16(client, addr):
    """Liest ein einzelnes Register als signed int16"""
    raw = read_raw(client, addr)
    if raw is None:
        return None
    return raw if raw < 0x8000 else raw - 0x10000


def read_scaled(client, addr, sf_addr):
    """Liest einen Wert mit Scale Factor"""
    raw = read_raw(client, addr)
    sf_raw = read_raw(client, sf_addr)
    if raw is None:
        return None, raw, sf_raw
    if sf_raw is None:
        return raw, raw, sf_raw

    # Scale Factor ist signed int16
    sf = sf_raw if sf_raw < 0x8000 else sf_raw - 0x10000
    scaled = raw * (10 ** sf)
    return scaled, raw, sf


def read_int16_scaled(client, addr, sf_addr):
    """Liest einen signed int16 Wert mit Scale Factor"""
    raw = read_int16(client, addr)
    sf_raw = read_raw(client, sf_addr)
    if raw is None:
        return None, raw, sf_raw

    sf = sf_raw if sf_raw < 0x8000 else sf_raw - 0x10000
    scaled = raw * (10 ** sf)
    return scaled, raw, sf


def print_status(client):
    """Zeigt kompletten Batterie-Status"""
    print("=" * 65)
    print("  BYD HVS 10,2 kWh - Batterie-Status via SunSpec Model 124")
    print("=" * 65)

    # Prüfe Model 124 Präsenz
    model_id = read_raw(client, REG['ID'])
    if model_id != 124:
        print(f"\n[FEHLER] Model 124 nicht an erwartet Adresse! ID={model_id}")
        print("  Tipp: modbus_scan.py ausführen um Modelladressen zu finden")
        return False

    # --- Nameplate (Model 120) ---
    print("\n── Nameplate (Model 120) ──────────────────────────────────")
    wh_rtg, wh_raw, wh_sf = read_scaled(client, REG_120['WHRtg'], REG_120['WHRtg_SF'])
    ahr_rtg, ahr_raw, ahr_sf = read_scaled(client, REG_120['AhrRtg'], REG_120['AhrRtg_SF'])
    max_cha, mc_raw, mc_sf = read_scaled(client, REG_120['MaxChaRte'], REG_120['MaxChaRte_SF'])
    max_dis, md_raw, md_sf = read_scaled(client, REG_120['MaxDisChaRte'], REG_120['MaxDisChaRte_SF'])

    if wh_rtg is not None:
        print(f"  Nennkapazität:        {wh_rtg:,.0f} Wh  ({wh_rtg/1000:.1f} kWh)  [raw={wh_raw}, SF={wh_sf}]")
    if ahr_rtg is not None and ahr_raw != 65535:  # 0xFFFF = not implemented
        print(f"  Nutzbare Kapazitaet:  {ahr_rtg:,.1f} Ah  [raw={ahr_raw}, SF={ahr_sf}]")
    if max_cha is not None:
        print(f"  Max. Laderate:        {max_cha:,.0f} W  [raw={mc_raw}, SF={mc_sf}]")
    if max_dis is not None:
        print(f"  Max. Entladerate:     {max_dis:,.0f} W  [raw={md_raw}, SF={md_sf}]")

    # --- Storage Control (Model 124) ---
    print("\n── Storage Status (Model 124) ─────────────────────────────")

    # SOC
    soc, soc_raw, soc_sf = read_scaled(client, REG['ChaState'], REG['ChaState_SF'])
    if soc is not None:
        bar_len = int(soc / 5)
        bar = '█' * bar_len + '░' * (20 - bar_len)
        print(f"  SOC:                  {soc:.1f}%  [{bar}]  [raw={soc_raw}, SF={soc_sf}]")

    # Ladestatus
    chast_raw = read_raw(client, REG['ChaSt'])
    if chast_raw is not None:
        chast_name = CHAST_NAMES.get(chast_raw, f'UNBEKANNT({chast_raw})')
        print(f"  Ladestatus:           {chast_name}  (Code {chast_raw})")

    # WChaMax (max. Ladeleistung Setpoint)
    wcha_max, wcha_raw, wcha_sf = read_scaled(client, REG['WChaMax'], REG['WChaMax_SF'])
    if wcha_max is not None:
        print(f"  WChaMax (Setpoint):   {wcha_max:,.0f} W  [raw={wcha_raw}, SF={wcha_sf}]")

    # Batterie-Spannung
    inbatv, inbatv_raw, inbatv_sf = read_scaled(client, REG['InBatV'], REG['InBatV_SF'])
    if inbatv is not None and inbatv > 0:
        print(f"  Batterie-Spannung:    {inbatv:.1f} V  [raw={inbatv_raw}, SF={inbatv_sf}]")

    # --- Steuerregister ---
    print("\n── Steuerregister (RW) ────────────────────────────────────")

    # StorCtl_Mod
    storctl = read_raw(client, REG['StorCtl_Mod'])
    if storctl is not None:
        charge_active = bool(storctl & STORCTL_CHARGE)
        discharge_active = bool(storctl & STORCTL_DISCHARGE)
        mode_str = "AUTOMATIK"
        if storctl == 0:
            mode_str = "AUTOMATIK (keine Limits aktiv)"
        elif storctl == 1:
            mode_str = "CHARGE-LIMIT aktiv"
        elif storctl == 2:
            mode_str = "DISCHARGE-LIMIT aktiv"
        elif storctl == 3:
            mode_str = "CHARGE + DISCHARGE Limits aktiv"
        print(f"  StorCtl_Mod:          {storctl}  → {mode_str}")
        print(f"    Bit 0 (Charge):     {'AKTIV' if charge_active else 'inaktiv'}")
        print(f"    Bit 1 (Discharge):  {'AKTIV' if discharge_active else 'inaktiv'}")

    # MinRsvPct (Minimum-Reserve)
    minrsv, minrsv_raw, minrsv_sf = read_scaled(client, REG['MinRsvPct'], REG['MinRsvPct_SF'])
    if minrsv is not None:
        print(f"  MinRsvPct (Reserve):  {minrsv:.1f}%  [raw={minrsv_raw}, SF={minrsv_sf}]")

    # InWRte (Laderate)
    inwrte, inwrte_raw, inwrte_sf = read_int16_scaled(client, REG['InWRte'], REG['InOutWRte_SF'])
    if inwrte is not None:
        print(f"  InWRte (Laderate):    {inwrte:.2f}% von WChaMax  [raw={inwrte_raw}, SF={inwrte_sf}]")

    # OutWRte (Entladerate)
    outwrte, outwrte_raw, outwrte_sf = read_int16_scaled(client, REG['OutWRte'], REG['InOutWRte_SF'])
    if outwrte is not None:
        print(f"  OutWRte (Entladerate): {outwrte:.2f}% von WChaMax  [raw={outwrte_raw}, SF={outwrte_sf}]")

    # ChaGriSet (Netzladung)
    chagri = read_raw(client, REG['ChaGriSet'])
    if chagri is not None:
        gri_str = "PV only (Netzladung AUS)" if chagri == 0 else "GRID (Netzladung EIN)"
        print(f"  ChaGriSet:            {chagri}  → {gri_str}")

    # Timeouts (informativ)
    wintms = read_raw(client, REG['InOutWRte_WinTms'])
    rvrttms = read_raw(client, REG['InOutWRte_RvrtTms'])
    rmptms = read_raw(client, REG['InOutWRte_RmpTms'])
    print(f"\n── Timeouts (Read-Only, Fronius: not supported) ──────────")
    print(f"  WinTms:   {wintms}   RvrtTms: {rvrttms}   RmpTms: {rmptms}")

    # Fronius proprietary Register (nicht via SunSpec Chain erreichbar)
    # Reg 217 (F_Storage_Restrictions_View_Mode) liegt im Fronius-eigenen
    # Adressbereich und braucht spezielle Behandlung - hier uebersprungen
    print(f"\n── Hinweis ────────────────────────────────────────────────")
    print(f"  RvrtTms=0: Kein Auto-Revert! Geschriebene Werte bleiben")
    print(f"  bis zum naechsten Schreibvorgang/Neustart bestehen.")

    print("\n" + "=" * 65)
    return True


def set_min_reserve(client, percent):
    """Setzt minimale SOC-Reserve"""
    # MinRsvPct_SF = -2, also raw = percent * 100
    sf = read_raw(client, REG['MinRsvPct_SF'])
    if sf is None:
        print("[FEHLER] Kann MinRsvPct_SF nicht lesen")
        return False
    sf_val = sf if sf < 0x8000 else sf - 0x10000
    raw_value = int(percent * (10 ** (-sf_val)))
    print(f"  Schreibe MinRsvPct: {percent}% → raw={raw_value} (SF={sf_val})")
    return client.write_single_register(REG['MinRsvPct'], raw_value)


def set_charge_rate(client, percent):
    """Setzt Laderate (0-100%)"""
    sf = read_raw(client, REG['InOutWRte_SF'])
    if sf is None:
        return False
    sf_val = sf if sf < 0x8000 else sf - 0x10000
    raw_value = int(percent * (10 ** (-sf_val)))
    # Aktiviere Charge-Limit in StorCtl_Mod
    storctl = read_raw(client, REG['StorCtl_Mod']) or 0
    storctl |= STORCTL_CHARGE
    print(f"  Schreibe InWRte: {percent}% → raw={raw_value} (SF={sf_val})")
    print(f"  Aktiviere StorCtl_Mod Bit 0 (Charge): {storctl}")
    ok1 = client.write_single_register(REG['InWRte'], raw_value)
    ok2 = client.write_single_register(REG['StorCtl_Mod'], storctl)
    return ok1 and ok2


def set_discharge_rate(client, percent):
    """Setzt Entladerate (0-100%)"""
    sf = read_raw(client, REG['InOutWRte_SF'])
    if sf is None:
        return False
    sf_val = sf if sf < 0x8000 else sf - 0x10000
    raw_value = int(percent * (10 ** (-sf_val)))
    # Aktiviere Discharge-Limit in StorCtl_Mod
    storctl = read_raw(client, REG['StorCtl_Mod']) or 0
    storctl |= STORCTL_DISCHARGE
    print(f"  Schreibe OutWRte: {percent}% → raw={raw_value} (SF={sf_val})")
    print(f"  Aktiviere StorCtl_Mod Bit 1 (Discharge): {storctl}")
    ok1 = client.write_single_register(REG['OutWRte'], raw_value)
    ok2 = client.write_single_register(REG['StorCtl_Mod'], storctl)
    return ok1 and ok2


def hold_battery(client):
    """Hält Batterie (Laderate UND Entladerate auf 0%)"""
    sf = read_raw(client, REG['InOutWRte_SF'])
    if sf is None:
        return False
    # Beide Raten auf 0
    ok1 = client.write_single_register(REG['InWRte'], 0)
    ok2 = client.write_single_register(REG['OutWRte'], 0)
    # Beide Bits aktivieren
    ok3 = client.write_single_register(REG['StorCtl_Mod'], STORCTL_CHARGE | STORCTL_DISCHARGE)
    print(f"  Batterie GEHALTEN: InWRte=0, OutWRte=0, StorCtl_Mod=3")
    return ok1 and ok2 and ok3


def auto_battery(client):
    """Zurück auf Automatik"""
    # StorCtl_Mod auf 0 = keine Limits aktiv
    ok = client.write_single_register(REG['StorCtl_Mod'], 0)
    print(f"  Batterie AUTOMATIK: StorCtl_Mod=0 (alle Limits deaktiviert)")
    return ok


def set_grid_charge(client, enabled):
    """Netzladung ein/ausschalten"""
    value = 1 if enabled else 0
    gri_str = "EIN (Grid)" if enabled else "AUS (PV only)"
    print(f"  Schreibe ChaGriSet: {value} → Netzladung {gri_str}")
    return client.write_single_register(REG['ChaGriSet'], value)


def main():
    parser = argparse.ArgumentParser(
        description='BYD HVS Batterie-Steuerung via Fronius SunSpec Model 124',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s                        Status anzeigen
  %(prog)s --set-min-soc 15       Min-Reserve auf 15%%
  %(prog)s --set-charge 50        Laderate auf 50%%
  %(prog)s --set-discharge 80     Entladerate auf 80%%
  %(prog)s --hold                 Batterie halten (kein Laden/Entladen)
  %(prog)s --auto                 Zurück auf Automatik
  %(prog)s --grid-charge off      Netzladung verbieten
        """)

    parser.add_argument('--set-min-soc', type=float, metavar='PCT',
                        help='Minimale SOC-Reserve setzen (0-100%%)')
    parser.add_argument('--set-charge', type=float, metavar='PCT',
                        help='Laderate begrenzen (0-100%% von WChaMax)')
    parser.add_argument('--set-discharge', type=float, metavar='PCT',
                        help='Entladerate begrenzen (0-100%% von WChaMax)')
    parser.add_argument('--hold', action='store_true',
                        help='Batterie halten (kein Laden/Entladen)')
    parser.add_argument('--auto', action='store_true',
                        help='Zurück auf Automatik (alle Limits deaktivieren)')
    parser.add_argument('--grid-charge', choices=['on', 'off'],
                        help='Netzladung ein/ausschalten')
    parser.add_argument('--ip', default=IP_ADDRESS,
                        help=f'Inverter IP (default: {IP_ADDRESS})')
    parser.add_argument('--confirm', action='store_true',
                        help='Schreiboperationen ohne Rückfrage ausführen')

    args = parser.parse_args()

    # Erkenne ob Schreiboperation gewünscht
    is_write = any([
        args.set_min_soc is not None,
        args.set_charge is not None,
        args.set_discharge is not None,
        args.hold,
        args.auto,
        args.grid_charge is not None,
    ])

    # Verbinden
    client = ModbusClient(args.ip, PORT)
    if not client.connect():
        sys.exit(1)

    try:
        time.sleep(0.1)

        # Immer Status anzeigen
        if not print_status(client):
            sys.exit(1)

        if not is_write:
            return

        # Schreiboperationen
        print("\n── Schreiboperationen ─────────────────────────────────────")

        if not args.confirm:
            print("\n  ⚠️  ACHTUNG: Schreibzugriff auf Wechselrichter!")
            print("  Falsche Werte können die Batterie schädigen.")
            print("  Fügen Sie --confirm hinzu um ohne Rückfrage auszuführen.")
            answer = input("\n  Fortfahren? [j/N] ")
            if answer.lower() not in ('j', 'ja', 'y', 'yes'):
                print("  Abgebrochen.")
                return

        success = True

        if args.auto:
            success = auto_battery(client) and success

        if args.hold:
            success = hold_battery(client) and success

        if args.set_min_soc is not None:
            if not 0 <= args.set_min_soc <= 100:
                print(f"  [FEHLER] --set-min-soc muss zwischen 0 und 100 liegen")
                success = False
            else:
                success = set_min_reserve(client, args.set_min_soc) and success

        if args.set_charge is not None:
            if not 0 <= args.set_charge <= 100:
                print(f"  [FEHLER] --set-charge muss zwischen 0 und 100 liegen")
                success = False
            else:
                success = set_charge_rate(client, args.set_charge) and success

        if args.set_discharge is not None:
            if not 0 <= args.set_discharge <= 100:
                print(f"  [FEHLER] --set-discharge muss zwischen 0 und 100 liegen")
                success = False
            else:
                success = set_discharge_rate(client, args.set_discharge) and success

        if args.grid_charge is not None:
            success = set_grid_charge(client, args.grid_charge == 'on') and success

        if success:
            print("\n  ✅ Alle Schreiboperationen erfolgreich")
            # Kurz warten und neuen Status lesen
            time.sleep(1.0)
            print("\n── Neuer Status nach Änderung ─────────────────────────────")
            print_status(client)
        else:
            print("\n  ❌ Mindestens eine Schreiboperation fehlgeschlagen")

    finally:
        client.close()


if __name__ == '__main__':
    main()
