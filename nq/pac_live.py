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

# Block C (Adr. 75..144): Max-Werte §12–§22. FLOAT32.
# Registerreferenz: doc/netzqualitaet/PAC4200-Modbus.md §12..§22.
FLOAT3_MAP: dict[str, tuple[int, str]] = {
    "Umax_L1N": (75, "V"), "Umax_L2N": (77, "V"), "Umax_L3N": (79, "V"),
    "Umax_L12": (81, "V"), "Umax_L23": (83, "V"), "Umax_L31": (85, "V"),
    "Imax_L1": (87, "A"), "Imax_L2": (89, "A"), "Imax_L3": (91, "A"),
    "Pmax_L1": (99, "W"), "Pmax_L2": (101, "W"), "Pmax_L3": (103, "W"),
    "FREQmax": (129, "Hz"),
    "Smax_tot": (137, "VA"), "Pmax_tot": (139, "W"), "Qmax_tot": (141, "var"),
}
_FLOAT3_READ_START = 75
_FLOAT3_READ_COUNT = 70   # 75..144 (je FLOAT32 = 2 Register)

# --- Verifizierter Energieblock (FLOAT64, offset = Modbus-Adresse) -----------
# Layout (Tarif 1 = aktiver Tarif; Tarife nicht konfiguriert → T1 verwenden):
# 801 Bezogene Wirkenergie T1, 805 Bezogene T2 (skip),
# 809 Gelieferte Wirkenergie T1, 813 Gelieferte T2 (skip),
# 817 Bezogene Blindenergie T1, 821 Bezogene T2 (skip),
# 825 Gelieferte Blindenergie T1, 829 Gelieferte T2 (skip),
# 833 Scheinenergie T1.  Quelle: doc/netzqualitaet/Modbus.md.
DOUBLE_MAP: dict[str, tuple[int, str]] = {
    "Wh_imp":   (801, "Wh"),    # Bezogene  Wirkenergie  T1
    "Wh_exp":   (809, "Wh"),    # Gelieferte Wirkenergie T1  ← FIX (frueherer Wert @805 = Bezug T2)
    "varh_imp": (817, "varh"),  # Bezogene  Blindenergie T1 ← FIX
    "varh_exp": (825, "varh"),  # Gelieferte Blindenergie T1 ← FIX
    "VAh":      (833, "VAh"),   # Scheinenergie T1           ← FIX
}
_DOUBLE_READ_START = 801
_DOUBLE_READ_COUNT = 36   # 801..836 (letzte addr 833, braucht regs[32..35])

# Blocks D/E/F: Einzelharmonische ohne Zeitstempel (A.3.10, Betriebsanleitung S. 240ff.)
# Ungerade Ordnungen H1 (V/A) + H3..H31 (% der Grundschwingung).
# Adresse = base + ordinal*6 + phase_offset  (ordinal 0=H1, 1=H3, ..., 15=H31)
# Endadressen aus Tab. A-17..A-19: @9095 H31 U L3-N, @11095 H31 I L3, @22095 H31 U L3-L1.
_HARM_ORDERS = (3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31)

HARM_UN_MAP: dict[str, tuple[int, str]] = {
    "H1_U_L1N": (9001, "V"), "H1_U_L2N": (9003, "V"), "H1_U_L3N": (9005, "V"),
}
for _i, _ord in enumerate(_HARM_ORDERS, start=1):
    for _ph, _po in (("L1N", 0), ("L2N", 2), ("L3N", 4)):
        HARM_UN_MAP[f"H{_ord}_U_{_ph}"] = (9001 + _i * 6 + _po, "%")
_HARM_UN_READ_START = 9001
_HARM_UN_READ_COUNT = 96   # @9001..@9096

HARM_I_MAP: dict[str, tuple[int, str]] = {
    "H1_I_L1": (11001, "A"), "H1_I_L2": (11003, "A"), "H1_I_L3": (11005, "A"),
}
for _i, _ord in enumerate(_HARM_ORDERS, start=1):
    for _ph, _po in (("L1", 0), ("L2", 2), ("L3", 4)):
        HARM_I_MAP[f"H{_ord}_I_{_ph}"] = (11001 + _i * 6 + _po, "%")
_HARM_I_READ_START = 11001
_HARM_I_READ_COUNT = 96    # @11001..@11096

