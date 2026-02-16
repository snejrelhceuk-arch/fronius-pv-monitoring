#!/bin/bash
# ========================================
# Web-Server Neustart Script
# ========================================
# Stoppt und startet nur den Web-API Server (gunicorn)
# Collector bleibt unberührt und läuft weiter
# LLM-freundlich mit klaren Status-Ausgaben
# ========================================

set -e  # Exit bei Fehler
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Farben für Ausgabe (optional)
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "Web-Server Neustart (nur Web-API)"
echo "========================================="
echo ""

# ========================================
# SCHRITT 1: Stoppe Web-API (gunicorn)
# ========================================
echo "STEP 1: Stoppe Web-API Server..."
if pgrep -f "gunicorn.*web_api" > /dev/null; then
    pkill -f "gunicorn.*web_api"
    echo -e "${GREEN}✓ Gunicorn-Prozesse beendet${NC}"
    sleep 2
    
    # Prüfe ob wirklich beendet
    if pgrep -f "gunicorn.*web_api" > /dev/null; then
        echo -e "${RED}✗ Gunicorn läuft noch, forciere Beendigung...${NC}"
        pkill -9 -f "gunicorn.*web_api"
        sleep 2
    fi
else
    echo -e "${YELLOW}ℹ Gunicorn war nicht aktiv${NC}"
fi

# ========================================
# SCHRITT 2: Validierung - Web-API gestoppt?
# ========================================
echo ""
echo "STEP 2: Validiere Prozess-Beendigung..."
RUNNING_WEB=$(ps aux | grep -E "gunicorn.*web_api" | grep -v grep | wc -l)

if [ "$RUNNING_WEB" -eq 0 ]; then
    echo -e "${GREEN}✓ Web-API erfolgreich beendet${NC}"
else
    echo -e "${RED}✗ FEHLER: Noch $RUNNING_WEB Web-API Prozess(e) aktiv!${NC}"
    ps aux | grep -E "gunicorn.*web_api" | grep -v grep
    echo ""
    echo "Bitte manuell prüfen oder mit 'pkill -9 -f gunicorn.*web_api' beenden"
    exit 1
fi

# ========================================
# SCHRITT 3: Starte Web-API neu
# ========================================
echo ""
echo "STEP 3: Starte Web-API Server..."
nohup gunicorn -c gunicorn_config.py web_api:app > /dev/null 2>&1 &
sleep 3

# Prüfe ob gestartet
if pgrep -f "gunicorn.*web_api" > /dev/null; then
    GUNICORN_COUNT=$(pgrep -f "gunicorn.*web_api" | wc -l)
    echo -e "${GREEN}✓ Web-API gestartet ($GUNICORN_COUNT Prozesse)${NC}"
else
    echo -e "${RED}✗ FEHLER: Web-API konnte nicht gestartet werden${NC}"
    echo "Prüfe gunicorn_config.py und web_api.py"
    exit 1
fi

# ========================================
# SCHRITT 4: Finale Statusprüfung
# ========================================
echo ""
echo "STEP 4: Finale Statusprüfung..."
echo "========================================="

GUNICORN_PROCESSES=$(ps aux | grep -E "gunicorn.*web_api" | grep -v grep | wc -l)
COLLECTOR_RUNNING=$(ps aux | grep -E "collector.py" | grep -v grep | wc -l)

if [ "$GUNICORN_PROCESSES" -ge 1 ]; then
    echo -e "${GREEN}✓✓✓ WEB-SERVER ERFOLGREICH NEU GESTARTET ✓✓✓${NC}"
    echo ""
    echo "Web-API Prozesse:"
    ps aux | grep -E "gunicorn.*web_api" | grep -v grep | awk '{print "  - PID " $2 ": Web-API Worker"}'
    echo ""
    if [ "$COLLECTOR_RUNNING" -ge 1 ]; then
        echo -e "${GREEN}ℹ Collector läuft weiter (unverändert)${NC}"
    else
        echo -e "${YELLOW}⚠ Collector läuft nicht! Ggf. mit 'nohup python3 collector.py &' starten${NC}"
    fi
    echo ""
    echo "Web-Interface: http://localhost:5000"
    echo "========================================="
    exit 0
else
    echo -e "${RED}✗✗✗ FEHLER: Web-API konnte nicht gestartet werden ✗✗✗${NC}"
    echo "Keine Gunicorn-Prozesse gefunden"
    exit 1
fi
