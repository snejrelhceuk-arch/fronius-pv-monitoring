#!/usr/bin/env python3
"""nq.analysis.nq_spectral — Spektralanalyse-Pipeline der Netzqualitaet (Rolle N).

Ersetzt die alte "Netzmusteranalyse" durch eine mathematisch fundierte
Spektral-Pipeline. **Read-only** auf den NQ-Aggregat-DBs (``nq/db/nq_YYYY-MM.db``);
kein Schreibpfad in Produktion/Aktoren (Rolle-N-Invariante).

Abhaengigkeiten: **nur numpy** (Prod-venv hat kein scipy). Alle Verfahren
(Welch-PSD, Lomb-Scargle, Dezimation mit Anti-Aliasing, STFT, Morlet-CWT,
Frequenz-Binning, THD) sind hier in reinem numpy implementiert.

================================================================================
MESSTECHNISCHE REALITAET (wichtig fuer die Interpretation)
================================================================================
Die gespeicherten Zeitreihen sind **aggregiert**, keine Roh-Kurvenformen:
  - Fronius Smart-Meter (raw_data):  ~3 s   -> Nyquist ~0,167 Hz
  - PAC4200 nq_5min:                 300 s  -> Nyquist  1,667 mHz
  - nq_hourly / nq_daily:            3600 s / 86400 s

Daraus folgt zwingend:
  * Eine echte PSD/THD ueber 50 Hz aus **Abtastwerten** ist unmoeglich
    (Nyquist << 50 Hz). Der Hochfrequenz-/Oberschwingungsteil (>50 Hz) stammt
    daher aus den **geraeteinternen FFT-Registern** des PAC4200:
    Einzelharmonische H1,H3,H5,...,H31 (ungerade, A.3.10) und THDu/THDi.
    Ordnung n  ->  Frequenz  f_n = n * 50 Hz  (H3=150 Hz, H5=250 Hz, ...).
    Gerade Ordnungen (z.B. 100 Hz, Gleichrichter) werden vom Geraet nicht als
    Einzelregister gefuehrt; ihr Beitrag steckt indirekt in THD/Unsymmetrie.
  * Der Sub-50-Hz-Bereich (LF/VLF/eVLF: Handelstakte, Tag/Nacht, Woche, Saison,
    Jahr) ist mit den 5-min-/stuendlichen/taeglichen Reihen vollstaendig
    aufloesbar und ist der eigentliche Erkenntnisgewinn dieser Pipeline.

================================================================================
MATHEMATISCHE BEGRUENDUNG (Filterordnungen, Fenster, Dezimationsfaktoren)
================================================================================
1) 50-Hz-Notch / Bandsplit
   Bei Roh-Kurvenformen dominiert die 50-Hz-Grundschwingung die gesamte Energie
   und maskiert alles andere. Der klassische Weg ist ein steiler IIR-Notch
   (Butterworth/Sperrband 48..52 Hz). Da wir **keine** Roh-Kurvenform haben,
   ist der Notch fuer die Live-Daten gegenstandslos; die Funktion
   ``notch_biquad``/``bandstop_zeros`` ist als reine-numpy-Referenz enthalten
   (RBJ-Biquad, Q=f0/BW), falls spaeter ein kHz-Feed hinzukommt. Fuer die
   Darstellung nutzen wir stattdessen den **Log-Log-Bandsplit**: getrennte
   Achsen fuer die Baender, damit die energiearmen Linien sichtbar werden.

2) Welch-PSD
   Fenster: **Hann** (guter Nebenkeulen-Kompromiss, -31,5 dB, glatte Leckage)
   als Default; **Blackman** (-58 dB) wenn benachbarte starke Linien getrennt
   werden muessen. Segmentierung mit 50 % Overlap reduziert die Varianz der
   Schaetzung (~1/K bei K Segmenten) auf Kosten der Frequenzaufloesung
   (df = fs/nperseg). One-sided, korrekt normiert (V^2/Hz).

3) Lomb-Scargle (VLF/eVLF)
   Die 5-min-Reihe hat Luecken (DB-Retention, Ausfaelle). Lomb-Scargle ist fuer
   **ungleichmaessig** abgetastete Daten definiert und vermeidet die
   Interpolationsartefakte, die eine FFT einfuehren wuerde. Normierung nach
   Press & Rybicki (auf die Datenvarianz).

4) Dezimation
   Fuer sehr lange Zeitraeume (Jahre) wird vor der Analyse dezimiert. Ein
   Dezimationsfaktor M erfordert **vor** dem Downsampling einen Anti-Aliasing-
   Tiefpass mit Grenzfrequenz fc = 0,5/M * fs (normiert). Wir nutzen einen
   windowed-sinc FIR (Blackman-Fenster, numtaps ungerade, linearphasig). Die
   Taps skalieren mit der geforderten Flankensteilheit; Default numtaps = 8*M+1.
   Faustregel Faktoren: M so waehlen, dass die interessierende Obergrenze
   (z.B. Handelstakt 1,11 mHz) mit >=4-facher Ueberabtastung erhalten bleibt.

5) STFT / Morlet-CWT (Transienten: Verschiebungen & Aufschwingen)
   STFT: Hann-Fenster, nperseg als Kompromiss Zeit/Frequenz. CWT (komplexer
   Morlet, w0=6) hat logarithmisch skalierende Zeit-Frequenz-Aufloesung und
   isoliert kurze Ringing-Bursts (Aufschwingen) sowie driftende Dominanz-
   frequenzen (Verschiebungen) besser als eine STFT mit fester Fensterbreite.

Start (Selbsttest/CLI):
  python3 -m nq.analysis.nq_spectral --demo
  python3 -m nq.analysis.nq_spectral --periodogram --days 30
Doku: doc/llm/cards/netzqualitaet-nq-analysis-events.card.md
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import sqlite3
import time
from typing import Iterable

import numpy as np

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")

# Skalar-Selektor in nq_5min/nq_hourly (Skalare: meas='' , phase=0, ord=0).
_SCALAR_WHERE = "meas='' AND phase=0 AND ord=0"

# Zyklus-Marker (Attribution) fuer den VLF/eVLF-Bereich: Periode [s] -> Label.
# Frequenz f = 1/T; im Frontend als vertikale Marker + Tooltip verwendet.
CYCLE_MARKERS: list[dict] = [
    {"label": "15-min-Handelstakt", "period_s": 900,       "attr": "EPEX-Viertelstundenkontrakte (Fahrplanwechsel)"},
    {"label": "30-min",            "period_s": 1800,      "attr": "Halbstundenraster einzelner Regelprodukte"},
    {"label": "Stundentakt",       "period_s": 3600,      "attr": "Stundenkontrakte / Lastwechsel zur vollen Stunde"},
    {"label": "12-h (semidiurnal)", "period_s": 43200,    "attr": "Halbtaegiger Last-/Temperaturgang"},
    {"label": "Tagesgang",         "period_s": 86400,     "attr": "PV-Einspeisung + Tag/Nacht-Last (diurnal)"},
    {"label": "Wochenrhythmus",    "period_s": 604800,    "attr": "Werktag vs. Wochenende (Industrielast)"},
    {"label": "Jahresgang",        "period_s": 31557600,  "attr": "Saison/Jahreszeit + Urlaubs-/Feiertagsphasen"},
]


# ===========================================================================
# 1) Daten-Loader (read-only, monatsweise DBs)
# ===========================================================================

def _months_in_range(start: int, end: int) -> list[str]:
    import datetime as _dt
    out: list[str] = []
    d = _dt.date.fromtimestamp(start).replace(day=1)
    last = _dt.date.fromtimestamp(max(start, end - 1))
    while d <= last:
        out.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    return out


def _db_paths(start: int, end: int) -> list[str]:
    paths = [os.path.join(_DB_DIR, f"nq_{m}.db") for m in _months_in_range(start, end)]
    return [p for p in paths if os.path.exists(p)]


def _open_ro(path: str) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except Exception:
        return None


def load_scalar_series(quantity: str, start: int, end: int,
                       table: str = "nq_5min", value: str = "vavg") -> tuple[np.ndarray, np.ndarray]:
    """Laedt eine Skalar-Zeitreihe (ts, v) aus nq_5min/nq_hourly/nq_daily.

    nq_daily nutzt den TEXT-Schluessel ``day`` (localtime-Mitternacht -> Unix-ts).
    Rueckgabe: (ts:int64[s], v:float64), aufsteigend sortiert, NaN fuer Luecken
    werden nicht eingefuegt (echte Abtastpunkte).
    """
    ts_list: list[int] = []
    v_list: list[float] = []
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            if table == "nq_daily":
                rows = conn.execute(
                    f"SELECT day, {value} FROM nq_daily "
                    f"WHERE quantity=? AND {_SCALAR_WHERE} ORDER BY day",
                    (quantity,)).fetchall()
                for day, v in rows:
                    try:
                        t = time.strptime(day, "%Y-%m-%d")
                        tsec = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
                    except Exception:
                        continue
                    if start <= tsec < end and v is not None:
                        ts_list.append(tsec)
                        v_list.append(float(v))
            else:
                rows = conn.execute(
                    f"SELECT ts, {value} FROM {table} "
                    f"WHERE quantity=? AND {_SCALAR_WHERE} AND ts>=? AND ts<? ORDER BY ts",
                    (quantity, start, end)).fetchall()
                for tsec, v in rows:
                    if v is not None:
                        ts_list.append(int(tsec))
                        v_list.append(float(v))
        except Exception:
            pass
        finally:
            conn.close()
    if not ts_list:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    ts = np.asarray(ts_list, dtype=np.int64)
    v = np.asarray(v_list, dtype=np.float64)
    order = np.argsort(ts)
    return ts[order], v[order]


def load_clean_freq(start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    """Netzfrequenz-Reihe (5-min). Bevorzugt nq_pattern_5min.freq (residual-
    bereinigt), faellt auf nq_5min-Skalar 'FREQ' zurueck."""
    ts_list: list[int] = []
    v_list: list[float] = []
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(
                "SELECT ts, freq FROM nq_pattern_5min WHERE ts>=? AND ts<? AND freq IS NOT NULL ORDER BY ts",
                (start, end)).fetchall()
            for tsec, v in rows:
                ts_list.append(int(tsec))
                v_list.append(float(v))
        except Exception:
            pass
        finally:
            conn.close()
    if ts_list:
        ts = np.asarray(ts_list, dtype=np.int64)
        v = np.asarray(v_list, dtype=np.float64)
        order = np.argsort(ts)
        return ts[order], v[order]
    return load_scalar_series("FREQ", start, end, table="nq_5min")


def load_clean_voltage(start: int, end: int, phase: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Netzseitige (bereinigte) Spannung U_LN einer Phase aus nq_pattern_5min."""
    col = f"u_clean_l{phase}"
    ts_list: list[int] = []
    v_list: list[float] = []
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(
                f"SELECT ts, {col} FROM nq_pattern_5min WHERE ts>=? AND ts<? AND {col} IS NOT NULL ORDER BY ts",
                (start, end)).fetchall()
            for tsec, v in rows:
                ts_list.append(int(tsec))
                v_list.append(float(v))
        except Exception:
            pass
        finally:
            conn.close()
    if not ts_list:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    ts = np.asarray(ts_list, dtype=np.int64)
    v = np.asarray(v_list, dtype=np.float64)
    order = np.argsort(ts)
    return ts[order], v[order]