HARM_ULL_MAP: dict[str, tuple[int, str]] = {
    "H1_U_L12": (22001, "V"), "H1_U_L23": (22003, "V"), "H1_U_L31": (22005, "V"),
}
for _i, _ord in enumerate(_HARM_ORDERS, start=1):
    for _ph, _po in (("L12", 0), ("L23", 2), ("L31", 4)):
        HARM_ULL_MAP[f"H{_ord}_U_{_ph}"] = (22001 + _i * 6 + _po, "%")
_HARM_ULL_READ_START = 22001
_HARM_ULL_READ_COUNT = 96  # @22001..@22096
del _i, _ord, _ph, _po


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


def _decode_ab(fregs, f2regs) -> dict:
    """Dekodiert Block A (FLOAT_MAP) + Block B (FLOAT2_MAP) zu values-Dict.
    Berechnet vorzeichenbehaftete Ströme Is_L1/L2/L3 (Einspeisung negativ).
    Wird von read_fast_snapshot() und read_snapshot() gemeinsam genutzt.
    """
    vals: dict = {}
    if fregs:
        for name, (addr, _) in FLOAT_MAP.items():
            vals[name] = _f32(fregs, _FLOAT_READ_START, addr)
    if f2regs:
        for name, (addr, _) in FLOAT2_MAP.items():
            vals[name] = _f32(f2regs, _FLOAT2_READ_START, addr)
    isum = 0.0
    have_isum = False
    for ph in ("L1", "L2", "L3"):
        i_mag = vals.get(f"I_{ph}")
        p = vals.get(f"P_{ph}")
        if i_mag is None:
            vals[f"Is_{ph}"] = None
        else:
            i_signed = -abs(i_mag) if (p is not None and p < 0) else abs(i_mag)
            vals[f"Is_{ph}"] = i_signed
            isum += i_signed
            have_isum = True
    vals["Isum"] = (isum if math.isfinite(isum) else None) if have_isum else None
    return vals


def read_fast_snapshot(host: str | None = None, port: int | None = None,
                       unit_id: int | None = None, timeout: float = 2.0) -> dict:
    """Read-only: nur Block A (FLOAT_MAP) + Block B (FLOAT2_MAP), 2 Modbus-Reads.
    Kein Block C, keine Harmonischen, kein Energie-Block.
    Für den 200-ms-Fast-Loop des nq_poller.
    """
    host = host or _DEFAULT_HOST
    port = port or _DEFAULT_PORT
    unit_id = _DEFAULT_UNIT if unit_id is None else unit_id
    out: dict = {"ok": False, "ts": int(time.time()), "values": {}, "error": None}

    client = RawModbusClient(host, port, timeout=timeout)
    if not client.connect():
        out["error"] = "PAC4200 nicht erreichbar"
        return out
    try:
        fregs = read_registers_safe(client, _FLOAT_READ_START, _FLOAT_READ_COUNT, unit_id)
        f2regs = read_registers_safe(client, _FLOAT2_READ_START, _FLOAT2_READ_COUNT, unit_id)
    finally:
        client.close()

    if not fregs:
        out["error"] = "Keine Modbus-Antwort (Block A)"
        return out

    out["ok"] = True
    out["ts"] = int(time.time())
    out["values"] = _decode_ab(fregs, f2regs)
    return out


