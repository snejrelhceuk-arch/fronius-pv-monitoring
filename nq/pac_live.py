"""nq.pac_live — read-only Live-Snapshot des Siemens PAC4200 (Rolle N).

Verwendet den dependency-freien ``RawModbusClient`` des Collectors (kein
pymodbus) und liest ausschliesslich (Modbus FC3). Kein Schreibpfad zum Geraet.

Registerkarte **verifiziert gegen das reale Geraet** (192.0.2.111) am
2026-07-11: Messwertblock ab Adresse 1 (FLOAT32, big-endian, High-Word zuerst),
Energiezaehler ab Adresse 801 (FLOAT64). Siehe doc/netzqualitaet/MESSTECHNIK.md.

Genutzt von:
- der read-only Web-Anzeige (Rolle B, analog ``FroniusReadOnly``) und
- dem Feldtest/Collector (Rolle N).
"""
from __future__ import annotations

import math
import os
import struct
import time

from collector.modbus_client import RawModbusClient, read_registers_safe

try:
    import config
    _CFG_HOST = getattr(config, "PAC_IP", "192.0.2.111")
    _DEFAULT_PORT = getattr(config, "PAC_MODBUS_PORT", 502)
    _DEFAULT_UNIT = getattr(config, "PAC_UNIT_ID", 1)
except Exception:  # pragma: no cover - config immer vorhanden
    _CFG_HOST, _DEFAULT_PORT, _DEFAULT_UNIT = "192.0.2.111", 502, 1

# Host-Auflösung: ENV (systemd EnvironmentFile=.infra.local -> PV_PAC_IP) hat
# Vorrang, damit der Tech-Collector ohne config.py-Änderung deploybar ist;
# sonst config.PAC_IP (Primary). Kein Platzhalter im Betrieb.
_DEFAULT_HOST = os.environ.get("PV_PAC_IP") or _CFG_HOST

# --- Verifizierter Messwertblock (FLOAT32, offset = Modbus-Adresse) ----------
# Block A (Adr. 1..73): Betriebswerte. THD @43/45/47 = THD-U **L-L** (nicht L-N!).
# name -> (adresse, einheit)
FLOAT_MAP: dict[str, tuple[int, str]] = {
    "U_L1N": (1, "V"), "U_L2N": (3, "V"), "U_L3N": (5, "V"),
    "U_L12": (7, "V"), "U_L23": (9, "V"), "U_L31": (11, "V"),
    "I_L1": (13, "A"), "I_L2": (15, "A"), "I_L3": (17, "A"),
    "S_L1": (19, "VA"), "S_L2": (21, "VA"), "S_L3": (23, "VA"),
    "P_L1": (25, "W"), "P_L2": (27, "W"), "P_L3": (29, "W"),
    "Q_L1": (31, "var"), "Q_L2": (33, "var"), "Q_L3": (35, "var"),
    "PF_L1": (37, ""), "PF_L2": (39, ""), "PF_L3": (41, ""),
    "THDu_L12": (43, "%"), "THDu_L23": (45, "%"), "THDu_L31": (47, "%"),
    "FREQ": (55, "Hz"),
    "Uavg_LN": (57, "V"), "Uavg_LL": (59, "V"), "Iavg": (61, "A"),
    "S_tot": (63, "VA"), "P_tot": (65, "W"), "Q_tot": (67, "var"),
    "PF_tot": (69, ""), "Unbal_U": (71, "%"), "Unbal_I": (73, "%"),
}
_FLOAT_READ_START = 1
_FLOAT_READ_COUNT = 74

# Block B (Adr. 243..295): cos phi (Grundschwingung), per-Phase THD-U (L-N) und
# THD-I, Neutralleiterstrom. VERIFIZIERT 2026-07-11 gegen das reale Geraet
# (THD-I liegt hier, NICHT bei 49/51/53 — die sind undefiniert/NaN).
FLOAT2_MAP: dict[str, tuple[int, str]] = {
    "cosphi_L1": (243, ""), "cosphi_L2": (245, ""), "cosphi_L3": (247, ""),
    "ang_L1": (249, "\u00b0"), "ang_L2": (251, "\u00b0"), "ang_L3": (253, "\u00b0"),
    "THDu_L1": (261, "%"), "THDu_L2": (263, "%"), "THDu_L3": (265, "%"),
    "THDi_L1": (267, "%"), "THDi_L2": (269, "%"), "THDi_L3": (271, "%"),
    "Idist_L1": (273, "A"), "Idist_L2": (275, "A"), "Idist_L3": (277, "A"),
    "I_N": (295, "A"),
}
_FLOAT2_READ_START = 243
_FLOAT2_READ_COUNT = 55

