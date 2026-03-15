"""
tmpfs-DB Initialisierung & Persistierung für Fronius PV-Monitoring.

Architektur:
  - Primäre DB lebt in /dev/shm (tmpfs = RAM) → Echtzeit-R/W ohne Disk-I/O
    - Collector + Web-API + Cron-Scripts greifen alle auf tmpfs-DB zu
    - Persist-Thread: Alternierende Sicherung SD / Pi5 (je 1×/2 Tage)
    - Beim Boot: SD → tmpfs (Fallback: Pi5 → gz-Backup → leere DB)

Persistierungs-Schema (seit 2026-02-14):
  - Ungerade Tage (1,3,5...): tmpfs → SD-Card lokal (SQLite .backup)
  - Gerade Tage (2,4,6...):   tmpfs → Pi5 via rsync
  - Jede Einzelsicherung max. 2 Tage alt
  - Zusammen max. 1 Tag Datenverlust bei Ausfall
  - Fixpunkte (daily_data._start/_end) sichern Tages-/Monats-/Jahres-Werte

Stromausfall-Schutz:
  - ensure_tmpfs_db() prüft auf echte Tabellen, nicht nur Dateigröße
  - persist verweigert Überschreiben wenn tmpfs-DB leer/korrupt
  - fsync nach Persist für Crash-Sicherheit
  - Fallback-Kette: SD → Pi5 → gz-Backup → leere DB
"""
import os
import glob
import gzip
import shutil
import sqlite3
import logging
import time
import threading
import subprocess
from datetime import datetime
import config

logger = logging.getLogger(__name__)

# Minimale erwartete Tabellen in einer gültigen DB
REQUIRED_TABLES = {'raw_data', 'data_1min', 'daily_data'}
# Mindestgröße für eine "echte" DB (leere SQLite = ~4 KB)
MIN_VALID_DB_SIZE = 100_000  # 100 KB — eine frische DB mit Tabellen ist ~50 KB, mit Daten >> 1 MB


def _get_persist_unit_seconds():
    unit = getattr(config, 'DB_PERSIST_UNIT', 'hour')
    if isinstance(unit, (int, float)) and unit > 0:
        return int(unit)
    unit = str(unit).strip().lower()
    if unit in {'day', 'daily', '1d'}:
        return 86400
    return 3600


def describe_persist_schedule():
    return "Alternierend: ungerade Tage → SD, gerade Tage → Pi5"