def load_harmonics(start: int, end: int, meas: str = "U_LN") -> dict:
    """Einzelharmonische-Linienspektrum (geraeteinterne FFT) aus nq_5min.

    Mittelt vavg ueber das Fenster und ueber die 3 Phasen je Ordnung.
    meas: 'U_LN' (Phasenspannung), 'U_LL' (verkettet), 'I' (Strom).
    Rueckgabe: {'orders':[...], 'freqs_hz':[...], 'values':[...], 'unit':...,
                'n':..., 'meas':meas}. Ordnung n -> f = n*50 Hz.
    """
    acc: dict[int, list[float]] = {}
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(
                "SELECT ord, AVG(vavg) FROM nq_5min "
                "WHERE quantity='' AND meas=? AND ts>=? AND ts<? AND vavg IS NOT NULL "
                "GROUP BY ord",
                (meas, start, end)).fetchall()
            for ordn, v in rows:
                if v is not None:
                    acc.setdefault(int(ordn), []).append(float(v))
        except Exception:
            pass
        finally:
            conn.close()
    orders = sorted(acc)
    values = [float(np.mean(acc[o])) for o in orders]
    unit = "V" if meas.startswith("U") else "A"
    return {
        "orders": orders,
        "freqs_hz": [o * 50.0 for o in orders],
        "values": values,
        "unit": unit,
        "meas": meas,
        "n": len(orders),
    }