# --- Verifizierter Energieblock (FLOAT64, offset = Modbus-Adresse) -----------
DOUBLE_MAP: dict[str, tuple[int, str]] = {
    "Wh_imp": (801, "Wh"), "Wh_exp": (805, "Wh"),
    "varh_imp": (809, "varh"), "varh_exp": (813, "varh"),
    "VAh": (817, "VAh"),
}
_DOUBLE_READ_START = 801
_DOUBLE_READ_COUNT = 20


def _f32(regs: list[int], base: int, addr: int):
    i = addr - base
    if i < 0 or i + 1 >= len(regs):
        return None
    val = struct.unpack(">f", struct.pack(">HH", regs[i], regs[i + 1]))[0]
    return None if math.isnan(val) or math.isinf(val) else val


def _f64(regs: list[int], base: int, addr: int):
    i = addr - base
    if i < 0 or i + 3 >= len(regs):
        return None
    val = struct.unpack(">d", struct.pack(">HHHH", *regs[i:i + 4]))[0]
    return None if math.isnan(val) or math.isinf(val) else val


def read_snapshot(host: str | None = None, port: int | None = None,
                  unit_id: int | None = None, timeout: float = 3.0) -> dict:
    """Liest einen vollständigen read-only Snapshot vom PAC4200.

    Returns dict mit ``ok``, ``ts``, ``host``, ``values`` (flach) und
    ``screens`` (PAC-Display-Nachbildung). Bei Unerreichbarkeit ``ok=False``.
    """
    host = host or _DEFAULT_HOST
    port = port or _DEFAULT_PORT
    unit_id = _DEFAULT_UNIT if unit_id is None else unit_id

    out: dict = {"ok": False, "ts": int(time.time()), "host": host,
                 "values": {}, "screens": [], "error": None}

    client = RawModbusClient(host, port, timeout=timeout)
    if not client.connect():
        out["error"] = "PAC4200 nicht erreichbar"
        return out
    try:
        fregs = read_registers_safe(client, _FLOAT_READ_START, _FLOAT_READ_COUNT, unit_id)
        f2regs = read_registers_safe(client, _FLOAT2_READ_START, _FLOAT2_READ_COUNT, unit_id)
        dregs = read_registers_safe(client, _DOUBLE_READ_START, _DOUBLE_READ_COUNT, unit_id)
    finally:
        client.close()

    if not fregs:
        out["error"] = "Keine Modbus-Antwort (Messwertblock)"
        return out

    vals: dict[str, float | None] = {}
    units: dict[str, str] = {}
    for name, (addr, unit) in FLOAT_MAP.items():
        vals[name] = _f32(fregs, _FLOAT_READ_START, addr)
        units[name] = unit
    if f2regs:
        for name, (addr, unit) in FLOAT2_MAP.items():
            vals[name] = _f32(f2regs, _FLOAT2_READ_START, addr)
            units[name] = unit
    if dregs:
        for name, (addr, unit) in DOUBLE_MAP.items():
            vals[name] = _f64(dregs, _DOUBLE_READ_START, addr)
            units[name] = unit

    # --- Zweirichtungszähler: Stromrichtung aus dem Vorzeichen der Wirkleistung
    # Der PAC4200 liefert RMS-Ströme als vorzeichenlose Beträge. Am PCC (Bezug/
    # Lieferung) trägt der Strom die Richtung der Phasen-Wirkleistung: P<0
    # (Einspeisung) -> Strom negativ. Beträge bleiben unter I_Lx erhalten.
    isum = 0.0
    have_isum = False
    for ph in ("L1", "L2", "L3"):
        i_mag = vals.get(f"I_{ph}")
        p = vals.get(f"P_{ph}")
        if i_mag is None:
            vals[f"Is_{ph}"] = None
            continue
        i_signed = -abs(i_mag) if (p is not None and p < 0) else abs(i_mag)
        vals[f"Is_{ph}"] = i_signed
        units[f"Is_{ph}"] = "A"
        isum += i_signed
        have_isum = True
    vals["Isum"] = isum if have_isum else None
    units["Isum"] = "A"

    out["ok"] = True
    out["values"] = vals
    out["units"] = units
    out["screens"] = _build_screens(vals)
    return out


def _fmt(vals, key, digits=1):
    v = vals.get(key)
    return None if v is None else round(v, digits)