def read_harm_snapshot(host: str | None = None, port: int | None = None,
                       unit_id: int | None = None, timeout: float = 2.0) -> dict:
    """Read-only: nur Harmonik-Blöcke D/E/F (@9001/@11001/@22001), 3 Modbus-Reads.
    Liefert flat-key values-Dict (z. B. 'H3_U_L1N': 0.38, 'H5_I_L1': 0.39, …).
    Für den 1-s-Slow-Loop des nq_poller.
    """
    host = host or _DEFAULT_HOST
    port = port or _DEFAULT_PORT
    unit_id = _DEFAULT_UNIT if unit_id is None else unit_id
    out: dict = {"ok": False, "ts": int(time.time()), "values": {}, "error": None}

    client = RawModbusClient(host, port, timeout=timeout)
    if not client.connect():
        out["error"] = "PAC4200 nicht erreichbar"
        return out
    try:
        harm_un = read_registers_safe(client, _HARM_UN_READ_START, _HARM_UN_READ_COUNT, unit_id)
        harm_i = read_registers_safe(client, _HARM_I_READ_START, _HARM_I_READ_COUNT, unit_id)
        harm_ull = read_registers_safe(client, _HARM_ULL_READ_START, _HARM_ULL_READ_COUNT, unit_id)
    finally:
        client.close()

    vals: dict = {}
    if harm_un:
        for name, (addr, _) in HARM_UN_MAP.items():
            vals[name] = _f32(harm_un, _HARM_UN_READ_START, addr)
    if harm_i:
        for name, (addr, _) in HARM_I_MAP.items():
            vals[name] = _f32(harm_i, _HARM_I_READ_START, addr)
    if harm_ull:
        for name, (addr, _) in HARM_ULL_MAP.items():
            vals[name] = _f32(harm_ull, _HARM_ULL_READ_START, addr)

    if not vals:
        out["error"] = "Keine Harmonik-Daten (alle drei Blöcke leer)"
        return out
    out["ok"] = True
    out["ts"] = int(time.time())
    out["values"] = vals
    return out


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
        c_regs = read_registers_safe(client, _FLOAT3_READ_START, _FLOAT3_READ_COUNT, unit_id)
        dregs = read_registers_safe(client, _DOUBLE_READ_START, _DOUBLE_READ_COUNT, unit_id)
        harm_un = read_registers_safe(client, _HARM_UN_READ_START, _HARM_UN_READ_COUNT, unit_id)
        harm_i = read_registers_safe(client, _HARM_I_READ_START, _HARM_I_READ_COUNT, unit_id)
        harm_ull = read_registers_safe(client, _HARM_ULL_READ_START, _HARM_ULL_READ_COUNT, unit_id)
    finally:
        client.close()

    if not fregs:
        out["error"] = "Keine Modbus-Antwort (Messwertblock)"
        return out

    # Block A + B dekodieren (shared helper, inkl. Is_Lx)
    vals: dict[str, float | None] = _decode_ab(fregs, f2regs)
    units: dict[str, str] = {k: u for k, (_, u) in FLOAT_MAP.items()}
    units.update({k: u for k, (_, u) in FLOAT2_MAP.items()})
    if c_regs:
        for name, (addr, unit) in FLOAT3_MAP.items():
            vals[name] = _f32(c_regs, _FLOAT3_READ_START, addr)
            units[name] = unit
    if dregs:
        for name, (addr, unit) in DOUBLE_MAP.items():
            vals[name] = _f64(dregs, _DOUBLE_READ_START, addr)
            units[name] = unit
    if harm_un:
        for name, (addr, unit) in HARM_UN_MAP.items():
            vals[name] = _f32(harm_un, _HARM_UN_READ_START, addr)
            units[name] = unit
    if harm_i:
        for name, (addr, unit) in HARM_I_MAP.items():
            vals[name] = _f32(harm_i, _HARM_I_READ_START, addr)
            units[name] = unit
    if harm_ull:
        for name, (addr, unit) in HARM_ULL_MAP.items():
            vals[name] = _f32(harm_ull, _HARM_ULL_READ_START, addr)
            units[name] = unit

    out["ok"] = True
    out["values"] = vals
    out["units"] = units
    out["screens"] = _build_screens(vals)
    return out


def _fmt(vals, key, digits=1):
    """Gibt vorformatierten deutschen Dezimalstring oder None zurueck."""
    v = vals.get(key)
    if v is None:
        return None
    return f"{v:.{digits}f}".replace(".", ",")