def load_harmonic_thd_series(start: int, end: int, meas: str = "U_LN") -> dict:
    """THD-Zeitreihe **aus den Einzelharmonischen berechnet** (je 5-min-Bucket).

    Pro Bucket/Phase: THD = sqrt(sum_{n>=2} H_n^2)/H_1. Ueber die Phasen
    gemittelt. Dient dem Korrelationsvergleich gegen das PAC4200-THD-Register.
    Rueckgabe: {'ts':[...], 'values':[...]}  (THD in %).

    Plausibilitätsprüfung: Harmonischenwerte > 1e6 werden verworfen (in thd_from_harmonics).
    """
    # {ts: {phase: {ord: value}}}
    buckets: dict[int, dict[int, dict[int, float]]] = {}
    for path in _db_paths(start, end):
        conn = _open_ro(path)
        if conn is None:
            continue
        try:
            rows = conn.execute(
                "SELECT ts, phase, ord, vavg FROM nq_5min "
                "WHERE quantity='' AND meas=? AND ts>=? AND ts<? AND vavg IS NOT NULL",
                (meas, start, end)).fetchall()
            for tsec, phase, ordn, v in rows:
                # Plausibilitätsprüfung bereits in thd_from_harmonics
                buckets.setdefault(int(tsec), {}).setdefault(int(phase), {})[int(ordn)] = float(v)
        except Exception:
            pass
        finally:
            conn.close()
    ts_out: list[int] = []
    v_out: list[float] = []
    for tsec in sorted(buckets):
        phase_thd = []
        for phase, orders in buckets[tsec].items():
            thd = thd_from_harmonics(orders.keys(), orders.values())
            if thd is not None:
                phase_thd.append(thd)
        if phase_thd:
            ts_out.append(tsec)
            mean_thd = float(np.mean(phase_thd))
            # Zusätzliche Plausibilitätsprüfung des gemittelten Werts
            if math.isfinite(mean_thd) and 0 <= mean_thd <= 200.0:
                v_out.append(round(mean_thd, 3))
            else:
                continue
    return {"ts": ts_out, "values": v_out}