def _sleep_until_next_slot(unit_seconds):
    now = time.time()
    next_slot = (int(now // unit_seconds) + 1) * unit_seconds
    sleep_s = max(1, int(next_slot - now))
    time.sleep(sleep_s)


def _backup_sqlite_db(src_path, dst_path):
    src = sqlite3.connect(src_path, timeout=30.0)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _db_has_tables(db_path, required=None):
    """Prüft ob eine SQLite-DB die erwarteten Tabellen enthält.
    
    Returns:
        (bool, set): (hat_tabellen, gefundene_tabellen)
    """
    if required is None:
        required = REQUIRED_TABLES
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        return required.issubset(tables), tables
    except Exception as e:
        logger.warning(f"DB-Tabellenprüfung fehlgeschlagen für {db_path}: {e}")
        return False, set()


def _find_latest_backup():
    """Sucht das neueste tägliche Backup als Fallback.
    
    Returns:
        str oder None: Pfad zum neuesten .db.gz Backup
    """
    backup_dir = os.path.join(os.path.dirname(config.DB_PERSIST_PATH), 'backup', 'db', 'daily')
    if not os.path.isdir(backup_dir):
        return None
    
    gz_files = sorted(glob.glob(os.path.join(backup_dir, 'data_*.db.gz')), reverse=True)
    for gz_path in gz_files:
        if os.path.getsize(gz_path) > MIN_VALID_DB_SIZE:
            return gz_path
    return None


def _restore_from_gz_backup(gz_path, target_path):
    """Stellt DB aus .gz-Backup wieder her.
    
    Returns:
        bool: Erfolg
    """
    try:
        t0 = time.time()
        tmp_target = target_path + '.restore_tmp'
        
        with gzip.open(gz_path, 'rb') as f_in:
            with open(tmp_target, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Integrität prüfen
        has_tables, tables = _db_has_tables(tmp_target)
        if not has_tables:
            logger.error(f"Backup {gz_path} enthält nicht die erwarteten Tabellen: {tables}")
            os.remove(tmp_target)
            return False
        
        os.rename(tmp_target, target_path)
        dt = time.time() - t0
        size_mb = os.path.getsize(target_path) / 1e6
        logger.info(f"DB aus Backup wiederhergestellt: {gz_path} -> {target_path} "
                     f"({size_mb:.1f} MB in {dt:.1f}s)")
        return True
    except Exception as e:
        logger.error(f"Backup-Wiederherstellung fehlgeschlagen: {e}")
        for f in [target_path + '.restore_tmp']:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        return False


def ensure_tmpfs_db():
    """Stellt sicher, dass die tmpfs-DB existiert und GÜLTIGE DATEN enthält.
    
    Wird beim Start von Collector, Web-API und Cron-Scripts aufgerufen.
    Ablauf:
      1. tmpfs-DB vorhanden & enthält echte Tabellen → OK
    2. Persist-Kopie auf SD vorhanden & gültig → Kopiere nach tmpfs
    3. Tägliches Backup vorhanden → Wiederherstellen
    4. Alles fehlt → Erstelle leere DB (Collector befüllt sie)
    
    WICHTIG: Prüft auf echte Tabellen, nicht nur Dateigröße!
    Verhindert die Race-Condition bei der ein Cron-Job nach Stromausfall
    eine leere DB in tmpfs anlegt, bevor der Collector sie wiederherstellt.
    
    Thread-safe durch atomaren Rename.
    """
    tmpfs_path = config.DB_PATH           # /dev/shm/fronius_data.db
    persist_path = config.DB_PERSIST_PATH  # .../pv-system/data.db
    
    # 1. Schon da UND enthält echte Tabellen?
    if os.path.exists(tmpfs_path) and os.path.getsize(tmpfs_path) > MIN_VALID_DB_SIZE:
        has_tables, tables = _db_has_tables(tmpfs_path)
        if has_tables:
            logger.info(f"tmpfs-DB existiert bereits: {tmpfs_path} "
                         f"({os.path.getsize(tmpfs_path) / 1e6:.1f} MB, "
                         f"{len(tables)} Tabellen)")
            return True
        else:
            logger.warning(f"tmpfs-DB existiert aber ist LEER/KORRUPT "
                            f"({os.path.getsize(tmpfs_path)} Bytes, "
                            f"Tabellen: {tables}) — wird überschrieben")
            try:
                os.remove(tmpfs_path)
            except OSError:
                pass
    elif os.path.exists(tmpfs_path):
        logger.warning(f"tmpfs-DB zu klein ({os.path.getsize(tmpfs_path)} Bytes) "
                        f"— vermutlich leere DB nach Stromausfall, wird überschrieben")
        try:
            os.remove(tmpfs_path)
        except OSError:
            pass
    
    # 2. Persist-Kopie vorhanden UND gültig → Wiederherstellen
    #    BUG-FIX 2026-03-15: Retry bei transientem I/O-Error (SD nach Umstecken/Boot)
    persist_valid = False
    if os.path.exists(persist_path) and os.path.getsize(persist_path) > MIN_VALID_DB_SIZE:
        has_tables, tables = _db_has_tables(persist_path)
        if has_tables:
            persist_valid = True
            last_err = None
            for attempt in range(3):
                try:
                    if attempt > 0:
                        logger.info(f"SD-Restore Retry {attempt+1}/3 nach {attempt * 2}s Pause...")
                        time.sleep(attempt * 2)  # 0s, 2s, 4s
                    t0 = time.time()
                    tmp_target = tmpfs_path + '.tmp'
                    _backup_sqlite_db(persist_path, tmp_target)

                    os.rename(tmp_target, tmpfs_path)

                    dt = time.time() - t0
                    size_mb = os.path.getsize(tmpfs_path) / 1e6
                    logger.info(f"tmpfs-DB wiederhergestellt: {persist_path} -> {tmpfs_path} "
                                 f"({size_mb:.1f} MB in {dt:.1f}s)"
                                 + (f" [Retry {attempt+1}]" if attempt > 0 else ""))
                    return True

                except Exception as e:
                    last_err = e
                    logger.warning(f"SD-Restore Versuch {attempt+1}/3 fehlgeschlagen: {e}")
                    for f in [tmpfs_path + '.tmp', tmpfs_path]:
                        try:
                            os.remove(f)
                        except FileNotFoundError:
                            pass

            # Alle 3 Versuche fehlgeschlagen — letzter Fallback: Raw-Copy statt SQLite-Backup
            logger.warning(f"SQLite-Backup 3× fehlgeschlagen ({last_err}) — versuche Raw-Copy")
            try:
                tmp_target = tmpfs_path + '.tmp'
                shutil.copy2(persist_path, tmp_target)
                # Integrität nach Copy prüfen
                has_t, _ = _db_has_tables(tmp_target)
                if has_t:
                    os.rename(tmp_target, tmpfs_path)
                    size_mb = os.path.getsize(tmpfs_path) / 1e6
                    logger.info(f"tmpfs-DB per Raw-Copy wiederhergestellt ({size_mb:.1f} MB)")
                    return True
                else:
                    logger.error("Raw-Copy DB ist korrupt — Fallback auf Backup")
                    os.remove(tmp_target)
            except Exception as e2:
                logger.error(f"Raw-Copy ebenfalls fehlgeschlagen: {e2}")
                for f in [tmpfs_path + '.tmp']:
                    try:
                        os.remove(f)
                    except FileNotFoundError:
                        pass
        else:
            logger.warning(f"Persist-DB {persist_path} ist LEER/KORRUPT "
                            f"({os.path.getsize(persist_path)} Bytes, Tabellen: {tables})")

    # 2b. Pi5-Kopie als Fallback (alternierend persistiert)
    if not persist_valid:
        pi5_db = _try_restore_from_pi5(tmpfs_path)
        if pi5_db:
            return True

    # 3. Tägliches Backup als Fallback
    gz_backup = _find_latest_backup()
    if gz_backup:
        logger.warning(f"Persist-DB ungültig — versuche Backup: {gz_backup}")
        # Persist-DB sichern bevor sie überschrieben wird (könnte transient unlesbar,
        # aber physisch intakt sein — z.B. nach SD-Umstecken/Boot-I/O-Error)
        if os.path.exists(persist_path) and os.path.getsize(persist_path) > MIN_VALID_DB_SIZE:
            rescue_path = persist_path + '.pre_restore'
            try:
                os.rename(persist_path, rescue_path)
                logger.info(f"Persist-DB gesichert als {rescue_path} "
                             f"({os.path.getsize(rescue_path) / 1e6:.1f} MB) — "
                             f"manuell prüfbar falls Backup älter ist")
            except OSError as e:
                logger.warning(f"Persist-DB Sicherung fehlgeschlagen: {e}")
        if _restore_from_gz_backup(gz_backup, persist_path):
            try:
                tmp_target = tmpfs_path + '.tmp'
                _backup_sqlite_db(persist_path, tmp_target)
                os.rename(tmp_target, tmpfs_path)
                size_mb = os.path.getsize(tmpfs_path) / 1e6
                logger.info(f"tmpfs-DB aus Backup wiederhergestellt ({size_mb:.1f} MB)")

                # Nach GFS-Restore: Prüfe ob .pre_restore neuere Daten hat
                # (SD könnte jetzt lesbar sein — transiente I/O-Errors sind oft beim 2. Lesen weg)
                rescue_path = persist_path + '.pre_restore'
                if os.path.exists(rescue_path) and os.path.getsize(rescue_path) > MIN_VALID_DB_SIZE:
                    try:
                        rescue_conn = sqlite3.connect(f"file:{rescue_path}?mode=ro", uri=True, timeout=5)
                        rescue_max = rescue_conn.execute("SELECT MAX(ts) FROM raw_data").fetchone()[0]
                        rescue_conn.close()

                        current_conn = sqlite3.connect(f"file:{tmpfs_path}?mode=ro", uri=True, timeout=5)
                        current_max = current_conn.execute("SELECT MAX(ts) FROM raw_data").fetchone()[0]
                        current_conn.close()

                        if rescue_max and current_max and rescue_max > current_max:
                            diff_h = (rescue_max - current_max) / 3600
                            logger.info(f"pre_restore hat {diff_h:.1f}h neuere Daten "
                                         f"— restauriere stattdessen von pre_restore")
                            # pre_restore ist lesbar → als tmpfs und persist übernehmen
                            _backup_sqlite_db(rescue_path, tmpfs_path + '.tmp')
                            os.rename(tmpfs_path + '.tmp', tmpfs_path)
                            shutil.copy2(rescue_path, persist_path)
                            size_mb = os.path.getsize(tmpfs_path) / 1e6
                            logger.info(f"tmpfs-DB aus pre_restore wiederhergestellt "
                                         f"({size_mb:.1f} MB, {diff_h:.1f}h neuer als GFS)")
                        elif rescue_max and current_max:
                            logger.info(f"pre_restore nicht neuer als GFS — verwerfe")
                    except Exception as e_rescue:
                        logger.warning(f"pre_restore Prüfung fehlgeschlagen: {e_rescue} — bleibe bei GFS")

                return True
            except Exception as e:
                logger.error(f"tmpfs-Wiederherstellung aus Backup fehlgeschlagen: {e}")
    
    # 4. Weder tmpfs noch Persist noch Backup → Erstinstallation oder totaler Datenverlust
    logger.warning("WARNUNG: Keine gültige DB gefunden — erstelle leere DB!")
    logger.warning("  Daten müssen aus externem Backup wiederhergestellt werden.")
    try:
        conn = sqlite3.connect(tmpfs_path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Konnte leere tmpfs-DB nicht erstellen: {e}")
        return False


def _try_restore_from_pi5(tmpfs_path):
    """Versuche DB von Pi5 zu holen (Fallback wenn lokale SD-Kopie fehlt/korrupt).
    
    Wird nur aufgerufen wenn die lokale Persist-DB ungültig ist.
    Timeout: 30s — bei Pi5-Ausfall schnell weiter zum nächsten Fallback.
    """
    pi5_host = getattr(config, 'PI5_BACKUP_HOST', 'admin@192.0.2.195')
    pi5_db = getattr(config, 'PI5_BACKUP_DB_PATH',
                     '/srv/pv-system/data.db')
    tmp_file = '/tmp/pv_db_pi5_restore.db'
    
    logger.info(f"Versuche DB-Restore von Pi5 ({pi5_host})...")
    
    try:
        result = subprocess.run(
            ['rsync', '-az', '--timeout=30',
             f'{pi5_host}:{pi5_db}', tmp_file],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            logger.warning(f"Pi5-Restore: rsync fehlgeschlagen (rc={result.returncode})")
            return False
        
        if not os.path.exists(tmp_file) or os.path.getsize(tmp_file) < MIN_VALID_DB_SIZE:
            logger.warning("Pi5-Restore: Empfangene DB zu klein/fehlt")
            return False
        
        has_tables, tables = _db_has_tables(tmp_file)
        if not has_tables:
            logger.warning(f"Pi5-Restore: DB hat nicht die erwarteten Tabellen ({tables})")
            return False
        
        # Kopiere nach tmpfs (atomarer Rename)
        t0 = time.time()
        tmp_target = tmpfs_path + '.tmp'
        _backup_sqlite_db(tmp_file, tmp_target)
        os.rename(tmp_target, tmpfs_path)
        
        dt = time.time() - t0
        size_mb = os.path.getsize(tmpfs_path) / 1e6
        logger.info(f"tmpfs-DB von Pi5 wiederhergestellt: {size_mb:.1f} MB in {dt:.1f}s")
        return True
        
    except subprocess.TimeoutExpired:
        logger.warning("Pi5-Restore: Timeout (60s) — Pi5 nicht erreichbar")
        return False
    except Exception as e:
        logger.warning(f"Pi5-Restore fehlgeschlagen: {e}")
        return False
    finally:
        for f in [tmp_file, tmpfs_path + '.tmp']:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass


def _persist_tmpfs_to_sd(tmpfs_path, persist_path):
    if not os.path.exists(tmpfs_path):
        return False

    tmpfs_size = os.path.getsize(tmpfs_path)

    # SICHERHEITSCHECK: Nicht persistieren wenn tmpfs-DB verdächtig klein
    if tmpfs_size < MIN_VALID_DB_SIZE:
        logger.warning(f"Persist ÜBERSPRUNGEN: tmpfs-DB zu klein "
                        f"({tmpfs_size} Bytes) — vermutlich leer/korrupt")
        return False

    # SICHERHEITSCHECK: Nicht persistieren wenn tmpfs-DB keine echten Tabellen hat
    has_tables, tables = _db_has_tables(tmpfs_path)
    if not has_tables:
        logger.warning(f"Persist ÜBERSPRUNGEN: tmpfs-DB hat nicht die "
                        f"erwarteten Tabellen (gefunden: {tables})")
        return False

    # SICHERHEITSCHECK: Warnung wenn persist-DB viel größer als tmpfs-DB
    if os.path.exists(persist_path):
        persist_size = os.path.getsize(persist_path)
        if persist_size > MIN_VALID_DB_SIZE and tmpfs_size < persist_size * 0.5:
            logger.error(f"Persist ABGEBROCHEN: tmpfs-DB ({tmpfs_size/1e6:.1f} MB) "
                          f"ist <50% der persist-DB ({persist_size/1e6:.1f} MB) — "
                          f"möglicher Datenverlust!")
            return False

    t0 = time.time()
    tmp_target = persist_path + '.tmp'

    # SQLite .backup(): liest aus tmpfs (RAM-Speed), schreibt auf SD
    _backup_sqlite_db(tmpfs_path, tmp_target)

    # fsync für Crash-Sicherheit: Daten wirklich auf Disk
    fd = os.open(tmp_target, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)

    # Atomarer Rename (POSIX-garantiert auf gleichem Filesystem)
    os.rename(tmp_target, persist_path)

    # Directory-fsync: Rename-Metadaten auf Disk
    dir_fd = os.open(os.path.dirname(persist_path), os.O_RDONLY)
    os.fsync(dir_fd)
    os.close(dir_fd)

    dt = time.time() - t0
    size_mb = os.path.getsize(persist_path) / 1e6
    logger.info(f"DB persistiert (SD): {size_mb:.1f} MB in {dt:.1f}s")
    return True


def persist_to_disk():
    """Background-Thread: Stündliche Sicherung mit alternierendem Ziel.
    
    Schema:
      Jede Stunde:  tmpfs → SD-Card lokal
      Alle 6 Stunden zusätzlich: tmpfs → Pi5 via rsync
    
    Bei Stunden-Intervall max. 1h Datenverlust statt 24h.
    Fixpunkte (daily_data._start/_end) sichern Langzeit-Werte.
    
    SICHERHEIT: Verweigert Persist wenn tmpfs-DB leer/korrupt ist.
    """
    tmpfs_path = config.DB_PATH
    persist_path = config.DB_PERSIST_PATH
    unit_seconds = _get_persist_unit_seconds()

    logger.info(
        f"Persist-Thread gestartet: {tmpfs_path} | "
        f"Intervall: {unit_seconds}s | "
        f"{describe_persist_schedule()}"
    )

    cycle = 0
    while True:
        _sleep_until_next_slot(unit_seconds)
        cycle += 1
        try:
            # Immer lokal auf SD sichern
            logger.info(f"Persist Zyklus {cycle} → SD-Card lokal")
            _persist_tmpfs_to_sd(tmpfs_path, persist_path)
            
            # Alle 6 Zyklen zusätzlich auf Pi5
            if cycle % 6 == 0:
                logger.info(f"Persist Zyklus {cycle} → Pi5 (alle 6 Zyklen)")
                _persist_tmpfs_to_pi5(tmpfs_path)
        except Exception as e:
            logger.error(f"Persist-Fehler (Zyklus {cycle}): {e}")
            try:
                os.remove(persist_path + '.tmp')
            except FileNotFoundError:
                pass


def _persist_tmpfs_to_pi5(tmpfs_path):
    """Persist tmpfs-DB nach Pi5 via SQLite .backup() + rsync.
    
    1. SQLite .backup() → lokale temp-Datei (konsistent, WAL-safe)
    2. rsync → Pi5 (komprimiert, idempotent)
    3. Temp-Datei löschen
    """
    pi5_host = getattr(config, 'PI5_BACKUP_HOST', 'admin@192.0.2.195')
    pi5_db = getattr(config, 'PI5_BACKUP_DB_PATH',
                     '/srv/pv-system/data.db')
    
    if not os.path.exists(tmpfs_path):
        logger.warning("Pi5-Persist: tmpfs-DB nicht vorhanden")
        return False
    
    # Gleiche Sicherheitschecks wie bei SD
    tmpfs_size = os.path.getsize(tmpfs_path)
    if tmpfs_size < MIN_VALID_DB_SIZE:
        logger.warning(f"Pi5-Persist ÜBERSPRUNGEN: tmpfs-DB zu klein ({tmpfs_size} Bytes)")
        return False
    
    has_tables, tables = _db_has_tables(tmpfs_path)
    if not has_tables:
        logger.warning(f"Pi5-Persist ÜBERSPRUNGEN: tmpfs-DB hat nicht die erwarteten Tabellen")
        return False
    
    tmp_file = '/dev/shm/pv_db_pi5_transfer.db'
    t0 = time.time()
    
    try:
        # 1. Konsistente Kopie aus tmpfs (in /dev/shm, nicht /tmp — zu klein!)
        _backup_sqlite_db(tmpfs_path, tmp_file)
        
        # 2. rsync nach Pi5 (--compress, --timeout=120)
        result = subprocess.run(
            ['rsync', '-az', '--timeout=120', tmp_file,
             f'{pi5_host}:{pi5_db}'],
            capture_output=True, text=True, timeout=180
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"rsync → Pi5 fehlgeschlagen (rc={result.returncode}): "
                             f"{result.stderr.strip()}")
        
        dt = time.time() - t0
        size_mb = os.path.getsize(tmp_file) / 1e6
        logger.info(f"DB persistiert (Pi5): {size_mb:.1f} MB in {dt:.1f}s")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("Pi5-Persist: rsync Timeout (180s)")
        return False
    except Exception as e:
        logger.error(f"Pi5-Persist Fehler: {e}")
        return False
    finally:
        try:
            os.remove(tmp_file)
        except FileNotFoundError:
            pass


def ensure_forecast_table():
    """Erstellt forecast_daily-Tabelle falls nicht vorhanden.
    Stellt sicher, dass daily_data.forecast_kwh existiert.
    
    Speichert Tages-Prognosen + Clear-Sky persistent, damit sie
    im Tag-Chart auch für vergangene Tage als Hintergrund-Overlay
    angezeigt werden können.
    """
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=10.0)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_daily (
                date TEXT PRIMARY KEY,           -- YYYY-MM-DD
                expected_kwh REAL,               -- Prognostizierter PV-Ertrag
                clearsky_kwh REAL,               -- Clear-Sky Theoriewert
                quality TEXT,                    -- 'gut', 'mittel', 'schlecht'
                weather_text TEXT,               -- Wetterbeschreibung
                weather_code INTEGER,            -- WMO-Code
                sunrise TEXT,                    -- HH:MM
                sunset TEXT,                     -- HH:MM
                sunshine_hours REAL,             -- Progn. Sonnenstunden
                temp_min REAL,                   -- Min-Temperatur
                temp_max REAL,                   -- Max-Temperatur
                cloud_cover_avg REAL,            -- Ø Bewölkung %
                precipitation_mm REAL,           -- Erwarteter Niederschlag
                hourly_profile TEXT,             -- JSON: stündliche Leistungsprognose
                clearsky_profile TEXT,           -- JSON: [{ts, total_ac}]
                forecast_method TEXT,            -- 'geometry' oder 'ghi_factor'
                created_at REAL,                 -- Unix-Timestamp der Speicherung
                actual_kwh REAL                  -- Nachträglich: tatsächliche Produktion
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_forecast_date
            ON forecast_daily(date)
        """)
        conn.commit()
        
        # Migration: forecast_kwh in daily_data sicherstellen
        try:
            conn.execute("SELECT forecast_kwh FROM daily_data LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE daily_data ADD COLUMN forecast_kwh REAL DEFAULT NULL")
            conn.commit()
            logger.info("daily_data.forecast_kwh Spalte hinzugefügt")

        # Migration: Forecast/Clear-Sky Spalten in data_15min
        for col in ('P_PV_FC_avg', 'P_PV_CS_avg', 'W_PV_FC_delta', 'W_PV_CS_delta'):
            try:
                conn.execute(f"SELECT {col} FROM data_15min LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE data_15min ADD COLUMN {col} REAL DEFAULT NULL")
                conn.commit()
                logger.info(f"data_15min.{col} Spalte hinzugefügt")
        
        # Migration: sonnenstunden in statistics-Tabellen sicherstellen
        for table in ('monthly_statistics', 'yearly_statistics'):
            try:
                conn.execute(f"SELECT sonnenstunden FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN sonnenstunden REAL DEFAULT NULL")
                    conn.commit()
                    logger.info(f"{table}.sonnenstunden Spalte hinzugefügt")
                except Exception:
                    pass
        
        conn.close()
        logger.info("forecast_daily Tabelle bereit")
    except Exception as e:
        logger.error(f"forecast_daily Tabelle Fehler: {e}")


def start_persist_thread():
    """Startet den Persist-Thread als Daemon."""
    t = threading.Thread(target=persist_to_disk, daemon=True, name='db-persist')
    t.start()
    return t
