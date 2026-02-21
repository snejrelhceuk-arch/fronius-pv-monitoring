#!/bin/bash
# =================================================================
# GFS-Backup (Sohn-Vater-Großvater) für PV-Datenbank
# =================================================================
#
# Umstellung 2026-02-21:
#   - Sohn nur alle 3 Tage
#   - Quelle für Sohn: RAM-DB (/dev/shm/fronius_data.db)
#   - Vater/Großvater/Urgroßvater bleiben kalendarisch wie bisher
#   - Jede neu erzeugte Backup-Datei wird zusätzlich nach Pi5/NVMe kopiert
#
# Cron (Primary Pi4):
#   0 3 * * * /home/admin/Dokumente/PVAnlage/pv-system/scripts/backup_db_gfs.sh
#
# Hinweis:
#   Die alternierende 2-Tage-Persistierung (data.db auf Pi5) bleibt unverändert.
# =================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"

# --- Konfiguration ---
DB_PATH="${DB_PATH:-/dev/shm/fronius_data.db}"
BACKUP_BASE="${BACKUP_BASE:-${BASE}/backup/db}"
LOG_FILE="${LOG_FILE:-/tmp/db_backup_gfs.log}"

PI5_BACKUP_HOST="${PI5_BACKUP_HOST:-admin@192.168.2.195}"
PI5_BACKUP_BASE="${PI5_BACKUP_BASE:-/home/admin/Documents/PVAnlage/pv-system/backup/db}"

STATE_DIR="${STATE_DIR:-/var/lib/pv-system}"
SOHN_STAMP_FILE="${STATE_DIR}/backup_gfs_sohn_last_ts"
SOHN_MIN_AGE_SEC=$((70 * 3600))

# Retention
DAILY_KEEP=7
WEEKLY_KEEP=5
MONTHLY_KEEP=12

# Mindestgröße für gültige DB (leere SQLite ≈ 4 KB)
MIN_DB_SIZE=100000

# --- Verzeichnisse ---
DAILY_DIR="$BACKUP_BASE/daily"
WEEKLY_DIR="$BACKUP_BASE/weekly"
MONTHLY_DIR="$BACKUP_BASE/monthly"
YEARLY_DIR="$BACKUP_BASE/yearly"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR" "$MONTHLY_DIR" "$YEARLY_DIR" "$STATE_DIR"