def load_thd_series(start: int, end: int, kind: str = "u") -> dict:
    """THD-Zeitreihe (Phasen-Mittel) aus den PAC4200-THD-Registern (nq_5min).

    kind: 'u' -> THDu_L1..L3, 'i' -> THDi_L1..L3. Rueckgabe (ts, v) gemittelt.

    Plausibilitätsprüfung: NaN/Inf und Werte außerhalb [0, 200%] werden gefiltert.
    """
    prefix = "THDu_L" if kind == "u" else "THDi_L"
    series = [load_scalar_series(f"{prefix}{p}", start, end) for p in (1, 2, 3)]
    series = [s for s in series if s[0].size]
    if not series:
        return {"ts": [], "values": []}
    # gemeinsame Zeitbasis = Schnittmenge der Zeitstempel
    common = set(series[0][0].tolist())
    for ts, _ in series[1:]:
        common &= set(ts.tolist())
    if not common:
        ts0, v0 = series[0]
        # Plausibilitätsprüfung
        mask = np.isfinite(v0) & (v0 >= 0) & (v0 <= 200.0)
        return {"ts": ts0[mask].tolist(), "values": np.round(v0[mask], 3).tolist()}
    common_ts = np.array(sorted(common), dtype=np.int64)
    stacked = []
    for ts, v in series:
        idx = {int(t): float(val) for t, val in zip(ts, v)}
        stacked.append(np.array([idx[int(t)] for t in common_ts]))
    mean_v = np.mean(np.vstack(stacked), axis=0)
    # Plausibilitätsprüfung des Mittelwerts
    mask = np.isfinite(mean_v) & (mean_v >= 0) & (mean_v <= 200.0)
    return {"ts": common_ts[mask].tolist(), "values": np.round(mean_v[mask], 3).tolist()}


