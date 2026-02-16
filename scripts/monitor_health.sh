#!/bin/bash
# =================================================================
# Cron-Job Monitoring für Fronius PV-Monitoring
# Prüft: Services, Datenaktualität, Aggregation, Disk-Space
#
# Exit-Code:
#   0 = alles OK
#   1 = Warnung(en) gefunden
#   2 = Kritischer Fehler
#
# Cron: */15 * * * * /srv/pv-system/scripts/monitor_health.sh
# =================================================================

set -uo pipefail

DB_PATH="/srv/pv-system/data.db"
LOG_FILE="/tmp/monitor_health.log"
ALERT_FILE="/tmp/monitor_health_alerts.log"

# Schwellwerte
MAX_RAW_AGE_SEC=120        # raw_data nicht älter als 2 Minuten
MAX_1MIN_AGE_SEC=180       # data_1min nicht älter als 3 Minuten
MAX_15MIN_AGE_SEC=1200     # data_15min nicht älter als 20 Minuten
DISK_WARN_PERCENT=90       # Warnung ab 90% Disk-Nutzung
DB_SIZE_WARN_MB=500        # Warnung wenn DB > 500MB

ERRORS=0
WARNINGS=0
NOW=$(date +%s)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

alert() {
    local level="$1"
    local msg="$2"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $msg" | tee -a "$LOG_FILE" >> "$ALERT_FILE"
    if [ "$level" = "KRITISCH" ]; then
        ERRORS=$((ERRORS + 1))
    else
        WARNINGS=$((WARNINGS + 1))
    fi
}

ok() {
    log "[OK] $1"
}

# Logfile Rotation (maximal 1000 Zeilen)
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE" 2>/dev/null)" -gt 1000 ]; then
    tail -500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

log "=== Health-Check gestartet ==="

# --- 1. Service-Check ---
if systemctl is-active --quiet modbus-collector.service 2>/dev/null; then
    ok "modbus-collector.service läuft"
else
    alert "KRITISCH" "modbus-collector.service ist NICHT aktiv!"
fi

if systemctl is-active --quiet pv-web.service 2>/dev/null; then
    ok "pv-web.service läuft"
else
    alert "WARNUNG" "pv-web.service ist nicht aktiv"
fi

