#!/bin/bash
# =================================================================
# GFS-Backup (Sohn-Vater-Großvater) für NQ-Datenbank (Rolle N)
# =================================================================
#
# Sichert die aktuelle NQ-Monats-DB (nq/db/nq_YYYY-MM.db) nach
# backup/db/nq/{daily,weekly,monthly} und auf Pi5-FB (Offsite).
# Integritätsprüfung: gzip + PRAGMA integrity_check + Kerntabellen
# (nq_daily, nq_energy_daily, nq_agg_10s).
#
# Cron (Primary 03:00, nach Transfer 00:10 + Aggregation 00:15):
#   0 3 * * * /srv/pv-system/scripts/backup_nq_gfs.sh
#
# Konfiguration via Umgebungsvariablen (überschreibbar durch .infra.local):
#   NQ_DB_PATH, BACKUP_BASE, PI5_BACKUP_HOST, PI5_BACKUP_BASE
# =================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/scripts/load_infra_env.sh"

# --- Konfiguration ---
# Aktuelle Monats-DB ermitteln
MONTH=$(date +%Y-%m)
NQ_DB_PATH="${NQ_DB_PATH:-${BASE}/nq/db/nq_${MONTH}.db}"
BACKUP_BASE="${BACKUP_BASE:-${BASE}/backup/db/nq}"
LOG_FILE="${LOG_FILE:-/tmp/nq_backup_gfs.log}"

PI5_BACKUP_HOST="${PI5_BACKUP_HOST:-${PV_PI5_BACKUP_HOST:-backup-user@backup-host}}"
PI5_BACKUP_BASE="${PI5_BACKUP_BASE:-${PV_PI5_BACKUP_BASE:-/srv/pv-system/backup/db/nq}}"

# Retention
DAILY_KEEP=7
WEEKLY_KEEP=5
MONTHLY_KEEP=12

# Mindestgröße für gültige DB (leere SQLite ≈ 4 KB)
MIN_DB_SIZE=4096

# --- Verzeichnisse ---
DAILY_DIR="$BACKUP_BASE/daily"
WEEKLY_DIR="$BACKUP_BASE/weekly"
MONTHLY_DIR="$BACKUP_BASE/monthly"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR" "$MONTHLY_DIR"