# ===========================================================================
# 2) Hilfen: Uniform-Grid + Fenster
# ===========================================================================

def resample_uniform(ts: np.ndarray, v: np.ndarray, dt: float | None = None
                     ) -> tuple[np.ndarray, np.ndarray, float]:
    """Legt (ts, v) per linearer Interpolation auf ein aequidistantes Raster.

    Notwendig fuer Welch/STFT/CWT (setzen konstante Abtastung voraus). dt wird
    aus dem Median der Zeitdifferenzen geschaetzt, wenn nicht angegeben.
    Rueckgabe: (t_uniform[s], v_uniform, fs[Hz]).
    """
    if ts.size < 2:
        return ts.astype(float), v.astype(float), 0.0
    if dt is None:
        diffs = np.diff(ts).astype(float)
        dt = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 300.0
    t0, t1 = float(ts[0]), float(ts[-1])
    n = int(math.floor((t1 - t0) / dt)) + 1
    t_uni = t0 + np.arange(n) * dt
    v_uni = np.interp(t_uni, ts.astype(float), v)
    return t_uni, v_uni, 1.0 / dt


def get_window(name: str, n: int) -> np.ndarray:
    name = (name or "hann").lower()
    if name == "blackman":
        return np.blackman(n)
    if name == "hamming":
        return np.hamming(n)
    if name in ("boxcar", "rect", "none"):
        return np.ones(n)
    return np.hanning(n)


# ===========================================================================
# 3) Welch-PSD (pure numpy)
# ===========================================================================

