#!/bin/bash
# =================================================================
# GFS-Backup (Sohn-Vater-Großvater) für die permanente STATS-DB
# =================================================================
#
# Zweck:
#   Gleichbehandlung der Datenhaltungs-Stufen: Stufe 2 (data_stats.db =
#   data_5min_permanent + fritzdect/wattpilot_5min_permanent) erhält dieselbe
#   versionierte GFS-Sicherung wie Stufe 1 (data.db, scripts/backup_db_gfs.sh).
#   Bisher wurde data_stats.db nur per rsync gespiegelt (keine Historie).
#
# Quelle:
#   data_stats.db liegt bereits auf SD (permanent, 1×/Tag geschrieben vom
#   Archiv-Job scripts/stats_archive_daily.sh). Backup via SQLite .backup.
#
# Cron (Primary):  0 3 * * *  /srv/pv-system/scripts/backup_stats_db_gfs.sh
#   (parallel zum data.db-GFS-Backup, gleiche Kadenz & Pi5-Sync)
#
# Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md, scripts/backup_db_gfs.sh
# =================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$BASE/scripts/load_infra_env.sh" 2>/dev/null || true

# --- Nur auf dem Primary sichern (Failover ist Sync-Empfänger) ---
ROLE_FILE="${BASE}/.role"
if [ -f "$ROLE_FILE" ] && [ "$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')" = "failover" ]; then
    echo "$(date '+%F %T') Failover-Rolle → kein lokales STATS-Backup"
    exit 0
fi

STATS_DB="${STATS_DB_PATH:-${BASE}/data_stats.db}"
BACKUP_BASE="${STATS_BACKUP_BASE:-${BASE}/backup/stats}"
LOG_FILE="${STATS_LOG_FILE:-/tmp/stats_db_backup_gfs.log}"

PI5_BACKUP_HOST="${PI5_BACKUP_HOST:-${PV_PI5_BACKUP_HOST:-}}"
PI5_BACKUP_BASE="${PI5_STATS_BACKUP_BASE:-${PV_PI5_BACKUP_BASE:-/srv/pv-system/backup}/stats}"

STATE_DIR="${STATE_DIR:-${BASE}/.state}"
SOHN_STAMP_FILE="${STATE_DIR}/backup_stats_gfs_sohn_last_ts"
SOHN_MIN_AGE_SEC=$((70 * 3600))   # ~3 Tage (wie data.db-GFS)

DAILY_KEEP=7
WEEKLY_KEEP=5
MONTHLY_KEEP=12
MIN_DB_SIZE=50000

DAILY_DIR="$BACKUP_BASE/daily"
WEEKLY_DIR="$BACKUP_BASE/weekly"
MONTHLY_DIR="$BACKUP_BASE/monthly"
YEARLY_DIR="$BACKUP_BASE/yearly"
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR" "$MONTHLY_DIR" "$YEARLY_DIR" "$STATE_DIR"

DATE=$(date +%Y-%m-%d); DOW=$(date +%u); DOM=$(date +%d)
MONTH=$(date +%Y-%m); YEAR=$(date +%Y)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