# --- 2. Datenaktualität ---
if [ -f "$DB_PATH" ]; then
    # raw_data: letzter Eintrag
    LAST_RAW=$(sqlite3 "$DB_PATH" "SELECT CAST(MAX(ts) AS INTEGER) FROM raw_data;" 2>/dev/null || echo 0)
    if [ -n "$LAST_RAW" ] && [ "$LAST_RAW" != "" ] && [ "$LAST_RAW" != "0" ]; then
        RAW_AGE=$((NOW - LAST_RAW))
        if [ "$RAW_AGE" -lt "$MAX_RAW_AGE_SEC" ]; then
            ok "raw_data aktuell (${RAW_AGE}s alt)"
        else
            alert "KRITISCH" "raw_data veraltet: letzter Eintrag vor ${RAW_AGE}s (Limit: ${MAX_RAW_AGE_SEC}s)"
        fi
    else
        alert "KRITISCH" "raw_data ist LEER oder nicht lesbar!"
    fi

    # data_1min: letzter Eintrag
    LAST_1MIN=$(sqlite3 "$DB_PATH" "SELECT CAST(MAX(ts) AS INTEGER) FROM data_1min;" 2>/dev/null || echo 0)
    if [ -n "$LAST_1MIN" ] && [ "$LAST_1MIN" != "" ] && [ "$LAST_1MIN" != "0" ]; then
        AGE_1MIN=$((NOW - LAST_1MIN))
        if [ "$AGE_1MIN" -lt "$MAX_1MIN_AGE_SEC" ]; then
            ok "data_1min aktuell (${AGE_1MIN}s alt)"
        else
            alert "WARNUNG" "data_1min veraltet: letzter Eintrag vor ${AGE_1MIN}s (Limit: ${MAX_1MIN_AGE_SEC}s)"
        fi
    fi

    # data_15min: letzter Eintrag
    LAST_15MIN=$(sqlite3 "$DB_PATH" "SELECT CAST(MAX(ts) AS INTEGER) FROM data_15min;" 2>/dev/null || echo 0)
    if [ -n "$LAST_15MIN" ] && [ "$LAST_15MIN" != "" ] && [ "$LAST_15MIN" != "0" ]; then
        AGE_15MIN=$((NOW - LAST_15MIN))
        if [ "$AGE_15MIN" -lt "$MAX_15MIN_AGE_SEC" ]; then
            ok "data_15min aktuell (${AGE_15MIN}s alt)"
        else
            alert "WARNUNG" "data_15min veraltet: letzter Eintrag vor ${AGE_15MIN}s (Limit: ${MAX_15MIN_AGE_SEC}s)"
        fi
    fi

    # --- 3. Aggregation-Lücken (letzte Stunde) ---
    HOUR_AGO=$((NOW - 3600))
    GAP_COUNT=$(sqlite3 "$DB_PATH" "
        SELECT COUNT(*) FROM (
            SELECT ts, 
                   LEAD(ts) OVER (ORDER BY ts) - ts as diff
            FROM raw_data 
            WHERE ts > $HOUR_AGO
        ) WHERE diff > 30;" 2>/dev/null || echo -1)
    
    if [ "$GAP_COUNT" = "0" ]; then
        ok "Keine Lücken >30s in raw_data (letzte Stunde)"
    elif [ "$GAP_COUNT" -gt 0 ]; then
        alert "WARNUNG" "${GAP_COUNT} Lücken >30s in raw_data (letzte Stunde)"
    fi

    # --- 4. DB-Größe ---
    DB_SIZE_BYTES=$(stat -c%s "$DB_PATH" 2>/dev/null || echo 0)
    DB_SIZE_MB=$((DB_SIZE_BYTES / 1024 / 1024))
    if [ "$DB_SIZE_MB" -lt "$DB_SIZE_WARN_MB" ]; then
        ok "DB-Größe: ${DB_SIZE_MB} MB"
    else
        alert "WARNUNG" "DB-Größe: ${DB_SIZE_MB} MB (Limit: ${DB_SIZE_WARN_MB} MB)"
    fi
else
    alert "KRITISCH" "Datenbank nicht gefunden: $DB_PATH"
fi

# --- 5. Disk-Space ---
DISK_USAGE=$(df --output=pcent /home/user 2>/dev/null | tail -1 | tr -d ' %')
if [ -n "$DISK_USAGE" ] && [ "$DISK_USAGE" -lt "$DISK_WARN_PERCENT" ]; then
    ok "Disk-Nutzung: ${DISK_USAGE}%"
else
    alert "WARNUNG" "Disk-Nutzung: ${DISK_USAGE}% (Limit: ${DISK_WARN_PERCENT}%)"
fi

# --- 6. Cron-Log Fehler prüfen (letzte 15 Min) ---
for logfile in /tmp/aggregate.log /tmp/aggregate_1min.log /tmp/aggregate_daily.log /tmp/aggregate_monthly.log /tmp/aggregate_statistics.log; do
    if [ -f "$logfile" ]; then
        # Suche nach Fehlern in den letzten 20 Zeilen
        RECENT_ERRORS=$(tail -20 "$logfile" 2>/dev/null | grep -ci "error\|traceback\|exception\|fehler" || true)
        if [ "$RECENT_ERRORS" -gt 0 ]; then
            BASENAME=$(basename "$logfile")
            alert "WARNUNG" "Fehler in $BASENAME (${RECENT_ERRORS} Treffer in letzten 20 Zeilen)"
        fi
    fi
done

# --- 7. Backup-Aktualität ---
LATEST_BACKUP=$(ls -1t /srv/pv-system/backup/db/daily/*.gz 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ]; then
    BACKUP_AGE_HOURS=$(( (NOW - $(stat -c%Y "$LATEST_BACKUP")) / 3600 ))
    if [ "$BACKUP_AGE_HOURS" -lt 26 ]; then
        ok "Letztes Backup: vor ${BACKUP_AGE_HOURS}h"
    else
        alert "WARNUNG" "Letztes Backup vor ${BACKUP_AGE_HOURS}h (>24h!)"
    fi
else
    alert "WARNUNG" "Kein DB-Backup gefunden!"
fi

# --- Zusammenfassung ---
if [ "$ERRORS" -gt 0 ]; then
    log "=== ERGEBNIS: ${ERRORS} KRITISCH, ${WARNINGS} Warnungen ==="
    exit 2
elif [ "$WARNINGS" -gt 0 ]; then
    log "=== ERGEBNIS: ${WARNINGS} Warnungen ==="
    exit 1
else
    log "=== ERGEBNIS: Alles OK ✓ ==="
    exit 0
fi