# --- Datums-Variablen ---
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)       # 1=Mo ... 7=So
DOM=$(date +%d)       # Tag im Monat (01-31)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_backup_integrity() {
    local gz_file="$1"
    local label="$2"
    local tmp_check
    tmp_check=$(mktemp /dev/shm/nq_backup_check_XXXXXX)

    if gunzip -c "$gz_file" > "$tmp_check" 2>/dev/null; then
        local integrity
        integrity=$(sqlite3 "$tmp_check" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
        if [ "$integrity" = "ok" ]; then
            local tbl_count
            tbl_count=$(sqlite3 "$tmp_check" \
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' \
                 AND name IN ('nq_daily','nq_energy_daily','nq_agg_10s');" \
                2>/dev/null || echo "0")
            if [ "$tbl_count" -ge 3 ]; then
                log "  ✓ $label Integrität OK (3/3 NQ-Kerntabellen)"
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

sync_file_to_pi5() {
    local file_path="$1"
    local tier="$2"

    [ -f "$file_path" ] || return 1

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

log "=== NQ GFS-Backup gestartet (${DATE}, DOW=${DOW}, Monat=${MONTH}) ==="

# DB-Existenz + Mindestgröße prüfen
if [ ! -f "$NQ_DB_PATH" ]; then
    log "INFO: NQ-DB nicht vorhanden: $NQ_DB_PATH — kein Backup nötig"
    exit 0
fi

DB_SIZE=$(stat -c%s "$NQ_DB_PATH" 2>/dev/null || echo 0)
if [ "$DB_SIZE" -lt "$MIN_DB_SIZE" ]; then
    log "FEHLER: NQ-DB zu klein ($DB_SIZE Bytes) — vermutlich leer/korrupt"
    exit 1
fi
log "NQ-DB: $NQ_DB_PATH ($(numfmt --to=iec "$DB_SIZE"))"

# --- Tägliches Backup (Sohn) ---
DAILY_FILE="$DAILY_DIR/nq_${DATE}.db"
DAILY_GZ="${DAILY_FILE}.gz"

log "Daily: Erstelle Backup..."
if sqlite3 "$NQ_DB_PATH" ".backup '$DAILY_FILE'" 2>/dev/null; then
    if gzip -f "$DAILY_FILE"; then
        if check_backup_integrity "$DAILY_GZ" "Daily"; then
            log "  ✓ Daily gespeichert: $DAILY_GZ"
            sync_file_to_pi5 "$DAILY_GZ" "daily" || true
        else
            log "  ✗ Daily Integritätsfehler — verwerfe Backup"
            rm -f "$DAILY_GZ"
        fi
    else
        log "  ✗ Daily gzip fehlgeschlagen"
        rm -f "$DAILY_FILE"
    fi
else
    log "  ✗ Daily sqlite3 .backup fehlgeschlagen"
fi
cleanup_old "$DAILY_DIR" "$DAILY_KEEP" "Daily"

# --- Wöchentliches Backup (Vater, jeden Sonntag DOW=7) ---
if [ "$DOW" -eq 7 ]; then
    WEEK=$(date +%Y-W%V)
    WEEKLY_FILE="$WEEKLY_DIR/nq_${WEEK}.db"
    WEEKLY_GZ="${WEEKLY_FILE}.gz"
    LATEST_DAILY=$(ls -1t "$DAILY_DIR"/*.gz 2>/dev/null | head -n1 || true)

    log "Weekly: DOW=$DOW → erstelle Wochen-Backup (${WEEK})..."
    if [ -n "$LATEST_DAILY" ] && check_backup_integrity "$LATEST_DAILY" "Weekly-Quelle"; then
        cp "$LATEST_DAILY" "$WEEKLY_GZ"
        log "  ✓ Weekly gespeichert: $WEEKLY_GZ"
        sync_file_to_pi5 "$WEEKLY_GZ" "weekly" || true
    else
        log "  ✗ Weekly: kein valides Daily-Backup als Quelle"
    fi
    cleanup_old "$WEEKLY_DIR" "$WEEKLY_KEEP" "Weekly"
fi

# --- Monatliches Backup (Großvater, am 1. des Monats) ---
if [ "$DOM" = "01" ]; then
    PREV_MONTH=$(date -d "yesterday" +%Y-%m)
    PREV_DB="${BASE}/nq/db/nq_${PREV_MONTH}.db"
    MONTHLY_GZ="$MONTHLY_DIR/nq_${PREV_MONTH}.db.gz"

    log "Monthly: DOM=$DOM → erstelle Monats-Backup für ${PREV_MONTH}..."
    if [ -f "$PREV_DB" ]; then
        MONTHLY_TMP=$(mktemp /dev/shm/nq_monthly_XXXXXX)
        if sqlite3 "$PREV_DB" ".backup '$MONTHLY_TMP'" 2>/dev/null \
                && gzip -c "$MONTHLY_TMP" > "$MONTHLY_GZ"; then
            rm -f "$MONTHLY_TMP"
            if check_backup_integrity "$MONTHLY_GZ" "Monthly"; then
                log "  ✓ Monthly gespeichert: $MONTHLY_GZ"
                sync_file_to_pi5 "$MONTHLY_GZ" "monthly" || true
            else
                log "  ✗ Monthly Integritätsfehler — verwerfe Backup"
                rm -f "$MONTHLY_GZ"
            fi
        else
            rm -f "$MONTHLY_TMP"
            log "  ✗ Monthly Backup fehlgeschlagen"
        fi
    else
        log "  ✗ Monthly: Vormonats-DB nicht gefunden: $PREV_DB"
    fi
    cleanup_old "$MONTHLY_DIR" "$MONTHLY_KEEP" "Monthly"
fi

log "=== NQ GFS-Backup abgeschlossen ==="
