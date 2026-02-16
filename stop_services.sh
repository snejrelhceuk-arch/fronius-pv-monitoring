#!/bin/bash
# Stoppt alle Fronius-Datenerfassungs-Prozesse

echo "=== Stoppe Fronius-Prozesse ==="

# Killalle Python-Prozesse im pv-system Verzeichnis
echo "1. Stoppe Python-Prozesse..."
pkill -f "pv-system/collector.py" 2>/dev/null && echo "  ✓ collector.py gestoppt"
pkill -f "pv-system/aggregate" 2>/dev/null && echo "  ✓ aggregate Skripte gestoppt"
pkill -f "pv-system/web_api.py" 2>/dev/null && echo "  ✓ web_api.py gestoppt"
pkill -f "pv-system/modbus" 2>/dev/null && echo "  ✓ modbus Skripte gestoppt"

sleep 2

# Prüfe ob noch Prozesse laufen
echo ""
echo "2. Verbleibende Fronius-Prozesse:"
ps aux | grep -E "pv-system" | grep -v grep | grep python3

# Cron temporär deaktivieren
echo ""
echo "3. Deaktiviere Cron (temporär):"
crontab -l > /tmp/crontab_backup.txt 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ✓ Crontab gesichert nach /tmp/crontab_backup.txt"
    echo "  ! Bitte manuell Cron-Jobs kommentieren oder:"
    echo "    crontab -r  # Entfernt alle Cron-Jobs"
else
    echo "  ! Keine Crontab gefunden"
fi

echo ""
echo "=== NÄCHSTE SCHRITTE ==="
echo "1. Überprüfen ob Prozesse gestoppt: ps aux | grep fronius"
echo "2. Falls nötig forciertes Killen: pkill -9 -f pv-system"
echo "3. System-Neustart: sudo reboot"
echo "4. Nach Neustart Cron wieder aktivieren"
