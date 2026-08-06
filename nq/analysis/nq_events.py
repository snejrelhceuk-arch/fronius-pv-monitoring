"""nq.analysis.nq_events — Klassifikation von Netzereignissen (HF/NF/VLF).

Orchestrator für den Tages-Analyselauf auf Primary (Rolle N).

Verantwortung:
    - Lädt Skalare aus nq_5min (pivotiert als ts_series)
  - Koordiniert HF/NF/VLF-Detektoren (nq_hf / nq_nf / nq_vlf)
  - Cross-Check mit pv-system Produktions-DB: HP/WP/Wattpilot als Ursache prüfen
  - Schreibt idempotent nach nq_events (DELETE + INSERT je Tag)

Start:  python3 -m nq.analysis.nq_events --date YYYY-MM-DD [--data-db PATH]
Doku:   doc/netzqualitaet/NQ_MODUL.md §8
        doc/llm/cards/netzqualitaet-nq-analysis-events.card.md
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime
from typing import Any

import numpy as np

from nq.nq_common import BASE_DIR, load_config, open_db, PRIMARY_SCHEMA
from nq.analysis.nq_hf import run_hf
from nq.analysis.nq_nf import run_nf
from nq.analysis.nq_vlf import run_vlf

logger = logging.getLogger("nq.analysis.nq_events")

_IMPEDANCE_PATH = os.path.join(BASE_DIR, "config", "nq_impedance.json")
# Produktions-DB-Pfade für Cross-Check (read-only)
_DATA_DB_RAM = "/dev/shm/fronius_data.db"
_DATA_DB_SD = os.path.join(BASE_DIR, "data.db")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _month_db(day: str) -> str:
    return os.path.join(BASE_DIR, "nq", "db", f"nq_{day[:7]}.db")


def _load_z_loop() -> dict:
    if os.path.exists(_IMPEDANCE_PATH):
        with open(_IMPEDANCE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    logger.warning("nq_impedance.json nicht gefunden — Fallback-Impedanz")
    return {"R_mOhm": 163, "X_mOhm": 251, "Z_abs_mOhm": 299}


def _load_ts_series(
    conn: sqlite3.Connection,
    ts_start: int,
    ts_end: int,
) -> dict[str, dict[str, Any]]:
    """Pivotiert nq_5min-Skalare in ein Dict quantity → arrays.

    Skalare haben meas='', phase=0, ord=0 (Konvention Aggregator).
    Rückgabe: {quantity: {'ts': int64[], 'vmin': f64[], 'vavg': f64[], 'vmax': f64[], 'n': i32[]}}
    """
    rows = conn.execute(
        "SELECT ts, quantity, vmin, vavg, vmax, n FROM nq_5min "
        "WHERE meas='' AND phase=0 AND ord=0 "
        "AND ts >= ? AND ts < ? ORDER BY ts, quantity",
        (ts_start, ts_end),
    ).fetchall()

    raw: dict[str, list] = {}
    for ts, qty, vmin, vavg, vmax, n in rows:
        raw.setdefault(qty, []).append((ts, vmin, vavg, vmax, n))

    result: dict[str, dict] = {}
    for qty, pts in raw.items():
        arr = np.array(pts, dtype=np.float64)
        result[qty] = {
            "ts":   arr[:, 0].astype(np.int64),
            "vmin": arr[:, 1],
            "vavg": arr[:, 2],
            "vmax": arr[:, 3],
            "n":    arr[:, 4].astype(np.int32),
        }
    return result


def _check_pvsystem_cause(ts_start: int, ts_end: int, data_db: str | None = None) -> str:
    """Prüft pv-system Produktions-DB (read-only) auf aktive lokale Verbraucher.

    Prüfreihenfolge: RAM-DB → SD-DB → übergebener Pfad.
    Verbraucher: Wärmepumpe (W_Imp_WP), Heizpatrone (fritzdect_log),
                 Wattpilot (wattpilot_data.wattage).

    Returns:
        'lokal' wenn Verbraucher aktiv, sonst 'unklar'.
    """
    candidates = [_DATA_DB_RAM, _DATA_DB_SD]
    if data_db:
        candidates.insert(0, data_db)

    conn_pv = None
    for db_path in candidates:
        if db_path and os.path.exists(db_path):
            try:
                conn_pv = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
                break
            except Exception:
                continue
    if conn_pv is None:
        return "unklar"

    margin = 30
    t0, t1 = ts_start - margin, ts_end + margin
    try:
        # 1. Wärmepumpe
        try:
            r = conn_pv.execute(
                "SELECT 1 FROM raw_data WHERE ts >= ? AND ts < ? AND W_Imp_WP > 100 LIMIT 1",
                (t0, t1),
            ).fetchone()
            if r:
                return "lokal"
        except Exception:
            pass

        # 2. Heizpatrone (FritzDECT)
        try:
            r = conn_pv.execute(
                "SELECT 1 FROM fritzdect_log WHERE ts >= ? AND ts < ? "
                "AND (state='ein' OR power_w > 100) LIMIT 1",
                (t0, t1),
            ).fetchone()
            if r:
                return "lokal"
        except Exception:
            pass

        # 3. Wattpilot
        try:
            r = conn_pv.execute(
                "SELECT 1 FROM wattpilot_data WHERE ts >= ? AND ts < ? AND wattage > 500 LIMIT 1",
                (t0, t1),
            ).fetchone()
            if r:
                return "lokal"
        except Exception:
            pass

    finally:
        conn_pv.close()

    return "unklar"


def _dedup_key(ev: dict) -> str:
    """De-duplizierschlüssel: Trigger + Stunden-Bucket."""
    return f"{ev['trigger']}:{(ev['ts_start'] // 3600) * 3600}"


def _upsert_events(
    conn: sqlite3.Connection,
    events: list[dict],
    ts_start: int,
    ts_end: int,
) -> int:
    """Idempotent: Löscht Events des Tages, fügt neue ein (De-Duplikat per dedup_key)."""
    conn.execute(
        "DELETE FROM nq_events WHERE ts_start >= ? AND ts_start < ?",
        (ts_start, ts_end),
    )
    if not events:
        conn.commit()
        return 0

    now_ts = int(time.time())
    rows: list[tuple] = []
    seen: set[str] = set()

    for ev in events:
        dk = _dedup_key(ev)
        if dk in seen:
            continue
        seen.add(dk)
        rows.append((
            ev["ts_start"], ev["ts_end"],
            ev.get("duration_s"),
            ev["band"], ev.get("kind"), ev.get("trigger"),
            ev.get("severity"), ev.get("peak_quantity"), ev.get("peak_value"),
            ev.get("origin"), dk,
            ev.get("n_samples"), 0,
            ev.get("metrics"),
            now_ts,
        ))

    conn.executemany(
        "INSERT INTO nq_events "
        "(ts_start, ts_end, duration_s, band, kind, trigger, severity, "
        "peak_quantity, peak_value, origin, dedup_key, n_samples, "
        "has_snippet, metrics, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def analyze_window(
    ts_start: int,
    ts_end: int,
    data_db: str | None = None,
    bands: list[str] | None = None,
) -> int:
    """Netzereignis-Analyse für ein Zeitfenster: Bänder HF/NF/VLF → nq_events.

    Args:
        ts_start:  Fenster-Start (Unix-Sekunden)
        ts_end:    Fenster-Ende
        data_db:   optionaler Pfad zur pv-system Produktions-DB für Cross-Check
        bands:     Bänder zu analysieren ['HF_local', 'NF_global', 'VLF'];
                   None = alle

    Returns:
        Anzahl geschriebener Events (0 wenn keine Daten).
    """
    if bands is None:
        bands = ["HF_local", "NF_global", "VLF"]
    bands_set = set(bands)

    # Bestimme DB-Pfad aus ts_start (Fenster könnte Monatsgrenzen überschreiten;
    # vereinfacht: nutze Start-Monat)
    day_str = datetime.fromtimestamp(ts_start).strftime("%Y-%m-%d")
    db_path = _month_db(day_str)
    if not os.path.exists(db_path):
        logger.warning("NQ-DB nicht gefunden: %s", db_path)
        return 0

    cfg_full = load_config()
    cfg = cfg_full.get("analysis", {})
    z_loop = _load_z_loop()

    conn = open_db(db_path, PRIMARY_SCHEMA)
    try:
        ts_series = _load_ts_series(conn, ts_start, ts_end)
        if not ts_series:
            logger.warning(
                "Keine nq_5min-Daten für Fenster [%d,%d) in %s",
                ts_start, ts_end, db_path,
            )
            return 0

        n_buckets = max(len(v["ts"]) for v in ts_series.values())
        logger.info(
            "Analysiere Fenster [%d,%d) — %d Buckets, Bänder: %s",
            ts_start, ts_end, n_buckets, ",".join(bands),
        )

        events: list[dict] = []

        if "HF_local" in bands_set:
            events.extend(run_hf(ts_series, z_loop, cfg))
        if "NF_global" in bands_set:
            events.extend(run_nf(conn, ts_series, ts_start, ts_end, cfg))
        if "VLF" in bands_set:
            day_str = datetime.fromtimestamp(ts_start).strftime("%Y-%m-%d")
            events.extend(run_vlf(conn, day_str, cfg))

        # Cross-Check: lokale Verbraucher als Ursache prüfen
        if cfg.get("pvsystem_crosscheck", True):
            for ev in events:
                if ev.get("origin") is None:
                    ev["origin"] = _check_pvsystem_cause(
                        ev["ts_start"], ev["ts_end"], data_db
                    )

        n_written = _upsert_events(conn, events, ts_start, ts_end)
        logger.info(
            "Fenster [%d,%d): %d Events (HF=%d NF=%d VLF=%d)",
            ts_start, ts_end, n_written,
            sum(1 for e in events if e["band"] == "HF_local"),
            sum(1 for e in events if e["band"] == "NF_global"),
            sum(1 for e in events if e["band"] == "VLF"),
        )
        return n_written

    finally:
        conn.close()


def analyze_day(day: str, data_db: str | None = None) -> int:
    """Netzereignis-Analyse für einen Tag: HF/NF/VLF → nq_events (Backward-Compat).

    Args:
        day:     Analysetag 'YYYY-MM-DD'
        data_db: optionaler Pfad zur pv-system Produktions-DB für Cross-Check

    Returns:
        Anzahl geschriebener Events (0 wenn keine Daten).
    """
    day_dt = datetime.strptime(day, "%Y-%m-%d")
    ts_start = int(day_dt.timestamp())
    ts_end = ts_start + 86400

    # Sauberen Musteranalyse-Datensatz (nq_pattern_5min) mitführen (best-effort).
    try:
        from nq.analysis import nq_pattern
        nq_pattern.build_day(day)
    except Exception as _pe:
        print(f"[nq_events] Pattern-Datensatz übersprungen: {_pe}")

    return analyze_window(ts_start, ts_end, data_db=data_db)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="NQ Netzereignis-Analyse HF/NF/VLF")

    # Modus 1: Nach Tag (Backward-Compat für täglich 00:30 VLF)
    parser.add_argument(
        "--date",
        default=None,
        help="Analysetag YYYY-MM-DD (Backward-Compat; exclusive mit --hours)",
    )

    # Modus 2: Nach Zeitfenster (für 4h HF/NF)
    parser.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Fensterbreite in Stunden, rückwärts von jetzt (z. B. 4 für letzte 4h)",
    )

    # Filterung der Bänder
    parser.add_argument(
        "--bands",
        default="HF_local,NF_global,VLF",
        help="Kommagetrennter Band-Filter (HF_local|NF_global|VLF); default: alle",
    )

    parser.add_argument(
        "--data-db",
        default=None,
        help="Pfad zur pv-system data.db für Cross-Check (optional)",
    )

    args = parser.parse_args()

    bands = [b.strip() for b in args.bands.split(",")]

    if args.date is not None and args.hours is not None:
        print("ERROR: --date und --hours sind mutually exclusive")
        return

    if args.date is not None:
        # Tages-Modus (VLF + daily analyses)
        n = analyze_day(args.date, data_db=args.data_db)
        print(f"analyze_day({args.date!r}) -> {n} Events geschrieben")
    elif args.hours is not None:
        # Fenster-Modus (HF/NF 4h-Rhythmus)
        now = int(time.time())
        ts_end = now
        ts_start = now - args.hours * 3600
        logger = logging.getLogger("nq.analysis.nq_events")
        logger.info(
            "Fenster-Modus: Letzte %d Stunden [%d,%d), Bänder: %s",
            args.hours, ts_start, ts_end, ",".join(bands),
        )
        n = analyze_window(ts_start, ts_end, data_db=args.data_db, bands=bands)
        print(f"analyze_window({ts_start},{ts_end}, bands={bands}) -> {n} Events")
    else:
        # Default: heute (Backward-Compat)
        today = datetime.now().strftime("%Y-%m-%d")
        n = analyze_day(today, data_db=args.data_db)
        print(f"analyze_day({today!r}) -> {n} Events geschrieben")


if __name__ == "__main__":
    main()
