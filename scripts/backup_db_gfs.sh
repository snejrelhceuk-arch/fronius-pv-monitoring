#!/bin/bash
# =================================================================
# GFS-Backup (Sohn-Vater-Großvater) für PV-Datenbank auf Pi5
# =================================================================
#
# Strategie:
#   Sohn        (daily)  : 7 Tage            → ~270 MB
#   Vater       (weekly) : 5 Wochen (So)      → ~190 MB
#   Großvater   (monthly): 12 Monate (1.)     → ~460 MB
#   Urgroßvater (yearly) : permanent (1. Jan)  → ~38 MB/Jahr
#
# Gesamt: < 1 GB auf NVMe (421 GB frei)
#
# Cron auf Pi5:
#   0 3 * * * /srv/pv-system/scripts/backup_db_gfs.sh
#
# Die data.db wird vom Pi4 per rsync geliefert (gerade Tage) und
# lokal per backup_db.sh täglich um 03:00 gesichert.
# Falls kein rsync-Push kam, sichert das Script trotzdem die
# vorhandene data.db — schlimmstenfalls 2 Tage alt, aber immer
# besser als kein Backup.
#
# Integritätsprüfung nach jedem Backup.
# =================================================================

set -euo pipefail

# --- Konfiguration ---
DB_PATH="/srv/pv-system/data.db"
BACKUP_BASE="/srv/pv-system/backup/db"
LOG_FILE="/tmp/db_backup_gfs.log"

# Retention
DAILY_KEEP=7       # Sohn: 7 Tage
WEEKLY_KEEP=5      # Vater: 5 Wochen
MONTHLY_KEEP=12    # Großvater: 12 Monate
# Yearly: permanent (kein Limit)

# Mindestgröße für gültige DB (leere SQLite ≈ 4 KB)
MIN_DB_SIZE=100000  # 100 KB

# --- Verzeichnisse ---
DAILY_DIR="$BACKUP_BASE/daily"
WEEKLY_DIR="$BACKUP_BASE/weekly"
MONTHLY_DIR="$BACKUP_BASE/monthly"
YEARLY_DIR="$BACKUP_BASE/yearly"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR" "$MONTHLY_DIR" "$YEARLY_DIR"

# --- Datums-Variablen ---
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)          # 1=Mo ... 7=So
DOM=$(date +%d)           # Tag im Monat (01-31)
DOY=$(date +%j)           # Tag im Jahr (001-366)
MONTH=$(date +%Y-%m)
YEAR=$(date +%Y)

