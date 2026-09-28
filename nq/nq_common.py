"""nq.nq_common — geteilte Helfer für das NQ-Modul (Rolle N).

Funktional (kein Stub): Config-Laden, Schema-Anwenden, tmpfs-Belegung messen.
Wird von Collector (Tech), Transfer, Aggregation und Analyse (Primary) genutzt.
"""
from __future__ import annotations

import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "nq_config.json")
SCHEMA_DIR = os.path.join(BASE_DIR, "nq", "schema")
TECH_SCHEMA = os.path.join(SCHEMA_DIR, "nq_tech_schema.sql")
PRIMARY_SCHEMA = os.path.join(SCHEMA_DIR, "nq_primary_schema.sql")


def load_config(path: str = CONFIG_PATH) -> dict:
    """Lädt config/nq_config.json."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def open_db(db_path: str, schema_file: str | None = None) -> sqlite3.Connection:
    """Öffnet (und erstellt) eine NQ-DB mit WAL + optionalem Schema."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if schema_file:
        with open(schema_file, encoding="utf-8") as fh:
            conn.executescript(fh.read())
    return conn


# Flüchtige RAW-Ring-Buffer-Tabellen (tmpfs): bei Schema-Drift gefahrlos
# droppbar (max. retention.raw_hours Verlust). Persistente Tabellen
# (nq_energy_raw, nq_transfer_log, nq_limit_alerts, nq_capping_log) werden
# NIE automatisch gedroppt — sie tragen noch nicht transferierten/quittierten
# Zustand.
_VOLATILE_TECH_TABLES = (
    "nq_raw_fast", "nq_raw_medium", "nq_raw_slow",
    "nq_raw_max", "nq_5min", "nq_transient_5min",
)


def migrate_tech_schema(conn: sqlite3.Connection,
                        schema_file: str = TECH_SCHEMA) -> list[str]:
    """Heilt Spalten-Drift der flüchtigen tmpfs-RAW-Tabellen beim Poller-Start.

    ``CREATE TABLE IF NOT EXISTS`` migriert Spaltenänderungen nicht (z. B.
    ``nq_raw_medium`` ``ts``→``ts_ms``): eine im tmpfs überlebende Alt-Tabelle
    lässt neue Inserts scheitern, bis manuell gedroppt wird. Diese Funktion
    vergleicht die Ist-Spalten jeder Volatile-Tabelle mit dem Schema (Referenz
    aus einer :memory:-DB) und droppt+neuerzeugt nur die abweichenden. Gibt die
    Liste der neu erstellten Tabellen zurück.
    """
    with open(schema_file, encoding="utf-8") as fh:
        schema_sql = fh.read()
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(schema_sql)
        desired = {t: {r[1] for r in ref.execute(f"PRAGMA table_info({t})")}
                   for t in _VOLATILE_TECH_TABLES}
    finally:
        ref.close()

    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    drifted: list[str] = []
    for t in _VOLATILE_TECH_TABLES:
        if t not in existing:
            continue
        actual = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if actual != desired[t]:
            drifted.append(t)

    if drifted:
        for t in drifted:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.executescript(schema_sql)  # erzeugt gedroppte Tabellen + Indizes neu
        conn.commit()
    return drifted


def db_size_mb(conn: sqlite3.Connection) -> float:
    """Aktuelle DB-Größe (page_count × page_size) in MB — inkl. WAL grob."""
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return page_count * page_size / (1024 * 1024)


def tmpfs_free_mb(path: str) -> float:
    """Freier Platz im tmpfs des angegebenen Pfads in MB."""
    st = os.statvfs(os.path.dirname(path) or "/")
    return st.f_bavail * st.f_frsize / (1024 * 1024)