def _phasor_svg(v: dict) -> str:
    """Inline-SVG Zeigerdiagramm: 3 Spannungs- + 3 Stromzeiger."""
    cx, cy, r = 110, 110, 85
    u_vals = [v.get("U_L1N"), v.get("U_L2N"), v.get("U_L3N")]
    i_vals = [abs(v.get("Is_L1") or 0.0), abs(v.get("Is_L2") or 0.0),
              abs(v.get("Is_L3") or 0.0)]
    ang = [v.get("ang_L1") or 0.0, v.get("ang_L2") or 0.0, v.get("ang_L3") or 0.0]
    u_max = max((x for x in u_vals if x is not None), default=1.0) or 1.0
    i_max = max(i_vals) or 1.0
    vol_base = [90.0, -30.0, 210.0]   # L1 oben, L2 unten-rechts, L3 unten-links
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 220" '
        f'style="width:100%;max-width:240px;display:block;margin:6px auto">',
        '<defs>'
        '<marker id="aU" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">'
        '<path d="M0,0 L0,4 L6,2 z" fill="#5b9bd5"/></marker>'
        '<marker id="aI" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">'
        '<path d="M0,0 L0,4 L6,2 z" fill="#e07070"/></marker>'
        '</defs>',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="#2a3a2a" stroke-width="1" fill="none"/>',
        f'<line x1="{cx}" y1="{cy-r-2}" x2="{cx}" y2="{cy+r+2}" stroke="#1e2e1e" stroke-width="0.5"/>',
        f'<line x1="{cx-r-2}" y1="{cy}" x2="{cx+r+2}" y2="{cy}" stroke="#1e2e1e" stroke-width="0.5"/>',
    ]
    labels = []
    for idx, ph in enumerate(("L1", "L2", "L3")):
        ua_rad = math.radians(vol_base[idx])
        u_r = ((u_vals[idx] or 0.0) / u_max) * r
        ux = cx + u_r * math.cos(ua_rad)
        uy = cy - u_r * math.sin(ua_rad)
        parts.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ux:.1f}" y2="{uy:.1f}" '
            f'stroke="#5b9bd5" stroke-width="2" marker-end="url(#aU)"/>'
        )
        lux = cx + (u_r + 11) * math.cos(ua_rad)
        luy = cy - (u_r + 11) * math.sin(ua_rad)
        labels.append(f'<text x="{lux:.1f}" y="{luy:.1f}" fill="#5b9bd5" '
                      f'font-size="9" text-anchor="middle">U{ph}</text>')
        # Strom eilt Spannung nach (ang > 0 = induktiv = nacheilend)
        i_ang_rad = math.radians(vol_base[idx] - ang[idx])
        i_r = i_vals[idx] / i_max * r
        ix = cx + i_r * math.cos(i_ang_rad)
        iy = cy - i_r * math.sin(i_ang_rad)
        parts.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ix:.1f}" y2="{iy:.1f}" '
            f'stroke="#e07070" stroke-width="1.5" stroke-dasharray="4,2" marker-end="url(#aI)"/>'
        )
        cphi = v.get(f"cosphi_L{idx + 1}")
        cphi_str = f" {cphi:.2f}" if cphi is not None else ""
        lix = cx + (i_r + 11) * math.cos(i_ang_rad)
        liy = cy - (i_r + 11) * math.sin(i_ang_rad)
        labels.append(f'<text x="{lix:.1f}" y="{liy:.1f}" fill="#e07070" '
                      f'font-size="8" text-anchor="middle">I{ph}{cphi_str}</text>')
    parts.extend(labels)
    parts.extend([
        '<text x="4" y="12" fill="#5b9bd5" font-size="8">— U</text>',
        '<text x="4" y="22" fill="#e07070" font-size="8">- - I</text>',
        '</svg>',
    ])
    return ''.join(parts)


