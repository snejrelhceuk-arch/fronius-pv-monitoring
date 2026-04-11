#!/bin/bash
# Cron-Job: Überwacht pv-steuerbox.service und den HTTPS-Entry der Steuerbox
# Empfohlen: */5 * * * * <BASE_DIR>/monitor_steuerbox.sh

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Role Guard: Auf Failover-Host nichts tun ---
source "${BASE_DIR}/scripts/role_guard.sh" 2>/dev/null || exit 0

LOG_FILE="/tmp/steuerbox_monitor.log"
SERVICE_NAME="pv-steuerbox.service"
BACKEND_URL="http://127.0.0.1:11934/api/ops/health"
FRONTEND_URL="https://127.0.0.1:11933/api/ops/health"

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log_msg() {
    echo "$(timestamp) $1" >> "$LOG_FILE"
}

http_code() {
    local url="$1"
    local extra_args=()
    if [[ "$url" == https:* ]]; then
        extra_args=(-k)
    fi
    curl "${extra_args[@]}" -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo 000
}

restart_service() {
    log_msg "→ Starte ${SERVICE_NAME} neu..."
    sudo systemctl restart "$SERVICE_NAME" 2>/dev/null
    sleep 5
}

service_state=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)
backend_status=$(http_code "$BACKEND_URL")
frontend_status=$(http_code "$FRONTEND_URL")

if [ "$service_state" != "active" ]; then
    log_msg "⚠️  WARNUNG: ${SERVICE_NAME} ist ${service_state}"
    restart_service
    service_state=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)
    backend_status=$(http_code "$BACKEND_URL")
    frontend_status=$(http_code "$FRONTEND_URL")
fi

if [ "$backend_status" != "200" ]; then
    log_msg "❌ ALARM: Steuerbox-Backend liefert HTTP ${backend_status}"
    restart_service
    service_state=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo unknown)
    backend_status=$(http_code "$BACKEND_URL")
    frontend_status=$(http_code "$FRONTEND_URL")
fi

if [ "$frontend_status" != "200" ]; then
    if [ "$backend_status" = "200" ]; then
        nginx_state=$(systemctl is-active nginx 2>/dev/null || echo unknown)
        log_msg "⚠️  Frontend-Check fehlgeschlagen: HTTPS liefert ${frontend_status}, Backend ok, nginx=${nginx_state}"
    else
        log_msg "❌ Frontend-Check fehlgeschlagen: HTTPS liefert ${frontend_status}, Backend=${backend_status}"
    fi
fi

if [ "$service_state" = "active" ] && [ "$backend_status" = "200" ] && [ "$frontend_status" = "200" ]; then
    if [ ! -f "$LOG_FILE" ] || [ "$(wc -l < "$LOG_FILE")" -eq 0 ]; then
        log_msg "✓ Monitoring aktiv, Steuerbox läuft normal"
    fi
fi

if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 200 ]; then
    tail -200 "$LOG_FILE" > "$LOG_FILE.tmp"
    mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
