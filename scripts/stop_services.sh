#!/bin/bash
# Stoppt alle PV-System-Dienste sauber über systemd

echo "=== Stoppe PV-System-Dienste ==="

# 1. Systemd-Services stoppen (bevorzugt)
echo "1. Stoppe systemd-Services..."
for svc in pv-collector pv-web pv-wattpilot pv-automation pv-observer; do
    if systemctl is-active --quiet "$svc.service" 2>/dev/null; then
        sudo systemctl stop "$svc.service" && echo "  ✓ $svc gestoppt" || echo "  ✗ $svc Stop fehlgeschlagen"
    else
        echo "  – $svc nicht aktiv"
    fi
done

# 2. Verbleibende Prozesse die NICHT über systemd laufen
echo ""
echo "2. Stoppe verbleibende pv-system Python-Prozesse..."
pkill -f "pv-system/aggregate" 2>/dev/null && echo "  ✓ aggregate Skripte gestoppt" || true

sleep 2

# 3. Prüfe ob noch Prozesse laufen
echo ""
echo "3. Verbleibende PV-System-Prozesse:"
ps aux | grep -E "pv-system" | grep -v grep | grep python3 || echo "  (keine)"

# 4. Cron-Sicherung
echo ""
echo "4. Cron-Info:"
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
echo "1. Überprüfen: systemctl status pv-collector pv-web pv-wattpilot"
echo "2. Neustart: sudo systemctl start pv-collector pv-web pv-wattpilot"
echo "3. Falls nötig: sudo reboot"
