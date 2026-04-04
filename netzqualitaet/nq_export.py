#!/usr/bin/env python3
"""
nq_export.py — Täglicher Export von Netzqualitäts-Rohdaten in schlanke Monats-DBs.

Liest aus der Haupt-DB (raw_data) die netzrelevanten Spalten und schreibt sie
in monatliche SQLite-Dateien: netzqualitaet/db/nq_YYYY-MM.db

Spalten: ts, f_netz, u_l1_l2, u_l2_l3, u_l3_l1, i_l1, i_l2, i_l3
Auflösung: Original 3-Sekunden-Intervall (wie im SmartMeter)

Cron-Empfehlung:
  10 1 * * *  cd /srv/pv-system && .venv/bin/python netzqualitaet/nq_export.py >> /tmp/nq_export.log 2>&1

ABCD-Rollenmodell: Säule B (read-only auf Haupt-DB, write auf NQ-DB).
"""
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

# Projektpfad einbinden
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger('nq_export')

# --- Konfiguration ---
NQ_DB_DIR = os.path.join(config.BASE_DIR, 'netzqualitaet', 'db')
EXPORT_DAYS_BACK = 2  # Standardmäßig 2 Tage zurück (Sicherheitspuffer)

# Spalten, die aus raw_data extrahiert werden
RAW_COLUMNS = [
    'ts',
    'f_Netz',
    'U_L1_L2_Netz', 'U_L2_L3_Netz', 'U_L3_L1_Netz',
    'I_L1_Netz', 'I_L2_Netz', 'I_L3_Netz',
]

# Schema der NQ-Datenbank
NQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS nq_samples (
    ts        INTEGER PRIMARY KEY,
    f_netz    REAL,
    u_l1_l2   REAL,
    u_l2_l3   REAL,
    u_l3_l1   REAL,
    i_l1      REAL,
    i_l2      REAL,
    i_l3      REAL
);

CREATE INDEX IF NOT EXISTS idx_nq_samples_ts ON nq_samples(ts);

CREATE TABLE IF NOT EXISTS nq_export_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    export_ts  INTEGER NOT NULL,
    date_from  TEXT NOT NULL,
    date_to    TEXT NOT NULL,
    rows_added INTEGER NOT NULL,
    duration_s REAL NOT NULL
);
"""


def get_nq_db_path(date_obj):
    """Pfad zur Monats-DB für ein gegebenes Datum."""
    filename = f"nq_{date_obj.strftime('%Y-%m')}.db"
    return os.path.join(NQ_DB_DIR, filename)


def ensure_nq_db(db_path):
    """NQ-Datenbank erstellen/öffnen mit Schema."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(NQ_SCHEMA)
    return conn


def get_source_connection():
    """Verbindung zur Haupt-DB (read-only)."""
    uri = f"file:{config.DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def export_date_range(date_from, date_to):
    """Exportiert Rohdaten für einen Datumsbereich in die passenden Monats-DBs.

    Args:
        date_from: Start-Datum (datetime.date)
        date_to: End-Datum inklusiv (datetime.date)

    Returns:
        dict: {monat_str: rows_added, ...}
    """
    src = get_source_connection()
    results = {}

    try:
        # Unix-Timestamps für den Bereich (Lokalzeit-Grenzen)
        # Wir nutzen die gleiche Methode wie die bestehende API
        ts_from = date_from.strftime('%Y-%m-%d')
        ts_to = (date_to + timedelta(days=1)).strftime('%Y-%m-%d')

        query = f"""
            SELECT CAST(ts AS INTEGER),
                   f_Netz, U_L1_L2_Netz, U_L2_L3_Netz, U_L3_L1_Netz,
                   I_L1_Netz, I_L2_Netz, I_L3_Netz
            FROM raw_data
            WHERE datetime(ts, 'unixepoch', 'localtime') >= ?
              AND datetime(ts, 'unixepoch', 'localtime') < ?
              AND f_Netz IS NOT NULL
            ORDER BY ts
        """
        cursor = src.execute(query, (ts_from, ts_to))

        # Gruppiere nach Monat und schreibe in die jeweilige DB
        nq_connections = {}
        batch = {}

        for row in cursor:
            ts = row[0]
            dt = datetime.fromtimestamp(ts)
            month_key = dt.strftime('%Y-%m')

            if month_key not in batch:
                batch[month_key] = []
            batch[month_key].append(row)

        # Schreibe Batches in die jeweiligen Monats-DBs
        for month_key, rows in batch.items():
            month_date = datetime.strptime(month_key, '%Y-%m')
            db_path = get_nq_db_path(month_date)
            nq_conn = ensure_nq_db(db_path)

            try:
                nq_conn.executemany(
                    """INSERT OR IGNORE INTO nq_samples
                       (ts, f_netz, u_l1_l2, u_l2_l3, u_l3_l1, i_l1, i_l2, i_l3)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows
                )
                nq_conn.commit()
                results[month_key] = len(rows)
                logger.info(f"  {month_key}: {len(rows)} Datenpunkte exportiert → {db_path}")
            finally:
                nq_conn.close()

    finally:
        src.close()

    return results


def run_export(days_back=None):
    """Hauptfunktion: Exportiert die letzten N Tage."""
    if days_back is None:
        days_back = EXPORT_DAYS_BACK

    today = datetime.now().date()
    date_from = today - timedelta(days=days_back)
    date_to = today

    logger.info(f"NQ-Export: {date_from} bis {date_to}")
    t0 = time.time()

    results = export_date_range(date_from, date_to)

    duration = time.time() - t0
    total_rows = sum(results.values())

    # Export-Log in die aktuelle Monats-DB schreiben
    if results:
        current_db = get_nq_db_path(today)
        nq_conn = ensure_nq_db(current_db)
        try:
            nq_conn.execute(
                "INSERT INTO nq_export_log (export_ts, date_from, date_to, rows_added, duration_s) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(time.time()), str(date_from), str(date_to), total_rows, round(duration, 2))
            )
            nq_conn.commit()
        finally:
            nq_conn.close()

    logger.info(f"NQ-Export abgeschlossen: {total_rows} Datenpunkte in {duration:.1f}s")
    return results


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Optional: --days N als Argument
    days = EXPORT_DAYS_BACK
    if len(sys.argv) > 1:
        if sys.argv[1] == '--days' and len(sys.argv) > 2:
            days = int(sys.argv[2])
        elif sys.argv[1] == '--full':
            # Voller Export aller verfügbaren raw_data (bis zu RAW_DATA_RETENTION_DAYS)
            days = config.RAW_DATA_RETENTION_DAYS
            logger.info(f"Voller Export: {days} Tage zurück")
        else:
            print(f"Nutzung: {sys.argv[0]} [--days N | --full]")
            sys.exit(1)

    results = run_export(days_back=days)

    if not results:
        logger.warning("Keine Daten exportiert (raw_data leer oder außerhalb Retention?)")
    else:
        for month, count in sorted(results.items()):
            print(f"  {month}: {count:,} Datenpunkte")


if __name__ == '__main__':
    main()
