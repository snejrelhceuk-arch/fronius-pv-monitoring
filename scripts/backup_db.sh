#!/bin/bash
# =================================================================
# Tägliches DB-Backup für Fronius PV-Monitoring
# Verwendet SQLite .backup (crash-sicher, auch bei laufendem WAL)
#
# Retention:
#   - 7 tägliche Backups (rolling)
#   - Monatliche Snapshots (1. des Monats) → unbegrenzt
#
# Cron: 0 3 * * * /srv/pv-system/scripts/backup_db.sh
# =================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${BASE}/data.db"
BACKUP_DIR="${BASE}/backup/db"
LOG_FILE="/tmp/db_backup.log"
DAILY_KEEP=7

# Sicherstellen, dass Backup-Verzeichnis existiert
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"

DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_MONTH=$(date +%d)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== DB-Backup gestartet ==="

# Prüfe ob DB existiert
if [ ! -f "$DB_PATH" ]; then
    log "FEHLER: Datenbank nicht gefunden: $DB_PATH"
    exit 1
fi

DB_SIZE=$(stat -c%s "$DB_PATH" 2>/dev/null || echo 0)
log "DB-Größe: $(numfmt --to=iec $DB_SIZE)"

# --- Tägliches Backup (SQLite .backup = crash-sicher) ---
DAILY_FILE="$BACKUP_DIR/daily/data_${DATE}.db"

# SQLite .backup Befehl — sicher auch bei WAL-Modus
if sqlite3 "$DB_PATH" ".backup '$DAILY_FILE'"; then
    BACKUP_SIZE=$(stat -c%s "$DAILY_FILE" 2>/dev/null || echo 0)
    log "Tägliches Backup erstellt: $DAILY_FILE ($(numfmt --to=iec $BACKUP_SIZE))"
else
    log "FEHLER: SQLite .backup fehlgeschlagen!"
    exit 1
fi

# Komprimiere (gzip spart ~70% bei SQLite)
if gzip -f "$DAILY_FILE"; then
    GZ_SIZE=$(stat -c%s "${DAILY_FILE}.gz" 2>/dev/null || echo 0)
    log "Komprimiert: ${DAILY_FILE}.gz ($(numfmt --to=iec $GZ_SIZE))"
fi

# --- Monatlicher Snapshot (am 1. des Monats) ---
if [ "$DAY_OF_MONTH" = "01" ]; then
    MONTH=$(date +%Y-%m)
    MONTHLY_FILE="$BACKUP_DIR/monthly/data_${MONTH}.db.gz"
    
    if [ ! -f "$MONTHLY_FILE" ]; then
        # Kopiere das gerade erstellte tägliche Backup
        cp "${DAILY_FILE}.gz" "$MONTHLY_FILE"
        log "Monatlicher Snapshot erstellt: $MONTHLY_FILE"
    else
        log "Monatlicher Snapshot existiert bereits: $MONTHLY_FILE"
    fi
fi

# --- Alte tägliche Backups aufräumen ---
DELETED=0
while IFS= read -r old_backup; do
    rm -f "$old_backup"
    DELETED=$((DELETED + 1))
done < <(ls -1t "$BACKUP_DIR/daily/"*.gz 2>/dev/null | tail -n +$((DAILY_KEEP + 1)))

if [ "$DELETED" -gt 0 ]; then
    log "Alte Backups gelöscht: $DELETED Stück (behalte $DAILY_KEEP)"
fi

# --- Integritätsprüfung des Backups ---
TEMP_CHECK=$(mktemp)
if gunzip -c "${DAILY_FILE}.gz" > "$TEMP_CHECK" 2>/dev/null; then
    INTEGRITY=$(sqlite3 "$TEMP_CHECK" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
    if [ "$INTEGRITY" = "ok" ]; then
        log "Integritätsprüfung: OK ✓"
    else
        log "WARNUNG: Integritätsprüfung fehlgeschlagen: $INTEGRITY"
    fi
fi
rm -f "$TEMP_CHECK"

# --- Speicherplatz-Info ---
BACKUP_TOTAL=$(du -sh "$BACKUP_DIR" 2>/dev/null | awk '{print $1}')
log "Backup-Verzeichnis gesamt: $BACKUP_TOTAL"
log "=== DB-Backup abgeschlossen ==="