def _harm_bar_svg(vals: dict, ph: str, kind: str) -> str:
    """SVG-Balkendiagramm Harmonische H3..H31 fuer eine Phase.
    ph: 'L1N'/'L2N'/'L3N' (kind='U') oder 'L1'/'L2'/'L3' (kind='I')
    """
    orders = (3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31)
    h1_key = f"H1_{'U' if kind == 'U' else 'I'}_{ph}"
    h1_val = vals.get(h1_key)
    pct = [(vals.get(f"H{o}_{kind}_{ph}") or 0.0) for o in orders]

    scale_max = max(max(pct) if pct else 0.0, 0.1)
    for nice in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0):
        if scale_max <= nice:
            scale_max = nice
            break
    else:
        scale_max = math.ceil(scale_max)

    W, bx, by, bw, bh_max = 240, 26, 12, 208, 125
    H = by + bh_max + 45
    n = len(orders)
    slot = bw / n
    bar_w = max(slot - 2, 4)
    base_y = by + bh_max

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'style="width:100%;display:block">',
    ]
    for frac, lbl in ((0.5, f"{scale_max * .5:.1f}"), (1.0, f"{scale_max:.1f}%")):
        gy = base_y - bh_max * frac
        dash = ' stroke-dasharray="3,3"' if frac < 1.0 else ""
        parts.append(f'<line x1="{bx}" y1="{gy:.0f}" x2="{bx + bw}" y2="{gy:.0f}" '
                     f'stroke="#3a4a3a" stroke-width="0.5"{dash}/>')
        parts.append(f'<text x="{bx - 2}" y="{gy + 3:.0f}" fill="#2a3a2a" '
                     f'font-size="7" text-anchor="end">{lbl}</text>')
    parts.append(f'<text x="{bx - 2}" y="{base_y + 2}" fill="#2a3a2a" '
                 f'font-size="7" text-anchor="end">0</text>')
    parts.append(f'<line x1="{bx}" y1="{base_y}" x2="{bx + bw}" y2="{base_y}" '
                 f'stroke="#2a3a2a" stroke-width="1"/>')

    for i, (o, val) in enumerate(zip(orders, pct)):
        x = bx + i * slot + (slot - bar_w) / 2
        frac = min(val / scale_max, 1.0)
        bh = frac * bh_max
        y = base_y - bh
        color = "#2a5a2a" if frac < 0.3 else ("#7a6210" if frac < 0.7 else "#7a1a1a")
        if bh >= 1:
            parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bar_w:.0f}" '
                         f'height="{bh:.0f}" fill="{color}"/>')
        if val >= scale_max * 0.05:
            parts.append(f'<text x="{x + bar_w / 2:.0f}" y="{max(y - 1, by + 9):.0f}" '
                         f'fill="#1c2416" font-size="7" text-anchor="middle">{val:.1f}</text>')
        if i % 2 == 0:
            parts.append(f'<text x="{x + bar_w / 2:.0f}" y="{base_y + 12}" '
                         f'fill="#2a3a2a" font-size="8" text-anchor="middle">{o}</text>')

    h1_unit = "V" if kind == "U" else "A"
    h1_str = f"{h1_val:.2f} {h1_unit}" if h1_val is not None else "---"
    parts.append(f'<text x="4" y="{H - 2}" fill="#2a3a2a" font-size="8">H1={h1_str}</text>')
    parts.append(f'<text x="{W - 4}" y="{H - 2}" fill="#2a3a2a" font-size="8" '
                 f'text-anchor="end">max {scale_max:.1f}%</text>')
    parts.append('</svg>')
    return ''.join(parts)


