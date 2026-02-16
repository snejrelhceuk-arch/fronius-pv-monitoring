#!/bin/bash
# Web-Service Monitoring und Auto-Restart
# Prüft regelmäßig die Web-API und startet sie neu bei Blockaden

LOG_FILE="/srv/pv-system/web_service_monitor.log"
API_URL="http://192.0.2.195:8000/api/realtime_smart?hours=1"
TIMEOUT=5

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_api() {
    # Teste API-Antwort mit Timeout
    response=$(curl -s -m $TIMEOUT "$API_URL" 2>/dev/null)
    
    if [ -z "$response" ]; then
        return 1  # Keine Antwort
    fi
    
    # Prüfe ob JSON gültig ist
    echo "$response" | python3 -c "import json, sys; json.load(sys.stdin)" 2>/dev/null
    return $?
}

restart_service() {
    log_message "WARNUNG: Web-API antwortet nicht - starte Service neu..."
    sudo systemctl restart pv-web.service
    sleep 5
    
    if check_api; then
        log_message "OK: Service erfolgreich neugestartet"
        return 0
    else
        log_message "FEHLER: Service-Neustart fehlgeschlagen!"
        return 1
    fi
}

# Hauptschleife
log_message "=== Web-Service Monitor gestartet ==="

while true; do
    if check_api; then
        log_message "OK: Web-API antwortet normal"
    else
        log_message "FEHLER: Web-API blockiert oder antwortet nicht"
        restart_service
    fi
    
    # Warte 5 Minuten bis zur nächsten Prüfung
    sleep 300
done
