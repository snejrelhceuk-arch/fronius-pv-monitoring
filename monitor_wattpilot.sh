#!/bin/bash
# Cron-Job: Überwacht wattpilot_collector.py auf Duplikate und Ausfälle
# Empfohlen: */5 * * * * /srv/pv-system/monitor_wattpilot.sh
#
# Prüft:
#   1. Prozess läuft (falls nicht → systemd-Restart)
#   2. Keine Duplikate (falls doch → kill + systemd-Restart)
#   3. Frische Daten in DB (falls >5min alt → Warnung loggen)

BASE_DIR="/srv/pv-system"

# --- Role Guard: Auf Failover-Host nichts tun ---
source "${BASE_DIR}/scripts/role_guard.sh" 2>/dev/null || exit 0

LOG_FILE="/tmp/wattpilot_monitor.log"
DB_PATH="/dev/shm/fronius_data.db"
SERVICE_NAME="pv-wattpilot.service"
MAX_DATA_AGE=300  # Maximal 5 Minuten alte Daten akzeptabel

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log_msg() {
    echo "$(timestamp) $1" >> "$LOG_FILE"
}

# --- 1. Prozess-Check ---
PROCESS_COUNT=$(pgrep -fc "python3.*wattpilot_collector.py")

if [ "$PROCESS_COUNT" -gt 1 ]; then
    log_msg "❌ ALARM: $PROCESS_COUNT wattpilot_collector.py Prozesse!"
    ps aux | grep "[w]attpilot_collector.py" >> "$LOG_FILE"
    
    # Alle stoppen, systemd startet einen einzelnen neu
    log_msg "→ Stoppe alle Wattpilot-Collector, systemd startet neu..."
    pkill -9 -f "python3.*wattpilot_collector.py"
    rm -f "${BASE_DIR}/wattpilot_collector.pid"
    sleep 2
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null
    
    sleep 5
    NEW_COUNT=$(pgrep -fc "python3.*wattpilot_collector.py")
    if [ "$NEW_COUNT" -eq 1 ]; then
        log_msg "✓ Einzelner Prozess wiederhergestellt"
    else
        log_msg "⚠️  Restart-Ergebnis: $NEW_COUNT Prozesse"
    fi
    
elif [ "$PROCESS_COUNT" -eq 0 ]; then
    log_msg "⚠️  WARNUNG: Kein wattpilot_collector.py läuft!"
    
    # Stale PID-File aufräumen
    if [ -f "${BASE_DIR}/wattpilot_collector.pid" ]; then
        OLD_PID=$(cat "${BASE_DIR}/wattpilot_collector.pid" 2>/dev/null)
        if ! kill -0 "$OLD_PID" 2>/dev/null; then
            log_msg "→ Entferne verwaistes PID-File (PID $OLD_PID)"
            rm -f "${BASE_DIR}/wattpilot_collector.pid"
        fi
    fi
    
    # Systemd-Restart versuchen
    log_msg "→ Starte $SERVICE_NAME neu..."
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null
    
    sleep 5
    NEW_COUNT=$(pgrep -fc "python3.*wattpilot_collector.py")
    if [ "$NEW_COUNT" -ge 1 ]; then
        log_msg "✓ Wattpilot-Collector wiederhergestellt"
    else
        log_msg "❌ Systemd-Restart fehlgeschlagen!"
    fi
fi

# --- 2. Daten-Frische prüfen ---
if [ -f "$DB_PATH" ] && [ "$PROCESS_COUNT" -ge 1 ]; then
    NOW=$(date +%s)
    LATEST_TS=$(sqlite3 "$DB_PATH" "SELECT CAST(MAX(ts) AS INTEGER) FROM wattpilot_readings" 2>/dev/null)
    
    if [ -n "$LATEST_TS" ] && [ "$LATEST_TS" -gt 0 ] 2>/dev/null; then
        AGE=$((NOW - LATEST_TS))
        
        if [ "$AGE" -gt "$MAX_DATA_AGE" ]; then
            log_msg "⚠️  Wattpilot-Daten veraltet: ${AGE}s alt (Limit: ${MAX_DATA_AGE}s)"
            log_msg "   Mögliche Ursache: Wattpilot im WLAN nicht erreichbar"
        fi
    fi
fi

# --- 3. Log-Rotation (letzte 200 Zeilen behalten) ---
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 200 ]; then
    tail -200 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
