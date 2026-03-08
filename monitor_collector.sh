#!/bin/bash
# Cron-Job: Überwacht collector.py auf Duplikate
# Empfohlen: */5 * * * * /home/admin/Dokumente/PVAnlage/pv-system/monitor_collector.sh

# --- Role Guard: Auf Failover-Host nichts tun ---
source /home/admin/Dokumente/PVAnlage/pv-system/scripts/role_guard.sh 2>/dev/null || exit 0

LOG_FILE="/tmp/collector_monitor.log"
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

# Log-Rotation (behalte nur letzte 100 Zeilen)
if [ -f "$LOG_FILE" ] && [ $(wc -l < "$LOG_FILE") -gt 100 ]; then
    tail -100 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