check_integrity() {
    local gz_file="$1" label="$2" tmp_check
    tmp_check=$(mktemp /dev/shm/stats_backup_check_XXXXXX)
    if gunzip -c "$gz_file" > "$tmp_check" 2>/dev/null; then
        local integrity tbl
        integrity=$(sqlite3 "$tmp_check" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
        tbl=$(sqlite3 "$tmp_check" \
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='data_5min_permanent';" \
            2>/dev/null || echo "0")
        if [ "$integrity" = "ok" ] && [ "$tbl" -ge 1 ]; then
            log "  ✓ $label Integrität OK"
            rm -f "$tmp_check"; return 0
        fi
        log "  ✗ $label Integrität: $integrity, data_5min_permanent=$tbl"
    else
        log "  ✗ $label gunzip fehlgeschlagen"
    fi
    rm -f "$tmp_check"; return 1
}

cleanup_old() {
    local dir="$1" keep="$2" label="$3" deleted=0
    while IFS= read -r old; do rm -f "$old"; deleted=$((deleted + 1)); done \
        < <(ls -1t "$dir"/*.gz 2>/dev/null | tail -n +$((keep + 1)))
    [ "$deleted" -gt 0 ] && log "  $label: $deleted alte Backups gelöscht (behalte $keep)"
    return 0
}

latest_backup_file() { ls -1t "$1"/*.gz 2>/dev/null | head -n1 || true; }

sync_to_pi5() {
    local file_path="$1" tier="$2"
    [ -f "$file_path" ] || return 1
    [ -n "$PI5_BACKUP_HOST" ] || return 0
    local remote_dir="${PI5_BACKUP_BASE}/${tier}"
    if ssh -o ConnectTimeout=10 "$PI5_BACKUP_HOST" "mkdir -p '$remote_dir'" >/dev/null 2>&1 \
       && rsync -az --timeout=60 "$file_path" "$PI5_BACKUP_HOST:$remote_dir/" >/dev/null 2>&1; then
        log "  ✓ Pi5 Sync: $(basename "$file_path") → $tier"
    else
        log "  ⚠ Pi5 Sync fehlgeschlagen: $(basename "$file_path")"
    fi
    return 0
}

should_run_sohn() {
    [ -f "$SOHN_STAMP_FILE" ] || return 0
    local last; last=$(cat "$SOHN_STAMP_FILE" 2>/dev/null || echo 0)
    [[ "$last" =~ ^[0-9]+$ ]] || return 0
    [ "$(( $(date +%s) - last ))" -ge "$SOHN_MIN_AGE_SEC" ]
}

log "=== STATS-GFS-Backup gestartet (${DATE}, DOW=${DOW}) ==="

if [ ! -f "$STATS_DB" ]; then
    log "FEHLER: STATS-DB nicht gefunden: $STATS_DB"; exit 1
fi
DB_SIZE=$(stat -c%s "$STATS_DB" 2>/dev/null || echo 0)
if [ "$DB_SIZE" -lt "$MIN_DB_SIZE" ]; then
    log "FEHLER: STATS-DB zu klein ($DB_SIZE Bytes)"; exit 1
fi
log "STATS-DB-Größe: $(numfmt --to=iec "$DB_SIZE")"

DAILY_GZ=""
DAILY_FILE="$DAILY_DIR/stats_${DATE}.db"
if should_run_sohn; then
    log "Sohn: Erstelle 3-Tage-Backup aus STATS-DB..."
    if sqlite3 "$STATS_DB" ".backup '$DAILY_FILE'"; then
        gzip -f "$DAILY_FILE"
        DAILY_GZ="${DAILY_FILE}.gz"
        log "  Sohn: $DAILY_GZ ($(numfmt --to=iec "$(stat -c%s "$DAILY_GZ")"))"
        check_integrity "$DAILY_GZ" "Sohn" || true
        date +%s > "$SOHN_STAMP_FILE"
        sync_to_pi5 "$DAILY_GZ" "daily"
    else
        log "FEHLER: SQLite .backup fehlgeschlagen!"; exit 1
    fi
else
    DAILY_GZ=$(latest_backup_file "$DAILY_DIR")
    log "Sohn: übersprungen (Intervall 3 Tage). Letztes: ${DAILY_GZ:-keins}"
fi

cleanup_old "$DAILY_DIR" "$DAILY_KEEP" "Sohn"
[ -z "$DAILY_GZ" ] || [ ! -f "$DAILY_GZ" ] && DAILY_GZ=$(latest_backup_file "$DAILY_DIR")
if [ -z "$DAILY_GZ" ] || [ ! -f "$DAILY_GZ" ]; then
    log "FEHLER: Kein gültiges Sohn-Backup — Vater/Großvater/Urgroßvater nicht möglich"; exit 1
fi

if [ "$DOW" = "7" ]; then
    WEEKLY_FILE="$WEEKLY_DIR/stats_$(date +%Y-W%V).db.gz"
    if [ ! -f "$WEEKLY_FILE" ]; then
        log "Vater: wöchentliches Backup (KW $(date +%V))..."
        cp "$DAILY_GZ" "$WEEKLY_FILE"; check_integrity "$WEEKLY_FILE" "Vater" || true
        sync_to_pi5 "$WEEKLY_FILE" "weekly"
    fi
    cleanup_old "$WEEKLY_DIR" "$WEEKLY_KEEP" "Vater"
fi

if [ "$DOM" = "01" ]; then
    MONTHLY_FILE="$MONTHLY_DIR/stats_${MONTH}.db.gz"
    if [ ! -f "$MONTHLY_FILE" ]; then
        log "Großvater: monatliches Backup..."
        cp "$DAILY_GZ" "$MONTHLY_FILE"; check_integrity "$MONTHLY_FILE" "Großvater" || true
        sync_to_pi5 "$MONTHLY_FILE" "monthly"
    fi
    cleanup_old "$MONTHLY_DIR" "$MONTHLY_KEEP" "Großvater"
fi

if [ "$DOM" = "01" ] && [ "$(date +%m)" = "01" ]; then
    YEARLY_FILE="$YEARLY_DIR/stats_${YEAR}.db.gz"
    if [ ! -f "$YEARLY_FILE" ]; then
        log "Urgroßvater: jährliches Backup..."
        cp "$DAILY_GZ" "$YEARLY_FILE"; check_integrity "$YEARLY_FILE" "Urgroßvater" || true
        sync_to_pi5 "$YEARLY_FILE" "yearly"
    fi
fi

log "Speicher: $(du -sh "$BACKUP_BASE" 2>/dev/null | awk '{print $1}')"
log "=== STATS-GFS-Backup abgeschlossen ==="