def welch_psd(x: np.ndarray, fs: float, nperseg: int = 256,
              noverlap: int | None = None, window: str = "hann",
              detrend: str = "constant") -> tuple[np.ndarray, np.ndarray]:
    """Einseitige Leistungsdichte nach Welch (Segment-Mittelung, numpy-only).

    PSD-Normierung: |X|^2 / (fs * sum(w^2)); einseitig (x2 ausser DC/Nyquist).
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < 8:
        return np.array([]), np.array([])
    nperseg = int(min(nperseg, n))
    if noverlap is None:
        noverlap = nperseg // 2
    step = max(1, nperseg - noverlap)
    win = get_window(window, nperseg)
    scale = 1.0 / (fs * np.sum(win ** 2))
    starts = range(0, n - nperseg + 1, step)
    psd_acc = None
    k = 0
    for s in starts:
        seg = x[s:s + nperseg].copy()
        if detrend == "constant":
            seg -= seg.mean()
        elif detrend == "linear":
            seg = _detrend_linear(seg)
        seg = seg * win
        spec = np.fft.rfft(seg)
        p = (np.abs(spec) ** 2) * scale
        if p.size > 2:
            p[1:-1] *= 2.0
        psd_acc = p if psd_acc is None else psd_acc + p
        k += 1
    if k == 0 or psd_acc is None:
        return np.array([]), np.array([])
    psd = psd_acc / k
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return freqs, psd


def _detrend_linear(x: np.ndarray) -> np.ndarray:
    n = x.size
    t = np.arange(n)
    a, b = np.polyfit(t, x, 1)
    return x - (a * t + b)


# ===========================================================================
# 4) Lomb-Scargle-Periodogramm (ungleichmaessige Abtastung)
# ===========================================================================

def lombscargle(t: np.ndarray, x: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """Normiertes Lomb-Scargle-Periodogramm (Press & Rybicki).

    t [s], x beliebige Einheit, freqs [Hz]. Rueckgabe: Power (auf Varianz
    normiert). Robust gegen Luecken/ungleiche Abstaende.
    """
    t = np.asarray(t, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    mask = np.isfinite(t) & np.isfinite(x)
    t = t[mask]; x = x[mask]
    n = t.size
    if n < 4 or freqs.size == 0:
        return np.zeros_like(freqs)
    x = x - x.mean()
    var = x.var()
    if var <= 0:
        return np.zeros_like(freqs)
    power = np.empty(freqs.size, dtype=np.float64)
    for i, f in enumerate(freqs):
        w = 2.0 * math.pi * f
        if w == 0.0:
            power[i] = 0.0
            continue
        wt = w * t
        s2 = np.sum(np.sin(2.0 * wt))
        c2 = np.sum(np.cos(2.0 * wt))
        tau = 0.5 * math.atan2(s2, c2) / w
        wtt = w * (t - tau)
        cos_wtt = np.cos(wtt)
        sin_wtt = np.sin(wtt)
        cc = np.sum(cos_wtt ** 2)
        ss = np.sum(sin_wtt ** 2)
        xc = np.sum(x * cos_wtt)
        xs = np.sum(x * sin_wtt)
        term_c = (xc ** 2 / cc) if cc > 1e-12 else 0.0
        term_s = (xs ** 2 / ss) if ss > 1e-12 else 0.0
        power[i] = 0.5 * (term_c + term_s) / var
    return power


def log_freq_grid(f_min: float, f_max: float, points: int = 400) -> np.ndarray:
    """Logarithmisch verteiltes Frequenzraster (fuer VLF/eVLF sinnvoll)."""
    f_min = max(f_min, 1e-12)
    return np.logspace(math.log10(f_min), math.log10(f_max), points)


# ===========================================================================
# 5) Frequenz-Binning (log, energie-integrierend)
# ===========================================================================

def log_bin(freqs: np.ndarray, power: np.ndarray, bins_per_decade: int = 12
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aggregiert (summiert) benachbarte Bins in log-aequidistante Baender.

    Sinnvoll fuer breite, langsame Fluktuationen: die Spektralenergie eines
    Bandes wird aufaddiert und einem geometrischen Mittelpunkt zugeordnet.
    Rueckgabe: (bin_freq, bin_power_sum, bin_count).
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    power = np.asarray(power, dtype=np.float64)
    valid = np.isfinite(freqs) & (freqs > 0) & np.isfinite(power)
    freqs = freqs[valid]; power = power[valid]
    if freqs.size == 0:
        return np.array([]), np.array([]), np.array([])
    f_lo, f_hi = freqs.min(), freqs.max()
    n_dec = max(1.0, math.log10(f_hi / f_lo))
    n_bins = max(1, int(round(n_dec * bins_per_decade)))
    edges = np.logspace(math.log10(f_lo), math.log10(f_hi), n_bins + 1)
    idx = np.clip(np.digitize(freqs, edges) - 1, 0, n_bins - 1)
    bin_power = np.zeros(n_bins)
    bin_count = np.zeros(n_bins)
    for j, p in zip(idx, power):
        bin_power[j] += p
        bin_count[j] += 1
    centers = np.sqrt(edges[:-1] * edges[1:])
    keep = bin_count > 0
    return centers[keep], bin_power[keep], bin_count[keep]


# ===========================================================================
# 6) Dezimation mit Anti-Aliasing (windowed-sinc FIR, pure numpy)
# ===========================================================================

def fir_lowpass(numtaps: int, cutoff_norm: float, window: str = "blackman") -> np.ndarray:
    """Linearphasiger windowed-sinc Tiefpass. cutoff_norm in (0, 0.5] (x fs)."""
    if numtaps % 2 == 0:
        numtaps += 1
    m = (numtaps - 1) / 2.0
    n = np.arange(numtaps) - m
    h = 2.0 * cutoff_norm * np.sinc(2.0 * cutoff_norm * n)
    h *= get_window(window, numtaps)
    h /= np.sum(h)
    return h


def decimate(x: np.ndarray, factor: int, numtaps: int | None = None) -> np.ndarray:
    """Dezimiert x um ganzzahligen Faktor mit vorherigem Anti-Aliasing-TP.

    Grenzfrequenz fc = 0,5/factor (x fs). numtaps default 8*factor+1.
    """
    factor = int(factor)
    if factor <= 1 or x.size < factor * 4:
        return x
    factor = min(factor, 10)
    if numtaps is None:
        numtaps = 8 * factor + 1
    h = fir_lowpass(numtaps, 0.5 / factor)
    filtered = np.convolve(x, h, mode="same")
    return filtered[::factor]


# ===========================================================================
# 7) STFT-Spektrogramm (pure numpy)
# ===========================================================================

def stft(x: np.ndarray, fs: float, nperseg: int = 128,
         noverlap: int | None = None, window: str = "hann"
         ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Kurzzeit-FFT. Rueckgabe: (freqs[Hz], times[s ab 0], |Zxx| 2D [f, t])."""
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < nperseg:
        nperseg = max(8, n)
    if noverlap is None:
        noverlap = nperseg // 2
    step = max(1, nperseg - noverlap)
    win = get_window(window, nperseg)
    cols = []
    times = []
    for s in range(0, n - nperseg + 1, step):
        seg = x[s:s + nperseg] - x[s:s + nperseg].mean()
        spec = np.fft.rfft(seg * win)
        cols.append(np.abs(spec))
        times.append((s + nperseg / 2.0) / fs)
    if not cols:
        return np.array([]), np.array([]), np.zeros((0, 0))
    Z = np.array(cols).T
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return freqs, np.asarray(times), Z


