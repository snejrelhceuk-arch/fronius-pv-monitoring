#!/bin/bash
# =================================================================
# backup_tiered_dbs_gfs.sh — GFS-Backup der permanenten Stufe-2/3-DBs
# =================================================================
#
# Gleichbehandlung der Datenhaltungs-Stufen: Stufe 2 (monitoring.db, 5-min) und
# Stufe 3 (analysis.db, Tagesraster) erhalten dieselbe versionierte GFS-Sicherung
# (Sohn/Vater/Großvater/Urgroßvater, Integritätsprüfung, Pi5-Sync) wie Stufe 1
# (data.db, scripts/backup_db_gfs.sh).
#
# Beide DBs liegen permanent auf SD und werden 1×/Tag vom Tier-Sync
# (scripts/sync_tiered_daily.sh) fortgeschrieben. Backup via SQLite .backup.
#
# Cron (Primary):  0 3 * * *  /srv/pv-system/scripts/backup_tiered_dbs_gfs.sh
#
# Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md, scripts/backup_db_gfs.sh
# =================================================================

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$BASE/scripts/load_infra_env.sh" 2>/dev/null || true

# Nur auf dem Primary sichern (Failover ist Sync-Empfänger).
ROLE_FILE="${BASE}/.role"
if [ -f "$ROLE_FILE" ] && [ "$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')" = "failover" ]; then
    echo "$(date '+%F %T') Failover-Rolle → kein lokales Tier-Backup"
    exit 0
fi

# DB-Name → (Pfad, Pflichttabelle für den Integritätscheck)
declare -A DB_PATHS=(
  [monitoring]="${BASE}/monitoring.db"
  [analysis]="${BASE}/analysis.db"
)
declare -A DB_CHECK=(
  [monitoring]="data_5min_permanent"
  [analysis]="daily_data"
)

BACKUP_ROOT="${TIERED_BACKUP_BASE:-${BASE}/backup/tiered}"
LOG_FILE="${TIERED_LOG_FILE:-/tmp/tiered_db_backup_gfs.log}"
PI5_BACKUP_HOST="${PI5_BACKUP_HOST:-${PV_PI5_BACKUP_HOST:-}}"
PI5_BACKUP_BASE="${PI5_TIERED_BACKUP_BASE:-${PV_PI5_BACKUP_BASE:-/srv/pv-system/backup}/tiered}"

STATE_DIR="${STATE_DIR:-${BASE}/.state}"
SOHN_MIN_AGE_SEC=$((70 * 3600))   # ~3 Tage (wie data.db-GFS)
DAILY_KEEP=7; WEEKLY_KEEP=5; MONTHLY_KEEP=12; MIN_DB_SIZE=20000

mkdir -p "$STATE_DIR"
DATE=$(date +%Y-%m-%d); DOW=$(date +%u); DOM=$(date +%d)
MONTH=$(date +%Y-%m); YEAR=$(date +%Y)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

