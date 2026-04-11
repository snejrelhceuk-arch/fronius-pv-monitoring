#!/bin/bash
# ============================================================
# PV-System: Systemd-Services Installation
# Erstellt und aktiviert:
#   1. pv-collector.service  (Modbus-Datensammlung)
#   2. pv-web.service        (Flask Web-API)
#   3. pv-steuerbox.service  (Operator-Intent API hinter nginx)
#   4. pv-wattpilot.service  (Wattpilot Wallbox-Collector)
#   5. pv-restart.service + .timer (Neustart alle 3 Tage)
#   6. pv-backup-gfs.service + .timer (GFS-Backup, Sohn alle 3 Tage)
#
# Periodische Jobs (Checkpoints, Counter-Checks) laufen via Cron
# — siehe crontab -l
# ============================================================

set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== PV-System Systemd-Services installieren ==="

# 1. Collector Service (Modbus-Datensammlung)
echo "→ pv-collector.service erstellen..."
sudo tee /etc/systemd/system/pv-collector.service > /dev/null <<EOF
[Unit]
Description=PV-System Modbus Data Collector
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=10

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/collector.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 2. Web-API Service (Flask)
echo "→ pv-web.service erstellen..."
sudo tee /etc/systemd/system/pv-web.service > /dev/null <<EOF
[Unit]
Description=PV-System Web API (Flask)
After=network-online.target pv-collector.service
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=10

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/web_api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 3. Steuerbox Service
echo "→ pv-steuerbox.service installieren..."
sudo install -m 0644 ${BASE}/pv-steuerbox.service /etc/systemd/system/pv-steuerbox.service

# 4. Wattpilot Collector Service
echo "→ pv-wattpilot.service erstellen..."
sudo tee /etc/systemd/system/pv-wattpilot.service > /dev/null <<EOF
[Unit]
Description=PV-System Wattpilot Wallbox Collector
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=10

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/wattpilot_collector.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 5. Restart Service (führt den eigentlichen Neustart durch)
echo "→ pv-restart.service erstellen..."
sudo tee /etc/systemd/system/pv-restart.service > /dev/null <<'EOF'
[Unit]
Description=PV-System Services Restart (alle 3 Tage Mitternacht)

[Service]
Type=oneshot
ExecStart=/bin/bash -c '\
    echo "$(date): PV-System Scheduled Restart" >> /tmp/pv_restart.log && \
    systemctl restart pv-collector.service && \
    echo "$(date): Collector neugestartet" >> /tmp/pv_restart.log && \
    systemctl restart pv-web.service && \
    echo "$(date): Web-API neugestartet" >> /tmp/pv_restart.log && \
    systemctl restart pv-steuerbox.service && \
    echo "$(date): Steuerbox neugestartet" >> /tmp/pv_restart.log && \
    systemctl restart pv-wattpilot.service && \
    echo "$(date): Wattpilot neugestartet" >> /tmp/pv_restart.log'
EOF

# 6. Timer: Alle 3 Tage um 00:05
echo "→ pv-restart.timer erstellen..."
sudo tee /etc/systemd/system/pv-restart.timer > /dev/null <<'EOF'
[Unit]
Description=PV-System Services Restart Timer (alle 3 Tage)

[Timer]
OnCalendar=*-*-01,04,07,10,13,16,19,22,25,28 00:05:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 6. GFS Backup Service
echo "→ pv-backup-gfs.service erstellen..."
sudo tee /etc/systemd/system/pv-backup-gfs.service > /dev/null <<EOF
[Unit]
Description=PV-System GFS Database Backup (Sohn/Vater/Grossvater)
After=network-online.target pv-collector.service
Wants=network-online.target

[Service]
Type=oneshot
User=admin
WorkingDirectory=${BASE}
ExecStart=/bin/bash ${BASE}/scripts/backup_db_gfs.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

# 7. GFS Backup Timer: täglich 03:00, Sohn-Intervall wird im Script gesteuert
echo "→ pv-backup-gfs.timer erstellen..."
sudo tee /etc/systemd/system/pv-backup-gfs.timer > /dev/null <<'EOF'
[Unit]
Description=PV-System GFS Backup Timer (daily run, Sohn every 3 days)

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=180

[Install]
WantedBy=timers.target
EOF

# Services aktivieren
echo "→ systemd reload..."
sudo systemctl daemon-reload

echo "→ Services aktivieren..."
sudo systemctl enable pv-collector.service
sudo systemctl enable pv-web.service
sudo systemctl enable pv-steuerbox.service
sudo systemctl enable pv-wattpilot.service
sudo systemctl enable --now pv-restart.timer
sudo systemctl enable --now pv-backup-gfs.timer

# Alten manuellen Collector stoppen und durch systemd ersetzen
echo "→ Prüfe laufende Prozesse..."
for proc in "collector.py" "web_api.py" "steuerbox_api.py" "wattpilot_collector.py"; do
    PID=$(pgrep -f "python3.*${proc}" 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo "  Stoppe manuellen ${proc} (PID $PID)..."
        kill "$PID" 2>/dev/null || true
    fi
done
sleep 2

echo "→ Starte Services via systemd..."
sudo systemctl start pv-collector.service
sudo systemctl start pv-web.service
sudo systemctl start pv-steuerbox.service
sudo systemctl start pv-wattpilot.service

echo ""
echo "=== Status ==="
for svc in pv-collector pv-web pv-steuerbox pv-wattpilot; do
    echo "--- ${svc} ---"
    systemctl status ${svc}.service --no-pager | head -5
    echo ""
done
echo "--- Restart Timer ---"
systemctl status pv-restart.timer --no-pager | head -5
echo ""
echo "--- Backup Timer ---"
systemctl status pv-backup-gfs.timer --no-pager | head -5
echo ""
echo "--- Nächster Restart ---"
systemctl list-timers pv-restart.timer --no-pager
echo "--- Nächstes Backup ---"
systemctl list-timers pv-backup-gfs.timer --no-pager

echo ""
echo "✓ Installation abgeschlossen!"
echo "  Collector:   systemctl status pv-collector"
echo "  Web API:     systemctl status pv-web"
echo "  Steuerbox:   systemctl status pv-steuerbox"
echo "  Wattpilot:   systemctl status pv-wattpilot"
echo "  Timer:       systemctl list-timers pv-restart*"
echo "  Backup:      systemctl list-timers pv-backup-gfs*"
echo "  Cron-Jobs:   crontab -l"
echo "  Logs:        journalctl -u pv-collector -f"
echo "  Backup-Logs: journalctl -u pv-backup-gfs -n 100 --no-pager"
echo "  Web:         http://$(hostname -I | awk '{print $1}'):8000"
