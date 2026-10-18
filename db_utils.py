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


def _attach_stats_db(conn):
    # Permanente 5-min-Tagesdaten (STATS-DB, SD) read-only anhängen — ermöglicht
    # Tag-Charts für Tage älter als die data_1min/15min-Retention (90 T).
    # Best-effort: eine fehlende/gesperrte STATS-DB darf die Web-API nie brechen.
    try:
        _stats = getattr(config, 'STATS_DB_PATH', None)
        if _stats and os.path.exists(_stats):
            conn.execute("ATTACH DATABASE ? AS stats", (f"file:{_stats}?mode=ro",))
    except Exception as _e:
        logger.debug("STATS-DB ATTACH fehlgeschlagen: %s", _e)


# Stage 3: Analyse-Tabellen → Schlüssel für die Shadow-View-Union (RAM gewinnt).
_ANALYSIS_SHADOW = {
    'daily_data': ['ts'],
    'data_monthly': ['ts'],
    'monthly_statistics': ['id'],
    'yearly_statistics': ['id'],
    'heizpatrone_daily': ['ts'], 'klimaanlage_daily': ['ts'],
    'gefriertruhe_daily': ['ts'], 'lueftung_daily': ['ts'],
    'heizpatrone_monthly': ['year', 'month'], 'klimaanlage_monthly': ['year', 'month'],
    'gefriertruhe_monthly': ['year', 'month'], 'lueftung_monthly': ['year', 'month'],
    'wattpilot_daily': ['ts'],
    'battery_health_daily': ['day_ts'],
    'forecast_daily': ['date'],
    'price_history': ['valid_from'],
}


def _attach_tiered_ro(conn):
    """Stage-3-Read-Routing (nur read-only-Verbindung).

    Hängt analysis.db (Stufe 3) + monitoring.db (Stufe 2) read-only an und legt
    pro Analyse-Tabelle eine TEMP-VIEW an, die die gleichnamige RAM-Tabelle
    überdeckt: ``RAM-Zeilen ∪ analysis-Zeilen, die nicht in RAM sind``. So liest
    die API die volle Historie aus analysis.db, während der laufende Tag (noch
    nicht in analysis.db gespiegelt) aus der RAM-DB korrekt gewinnt. TEMP-Views
    sind verbindungslokal → Writer/Collector bleiben unberührt. Best-effort:
    jede Tabelle einzeln abgesichert, bei Fehler Fallback auf die RAM-Tabelle.
    """
    if not getattr(config, 'TIERED_READS', False):
        return
    ana = getattr(config, 'ANALYSIS_DB_PATH', None)
    mon = getattr(config, 'MONITORING_DB_PATH', None)
    try:
        if ana and os.path.exists(ana):
            conn.execute("ATTACH DATABASE ? AS ana", (f"file:{ana}?mode=ro",))
    except Exception as _e:
        logger.debug("analysis-DB ATTACH fehlgeschlagen: %s", _e)
        return
    try:
        if mon and os.path.exists(mon):
            conn.execute("ATTACH DATABASE ? AS mon", (f"file:{mon}?mode=ro",))
    except Exception as _e:
        logger.debug("monitoring-DB ATTACH fehlgeschlagen: %s", _e)
    for tbl, keys in _ANALYSIS_SHADOW.items():
        try:
            if not conn.execute(
                "SELECT 1 FROM ana.sqlite_master WHERE type='table' AND name=?",
                (tbl,),
            ).fetchone():
                continue
            cond = " AND ".join(f"m.{k}=a.{k}" for k in keys)
            conn.execute(
                f"CREATE TEMP VIEW {tbl} AS "
                f"SELECT * FROM main.{tbl} "
                f"UNION ALL SELECT * FROM ana.{tbl} a "
                f"WHERE NOT EXISTS (SELECT 1 FROM main.{tbl} m WHERE {cond})"
            )
        except Exception as _e:
            logger.debug("Shadow-View %s übersprungen: %s", tbl, _e)
            try:
                conn.execute(f"DROP VIEW IF EXISTS {tbl}")
            except Exception:
                pass


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
    _attach_stats_db(conn)
    return conn


def get_db_connection_ro(timeout=10.0):
    """Erstellt eine read-only SQLite-Verbindung fuer Web-/Diagnose-Lesepfade."""
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=timeout)
    conn.execute('PRAGMA cache_size=-64000')  # 64 MB
    _attach_stats_db(conn)
    _attach_tiered_ro(conn)  # legt ggf. TEMP-Views an → vor query_only=ON
    # query_only erst NACH dem Anlegen der TEMP-Views (CREATE TEMP VIEW würde sonst
    # scheitern). Die Haupt-DB ist bereits mode=ro → kein Schreibzugriff möglich.
    conn.execute('PRAGMA query_only=ON')
    return conn