check_integrity() {  # $1=gz $2=label $3=pflichttabelle
    local gz_file="$1" label="$2" need="$3" tmp_check
    tmp_check=$(mktemp /dev/shm/tiered_backup_check_XXXXXX)
    if gunzip -c "$gz_file" > "$tmp_check" 2>/dev/null; then
        local integrity tbl
        integrity=$(sqlite3 "$tmp_check" "PRAGMA integrity_check;" 2>/dev/null || echo "FEHLER")
        tbl=$(sqlite3 "$tmp_check" \
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$need';" 2>/dev/null || echo 0)
        if [ "$integrity" = "ok" ] && [ "$tbl" -ge 1 ]; then
            log "  ✓ $label Integrität OK"; rm -f "$tmp_check"; return 0
        fi
        log "  ✗ $label Integrität: $integrity, $need=$tbl"
    else
        log "  ✗ $label gunzip fehlgeschlagen"
    fi
    rm -f "$tmp_check"; return 1
}

cleanup_old() {  # $1=dir $2=keep $3=label
    local dir="$1" keep="$2" label="$3" deleted=0
    while IFS= read -r old; do rm -f "$old"; deleted=$((deleted + 1)); done \
        < <(ls -1t "$dir"/*.gz 2>/dev/null | tail -n +$((keep + 1)))
    [ "$deleted" -gt 0 ] && log "  $label: $deleted alte Backups gelöscht (behalte $keep)"
    return 0
}

latest_backup_file() { ls -1t "$1"/*.gz 2>/dev/null | head -n1 || true; }

sync_to_pi5() {  # $1=file $2=name $3=tier
    local file_path="$1" name="$2" tier="$3"
    [ -f "$file_path" ] || return 0
    [ -n "$PI5_BACKUP_HOST" ] || return 0
    local remote_dir="${PI5_BACKUP_BASE}/${name}/${tier}"
    if ssh -o ConnectTimeout=10 "$PI5_BACKUP_HOST" "mkdir -p '$remote_dir'" >/dev/null 2>&1 \
       && rsync -az --timeout=60 "$file_path" "$PI5_BACKUP_HOST:$remote_dir/" >/dev/null 2>&1; then
        log "  ✓ Pi5 Sync: $(basename "$file_path") → ${name}/${tier}"
    else
        log "  ⚠ Pi5 Sync fehlgeschlagen: $(basename "$file_path")"
    fi
    return 0
}

backup_one() {  # $1=name
    local name="$1" db="${DB_PATHS[$1]}" need="${DB_CHECK[$1]}"
    if [ ! -f "$db" ]; then log "FEHLER: $name-DB nicht gefunden: $db"; return 0; fi
    local sz; sz=$(stat -c%s "$db" 2>/dev/null || echo 0)
    if [ "$sz" -lt "$MIN_DB_SIZE" ]; then log "FEHLER: $name-DB zu klein ($sz B)"; return 0; fi
    log "=== $name-DB ($(numfmt --to=iec "$sz")) ==="

    local base="$BACKUP_ROOT/$name"
    local daily_dir="$base/daily" weekly_dir="$base/weekly" monthly_dir="$base/monthly" yearly_dir="$base/yearly"
    mkdir -p "$daily_dir" "$weekly_dir" "$monthly_dir" "$yearly_dir"
    local stamp="${STATE_DIR}/backup_tiered_${name}_sohn_last_ts"

    local run_sohn=1
    if [ -f "$stamp" ]; then
        local last; last=$(cat "$stamp" 2>/dev/null || echo 0)
        [[ "$last" =~ ^[0-9]+$ ]] && [ "$(( $(date +%s) - last ))" -lt "$SOHN_MIN_AGE_SEC" ] && run_sohn=0
    fi

    local daily_gz=""
    if [ "$run_sohn" = "1" ]; then
        local daily_file="$daily_dir/${name}_${DATE}.db"
        if sqlite3 "$db" ".backup '$daily_file'"; then
            gzip -f "$daily_file"; daily_gz="${daily_file}.gz"
            log "  Sohn: $(basename "$daily_gz") ($(numfmt --to=iec "$(stat -c%s "$daily_gz")"))"
            check_integrity "$daily_gz" "Sohn" "$need" || true
            date +%s > "$stamp"
            sync_to_pi5 "$daily_gz" "$name" "daily"
        else
            log "FEHLER: .backup $name fehlgeschlagen"; return 0
        fi
    else
        daily_gz=$(latest_backup_file "$daily_dir")
        log "  Sohn: übersprungen (Intervall 3 T). Letztes: ${daily_gz:-keins}"
    fi
    cleanup_old "$daily_dir" "$DAILY_KEEP" "Sohn"
    { [ -z "$daily_gz" ] || [ ! -f "$daily_gz" ]; } && daily_gz=$(latest_backup_file "$daily_dir")
    [ -z "$daily_gz" ] && { log "  Kein Sohn-Backup → Vater/… nicht möglich"; return 0; }

    if [ "$DOW" = "7" ]; then
        local wf="$weekly_dir/${name}_$(date +%Y-W%V).db.gz"
        [ -f "$wf" ] || { cp "$daily_gz" "$wf"; check_integrity "$wf" "Vater" "$need" || true; sync_to_pi5 "$wf" "$name" "weekly"; }
        cleanup_old "$weekly_dir" "$WEEKLY_KEEP" "Vater"
    fi
    if [ "$DOM" = "01" ]; then
        local mf="$monthly_dir/${name}_${MONTH}.db.gz"
        [ -f "$mf" ] || { cp "$daily_gz" "$mf"; check_integrity "$mf" "Großvater" "$need" || true; sync_to_pi5 "$mf" "$name" "monthly"; }
        cleanup_old "$monthly_dir" "$MONTHLY_KEEP" "Großvater"
    fi
    if [ "$DOM" = "01" ] && [ "$(date +%m)" = "01" ]; then
        local yf="$yearly_dir/${name}_${YEAR}.db.gz"
        [ -f "$yf" ] || { cp "$daily_gz" "$yf"; check_integrity "$yf" "Urgroßvater" "$need" || true; sync_to_pi5 "$yf" "$name" "yearly"; }
    fi
}

log "=== Tier-GFS-Backup gestartet (${DATE}, DOW=${DOW}) ==="
for name in monitoring analysis; do backup_one "$name"; done
log "Speicher: $(du -sh "$BACKUP_ROOT" 2>/dev/null | awk '{print $1}')"
log "=== Tier-GFS-Backup abgeschlossen ==="
