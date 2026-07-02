"""
Zentrale DB-Hilfsfunktionen für Fronius PV-Monitoring.
Stellt sicher, dass alle Scripts denselben WAL-Modus und Timeout verwenden.

DB lebt in tmpfs (/dev/shm) — Echtzeit-Zugriff ohne Disk-I/O.
Beim ersten Zugriff wird ggf. NVMe → tmpfs wiederhergestellt.

Verwendung:
    from db_utils import get_db_connection
    conn = get_db_connection()
    try:
        ...
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()
"""
import sqlite3
import logging
import os
import config
import db_init

logger = logging.getLogger(__name__)

# tmpfs-DB beim Import sicherstellen (idempotent)
db_init.ensure_tmpfs_db()
db_init.ensure_forecast_table()


def get_db_connection(timeout=10.0):
    """
    Erstellt eine SQLite-Verbindung mit WAL-Modus.
    
    WAL (Write-Ahead Logging) erlaubt parallele Lese- und Schreibzugriffe,
    was bei gleichzeitigen Cron-Jobs (aggregate_1min + aggregate_daily + ...)
    DB-Lock-Fehler verhindert.
    
    Args:
        timeout: Wartezeit in Sekunden bei gesperrter DB (Default: 10s)
    
    Returns:
        sqlite3.Connection mit WAL-Modus, NORMAL sync, 64MB Cache
    """
    conn = sqlite3.connect(f"file:{config.DB_PATH}", uri=True, timeout=timeout)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')  # 64 MB
    # Permanente 5-min-Tagesdaten (STATS-DB, SD) read-only anhängen — ermöglicht
    # Tag-Charts für Tage älter als die data_1min/15min-Retention (90 T).
    # Best-effort: eine fehlende/gesperrte STATS-DB darf die Web-API nie brechen.
    try:
        _stats = getattr(config, 'STATS_DB_PATH', None)
        if _stats and os.path.exists(_stats):
            conn.execute("ATTACH DATABASE ? AS stats", (f"file:{_stats}?mode=ro",))
    except Exception as _e:
        logger.debug("STATS-DB ATTACH fehlgeschlagen: %s", _e)
    return conn