def _fill_missing_values(v: dict) -> dict:
    """Berechnet fehlende Messwerte aus verfügbaren Daten.
    
    Fügt Phase-spezifische Leistungen, Durchschnittswerte und Unsymmetrien ein,
    die vom Tech-Collector nicht gespeichert wurden.
    """
    v = dict(v)  # Kopie, um Original nicht zu verändern
    
    # Sicherstelle, dass I_L1/L2/L3 (Betrag) aus Is_L1/L2/L3 berechnet sind
    for ph in ("L1", "L2", "L3"):
        is_key = f"Is_{ph}"
        i_key = f"I_{ph}"
        if is_key in v and v[is_key] is not None and i_key not in v:
            v[i_key] = abs(v[is_key])
    
    # Durchschnittsspannungen
    u_ln_vals = [v.get(f"U_L{i}N") for i in (1, 2, 3)]
    u_ln_finite = [u for u in u_ln_vals if u is not None]
    if len(u_ln_finite) == 3 and not v.get("Uavg_LN"):
        v["Uavg_LN"] = sum(u_ln_finite) / 3.0
    
    u_ll_vals = [v.get(f"U_L{ab}") for ab in ("L12", "L23", "L31")]
    u_ll_finite = [u for u in u_ll_vals if u is not None]
    if len(u_ll_finite) == 3 and not v.get("Uavg_LL"):
        v["Uavg_LL"] = sum(u_ll_finite) / 3.0
    
    # Phase-spezifische Leistungen aus U, I, cos(phi)
    for ph in ("L1", "L2", "L3"):
        u_key = f"U_{ph}N"
        i_key = f"I_{ph}"
        cos_key = f"cosphi_{ph}"
        s_key = f"S_{ph}"
        p_key = f"P_{ph}"
        q_key = f"Q_{ph}"
        
        u = v.get(u_key)
        i = v.get(i_key)
        cos_phi = v.get(cos_key)
        
        # S = U * I (wenn nicht vorhanden)
        if u is not None and i is not None and v.get(s_key) is None:
            s = u * i
            v[s_key] = s
            
            # P = S * |cos(phi)| (wenn cos_phi vorhanden)
            if cos_phi is not None and v.get(p_key) is None:
                v[p_key] = s * abs(cos_phi)
            
            # Q = S * sqrt(1 - cos(phi)²)
            if cos_phi is not None and v.get(q_key) is None:
                sin_sq = max(0, 1.0 - cos_phi * cos_phi)
                v[q_key] = s * math.sqrt(sin_sq)
    
    # Phase-spezifische Leistungsfaktoren aus cos(phi)
    for ph in ("L1", "L2", "L3"):
        cos_key = f"cosphi_{ph}"
        pf_key = f"PF_{ph}"
        if cos_key in v and v[cos_key] is not None and pf_key not in v:
            v[pf_key] = abs(v[cos_key])
    
    # THD L-L aus L-N (grobe Approximation)
    # THD_L12 ≈ sqrt((THD_L1² + THD_L2²) / 2)
    for l1_n, l2_n, l_ll in (("L1", "L2", "L12"), ("L2", "L3", "L23"), ("L3", "L1", "L31")):
        thd1_key = f"THDu_{l1_n}"
        thd2_key = f"THDu_{l2_n}"
        thd_ll_key = f"THDu_{l_ll}"
        
        thd1 = v.get(thd1_key)
        thd2 = v.get(thd2_key)
        if thd1 is not None and thd2 is not None and thd_ll_key not in v:
            v[thd_ll_key] = math.sqrt((thd1*thd1 + thd2*thd2) / 2.0)
    
    # Unsymmetrie U aus 3-Phasen-Spannungen (negatives Phasensystem-Verhältnis)
    # Vereinfachte Berechnung: Unbal = 100 * (U_max - U_min) / U_avg
    if "Unbal_U" not in v:
        u_ln_vals = [v.get(f"U_L{i}N") for i in (1, 2, 3)]
        u_ln_finite = [u for u in u_ln_vals if u is not None]
        if len(u_ln_finite) == 3:
            u_min = min(u_ln_finite)
            u_max = max(u_ln_finite)
            u_avg = sum(u_ln_finite) / 3.0
            if u_avg > 10:  # Plausibilität
                v["Unbal_U"] = 100.0 * (u_max - u_min) / u_avg
    
    # Unsymmetrie I aus 3-Phasen-Strömen
    if "Unbal_I" not in v:
        i_vals = [v.get(f"I_L{i}") for i in (1, 2, 3)]
        i_finite = [i for i in i_vals if i is not None]
        if len(i_finite) == 3:
            i_min = min(i_finite)
            i_max = max(i_finite)
            i_avg = sum(i_finite) / 3.0
            if i_avg > 0.5:  # Plausibilität
                v["Unbal_I"] = 100.0 * (i_max - i_min) / i_avg
    
    return v


