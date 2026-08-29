#!/usr/bin/env python3
"""nq.analysis.nq_reflection — Reflexions-/Laufwellen-Analyse im Verbundnetz (Rolle N).

**Versuch** einer Reflexionserkennung an den Grenzen des kontinentaleuropäischen
Synchronverbunds (CESA, 50 Hz). **Read-only** auf `nq/db/nq_YYYY-MM.db`; kein
Schreibpfad in Produktion/Aktoren. Nur numpy (Prod-venv ohne scipy).

================================================================================
IDEE / PHYSIK
================================================================================
Eine Störung im Verbundnetz (Erzeuger-Ausfall, großer Lastsprung) regt eine
*elektromechanische Laufwelle* an, die sich mit endlicher Geschwindigkeit über
das Netz ausbreitet und an den **Netzgrenzen** (Rand des Synchrongebiets,
Impedanz-/Trägheitssprung) teilweise **reflektiert** wird. Am Messpunkt sieht man
dann das Primärereignis und — zeitversetzt und gedämpft — ein **Echo** gleicher
Signatur (gleiche Form, geringere Amplitude/Gradient, ggf. invertiert).

Aus der Laufzeit Δt zwischen Primär und Echo folgt die **Umlauf-Distanz** zur
reflektierenden Grenze:

    d = v_em · Δt / 2                      (Hin- und Rückweg)

mit der elektromechanischen Ausbreitungsgeschwindigkeit v_em (Literatur ~200…
1400 km/s, hier konfigurierbarer Default 500 km/s, Thorp/Seyler/Phadke 1998).
Kennt man die Distanzen des Standorts zu den einzelnen Netzgrenzen, ordnet man
d der wahrscheinlichsten **Reflexionsstelle** zu (kleinstes |dist − d|).

================================================================================
MESSTECHNISCHE GRENZEN (ehrlich)
================================================================================
* PAC4200-**Frequenz**register: internes Refresh ~10 s → nutzbares Band nur bis
  ~50 mHz. Schnelle Inter-Area-Moden (0,15 Hz O–W, 0,25 Hz N–S) und sekunden-
  schnelle Laufwellen-Echos sind damit **nicht** in der Frequenz auflösbar.
* PAC4200-**Spannung**: Block-A-Refresh ≤250 ms → im Event-Schnipsel
  (`nq_event_fast`, 200 ms) bis ~2,5 Hz auflösbar, aber **lokale** Größe (PCC).
* Kontinuierliche 5-min-Reihe (`nq_pattern_5min.freq`): Band ≤1,667 mHz →
  langsame Schwingungspakete (VLF), **keine** Laufwellen-Echos.
* Aus **einem** Messpunkt ist die *Richtung* eines skalaren Frequenzereignisses
  prinzipiell nicht bestimmbar (dafür bräuchte es ein zeitsynchrones Sensornetz
  wie FNET/GridEye). Wir liefern deshalb **Distanz-Hypothesen** (Δt→d→Grenze)
  und Arbeitsthesen, keine gesicherten Richtungen.

Der physikalisch belastbare Pfad ist die **Event-Schnipsel-Analyse** (Spannung,
200 ms) mit Δt im Sekundenbereich. Die kontinuierliche 5-min-Analyse liefert
ergänzend die langsamen Schwingungspakete für den Zeitreihen-Chart.

Start (CLI/Selbsttest):
  python3 -m nq.analysis.nq_reflection --geometry
  python3 -m nq.analysis.nq_reflection --days 30
Doku: doc/llm/cards/netzqualitaet-nq-analysis-events.card.md
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sqlite3
import time

import numpy as np

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")

# ===========================================================================
# Referenz-Geometrie: Kontinentaleuropäischer Synchronverbund (CESA, 50 Hz)
# ---------------------------------------------------------------------------
# Stilisierter Außenrand (lat, lon) des Synchrongebiets — bewusst vereinfacht
# (für die Karte + Distanzschätzung, keine geodätisch exakte Grenze).
# Quelle: ENTSO-E Continental Europe Synchronous Area (32 Länder, PT→UA/TR,
# DK-West→GR/Sizilien + Südwest-Mittelmeer-Block Marokko/Algerien/Tunesien).
# ===========================================================================
GRID_BOUNDARY: list[tuple[float, float]] = [
    (37.0, -9.5),   # Portugal SW (Cabo de São Vicente)
    (43.8, -8.9),   # Galicien NW
    (48.6, -4.8),   # Bretagne
    (51.5, 3.4),    # Niederlande/Belgien Küste
    (53.6, 8.5),    # Deutsche Nordseeküste
    (57.6, 9.9),    # Dänemark (Jütland-Nord, DK-West im CE)
    (54.4, 19.6),   # Ostsee (Danzig)
    (55.7, 21.1),   # Litauen Küste (Baltikum seit 2025 synchron)
    (59.6, 24.8),   # Estland (Tallinn)
    (52.1, 40.2),   # Ukraine NO (seit 2022 synchron)
    (47.9, 39.7),   # Ukraine SO / Asowsches Meer
    (44.6, 33.5),   # Krim / Schwarzes Meer
    (41.0, 29.0),   # Istanbul / Bosporus (Türkei seit 2010 synchron)
    (37.0, 35.3),   # SO-Anatolien
    (35.0, 25.6),   # Kreta
    (36.4, 15.1),   # Sizilien / Malta
    (37.3, 10.2),   # Tunesien (Südwest-Mittelmeer-Block)
    (35.8, -0.6),   # Algerien (Oran)
    (33.6, -7.6),   # Marokko (Casablanca)
    (30.0, -9.7),   # Marokko SW (Agadir)
    (37.0, -9.5),   # zurück zum Start
]

# Benannte Grenz-Referenzpunkte (Kardinal-Richtungen) für die Δt→Distanz-Zuordnung.
BOUNDARY_POINTS: list[dict] = [
    {"key": "nord",     "name": "Nordgrenze (Jütland/DK-West)",        "lat": 57.6, "lon": 9.9},
    {"key": "nordost",  "name": "Nordostgrenze (Baltikum)",           "lat": 59.6, "lon": 24.8},
    {"key": "ost",      "name": "Ostgrenze (Ukraine)",                "lat": 49.5, "lon": 40.0},
    {"key": "suedost",  "name": "Südostgrenze (Anatolien/Türkei)",    "lat": 37.5, "lon": 35.0},
    {"key": "sued",     "name": "Südgrenze (Sizilien/Malta)",         "lat": 36.0, "lon": 14.5},
    {"key": "suedwest", "name": "Südwestgrenze (Marokko/Agadir)",     "lat": 30.5, "lon": -9.2},
    {"key": "west",     "name": "Westgrenze (Iberien/Atlantik)",      "lat": 40.5, "lon": -9.2},
]

# Bekannte Inter-Area-Eigenmoden des CE-Verbunds (Referenz für Attribution).
INTER_AREA_MODES: list[dict] = [
    {"name": "Ost–West-Mode",  "freq_hz": 0.15, "note": "dominante Pendelung Iberien ↔ Türkei/Osten"},
    {"name": "Nord–Süd-Mode",  "freq_hz": 0.25, "note": "Pendelung Norden ↔ Italien/Süden"},
]

# Standort (aus config; Fallback = Prognose-Standort Sachsen).
_DEFAULT_LAT, _DEFAULT_LON = 51.01, 12.95
_EARTH_R_KM = 6371.0

# Konfig-Defaults (überschreibbar via config/nq_config.json → "reflection").
_DEF_CFG = {
    "v_em_km_s": 500.0,          # elektromechanische Ausbreitungsgeschwindigkeit
    "v_em_min_km_s": 200.0,      # Literatur-Bandbreite (für Distanz-Unsicherheit)
    "v_em_max_km_s": 1400.0,
    "band_lo_hz": 0.001,         # Auswerteband (Nutzeranforderung 1 mHz…1 Hz)
    "band_hi_hz": 1.0,
    "echo_tau_min_s": 0.5,       # plausibler Echo-Laufzeitbereich (Event-Schnipsel)
    "echo_tau_max_s": 30.0,
    "echo_min_corr": 0.5,        # min. normierte Autokorrelation für ein Echo
    "echo_max_amp_ratio": 0.95,  # Echo muss schwächer als Primär sein
    "packet_env_k": 3.0,         # Paket-Schwelle = k · Median-Hüllkurve
    "packet_min_len": 4,         # min. Stützstellen je Paket
    "dist_tol_km": 250.0,        # Toleranz Distanz↔Grenze für "confident"
}


# ===========================================================================
# 1) Geometrie: Distanzen & Peilungen
# ===========================================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def _initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _compass(bearing: float) -> str:
    dirs = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((bearing + 11.25) % 360 // 22.5)]


def _load_cfg() -> dict:
    cfg = dict(_DEF_CFG)
    try:
        from nq.nq_common import load_config
        blk = (load_config() or {}).get("reflection", {})
        if isinstance(blk, dict):
            for k, v in blk.items():
                if k in cfg and isinstance(v, (int, float)):
                    cfg[k] = float(v)
    except Exception:
        pass
    return cfg


def _location() -> tuple[float, float]:
    try:
        import config
        return float(getattr(config, "LATITUDE", _DEFAULT_LAT)), \
            float(getattr(config, "LONGITUDE", _DEFAULT_LON))
    except Exception:
        return _DEFAULT_LAT, _DEFAULT_LON


def geometry(cfg: dict | None = None) -> dict:
    """Standort + Netzgrenz-Referenzpunkte (mit Distanz + Peilung) + Randpolygon.

    Diese Ausgabe speist die stilisierte Europakarte und die Δt→Distanz-Zuordnung.
    """
    cfg = cfg or _load_cfg()
    lat, lon = _location()
    pts = []
    for b in BOUNDARY_POINTS:
        dist = _haversine_km(lat, lon, b["lat"], b["lon"])
        brg = _initial_bearing_deg(lat, lon, b["lat"], b["lon"])
        pts.append({
            "key": b["key"], "name": b["name"], "lat": b["lat"], "lon": b["lon"],
            "dist_km": round(dist, 1), "bearing_deg": round(brg, 1), "compass": _compass(brg),
        })
    pts.sort(key=lambda p: p["dist_km"])
    return {
        "location": {"lat": lat, "lon": lon, "name": "Messpunkt (PCC)"},
        "boundary_polygon": [{"lat": a, "lon": o} for a, o in GRID_BOUNDARY],
        "boundary_points": pts,
        "inter_area_modes": INTER_AREA_MODES,
        "wave_speed": {
            "v_em_km_s": cfg["v_em_km_s"],
            "v_em_min_km_s": cfg["v_em_min_km_s"],
            "v_em_max_km_s": cfg["v_em_max_km_s"],
        },
        "band_hz": {"lo": cfg["band_lo_hz"], "hi": cfg["band_hi_hz"]},
    }


def match_boundary(delta_t_s: float, primary_bearing_deg: float | None,
                   geo: dict, cfg: dict) -> dict:
    """Ordnet eine Echo-Laufzeit Δt der wahrscheinlichsten Reflexionsstelle zu.

    d = v·Δt/2; Kandidaten = Grenzpunkte nach |dist − d| sortiert. Die
    Geschwindigkeits-Unsicherheit (v_min..v_max) spannt ein Distanzintervall auf.
    """
    v = cfg["v_em_km_s"]
    d = v * delta_t_s / 2.0
    d_lo = cfg["v_em_min_km_s"] * delta_t_s / 2.0
    d_hi = cfg["v_em_max_km_s"] * delta_t_s / 2.0
    cands = []
    for b in geo["boundary_points"]:
        cands.append({**b, "residual_km": round(abs(b["dist_km"] - d), 1),
                      "in_uncertainty": bool(d_lo <= b["dist_km"] <= d_hi)})
    cands.sort(key=lambda c: c["residual_km"])
    best = cands[0] if cands else None
    conf = "hoch" if best and best["residual_km"] <= cfg["dist_tol_km"] else (
        "mittel" if best and best["in_uncertainty"] else "gering")
    # Gegenrichtung (Herkunfts-These): der Primärimpuls lief zur Grenze, die
    # Quelle liegt tendenziell auf der gegenüberliegenden Seite.
    origin_bearing = None
    if best:
        origin_bearing = round((best["bearing_deg"] + 180.0) % 360.0, 1)
    return {
        "distance_km": round(d, 1),
        "distance_range_km": [round(d_lo, 1), round(d_hi, 1)],
        "candidate": best,
        "alternatives": cands[1:4],
        "confidence": conf,
        "origin_bearing_deg": origin_bearing,
        "origin_compass": _compass(origin_bearing) if origin_bearing is not None else None,
    }


# ===========================================================================
# 2) Signal-Loader (read-only)
# ===========================================================================

def _db_paths(start: int, end: int) -> list[str]:
    import datetime as _dt
    months, d = [], _dt.date.fromtimestamp(start).replace(day=1)
    last = _dt.date.fromtimestamp(max(start, end - 1))
    while d <= last:
        months.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    paths = [os.path.join(_DB_DIR, f"nq_{m}.db") for m in months]
    return [p for p in paths if os.path.exists(p)]


def _open_ro(path: str) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except Exception:
        return None


def load_freq_5min(start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    """Kontinuierliche Netzfrequenz (5-min) aus nq_pattern_5min (Fallback nq_5min)."""
    from nq.analysis import nq_spectral as spec
    return spec.load_clean_freq(start, end)


def load_events(start: int, end: int, limit: int = 200) -> list[dict]:
    """NF/HF-Ereigniskatalog im Fenster (read-only, für Cross-Referenz)."""
    out: list[dict] = []
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(
                "SELECT event_id, ts_start, ts_end, band, kind, trigger, severity, "
                "peak_quantity, peak_value, origin, has_snippet, metrics "
                "FROM nq_events WHERE ts_start>=? AND ts_start<? "
                "ORDER BY ts_start DESC LIMIT ?",
                (start, end, limit)).fetchall()
            for r in rows:
                metrics = {}
                try:
                    metrics = json.loads(r[11]) if r[11] else {}
                except Exception:
                    metrics = {}
                out.append({
                    "event_id": r[0], "ts_start": r[1], "ts_end": r[2], "band": r[3],
                    "kind": r[4], "trigger": r[5], "severity": r[6],
                    "peak_quantity": r[7], "peak_value": r[8], "origin": r[9],
                    "has_snippet": r[10], "metrics": metrics,
                })
        except Exception:
            pass
        finally:
            conn.close()
    out.sort(key=lambda e: e["ts_start"])
    return out


def load_event_snippet(event_id: int, start: int, end: int,
                       signal: str = "voltage") -> tuple[np.ndarray, np.ndarray, str]:
    """Hochaufgelöste Event-Wellenform (200 ms) aus nq_event_fast.

    signal='voltage' → Mittel U_L1..L3 (200 ms, bis ~2,5 Hz), 'freq' → f (≈10 s).
    Rückgabe (t_s[float], v[float], unit).
    """
    ts_ms: list[int] = []
    val: list[float] = []
    col = "f" if signal == "freq" else None
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            if signal == "freq":
                rows = conn.execute(
                    "SELECT ts_ms, f FROM nq_event_fast WHERE event_id=? AND f IS NOT NULL ORDER BY ts_ms",
                    (event_id,)).fetchall()
                for t, v in rows:
                    ts_ms.append(int(t)); val.append(float(v))
            else:
                rows = conn.execute(
                    "SELECT ts_ms, u_l1, u_l2, u_l3 FROM nq_event_fast "
                    "WHERE event_id=? ORDER BY ts_ms", (event_id,)).fetchall()
                for t, a, b, c in rows:
                    vs = [x for x in (a, b, c) if x is not None]
                    if vs:
                        ts_ms.append(int(t)); val.append(float(np.mean(vs)))
        except Exception:
            pass
        finally:
            conn.close()
    if not ts_ms:
        return np.array([]), np.array([]), ("Hz" if signal == "freq" else "V")
    t = np.asarray(ts_ms, dtype=np.float64) / 1000.0
    v = np.asarray(val, dtype=np.float64)
    order = np.argsort(t)
    return t[order] - t[order][0], v[order], ("Hz" if signal == "freq" else "V")


# ===========================================================================
# 3) Muster: Schwingungspakete + Echo-Autokorrelation
# ===========================================================================

def _detrend(x: np.ndarray) -> np.ndarray:
    if x.size < 2:
        return x - (x.mean() if x.size else 0.0)
    t = np.arange(x.size, dtype=np.float64)
    A = np.vstack([t, np.ones_like(t)]).T
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    return x - A @ coef


def _envelope(x: np.ndarray, win: int = 3) -> np.ndarray:
    """Grobe Hüllkurve = gleitendes RMS über ±win."""
    n = x.size
    if n == 0:
        return x
    out = np.empty(n)
    for i in range(n):
        lo, hi = max(0, i - win), min(n, i + win + 1)
        out[i] = math.sqrt(float(np.mean(x[lo:hi] ** 2)))
    return out


def detect_packets(t: np.ndarray, x: np.ndarray, cfg: dict) -> list[dict]:
    """Findet Schwingungspakete (Bursts erhöhter Hüllkurve) in (t, x).

    Je Paket: Startzeit, Dauer, dominante Periode (aus Nulldurchgängen),
    Amplitude (max|x|), Gradient (max|dx/dt|), Dämpfung (Hüllkurven-Abfall).
    """
    if x.size < cfg["packet_min_len"] * 2:
        return []
    xd = _detrend(x)
    env = _envelope(xd, win=2)
    med = float(np.median(env)) or 1e-12
    thr = cfg["packet_env_k"] * med
    packets: list[dict] = []
    i, n = 0, x.size
    while i < n:
        if env[i] <= thr:
            i += 1
            continue
        j = i
        while j < n and env[j] > thr:
            j += 1
        seg_t, seg_x = t[i:j], xd[i:j]
        if seg_x.size >= cfg["packet_min_len"]:
            # dominante Periode aus Nulldurchgängen
            zc = np.where(np.diff(np.sign(seg_x)))[0]
            period_s = None
            if zc.size >= 2:
                half = float(np.mean(np.diff(seg_t[zc])))
                period_s = 2.0 * half if half > 0 else None
            dt = float(np.median(np.diff(seg_t))) if seg_t.size > 1 else 1.0
            grad = float(np.max(np.abs(np.diff(seg_x)))) / dt if seg_t.size > 1 else 0.0
            e0, e1 = float(env[i]), float(env[max(i, j - 1)])
            packets.append({
                "t_start": float(seg_t[0]), "t_end": float(seg_t[-1]),
                "duration_s": float(seg_t[-1] - seg_t[0]),
                "amplitude": round(float(np.max(np.abs(seg_x))), 6),
                "gradient_per_s": round(grad, 6),
                "period_s": round(period_s, 3) if period_s else None,
                "freq_hz": round(1.0 / period_s, 6) if period_s else None,
                "damping": round((e0 - e1) / e0, 3) if e0 > 0 else None,
                "n": int(seg_x.size),
            })
        i = j
    return packets


def autocorr_echo(t: np.ndarray, x: np.ndarray, cfg: dict) -> dict | None:
    """Sucht ein Echo via normierter Autokorrelation im plausiblen Laufzeitband.

    Rückgabe (bestes Echo) oder None: {delta_t_s, corr, amp_ratio}.
    """
    if x.size < 8:
        return None
    xd = _detrend(x)
    dt = float(np.median(np.diff(t))) if t.size > 1 else 1.0
    if dt <= 0:
        return None
    ac = np.correlate(xd, xd, mode="full")
    mid = ac.size // 2
    ac = ac[mid:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    lag_min = max(1, int(round(cfg["echo_tau_min_s"] / dt)))
    lag_max = min(ac.size - 1, int(round(cfg["echo_tau_max_s"] / dt)))
    if lag_max <= lag_min:
        return None
    window = ac[lag_min:lag_max + 1]
    # lokale Maxima
    best_lag, best_corr = None, -1.0
    for k in range(1, window.size - 1):
        if window[k] > window[k - 1] and window[k] >= window[k + 1] and window[k] > best_corr:
            best_corr, best_lag = float(window[k]), lag_min + k
    if best_lag is None or best_corr < cfg["echo_min_corr"]:
        return None
    # Amplitudenverhältnis (Hüllkurve bei 0 vs. Echo-Lag)
    env = _envelope(xd, win=2)
    a0 = float(np.max(env[:max(1, best_lag)]))
    a1 = float(np.max(env[best_lag:min(env.size, 2 * best_lag)]))
    amp_ratio = round(a1 / a0, 3) if a0 > 0 else None
    if amp_ratio is not None and amp_ratio > cfg["echo_max_amp_ratio"]:
        return None
    return {"delta_t_s": round(best_lag * dt, 3), "corr": round(best_corr, 3),
            "amp_ratio": amp_ratio}


# ===========================================================================
# 4) Orchestrierung
# ===========================================================================

def analyze_event(ev: dict, start: int, end: int, geo: dict, cfg: dict) -> dict | None:
    """Analysiert einen Event-Schnipsel (Spannung 200 ms) auf ein Echo →
    Reflexionsstellen-Hypothese (physikalisch belastbarer Pfad)."""
    if not ev.get("has_snippet"):
        return None
    t, v, unit = load_event_snippet(ev["event_id"], start, end, signal="voltage")
    if t.size < 8:
        return None
    echo = autocorr_echo(t, v, cfg)
    if not echo:
        return None
    match = match_boundary(echo["delta_t_s"], None, geo, cfg)
    return {
        "event_id": ev["event_id"], "ts_start": ev["ts_start"], "band": ev["band"],
        "kind": ev["kind"], "signal": "voltage", "unit": unit, "n": int(t.size),
        "echo": echo, "reflection": match,
        "series": {"t_s": [round(float(x), 3) for x in t],
                   "v": [round(float(x), 4) for x in v]},
        "thesis": _event_thesis(ev, echo, match),
    }


def _event_thesis(ev: dict, echo: dict, match: dict) -> str:
    cand = match.get("candidate") or {}
    return (
        f"Event #{ev['event_id']} ({ev.get('kind') or ev.get('band')}): Echo nach "
        f"Δt={echo['delta_t_s']} s (Korr {echo['corr']}, Amplitude {echo.get('amp_ratio')}× "
        f"des Primärimpulses). Umlaufdistanz d≈{match['distance_km']} km ⇒ wahrscheinliche "
        f"Reflexionsstelle: {cand.get('name','?')} "
        f"(Δ {cand.get('residual_km','?')} km, Konfidenz {match['confidence']}). "
        f"Herkunfts-These (Gegenrichtung): {match.get('origin_compass','?')}."
    )


def analyze(start: int, end: int, signal: str = "freq",
            max_events: int = 40) -> dict:
    """Gesamt-Reflexionsanalyse für [start, end).

    Liefert traceable JSON: Geometrie + kontinuierliche Schwingungspakete
    (5-min, für den Zeitreihen-Chart) + Event-basierte Reflexions-Hypothesen
    (Spannungs-Schnipsel) + Arbeitsthesen.
    """
    cfg = _load_cfg()
    geo = geometry(cfg)

    # (a) kontinuierliche Frequenz-Schwingungspakete (mHz-Band, VLF)
    ts, fv = load_freq_5min(start, end)
    packets: list[dict] = []
    series: dict = {"ts": [], "values": [], "unit": "mHz", "signal": "freq"}
    if ts.size >= cfg["packet_min_len"] * 2:
        dev_mhz = (fv - 50.0) * 1000.0  # Frequenzabweichung in mHz
        packets = detect_packets(ts.astype(float), dev_mhz, cfg)
        # Reihe kompakt (max ~1500 Punkte) für den Chart
        step = max(1, ts.size // 1500)
        series = {
            "ts": [int(t) for t in ts[::step]],
            "values": [round(float(x), 3) for x in dev_mhz[::step]],
            "unit": "mHz", "signal": "freq",
        }

    # (b) Event-Katalog + Schnipsel-Reflexionen (physikalischer Pfad)
    events = load_events(start, end, limit=200)
    reflections: list[dict] = []
    for ev in events:
        if len(reflections) >= max_events:
            break
        res = analyze_event(ev, start, end, geo, cfg)
        if res:
            reflections.append(res)

    theses = _global_theses(packets, reflections, events, geo)
    return {
        "start": start, "end": end, "signal": signal,
        "geometry": geo,
        "series": series,
        "packets": packets,
        "reflections": reflections,
        "events_total": len(events),
        "events_with_snippet": sum(1 for e in events if e.get("has_snippet")),
        "theses": theses,
        "method": "autocorr-echo + Δt→d=v·Δt/2 → Grenz-Zuordnung",
        "caveats": [
            "Aus einem Messpunkt keine gesicherte Richtung skalarer Frequenzereignisse.",
            "PAC-Frequenzband ≤50 mHz (10-s-Refresh); schnelle Laufwellen nur in der "
            "Spannung (200 ms, lokal) und nur in Event-Schnipseln auflösbar.",
            "5-min-Schwingungspakete = VLF-Beobachtung, keine Laufwellen-Echos.",
            f"v_em={cfg['v_em_km_s']} km/s ist ein Literaturwert (200…1400) — die "
            "Distanz skaliert linear mit v_em.",
        ],
        "n_freq_samples": int(ts.size),
        "source": "nq_pattern_5min + nq_events/nq_event_fast",
    }


def _global_theses(packets: list, reflections: list, events: list, geo: dict) -> list[str]:
    out: list[str] = []
    near = geo["boundary_points"][0] if geo["boundary_points"] else None
    if near:
        out.append(
            f"Nächste Netzgrenze: {near['name']} in ~{near['dist_km']} km "
            f"({near['compass']}, Peilung {near['bearing_deg']}°). Ein dortiges Echo "
            f"erschiene bei v={geo['wave_speed']['v_em_km_s']} km/s nach "
            f"Δt≈{round(2*near['dist_km']/geo['wave_speed']['v_em_km_s'],2)} s.")
    if reflections:
        out.append(f"{len(reflections)} Event-Schnipsel mit belastbarem Echo → "
                   "Distanz-Hypothesen zu Netzgrenzen (siehe Karte/Tabelle).")
    else:
        out.append("Keine Event-Schnipsel mit belastbarem Echo im Zeitraum — "
                   "die Reflexionskarte zeigt die Geometrie/Erwartungswerte.")
    if packets:
        strongest = max(packets, key=lambda p: p["amplitude"])
        fh = strongest.get("freq_hz")
        out.append(
            f"Stärkstes Frequenz-Schwingungspaket: Amplitude {strongest['amplitude']} mHz"
            + (f", ~{round(fh*1000,3)} mHz (T≈{strongest['period_s']} s)" if fh else "")
            + f", Dämpfung {strongest.get('damping')}.")
    return out


# ===========================================================================
# CLI / Selbsttest
# ===========================================================================

def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Reflexions-/Laufwellen-Analyse (Rolle N)")
    ap.add_argument("--geometry", action="store_true", help="nur Geometrie ausgeben")
    ap.add_argument("--days", type=int, default=30, help="Analysefenster (Tage)")
    ap.add_argument("--signal", default="freq", choices=["freq", "voltage"])
    a = ap.parse_args()
    if a.geometry:
        print(json.dumps(geometry(), ensure_ascii=False, indent=2))
        return 0
    end = int(time.time())
    start = end - a.days * 86400
    print(json.dumps(analyze(start, end, a.signal), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