# ===========================================================================
# 8) Morlet-CWT (komplex, pure numpy) — Transienten/Ringing
# ===========================================================================

def morlet_cwt(x: np.ndarray, fs: float, freqs: np.ndarray, w0: float = 6.0
               ) -> np.ndarray:
    """Kontinuierliche Wavelet-Transformation mit komplexem Morlet.

    scale_f = w0 * fs / (2*pi*f). Rueckgabe: |W| 2D [len(freqs), len(x)].
    Fuer moderate Laengen (bis ~50k) via FFT-Faltung effizient.
    """
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    n = x.size
    if n == 0 or freqs.size == 0:
        return np.zeros((freqs.size, n))
    out = np.empty((freqs.size, n), dtype=np.float64)
    Xf = np.fft.fft(x, n=2 * n)  # zero-pad -> lineare Faltung
    for i, f in enumerate(freqs):
        if f <= 0:
            out[i] = 0.0
            continue
        s = w0 * fs / (2.0 * math.pi * f)          # Skala in Samples
        half = int(min(n, math.ceil(8.0 * s)))
        tt = np.arange(-half, half + 1) / s
        # komplexes Morlet-Wavelet (normiert)
        psi = (math.pi ** -0.25) * np.exp(1j * w0 * tt) * np.exp(-0.5 * tt ** 2)
        psi /= math.sqrt(s)
        L = psi.size
        Pf = np.fft.fft(psi, n=2 * n)
        conv = np.fft.ifft(Xf * Pf)[:n + L - 1]
        start = L // 2
        w = conv[start:start + n]
        out[i] = np.abs(w)
    return out