def _build_screens(v: dict) -> list[dict]:
    """PAC4200-Display-Bildschirme nach Original-Geraet (A.1 Messgroessen)."""
    v = _fill_missing_values(v)  # Fehlende Werte berechnen
    _KILO = frozenset({"W", "VA", "var", "Wh", "varh", "VAh"})

    def L(label, key, unit, digits=1):
        return {"label": label, "value": _fmt(v, key, digits), "unit": unit}

    def PL(*specs):
        """Leistungs-/Energie-Zeilen: alle auf kilo umschalten wenn |Wert| >= 1000."""
        raw = [(lbl, key, unit, digs, v.get(key)) for lbl, key, unit, digs in specs]
        kilo = any(
            val is not None and abs(val) >= 1000 and unit in _KILO
            for _, _, unit, _, val in raw
        )
        out = []
        for lbl, key, unit, digs, val in raw:
            if val is None:
                out.append({"label": lbl, "value": None, "unit": unit})
            elif kilo and unit in _KILO:
                kd = max(digs, 2)
                out.append({"label": lbl,
                            "value": f"{val / 1000:.{kd}f}".replace(".", ","),
                            "unit": "k" + unit})
            else:
                out.append({"label": lbl,
                            "value": f"{val:.{digs}f}".replace(".", ","),
                            "unit": unit})
        return out

    return [
        # Display 1 — Spannung L-N
        {"id": "u_ln", "title": "Spannung L-N", "lines": [
            L("U<sub>L1-N</sub>", "U_L1N", "V", 1), L("U<sub>L2-N</sub>", "U_L2N", "V", 1),
            L("U<sub>L3-N</sub>", "U_L3N", "V", 1)]},
        # Display 2 — Spannung L-L
        {"id": "u_ll", "title": "Spannung L-L", "lines": [
            L("U<sub>L1-L2</sub>", "U_L12", "V", 1), L("U<sub>L2-L3</sub>", "U_L23", "V", 1),
            L("U<sub>L3-L1</sub>", "U_L31", "V", 1)]},
        # Display 3 — Strom (vorzeichenbehaftet; IN vorzeichenlos vom Geraet)
        {"id": "i", "title": "Strom", "lines": [
            L("I<sub>L1</sub>", "Is_L1", "A", 2), L("I<sub>L2</sub>", "Is_L2", "A", 2),
            L("I<sub>L3</sub>", "Is_L3", "A", 2),
            L("I<sub>\u03a3</sub>", "Isum", "A", 2), L("I<sub>N</sub>", "I_N", "A", 2)]},
        # Display 4 — Scheinleistung S (stets >= 0)
        {"id": "s", "title": "Scheinleistung S", "lines": PL(
            ("S<sub>L1</sub>", "S_L1", "VA", 0), ("S<sub>L2</sub>", "S_L2", "VA", 0),
            ("S<sub>L3</sub>", "S_L3", "VA", 0), ("S<sub>\u03a3</sub>", "S_tot", "VA", 0))},
        # Display 5 — Wirkleistung P
        {"id": "p", "title": "Wirkleistung P", "lines": PL(
            ("P<sub>L1</sub>", "P_L1", "W", 0), ("P<sub>L2</sub>", "P_L2", "W", 0),
            ("P<sub>L3</sub>", "P_L3", "W", 0), ("P<sub>\u03a3</sub>", "P_tot", "W", 0))},
        # Display 6 — Blindleistung Q
        {"id": "q", "title": "Blindleistung Q", "lines": PL(
            ("Q<sub>L1</sub>", "Q_L1", "var", 0), ("Q<sub>L2</sub>", "Q_L2", "var", 0),
            ("Q<sub>L3</sub>", "Q_L3", "var", 0), ("Q<sub>\u03a3</sub>", "Q_tot", "var", 0))},
        # Display 8 — Leistungsfaktor |PF|
        {"id": "pf", "title": "Leistungsfaktor |PF|", "lines": [
            L("|PF|<sub>L1</sub>", "PF_L1", "", 3), L("|PF|<sub>L2</sub>", "PF_L2", "", 3),
            L("|PF|<sub>L3</sub>", "PF_L3", "", 3), L("|PF|<sub>\u03a3</sub>", "PF_tot", "", 3)]},
        # Display 10 — cos phi + Phasenverschiebungswinkel
        {"id": "cosphi", "title": "cos \u03c6 / Phasenwinkel", "lines": [
            L("cos\u03c6<sub>L1</sub>", "cosphi_L1", "", 3), L("cos\u03c6<sub>L2</sub>", "cosphi_L2", "", 3),
            L("cos\u03c6<sub>L3</sub>", "cosphi_L3", "", 3),
            L("\u03c6<sub>L1</sub>", "ang_L1", "\u00b0", 1), L("\u03c6<sub>L2</sub>", "ang_L2", "\u00b0", 1),
            L("\u03c6<sub>L3</sub>", "ang_L3", "\u00b0", 1)]},
        # Display 11 — Netzfrequenz (4 NKS) + 3ph-Mittelspannungen
        {"id": "freq", "title": "Frequenz", "lines": [
            L("f<sub>N</sub>", "FREQ", "Hz", 4),
            L("\u016c<sub>L-N</sub>", "Uavg_LN", "V", 1),
            L("\u016c<sub>L-L</sub>", "Uavg_LL", "V", 1)]},
        # Display 12 — THD Spannung L-N
        {"id": "thd_u", "title": "THD Spannung L-N", "lines": [
            L("THD<sub>U,L1</sub>", "THDu_L1", "%", 2), L("THD<sub>U,L2</sub>", "THDu_L2", "%", 2),
            L("THD<sub>U,L3</sub>", "THDu_L3", "%", 2)]},
        # THD Spannung L-L (kein eigenes Display im Original)
        {"id": "thd_ull", "title": "THD Spannung L-L", "lines": [
            L("THD<sub>L12</sub>", "THDu_L12", "%", 2), L("THD<sub>L23</sub>", "THDu_L23", "%", 2),
            L("THD<sub>L31</sub>", "THDu_L31", "%", 2)]},
        # Display 13 — THD Strom
        {"id": "thd_i", "title": "THD Strom", "lines": [
            L("THD<sub>I,L1</sub>", "THDi_L1", "%", 2), L("THD<sub>I,L2</sub>", "THDi_L2", "%", 2),
            L("THD<sub>I,L3</sub>", "THDi_L3", "%", 2)]},
        # Display 17 — Verzerrungsstrom Idist (RMS Oberschw.-Anteil, stets >= 0)
        {"id": "dist", "title": "Verzerrungsstrom", "lines": [
            L("I<sub>dist,L1</sub>", "Idist_L1", "A", 2), L("I<sub>dist,L2</sub>", "Idist_L2", "A", 2),
            L("I<sub>dist,L3</sub>", "Idist_L3", "A", 2), L("I<sub>N</sub>", "I_N", "A", 2)]},
        # Display 23 — Unsymmetrie
        {"id": "unbal", "title": "Unsymmetrie", "lines": [
            L("Unsym.<sub>U</sub>", "Unbal_U", "%", 2), L("Unsym.<sub>I</sub>", "Unbal_I", "%", 2)]},
        # Displays 18-20 — Energiezaehler (Ea=Wirkarbeit, Er=Blindarbeit, Eap=Scheinarbeit)
        {"id": "energy", "title": "Energiez\u00e4hler", "lines": PL(
            ("E<sub>a</sub> Bezug", "Wh_imp", "Wh", 1),
            ("E<sub>a</sub> Einspeis.", "Wh_exp", "Wh", 1),
            ("E<sub>r</sub> Bezug", "varh_imp", "varh", 1),
            ("E<sub>r</sub> Einspeis.", "varh_exp", "varh", 1),
            ("E<sub>ap</sub>", "VAh", "VAh", 1))},
        # Extras (kein Original-Display)
        {"id": "phasor", "title": "Zeigerdiagramm", "svg": _phasor_svg(v)},
        {"id": "extrema", "title": "Max-Werte", "lines": [
            L("U<sub>max,L1-N</sub>", "Umax_L1N", "V", 1), L("U<sub>max,L2-N</sub>", "Umax_L2N", "V", 1),
            L("U<sub>max,L3-N</sub>", "Umax_L3N", "V", 1)] + PL(
            ("I<sub>max,L1</sub>", "Imax_L1", "A", 2), ("I<sub>max,L2</sub>", "Imax_L2", "A", 2),
            ("I<sub>max,L3</sub>", "Imax_L3", "A", 2),
            ("P<sub>max,L1</sub>", "Pmax_L1", "W", 0), ("P<sub>max,\u03a3</sub>", "Pmax_tot", "W", 0)) + [
            L("f<sub>max</sub>", "FREQmax", "Hz", 3)]},
        {"id": "harm_u_l1", "title": "Harm. U L1-N (%)", "svg": _harm_bar_svg(v, "L1N", "U")},
        {"id": "harm_u_l2", "title": "Harm. U L2-N (%)", "svg": _harm_bar_svg(v, "L2N", "U")},
        {"id": "harm_u_l3", "title": "Harm. U L3-N (%)", "svg": _harm_bar_svg(v, "L3N", "U")},
        {"id": "harm_i_l1", "title": "Harm. I L1 (%)", "svg": _harm_bar_svg(v, "L1", "I")},
        {"id": "harm_i_l2", "title": "Harm. I L2 (%)", "svg": _harm_bar_svg(v, "L2", "I")},
        {"id": "harm_i_l3", "title": "Harm. I L3 (%)", "svg": _harm_bar_svg(v, "L3", "I")},
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
        if scr.get("svg"):
            print(f"  <SVG {len(scr['svg'])} chars>")
        else:
            for ln in scr.get("lines", []):
                print(f"  {ln['label']:<12} {ln['value']} {ln['unit']}")
