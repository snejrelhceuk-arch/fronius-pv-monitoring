#!/bin/bash
# ========================================
# Web-Server Neustart Script
# ========================================
# Delegiert an systemd (pv-web.service).
# Manueller nohup-Start ist NICHT erlaubt — Port-Konflikte vermeiden!
# ========================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

SERVICE="pv-web.service"

echo "========================================="
echo "Web-Server Neustart (via systemd)"
echo "========================================="
echo ""

# ========================================
# Guard: pv-web.service muss enabled sein
# ========================================
if ! systemctl is-enabled "$SERVICE" >/dev/null 2>&1; then
    echo -e "${RED}✗ FEHLER: $SERVICE ist nicht enabled!${NC}"
    echo "  Aktivieren mit: sudo systemctl enable $SERVICE"
    exit 1
fi

# ========================================
# SCHRITT 1: Restart via systemd
# ========================================
echo "STEP 1: Neustart via 'systemctl restart $SERVICE'..."
sudo systemctl restart "$SERVICE"
sleep 3

# ========================================
# SCHRITT 2: Status prüfen
# ========================================
echo ""
echo "STEP 2: Prüfe Service-Status..."

if systemctl is-active --quiet "$SERVICE"; then
    GUNICORN_COUNT=$(pgrep -fc "gunicorn.*web_api" || echo 0)
    echo -e "${GREEN}✓ $SERVICE aktiv ($GUNICORN_COUNT Prozesse)${NC}"
else
    echo -e "${RED}✗ $SERVICE nicht aktiv!${NC}"
    systemctl status "$SERVICE" --no-pager -l | tail -10
    exit 1
fi

# ========================================
# SCHRITT 3: API-Funktionstest
# ========================================
echo ""
echo "STEP 3: API-Funktionstest..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/ 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" =~ ^(200|302)$ ]]; then
    echo -e "${GREEN}✓ Web-API antwortet (HTTP $HTTP_CODE)${NC}"
else
    echo -e "${RED}✗ Web-API antwortet nicht (HTTP $HTTP_CODE)${NC}"
    exit 1
fi

# ========================================
# SCHRITT 4: Finale Zusammenfassung
# ========================================
echo ""
echo "========================================="
COLLECTOR_RUNNING=$(pgrep -fc "[^_]collector\.py" || echo 0)
if [ "$COLLECTOR_RUNNING" -ge 1 ]; then
    echo -e "${GREEN}ℹ Collector läuft (unverändert)${NC}"
else
    echo -e "${YELLOW}⚠ Collector läuft nicht!${NC}"
fi
echo -e "${GREEN}✓✓✓ WEB-SERVER ERFOLGREICH NEU GESTARTET ✓✓✓${NC}"
echo "Web-Interface: http://localhost:8000"
echo "========================================="