# ===========================================================================
# 9) THD aus Einzelharmonischen
# ===========================================================================

def thd_from_harmonics(orders: Iterable[int], values: Iterable[float]) -> float | None:
    """THD [%] = sqrt(sum_{n>=2} H_n^2) / H_1 * 100.

    Nutzt die vorhandenen (ungeraden) Ordnungen. Gerade Ordnungen fehlen im
    PAC4200-Registersatz -> Ergebnis ist eine untere Schranke (dokumentiert).

    Plausibilitätsprüfungen:
      - h1 > 0 und < 1e6 (Volt/Ampere)
      - Harmonische < 1e6 und endlich
      - Ergebnis < 200% (theoretisches Maximum)
    """
    d = {}
    for o, v in zip(orders, values):
        # Plausibilitätsprüfung der Eingabewerte
        if not math.isfinite(v) or abs(v) > 1e6:
            continue
        d[int(o)] = float(v)

    h1 = d.get(1)
    if not h1 or h1 <= 0 or h1 > 1e6:
        return None
    rest = math.sqrt(sum(v * v for o, v in d.items() if o >= 2))
    thd = 100.0 * rest / h1

    # Plausibilitätsprüfung des Ergebnisses (THD sollte < 200% sein)
    if not math.isfinite(thd) or thd < 0 or thd > 200.0:
        return None
    return round(thd, 3)


# ===========================================================================
# CLI / Selbsttest
# ===========================================================================

def _demo() -> int:
    """Synthetischer Selbsttest ohne DB (verifiziert die DSP-Kerne)."""
    fs = 1.0 / 300.0  # 5-min
    n = 4096
    t = np.arange(n) / fs
    # Staerkerer Tagesgang (11,57 uHz) + 15-min-Takt (1,11 mHz) + Rauschen
    sig = (0.02 * np.sin(2 * math.pi * (1 / 900) * t)
           + 0.05 * np.sin(2 * math.pi * (1 / 86400) * t)
           + 0.01 * np.random.randn(n))
    f, p = welch_psd(sig, fs, nperseg=1024, window="hann")
    fg = log_freq_grid(1e-5, fs / 2, 300)
    ls = lombscargle(t, sig, fg)
    cf, cp, _ = log_bin(f, p, 12)
    print(f"welch: {f.size} bins, peak@{f[np.argmax(p)]:.3e} Hz")
    print(f"lomb : peak@{fg[np.argmax(ls)]:.3e} Hz (dominant: Tagesgang ~1.16e-5)")
    print(f"logbin: {cf.size} baender")
    dec = decimate(sig, 4)
    print(f"decimate x4: {sig.size} -> {dec.size}")
    fr, tt, Z = stft(sig, fs, nperseg=256)
    print(f"stft: {Z.shape}")
    W = morlet_cwt(sig[:512], fs, np.array([1 / 900, 1 / 3600]))
    print(f"cwt: {W.shape}")
    print(f"thd_demo: {thd_from_harmonics([1, 3, 5], [230.0, 6.9, 3.4])} %")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="NQ-Spektralanalyse (Rolle N, read-only)")
    ap.add_argument("--demo", action="store_true", help="Synthetischer DSP-Selbsttest")
    ap.add_argument("--periodogram", action="store_true", help="Lomb-Scargle ueber echte Daten")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    if a.demo:
        return _demo()
    if a.periodogram:
        end = int(time.time())
        start = end - a.days * 86400
        ts, f = load_clean_freq(start, end)
        if ts.size < 8:
            print("zu wenig Daten"); return 1
        x = f - 50.0
        fg = log_freq_grid(1e-6, 1.0 / 600.0, 400)
        p = lombscargle(ts.astype(float), x, fg)
        top = np.argsort(p)[-5:][::-1]
        print(f"n={ts.size}, Zeitraum {a.days} d")
        for i in top:
            print(f"  f={fg[i]:.3e} Hz  T={1/fg[i]:.0f} s  P={p[i]:.3f}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
