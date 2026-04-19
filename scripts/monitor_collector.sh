#!/bin/bash
# Cron-Job: Überwacht collector.py auf Duplikate
# Empfohlen: */5 * * * * /srv/pv-system/monitor_collector.sh

# --- Role Guard: Auf Failover-Host nichts tun ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/scripts/role_guard.sh" 2>/dev/null || exit 0

LOG_FILE="/tmp/collector_monitor.log"
WP_PROTOCOL_FILE="${SCRIPT_DIR}/logs/wp_netzbetreiber_leistung.csv"
WP_PROTOCOL_MAX_AGE_S=600
# Nur collector.py zählen, NICHT wattpilot_collector.py
# Pattern: 'python3 ' gefolgt von optionalem Pfad + 'collector.py' (kein _ davor)
PROCESS_COUNT=$(pgrep -fc "python3 (./)?collector\.py" || true)

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

# Prüfe Prozess-Anzahl
if [ "$PROCESS_COUNT" -gt 1 ]; then
    echo "$(timestamp) ❌ ALARM: $PROCESS_COUNT collector.py Prozesse!" >> "$LOG_FILE"
    ps aux | grep "[p]ython3.*[^_]collector.py" >> "$LOG_FILE"
    
    # Stoppe nur collector.py (nicht wattpilot_collector.py) und lasse systemd neu starten
    echo "$(timestamp) → Stoppe collector.py Prozesse, systemd startet neu..." >> "$LOG_FILE"
    pkill -9 -f "python3 (./)?collector\.py" || true
    sleep 2
    
    # Prüfe ob systemd automatisch neugestartet hat
    NEW_COUNT=$(pgrep -fc "python3 (./)?collector\.py" || true)
    if [ "$NEW_COUNT" -eq 1 ]; then
        echo "$(timestamp) ✓ Einzelner Prozess wiederhergestellt" >> "$LOG_FILE"
    else
        echo "$(timestamp) ⚠️  Systemd-Restart fehlgeschlagen: $NEW_COUNT Prozesse" >> "$LOG_FILE"
    fi
    
elif [ "$PROCESS_COUNT" -eq 0 ]; then
    echo "$(timestamp) ⚠️  WARNUNG: Kein collector.py läuft!" >> "$LOG_FILE"
    echo "$(timestamp) → Systemd sollte automatisch neustarten..." >> "$LOG_FILE"
    
else
    # Normal: Einzelner Prozess (nur bei erstem Lauf loggen)
    if [ ! -f "$LOG_FILE" ] || [ $(wc -l < "$LOG_FILE") -eq 0 ]; then
        echo "$(timestamp) ✓ Monitoring aktiv, collector läuft normal" >> "$LOG_FILE"
    fi
fi

# Prüfe dauerhaftes WP-Netzbetreiber-Protokoll
NOW_EPOCH=$(date +%s)
if [ ! -f "$WP_PROTOCOL_FILE" ]; then
    echo "$(timestamp) ⚠️  WARNUNG: WP-Protokolldatei fehlt: $WP_PROTOCOL_FILE" >> "$LOG_FILE"
else
    LAST_LINE=$(tail -1 "$WP_PROTOCOL_FILE" 2>/dev/null)
    LAST_TS=$(echo "$LAST_LINE" | cut -d',' -f1)
    LAST_MAX_W=$(echo "$LAST_LINE" | cut -d',' -f3)
    LAST_LIMIT_OK=$(echo "$LAST_LINE" | cut -d',' -f5)

    if [[ "$LAST_TS" =~ ^[0-9]+$ ]]; then
        AGE_S=$((NOW_EPOCH - LAST_TS))
        if [ "$AGE_S" -gt "$WP_PROTOCOL_MAX_AGE_S" ]; then
            echo "$(timestamp) ⚠️  WARNUNG: WP-Protokoll veraltet (${AGE_S}s alt, Limit ${WP_PROTOCOL_MAX_AGE_S}s)" >> "$LOG_FILE"
        fi

        if [ "$LAST_LIMIT_OK" = "0" ]; then
            echo "$(timestamp) ❌ ALARM: WP-Leistungsgrenze verletzt (letzter Maxwert ${LAST_MAX_W} W)" >> "$LOG_FILE"
        fi
    fi
fi

# Log-Rotation (behalte nur letzte 100 Zeilen)
if [ -f "$LOG_FILE" ] && [ $(wc -l < "$LOG_FILE") -gt 100 ]; then
    tail -100 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
