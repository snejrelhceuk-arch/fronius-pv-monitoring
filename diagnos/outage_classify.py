"""diagnos/outage_classify.py — Read-only Klassifikation von Datenlücken.

Schicht D (Analyse, read-only). Eine fehlende Fronius-Messreihe (F1/prim.SM)
ist für sich allein **kein** Beweis für einen Netzausfall: Der pv-system-Collector
kann neu gestartet sein, während das Netz durchgehend anlag. Dieses Modul kreuzt
jede Fronius-Lücke gegen unabhängige Evidenz:

- **NQ/PAC-Präsenz:** Das PAC4200 (Rolle N) scannt batteriegestützt weiter; der
  Tech-Pi4 kann USV-gestützt sein. Liegen im Lückenfenster NQ-Messwerte vor, lag
  physisch Netz an → die Fronius-Lücke ist eine reine Erfassungs-/Systemunterbrechung.
- **Netzspannung/-frequenz (NQ):** Misst das PAC U≈0 / f≈0, war das Netz wirklich
  weg (NQ-bestätigter Netzausfall). Abnorm hohe Frequenz (>50,5 Hz) deutet auf
  Insel-/Notstrombetrieb (vgl. Überfrequenz-Ereignis 08.09.2026).
- **NQ-Tagesverfügbarkeit:** Fehlen im Fenster NQ-Werte, obwohl NQ am selben Tag
  sonst lief, fiel der ganze Standort (inkl. battery-/USV-gestütztem PAC) aus →
  echter Netzausfall. Fehlt NQ generell, bleibt die Ursache unbestätigt.

Keine Hardware-/DB-Schreibzugriffe. Liest nur ``nq/db/nq_YYYY-MM.db`` (lokal, ohne
SSH) sowie — für die Ränder — eine übergebene read-only Fronius-Verbindung.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_NQ_DIR = os.path.join(BASE_DIR, 'nq', 'db')

# Lücken-Schwelle: identisch zur Frontend-Erkennung (nav-ui.js, 20 min).
GAP_THRESHOLD_S = 1200

# Netzfrequenz-Bewertung (Hz).
_FREQ_DEAD = 5.0        # darunter: kein Netz (f≈0)
_FREQ_LO = 49.5         # VDE-naher Normalband-Rand unten
_FREQ_HI = 50.5         # darüber: Überfrequenz / Insel

# Netzspannung L-L (V): unter diesem Wert gilt das Netz als weg.
_U_DEAD = 150.0

# Mindest-NQ-Messpunkte im Fenster für hohe Konfidenz (sonst nur Stichprobe).
_MIN_PTS_STRONG = 3

# Klassen-Keys (stabil für Frontend + Mail).
CLS_GRID = 'netzausfall'
CLS_ISLAND = 'insel'
CLS_SYSTEM = 'systemausfall'
CLS_UNKNOWN = 'unbekannt'

# Anzeige-/Mail-Metadaten je Klasse (Frontend hält eigene Farb-Map in nav-ui.js).
CLASS_META = {
    CLS_GRID:    {'label': 'Netzausfall',             'color': '#d9534f'},
    CLS_ISLAND:  {'label': 'Insel-/Notstrombetrieb',  'color': '#e67e22'},
    CLS_SYSTEM:  {'label': 'Systemunterbrechung',     'color': '#f0ad4e'},
    CLS_UNKNOWN: {'label': 'Daten-Lücke',             'color': '#888888'},
}


# ─────────────────────────────────────────────────────────────────────────
# NQ-Lesepfad (lokal, SSH-frei)
# ─────────────────────────────────────────────────────────────────────────
def _nq_month_dbs(start: int, end: int) -> list[str]:
    """Lokale NQ-Monats-DBs, die [start,end] überlappen."""
    dbs: list[str] = []
    if not os.path.isdir(_NQ_DIR):
        return dbs
    d = datetime.fromtimestamp(start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_dt = datetime.fromtimestamp(end)
    guard = 0
    while d <= end_dt and guard < 130:
        guard += 1
        p = os.path.join(_NQ_DIR, f"nq_{d.strftime('%Y-%m')}.db")
        if os.path.exists(p) and p not in dbs:
            dbs.append(p)
        d = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)
    return dbs


def _nq_series(start: int, end: int) -> list[dict]:
    """NQ-5min-Punkte [start,end] als ``[{ts, freq, u}]`` (lokal, read-only).

    ``freq`` = FREQ-Mittel, ``u`` = max. der L-L-Spannungsmittel (U_L12/23/31).
    Nur Punkte mit mindestens einem belegten Feld werden zurückgegeben.
    """
    by_ts: dict[int, dict] = {}
    for db_path in _nq_month_dbs(start, end):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            rows = conn.execute(
                "SELECT ts, quantity, vavg FROM nq_5min "
                "WHERE ts>=? AND ts<=? AND meas='' "
                "AND quantity IN ('FREQ','U_L12','U_L23','U_L31')",
                (int(start), int(end)),
            ).fetchall()
            conn.close()
        except Exception:
            continue
        for ts, q, vavg in rows:
            if vavg is None:
                continue
            slot = by_ts.setdefault(int(ts), {'ts': int(ts), 'freq': None, 'u': None})
            if q == 'FREQ':
                slot['freq'] = vavg
            else:
                slot['u'] = vavg if slot['u'] is None else max(slot['u'], vavg)
    return [by_ts[k] for k in sorted(by_ts)]


def _window_stats(series: list[dict], start: int, end: int) -> dict:
    """Aggregiert NQ-Punkte strikt innerhalb (start, end)."""
    freqs = [p['freq'] for p in series if start < p['ts'] < end and p['freq'] is not None]
    us = [p['u'] for p in series if start < p['ts'] < end and p['u'] is not None]
    n = sum(1 for p in series if start < p['ts'] < end)
    return {
        'n': n,
        'freq_min': min(freqs) if freqs else None,
        'freq_max': max(freqs) if freqs else None,
        'freq_avg': (sum(freqs) / len(freqs)) if freqs else None,
        'u_max': max(us) if us else None,
    }


# ─────────────────────────────────────────────────────────────────────────
# Lücken-Erkennung + Klassifikation
# ─────────────────────────────────────────────────────────────────────────
def detect_gaps(timestamps, threshold_s: int = GAP_THRESHOLD_S) -> list[tuple]:
    """Lücken > threshold zwischen aufeinanderfolgenden Zeitstempeln (epoch s)."""
    ts = sorted(int(t) for t in timestamps if t is not None)
    gaps = []
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > threshold_s:
            gaps.append((ts[i - 1], ts[i]))
    return gaps


def _confidence(level: str) -> str:
    return level


def classify_gap(
    start_ts: int,
    end_ts: int,
    *,
    series: Optional[list[dict]] = None,
    nq_day_present: Optional[bool] = None,
    boot_ts: Optional[float] = None,
) -> dict:
    """Klassifiziert eine einzelne Fronius-Lücke [start_ts, end_ts].

    ``series`` (optional): vorab geladene NQ-Punkte des Tages (spart Mehrfach-IO).
    ``nq_day_present``: ob NQ am selben Tag überhaupt Daten hat (Negativ-Evidenz).
    ``boot_ts``: ungefährer Systemstart (für Neustart-Nähe am Lückenende).
    """
    start_ts, end_ts = int(start_ts), int(end_ts)
    if series is None:
        series = _nq_series(start_ts - 300, end_ts + 300)
    if nq_day_present is None:
        nq_day_present = bool(series)

    st = _window_stats(series, start_ts, end_ts)
    near_boot = (boot_ts is not None and abs(end_ts - boot_ts) <= 900)

    freq_max, freq_min, u_max = st['freq_max'], st['freq_min'], st['u_max']
    strong = st['n'] >= _MIN_PTS_STRONG

    if st['n'] > 0:
        # NQ/PAC lieferte während der Fronius-Lücke Messwerte → unabhängige Evidenz.
        base = 'hoch' if strong else 'mittel'
        stichprobe = "" if strong else f" (nur {st['n']} NQ-Stichprobe)"
        grid_dead = (
            (u_max is not None and u_max < _U_DEAD)
            or (freq_max is not None and freq_max < _FREQ_DEAD)
        )
        island = (
            not grid_dead and freq_max is not None
            and (freq_max > _FREQ_HI or (freq_min is not None and _FREQ_DEAD < freq_min < _FREQ_LO))
        )
        if grid_dead:
            cls, conf = CLS_GRID, base
            detail = (
                f"PAC/NQ lief weiter (USV/Stützbatterie), maß aber Netz ≈ 0 "
                f"(U≈{_fmt(u_max)} V, f≈{_fmt(freq_max)} Hz) über {_dur(end_ts - start_ts)} "
                f"→ bestätigter Netzausfall{stichprobe}."
            )
        elif island:
            cls, conf = CLS_ISLAND, base
            detail = (
                f"NQ maß im Fenster ein Netz mit abnormaler Frequenz "
                f"({_fmt(freq_min)}–{_fmt(freq_max)} Hz){stichprobe} → Insel-/Notstrom- "
                f"bzw. Netzrückkehr-Ereignis, kein sauberer Netzausfall."
            )
        else:
            cls, conf = CLS_SYSTEM, base
            detail = (
                f"PAC/NQ registrierte normales Netz "
                f"(f≈{_fmt(st['freq_avg'])} Hz, U≈{_fmt(u_max)} V, {st['n']} Messpunkte) "
                f"→ kein Netzausfall, sondern Unterbrechung der Fronius-/Collector-Erfassung."
            )
    elif nq_day_present:
        # NQ lief am Tag, aber nicht im Fenster → ganzer Standort ohne Messung.
        cls = CLS_GRID
        conf = 'hoch' if near_boot else 'mittel'
        detail = (
            "Weder Fronius noch das batteriegestützte PAC lieferten im Fenster "
            "Messwerte → vollständiger Standort-Ausfall (echter Netzausfall)."
        )
    else:
        cls = CLS_UNKNOWN
        conf = 'niedrig'
        detail = (
            "Keine unabhängige NQ-Evidenz verfügbar — Ursache unbestätigt "
            "(möglich: Netzausfall, Collector-/System-Neustart, NQ nicht erreichbar)."
        )

    if near_boot:
        detail += " Systemstart fällt mit dem Lückenende zusammen."

    meta = CLASS_META[cls]
    return {
        'start_ts': start_ts,
        'end_ts': end_ts,
        'duration_s': end_ts - start_ts,
        'cls': cls,
        'label': meta['label'],
        'color': meta['color'],
        'confidence': _confidence(conf),
        'detail': detail,
        'nq_points': st['n'],
        'freq_min': _round(freq_min),
        'freq_max': _round(freq_max),
        'u_max': _round(u_max),
    }


def classify_timestamps(timestamps, *, boot_ts: Optional[float] = None,
                        threshold_s: int = GAP_THRESHOLD_S) -> list[dict]:
    """Erkennt + klassifiziert alle Lücken einer Zeitstempel-Reihe (ein Tag)."""
    gaps = detect_gaps(timestamps, threshold_s)
    if not gaps:
        return []
    day_start = min(int(t) for t in timestamps if t is not None)
    day_end = max(int(t) for t in timestamps if t is not None)
    series = _nq_series(day_start - 300, day_end + 300)
    nq_day_present = bool(series)
    return [
        classify_gap(s, e, series=series, nq_day_present=nq_day_present, boot_ts=boot_ts)
        for (s, e) in gaps
    ]


def classify_latest_gap(conn, *, lookback_h: int = 12,
                        boot_ts: Optional[float] = None) -> Optional[dict]:
    """Jüngste Fronius-Lücke der letzten ``lookback_h`` Stunden (für Warn-Mail).

    ``conn``: read-only Fronius-Verbindung (RAM- oder Persist-DB) mit ``raw_data``.
    Gibt ``None`` zurück, wenn keine klassifizierbare Lücke vorliegt.
    """
    now = int(datetime.now().timestamp())
    since = now - lookback_h * 3600
    try:
        rows = conn.execute(
            "SELECT ts FROM raw_data WHERE ts>=? ORDER BY ts", (since,)
        ).fetchall()
    except Exception:
        return None
    ts = [int(r[0]) for r in rows]
    gaps = detect_gaps(ts)
    if not gaps:
        return None
    start_ts, end_ts = gaps[-1]
    series = _nq_series(start_ts - 300, end_ts + 300)
    nq_day_present = bool(_nq_series(
        int(datetime.fromtimestamp(start_ts).replace(hour=0, minute=0, second=0).timestamp()),
        end_ts,
    ))
    return classify_gap(start_ts, end_ts, series=series,
                        nq_day_present=nq_day_present, boot_ts=boot_ts)


# ─────────────────────────────────────────────────────────────────────────
# Formatierung
# ─────────────────────────────────────────────────────────────────────────
def _round(v):
    return round(v, 2) if isinstance(v, (int, float)) else None


def _fmt(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def _dur(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h} h {m} min"
    return f"{m} min"
