#!/bin/bash
# ========================================
# Steuerbox Neustart Script
# ========================================
# Beendet alte Steuerbox-Instanzen sauber und startet
# alle für die Steuerbox nötigen Dienste neu:
#   1) pv-steuerbox.service (Backend, Port 11934)
#   2) nginx.service        (HTTPS-Proxy, Port 11933)
# ========================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

source "$SCRIPT_DIR/role_guard.sh" 2>/dev/null || {
    echo "Steuerbox-Neustart nur auf role=primary erlaubt."
    exit 0
}

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

STEUERBOX_SERVICE="pv-steuerbox.service"
PROXY_SERVICE="nginx.service"
BACKEND_URL="http://127.0.0.1:11934/api/ops/health"
FRONTEND_URL="https://127.0.0.1:11933/api/ops/health"

echo "========================================="
echo "Steuerbox Neustart (Backend + Proxy)"
echo "========================================="
echo ""

if ! systemctl is-enabled "$STEUERBOX_SERVICE" >/dev/null 2>&1; then
    echo -e "${RED}✗ FEHLER: ${STEUERBOX_SERVICE} ist nicht enabled.${NC}"
    echo "  Aktivieren mit: sudo systemctl enable ${STEUERBOX_SERVICE}"
    exit 1
fi

echo "STEP 1: Stoppe ${STEUERBOX_SERVICE} sauber..."
if systemctl is-active --quiet "$STEUERBOX_SERVICE"; then
    sudo systemctl stop "$STEUERBOX_SERVICE"
    echo -e "${GREEN}✓ ${STEUERBOX_SERVICE} gestoppt${NC}"
else
    echo -e "${YELLOW}ℹ ${STEUERBOX_SERVICE} war bereits inaktiv${NC}"
fi

echo ""
echo "STEP 2: Beende alte manuelle Steuerbox-Prozesse..."
STALE_PIDS="$(pgrep -f 'python3 .*steuerbox(\.steuerbox_api|/steuerbox_api\.py)' || true)"
if [ -n "$STALE_PIDS" ]; then
    for pid in $STALE_PIDS; do
        kill "$pid" 2>/dev/null || true
        echo "  TERM an PID $pid"
    done

    sleep 2

    REMAINING_PIDS="$(pgrep -f 'python3 .*steuerbox(\.steuerbox_api|/steuerbox_api\.py)' || true)"
    if [ -n "$REMAINING_PIDS" ]; then
        for pid in $REMAINING_PIDS; do
            kill -9 "$pid" 2>/dev/null || true
            echo "  KILL an PID $pid"
        done
    fi
    echo -e "${GREEN}✓ Altprozesse bereinigt${NC}"
else
    echo -e "${GREEN}✓ Keine alten Steuerbox-Prozesse gefunden${NC}"
fi

echo ""
echo "STEP 3: Starte nötige Dienste neu..."
sudo systemctl daemon-reload
sudo systemctl start "$STEUERBOX_SERVICE"
sudo systemctl restart "$PROXY_SERVICE"
sleep 3

echo ""
echo "STEP 4: Prüfe Service-Status..."
if systemctl is-active --quiet "$STEUERBOX_SERVICE"; then
    NEW_PID="$(systemctl show "$STEUERBOX_SERVICE" -p MainPID --value 2>/dev/null || echo 0)"
    echo -e "${GREEN}✓ ${STEUERBOX_SERVICE} aktiv (MainPID ${NEW_PID})${NC}"
else
    echo -e "${RED}✗ ${STEUERBOX_SERVICE} ist nicht aktiv${NC}"
    systemctl status "$STEUERBOX_SERVICE" --no-pager -l | tail -15
    exit 1
fi

if systemctl is-active --quiet "$PROXY_SERVICE"; then
    echo -e "${GREEN}✓ ${PROXY_SERVICE} aktiv${NC}"
else
    echo -e "${RED}✗ ${PROXY_SERVICE} ist nicht aktiv${NC}"
    systemctl status "$PROXY_SERVICE" --no-pager -l | tail -15
    exit 1
fi

echo ""
echo "STEP 5: Funktionstest..."
BACKEND_HTTP="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BACKEND_URL" 2>/dev/null || echo "000")"
FRONTEND_HTTP="$(curl -k -s -o /dev/null -w "%{http_code}" --max-time 5 "$FRONTEND_URL" 2>/dev/null || echo "000")"

if [ "$BACKEND_HTTP" = "200" ]; then
    echo -e "${GREEN}✓ Backend gesund (HTTP ${BACKEND_HTTP})${NC}"
else
    echo -e "${RED}✗ Backend-Healthcheck fehlgeschlagen (HTTP ${BACKEND_HTTP})${NC}"
    exit 1
fi

if [ "$FRONTEND_HTTP" = "200" ]; then
    echo -e "${GREEN}✓ HTTPS-Proxy gesund (HTTP ${FRONTEND_HTTP})${NC}"
else
    echo -e "${RED}✗ HTTPS-Proxy-Healthcheck fehlgeschlagen (HTTP ${FRONTEND_HTTP})${NC}"
    exit 1
fi

echo ""
echo "========================================="
echo -e "${GREEN}✓✓✓ STEUERBOX ERFOLGREICH NEU GESTARTET ✓✓✓${NC}"
echo "Backend:  ${BACKEND_URL}"
echo "Frontend: ${FRONTEND_URL}"
echo "========================================="