# --- Logging ---
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# --- Integritätsprüfung ---
check_backup_integrity() {
    local gz_file="$1"
    local label="$2"
    local tmp_check
    tmp_check=$(mktemp)

    if gunzip -c "$gz_file" > "$tmp_check" 2>/dev/null; then
        local integrity
        integrity=$(sqlite3 "$tmp_check" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
        if [ "$integrity" = "ok" ]; then
            # Prüfe ob Kernabellen vorhanden
            local tbl_count
            tbl_count=$(sqlite3 "$tmp_check" \
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('raw_data','data_1min','daily_data');" \
                2>/dev/null || echo "0")
            if [ "$tbl_count" -ge 3 ]; then
                log "  ✓ $label Integrität OK (3/3 Kerntabellen)"
                rm -f "$tmp_check"
                return 0
            else
                log "  ✗ $label Kerntabellen fehlen ($tbl_count/3)"
            fi
        else
            log "  ✗ $label Integritätsprüfung: $integrity"
        fi
    else
        log "  ✗ $label gunzip fehlgeschlagen"
    fi

    rm -f "$tmp_check"
    return 1
}

# --- Alte Backups aufräumen ---
cleanup_old() {
    local dir="$1"
    local keep="$2"
    local label="$3"
    local deleted=0

    while IFS= read -r old_file; do
        rm -f "$old_file"
        deleted=$((deleted + 1))
    done < <(ls -1t "$dir"/*.gz 2>/dev/null | tail -n +$((keep + 1)))

    if [ "$deleted" -gt 0 ]; then
        log "  $label: $deleted alte Backups gelöscht (behalte $keep)"
    fi
}

# =================================================================
# HAUPTPROGRAMM
# =================================================================

log "=== GFS-Backup gestartet (${DATE}, DOW=${DOW}) ==="

# --- Prüfe DB ---
if [ ! -f "$DB_PATH" ]; then
    log "FEHLER: Datenbank nicht gefunden: $DB_PATH"
    exit 1
fi

DB_SIZE=$(stat -c%s "$DB_PATH" 2>/dev/null || echo 0)
if [ "$DB_SIZE" -lt "$MIN_DB_SIZE" ]; then
    log "FEHLER: DB zu klein ($DB_SIZE Bytes) — vermutlich leer/korrupt"
    exit 1
fi

log "DB-Größe: $(numfmt --to=iec $DB_SIZE)"

# --- SOHN: Tägliches Backup ---
DAILY_FILE="$DAILY_DIR/data_${DATE}.db"

log "Sohn: Erstelle tägliches Backup..."
if sqlite3 "$DB_PATH" ".backup '$DAILY_FILE'"; then
    if gzip -f "$DAILY_FILE"; then
        GZ_SIZE=$(stat -c%s "${DAILY_FILE}.gz" 2>/dev/null || echo 0)
        log "  Sohn: ${DAILY_FILE}.gz ($(numfmt --to=iec $GZ_SIZE))"
        check_backup_integrity "${DAILY_FILE}.gz" "Sohn"
    fi
else
    log "FEHLER: SQLite .backup fehlgeschlagen!"
    exit 1
fi

cleanup_old "$DAILY_DIR" "$DAILY_KEEP" "Sohn"

# --- VATER: Wöchentliches Backup (Sonntags) ---
if [ "$DOW" = "7" ]; then
    WEEK_NUM=$(date +%Y-W%V)
    WEEKLY_FILE="$WEEKLY_DIR/data_${WEEK_NUM}.db.gz"

    if [ ! -f "$WEEKLY_FILE" ]; then
        log "Vater: Erstelle wöchentliches Backup (KW $(date +%V))..."
        cp "${DAILY_FILE}.gz" "$WEEKLY_FILE"
        log "  Vater: $WEEKLY_FILE"
        check_backup_integrity "$WEEKLY_FILE" "Vater"
    else
        log "Vater: Wöchentliches Backup existiert bereits: $WEEKLY_FILE"
    fi

    cleanup_old "$WEEKLY_DIR" "$WEEKLY_KEEP" "Vater"
fi

# --- GROSSVATER: Monatliches Backup (1. des Monats) ---
if [ "$DOM" = "01" ]; then
    MONTHLY_FILE="$MONTHLY_DIR/data_${MONTH}.db.gz"

    if [ ! -f "$MONTHLY_FILE" ]; then
        log "Großvater: Erstelle monatliches Backup..."
        cp "${DAILY_FILE}.gz" "$MONTHLY_FILE"
        log "  Großvater: $MONTHLY_FILE"
        check_backup_integrity "$MONTHLY_FILE" "Großvater"
    else
        log "Großvater: Monatliches Backup existiert bereits: $MONTHLY_FILE"
    fi

    cleanup_old "$MONTHLY_DIR" "$MONTHLY_KEEP" "Großvater"
fi

# --- URGROSSVATER: Jährliches Backup (1. Januar) ---
if [ "$DOM" = "01" ] && [ "$(date +%m)" = "01" ]; then
    YEARLY_FILE="$YEARLY_DIR/data_${YEAR}.db.gz"

    if [ ! -f "$YEARLY_FILE" ]; then
        log "Urgroßvater: Erstelle jährliches Backup..."
        cp "${DAILY_FILE}.gz" "$YEARLY_FILE"
        log "  Urgroßvater: $YEARLY_FILE"
        check_backup_integrity "$YEARLY_FILE" "Urgroßvater"
    else
        log "Urgroßvater: Jährliches Backup existiert bereits: $YEARLY_FILE"
    fi
    # Yearly: KEIN cleanup — permanent aufheben
fi

# --- Speicherplatz-Info ---
DAILY_TOTAL=$(du -sh "$DAILY_DIR" 2>/dev/null | awk '{print $1}')
WEEKLY_TOTAL=$(du -sh "$WEEKLY_DIR" 2>/dev/null | awk '{print $1}')
MONTHLY_TOTAL=$(du -sh "$MONTHLY_DIR" 2>/dev/null | awk '{print $1}')
YEARLY_TOTAL=$(du -sh "$YEARLY_DIR" 2>/dev/null | awk '{print $1}')
ALL_TOTAL=$(du -sh "$BACKUP_BASE" 2>/dev/null | awk '{print $1}')

log "Speicher: Sohn=${DAILY_TOTAL} Vater=${WEEKLY_TOTAL} Großvater=${MONTHLY_TOTAL} Urgroßvater=${YEARLY_TOTAL} | Gesamt=${ALL_TOTAL}"
log "=== GFS-Backup abgeschlossen ==="
