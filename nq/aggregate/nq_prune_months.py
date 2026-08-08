#!/usr/bin/env python3
"""nq.aggregate.nq_prune_months — Speicher-Reclaim fuer eingefrorene NQ-Monats-DBs (Rolle N).

SQLite gibt nach ``DELETE`` keinen Plattenplatz frei (kein ``auto_vacuum``). Die
Monats-DBs ``nq/db/nq_YYYY-MM.db`` frieren daher mit ~180 MB freien Seiten aus dem
ephemeren ``nq_raw_slow``-Churn (1-s-Harmonik-RAW, 12 h Retention) + der toten
Legacy-Tabelle ``nq_agg_10s`` (10s-Architektur entfernt 2026-07-14) ein.

Dieses Werkzeug (nur **eingefrorene** Monate, der laufende Monat bleibt unberuehrt):
- droppt tote Legacy-Tabellen (``nq_agg_10s``),
- loescht ``nq_raw_slow`` vollstaendig (Harmonische sind bereits in ``nq_5min``
  aggregiert; das RAW wird nur transient fuer die 5-min-Stufe gebraucht),
- gibt Platz per ``VACUUM`` frei — aber **nur wenn noetig** (etwas geloescht ODER
  Freelist-Anteil >= ``--min-free-pct``), um SD-Schreiblast zu minimieren.

Ergaenzt die zeilenbasierte Retention in ``nq_aggregate``/``nq_agg_transfer``
(die loeschen, aber vacuumen nicht). Idempotent, **Dry-Run-Default**.

Start: python3 -m nq.aggregate.nq_prune_months [--commit] [--min-free-pct N]
Doku:  doc/netzqualitaet/NQ_SPEICHER.md
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import time

from nq.nq_common import BASE_DIR

# Tote Legacy-Tabellen (werden von keinem Schreibpfad mehr befuellt).
DEAD_TABLES = ("nq_agg_10s",)
# Ephemere RAW-Tabellen, die in eingefrorenen Monaten komplett entfallen duerfen.
EPHEMERAL_TABLES = ("nq_raw_slow",)


def _db_dir() -> str:
    return os.path.join(BASE_DIR, "nq", "db")


def _current_db_name() -> str:
    return time.strftime("nq_%Y-%m.db")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _free_pct(conn: sqlite3.Connection) -> float:
    pc = conn.execute("PRAGMA page_count").fetchone()[0]
    fl = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return (fl / pc * 100.0) if pc else 0.0


def prune(commit: bool = False, min_free_pct: float = 20.0) -> list[dict]:
    """Bereinigt alle eingefrorenen Monats-DBs. Gibt eine Report-Liste zurueck."""
    current = _current_db_name()
    report: list[dict] = []
    for path in sorted(glob.glob(os.path.join(_db_dir(), "nq_????-??.db"))):
        name = os.path.basename(path)
        if name == current:
            continue
        try:
            conn = sqlite3.connect(path, timeout=30.0)
            conn.isolation_level = None  # Autocommit — VACUUM darf nicht in TX laufen.
        except Exception as exc:
            report.append({"db": name, "error": str(exc)})
            continue
        try:
            size_before = os.path.getsize(path)
            dead = [t for t in DEAD_TABLES if _table_exists(conn, t)]
            raw_n = 0
            for t in EPHEMERAL_TABLES:
                if _table_exists(conn, t):
                    raw_n += conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            free_pct = _free_pct(conn)
            changed = bool(dead) or raw_n > 0
            did_vacuum = False
            if commit:
                for t in dead:
                    conn.execute(f"DROP TABLE IF EXISTS {t}")
                for t in EPHEMERAL_TABLES:
                    if _table_exists(conn, t):
                        conn.execute(f"DELETE FROM {t}")
                if changed or free_pct >= min_free_pct:
                    conn.execute("VACUUM")
                    did_vacuum = True
            size_after = os.path.getsize(path)
            report.append({
                "db": name,
                "dead_dropped": dead,
                "raw_slow_deleted": raw_n,
                "free_pct_before": round(free_pct, 1),
                "vacuumed": did_vacuum,
                "mb_before": round(size_before / 1048576, 1),
                "mb_after": round(size_after / 1048576, 1),
            })
        except Exception as exc:
            report.append({"db": name, "error": str(exc)})
        finally:
            conn.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Reclaim eingefrorener NQ-Monats-DBs (Rolle N).")
    ap.add_argument("--commit", action="store_true", help="Tatsaechlich prunen/vacuumen (sonst Dry-Run).")
    ap.add_argument("--min-free-pct", type=float, default=20.0,
                    help="VACUUM-Schwelle: freie Seiten in %% (Default 20).")
    a = ap.parse_args()
    rep = prune(commit=a.commit, min_free_pct=a.min_free_pct)
    mode = "COMMIT" if a.commit else "DRY-RUN"
    total_before = sum(r.get("mb_before", 0) for r in rep)
    total_after = sum(r.get("mb_after", 0) for r in rep)
    print(f"[{mode}] NQ-Monats-Prune (min_free_pct={a.min_free_pct})")
    for r in rep:
        if "error" in r:
            print(f"  FEHLER {r['db']}: {r['error']}")
            continue
        print(f"  {r['db']}: raw_slow={r['raw_slow_deleted']} dead={r['dead_dropped']} "
              f"free={r['free_pct_before']}% vacuum={r['vacuumed']} "
              f"{r['mb_before']}→{r['mb_after']} MB")
    print(f"Summe eingefrorener Monate: {round(total_before,1)}→{round(total_after,1)} MB")
    if not a.commit:
        print("\nHinweis: Dry-Run. Mit --commit tatsaechlich freigeben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