def _build_screens(v: dict) -> list[dict]:
    """Bildet die PAC4200-Display-Bildschirme nach (Reihenfolge = up/down)."""
    def L(label, key, unit, digits=1):
        return {"label": label, "value": _fmt(v, key, digits), "unit": unit}
    return [
        {"id": "u_ln", "title": "Spannung L-N", "lines": [
            L("U L1-N", "U_L1N", "V"), L("U L2-N", "U_L2N", "V"), L("U L3-N", "U_L3N", "V")]},
        {"id": "u_ll", "title": "Spannung L-L", "lines": [
            L("U L1-L2", "U_L12", "V"), L("U L2-L3", "U_L23", "V"), L("U L3-L1", "U_L31", "V")]},
        {"id": "i", "title": "Strom", "lines": [
            L("I L1", "Is_L1", "A", 2), L("I L2", "Is_L2", "A", 2),
            L("I L3", "Is_L3", "A", 2), L("I \u03a3", "Isum", "A", 2),
            L("I N", "I_N", "A", 2)]},
        {"id": "p", "title": "Wirkleistung P", "lines": [
            L("P L1", "P_L1", "W", 0), L("P L2", "P_L2", "W", 0),
            L("P L3", "P_L3", "W", 0), L("P Σ", "P_tot", "W", 0)]},
        {"id": "qs", "title": "Blind-/Scheinleistung", "lines": [
            L("Q Σ", "Q_tot", "var", 0), L("S Σ", "S_tot", "VA", 0)]},
        {"id": "pf", "title": "Leistungsfaktor / cos \u03c6", "lines": [
            L("PF L1", "PF_L1", "", 3), L("PF L2", "PF_L2", "", 3),
            L("PF L3", "PF_L3", "", 3), L("PF \u03a3", "PF_tot", "", 3),
            L("cos\u03c6 L1", "cosphi_L1", "", 3), L("cos\u03c6 L2", "cosphi_L2", "", 3),
            L("cos\u03c6 L3", "cosphi_L3", "", 3)]},
        {"id": "thd", "title": "THD Spannung / Strom", "lines": [
            L("THD-U L1", "THDu_L1", "%", 2), L("THD-U L2", "THDu_L2", "%", 2),
            L("THD-U L3", "THDu_L3", "%", 2), L("THD-I L1", "THDi_L1", "%", 2),
            L("THD-I L2", "THDi_L2", "%", 2), L("THD-I L3", "THDi_L3", "%", 2)]},
        {"id": "thd_ll", "title": "THD Spannung L-L", "lines": [
            L("THD L1-L2", "THDu_L12", "%", 2), L("THD L2-L3", "THDu_L23", "%", 2),
            L("THD L3-L1", "THDu_L31", "%", 2)]},
        {"id": "angle", "title": "Phasenwinkel", "lines": [
            L("\u03c6 L1", "ang_L1", "\u00b0", 1), L("\u03c6 L2", "ang_L2", "\u00b0", 1),
            L("\u03c6 L3", "ang_L3", "\u00b0", 1)]},
        {"id": "dist", "title": "Verzerrungsstrom / I_N", "lines": [
            L("I dist L1", "Idist_L1", "A", 2), L("I dist L2", "Idist_L2", "A", 2),
            L("I dist L3", "Idist_L3", "A", 2), L("I N", "I_N", "A", 2)]},
        {"id": "freq", "title": "Frequenz & Mittelwerte", "lines": [
            L("Frequenz", "FREQ", "Hz", 3), L("U Ø L-N", "Uavg_LN", "V"),
            L("U Ø L-L", "Uavg_LL", "V"), L("Unsym. U", "Unbal_U", "%", 2),
            L("Unsym. I", "Unbal_I", "%", 2)]},
        {"id": "energy", "title": "Energiezähler", "lines": [
            L("Wirk Bezug", "Wh_imp", "Wh", 1), L("Wirk Lief.", "Wh_exp", "Wh", 1),
            L("Blind Bezug", "varh_imp", "varh", 1), L("Blind Lief.", "varh_exp", "varh", 1),
            L("Schein", "VAh", "VAh", 1)]},
    ]


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    snap = read_snapshot()
    print(f"ok={snap['ok']} host={snap['host']} error={snap['error']}")
    for scr in snap["screens"]:
        print(f"\n[{scr['title']}]")
        for ln in scr["lines"]:
            print(f"  {ln['label']:<12} {ln['value']} {ln['unit']}")