# --- Datums-Variablen ---
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)          # 1=Mo ... 7=So
DOM=$(date +%d)          # Tag im Monat (01-31)
MONTH=$(date +%Y-%m)
YEAR=$(date +%Y)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_backup_integrity() {
    local gz_file="$1"
    local label="$2"
    local tmp_check
    tmp_check=$(mktemp)

    if gunzip -c "$gz_file" > "$tmp_check" 2>/dev/null; then
        local integrity
        integrity=$(sqlite3 "$tmp_check" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
        if [ "$integrity" = "ok" ]; then
            local tbl_count
            tbl_count=$(sqlite3 "$tmp_check" \
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('raw_data','data_1min','daily_data');" \
                2>/dev/null || echo "0")
            if [ "$tbl_count" -ge 3 ]; then
                log "  ✓ $label Integrität OK (3/3 Kerntabellen)"
                rm -f "$tmp_check"
                return 0
            fi
            log "  ✗ $label Kerntabellen fehlen ($tbl_count/3)"
        else
            log "  ✗ $label Integritätsprüfung: $integrity"
        fi
    else
        log "  ✗ $label gunzip fehlgeschlagen"
    fi

    rm -f "$tmp_check"
    return 1
}

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

latest_backup_file() {
    local dir="$1"
    ls -1t "$dir"/*.gz 2>/dev/null | head -n1 || true
}

sync_file_to_pi5() {
    local file_path="$1"
    local tier="$2"

    if [ ! -f "$file_path" ]; then
        return 1
    fi

    local remote_dir="${PI5_BACKUP_BASE}/${tier}"
    if ! ssh -o ConnectTimeout=10 "$PI5_BACKUP_HOST" "mkdir -p '$remote_dir'" >/dev/null 2>&1; then
        log "  ⚠ Pi5 Sync: Remote-Verzeichnis nicht erreichbar ($PI5_BACKUP_HOST:$remote_dir)"
        return 1
    fi

    if rsync -az --timeout=60 "$file_path" "$PI5_BACKUP_HOST:$remote_dir/" >/dev/null 2>&1; then
        log "  ✓ Pi5 Sync: $(basename "$file_path") → $PI5_BACKUP_HOST:$remote_dir"
        return 0
    fi

    log "  ⚠ Pi5 Sync fehlgeschlagen: $(basename "$file_path")"
    return 1
}

should_run_sohn() {
    local now_ts
    now_ts=$(date +%s)

    if [ ! -f "$SOHN_STAMP_FILE" ]; then
        return 0
    fi

    local last_ts
    last_ts=$(cat "$SOHN_STAMP_FILE" 2>/dev/null || echo 0)
    if [[ ! "$last_ts" =~ ^[0-9]+$ ]]; then
        return 0
    fi

    local age=$((now_ts - last_ts))
    [ "$age" -ge "$SOHN_MIN_AGE_SEC" ]
}

write_sohn_stamp() {
    date +%s > "$SOHN_STAMP_FILE"
}

log "=== GFS-Backup gestartet (${DATE}, DOW=${DOW}) ==="

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

DAILY_GZ=""
DAILY_FILE="$DAILY_DIR/data_${DATE}.db"

if should_run_sohn; then
    log "Sohn: Erstelle 3-Tage-Backup aus RAM-DB..."
    if sqlite3 "$DB_PATH" ".backup '$DAILY_FILE'"; then
        gzip -f "$DAILY_FILE"
        DAILY_GZ="${DAILY_FILE}.gz"
        GZ_SIZE=$(stat -c%s "$DAILY_GZ" 2>/dev/null || echo 0)
        log "  Sohn: $DAILY_GZ ($(numfmt --to=iec $GZ_SIZE))"
        check_backup_integrity "$DAILY_GZ" "Sohn"
        write_sohn_stamp
        sync_file_to_pi5 "$DAILY_GZ" "daily" || true
    else
        log "FEHLER: SQLite .backup fehlgeschlagen!"
        exit 1
    fi
else
    DAILY_GZ=$(latest_backup_file "$DAILY_DIR")
    log "Sohn: übersprungen (Intervall 3 Tage). Letztes Sohn-Backup: ${DAILY_GZ:-keins}"
fi

cleanup_old "$DAILY_DIR" "$DAILY_KEEP" "Sohn"

if [ -z "$DAILY_GZ" ] || [ ! -f "$DAILY_GZ" ]; then
    DAILY_GZ=$(latest_backup_file "$DAILY_DIR")
fi

if [ -z "$DAILY_GZ" ] || [ ! -f "$DAILY_GZ" ]; then
    log "FEHLER: Kein gültiges Sohn-Backup vorhanden — Vater/Großvater/Urgroßvater nicht möglich"
    exit 1
fi

if [ "$DOW" = "7" ]; then
    WEEK_NUM=$(date +%Y-W%V)
    WEEKLY_FILE="$WEEKLY_DIR/data_${WEEK_NUM}.db.gz"

    if [ ! -f "$WEEKLY_FILE" ]; then
        log "Vater: Erstelle wöchentliches Backup (KW $(date +%V))..."
        cp "$DAILY_GZ" "$WEEKLY_FILE"
        log "  Vater: $WEEKLY_FILE"
        check_backup_integrity "$WEEKLY_FILE" "Vater"
        sync_file_to_pi5 "$WEEKLY_FILE" "weekly" || true
    else
        log "Vater: Wöchentliches Backup existiert bereits: $WEEKLY_FILE"
    fi

    cleanup_old "$WEEKLY_DIR" "$WEEKLY_KEEP" "Vater"
fi

if [ "$DOM" = "01" ]; then
    MONTHLY_FILE="$MONTHLY_DIR/data_${MONTH}.db.gz"

    if [ ! -f "$MONTHLY_FILE" ]; then
        log "Großvater: Erstelle monatliches Backup..."
        cp "$DAILY_GZ" "$MONTHLY_FILE"
        log "  Großvater: $MONTHLY_FILE"
        check_backup_integrity "$MONTHLY_FILE" "Großvater"
        sync_file_to_pi5 "$MONTHLY_FILE" "monthly" || true
    else
        log "Großvater: Monatliches Backup existiert bereits: $MONTHLY_FILE"
    fi

    cleanup_old "$MONTHLY_DIR" "$MONTHLY_KEEP" "Großvater"
fi

if [ "$DOM" = "01" ] && [ "$(date +%m)" = "01" ]; then
    YEARLY_FILE="$YEARLY_DIR/data_${YEAR}.db.gz"

    if [ ! -f "$YEARLY_FILE" ]; then
        log "Urgroßvater: Erstelle jährliches Backup..."
        cp "$DAILY_GZ" "$YEARLY_FILE"
        log "  Urgroßvater: $YEARLY_FILE"
        check_backup_integrity "$YEARLY_FILE" "Urgroßvater"
        sync_file_to_pi5 "$YEARLY_FILE" "yearly" || true
    else
        log "Urgroßvater: Jährliches Backup existiert bereits: $YEARLY_FILE"
    fi
fi

DAILY_TOTAL=$(du -sh "$DAILY_DIR" 2>/dev/null | awk '{print $1}')
WEEKLY_TOTAL=$(du -sh "$WEEKLY_DIR" 2>/dev/null | awk '{print $1}')
MONTHLY_TOTAL=$(du -sh "$MONTHLY_DIR" 2>/dev/null | awk '{print $1}')
YEARLY_TOTAL=$(du -sh "$YEARLY_DIR" 2>/dev/null | awk '{print $1}')
ALL_TOTAL=$(du -sh "$BACKUP_BASE" 2>/dev/null | awk '{print $1}')

log "Speicher: Sohn=${DAILY_TOTAL} Vater=${WEEKLY_TOTAL} Großvater=${MONTHLY_TOTAL} Urgroßvater=${YEARLY_TOTAL} | Gesamt=${ALL_TOTAL}"
log "=== GFS-Backup abgeschlossen ==="
