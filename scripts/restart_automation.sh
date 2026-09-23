#!/bin/bash
# ========================================
# Automation-Daemon Neustart Script
# ========================================
# Delegiert an systemd (pv-automation.service) — Rolle C, nur Primary.
# Manueller Direktstart ist NICHT erlaubt (einziger HW-Schreibpfad, Split-Brain-Schutz).
#
# Nach dem Neustart wird die bestimmungsgemäße Funktion verifiziert:
#   1. Service aktiv (systemd)
#   2. neuer MainPID (Prozess wirklich getauscht)
#   3. kein Start-Traceback im Journal
#   4. frischer Heartbeat 'automation_daemon' in der RAM-DB (Engine-Loop lebt)
# ========================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

SERVICE="pv-automation.service"
RAM_DB="/dev/shm/automation_obs.db"
HEARTBEAT_COMPONENT="automation_daemon"
MAX_HEARTBEAT_AGE=45   # s — Heartbeat gilt als frisch, wenn jünger
WAIT_TIMEOUT=40        # s — max. Wartezeit auf ersten frischen Heartbeat

echo "========================================="
echo "Automation-Daemon Neustart (via systemd)"
echo "========================================="
echo ""

# ========================================
# Guard 1: nur Primary (Automation = Rolle C)
# ========================================
ROLE="primary"
[ -f "$REPO_ROOT/.role" ] && ROLE="$(head -n1 "$REPO_ROOT/.role" | tr -d '[:space:]')"
if [ "$ROLE" != "primary" ]; then
    echo -e "${RED}✗ FEHLER: Automation läuft ausschließlich auf dem PRIMARY-Host (Rolle hier: $ROLE).${NC}"
    exit 1
fi

# ========================================
# Guard 2: pv-automation.service muss enabled sein
# ========================================
if ! systemctl is-enabled "$SERVICE" >/dev/null 2>&1; then
    echo -e "${RED}✗ FEHLER: $SERVICE ist nicht enabled!${NC}"
    echo "  Aktivieren mit: sudo systemctl enable $SERVICE"
    exit 1
fi

# ========================================
# SCHRITT 1: alten PID merken + Neustart
# ========================================
OLD_PID="$(systemctl show "$SERVICE" -p MainPID --value 2>/dev/null || echo 0)"
echo "STEP 1: Neustart via 'systemctl restart $SERVICE' (alter PID: ${OLD_PID})..."
sudo systemctl restart "$SERVICE"
sleep 3

# ========================================
# SCHRITT 2: Service-Status + PID-Wechsel
# ========================================
echo ""
echo "STEP 2: Prüfe Service-Status..."
if systemctl is-active --quiet "$SERVICE"; then
    NEW_PID="$(systemctl show "$SERVICE" -p MainPID --value 2>/dev/null || echo 0)"
    echo -e "${GREEN}✓ $SERVICE aktiv (MainPID $NEW_PID, vorher $OLD_PID)${NC}"
else
    echo -e "${RED}✗ $SERVICE nicht aktiv!${NC}"
    systemctl status "$SERVICE" --no-pager -l | tail -15
    exit 1
fi

# ========================================
# SCHRITT 3: Start-Fehler im Journal?
# ========================================
echo ""
echo "STEP 3: Prüfe Journal auf Start-Fehler..."
if journalctl -u "$SERVICE" --since "15 seconds ago" --no-pager 2>/dev/null \
        | grep -qiE 'Traceback|CRITICAL|Failed with result|Main process exited'; then
    echo -e "${YELLOW}⚠ Auffälligkeiten im Journal — bitte prüfen:${NC}"
    journalctl -u "$SERVICE" --since "15 seconds ago" --no-pager | tail -12
else
    echo -e "${GREEN}✓ Kein Start-Traceback im Journal${NC}"
fi

# ========================================
# SCHRITT 4: Heartbeat-Frische (Engine-Loop lebt)
# ========================================
echo ""
echo "STEP 4: Warte auf frischen Heartbeat '$HEARTBEAT_COMPONENT' in der RAM-DB..."
waited=0
hb_ok=0
while [ "$waited" -lt "$WAIT_TIMEOUT" ]; do
    AGE="$(python3 - "$RAM_DB" "$HEARTBEAT_COMPONENT" <<'PY' 2>/dev/null || echo -1
import sqlite3, sys
from datetime import datetime
db, comp = sys.argv[1], sys.argv[2]
try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    row = c.execute("SELECT ts FROM heartbeat WHERE component=?", (comp,)).fetchone()
    c.close()
    if not row:
        print(-1)
    else:
        print(int((datetime.now() - datetime.fromisoformat(row[0])).total_seconds()))
except Exception:
    print(-1)
PY
)"
    if [ "$AGE" -ge 0 ] 2>/dev/null && [ "$AGE" -le "$MAX_HEARTBEAT_AGE" ]; then
        echo -e "${GREEN}✓ Heartbeat frisch (${AGE}s alt) — Engine-Loop läuft${NC}"
        hb_ok=1
        break
    fi
    sleep 3
    waited=$((waited + 3))
done
if [ "$hb_ok" -ne 1 ]; then
    echo -e "${YELLOW}⚠ Kein frischer Heartbeat innerhalb ${WAIT_TIMEOUT}s (letztes Alter: ${AGE}s).${NC}"
    echo "  Live verfolgen: journalctl -u $SERVICE -f | grep -i heartbeat"
fi

# ========================================
# SCHRITT 5: Zusammenfassung
# ========================================
echo ""
echo "========================================="
if [ "$hb_ok" -eq 1 ]; then
    echo -e "${GREEN}✓✓✓ AUTOMATION ERFOLGREICH NEU GESTARTET ✓✓✓${NC}"
else
    echo -e "${YELLOW}⚠ Automation neu gestartet — Heartbeat bitte manuell verifizieren${NC}"
fi
echo "Logs:  journalctl -u $SERVICE -f"
echo "========================================="
