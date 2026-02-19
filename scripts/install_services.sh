#!/bin/bash
# ============================================================
# PV-System: Systemd-Services Installation
# Erstellt und aktiviert:
#   1. pv-collector.service  (Modbus-Datensammlung)
#   2. pv-web.service        (Flask Web-API)
#   3. pv-wattpilot.service  (Wattpilot Wallbox-Collector)
#   4. pv-restart.service + .timer (Neustart alle 3 Tage)
#   5. pv-energy-checkpoint.service + .timer (täglicher Counter-Fixpunkt)
#   6. pv-counter-check.service + .timer (tägliche Counter-Plausibilitätsprüfung)
# ============================================================

set -e
BASE="/srv/pv-system"

echo "=== PV-System Systemd-Services installieren ==="

# 1. Collector Service (Modbus-Datensammlung)
echo "→ pv-collector.service erstellen..."
sudo tee /etc/systemd/system/pv-collector.service > /dev/null <<EOF
[Unit]
Description=PV-System Modbus Data Collector
After=network-online.target
Wants=network-online.target

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/collector.py
Restart=always
RestartSec=30
StartLimitIntervalSec=600
StartLimitBurst=10
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

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/web_api.py
Restart=always
RestartSec=10
StartLimitIntervalSec=600
StartLimitBurst=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 3. Wattpilot Collector Service
echo "→ pv-wattpilot.service erstellen..."
sudo tee /etc/systemd/system/pv-wattpilot.service > /dev/null <<EOF
[Unit]
Description=PV-System Wattpilot Wallbox Collector
After=network-online.target
Wants=network-online.target

[Service]
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/wattpilot_collector.py
Restart=always
RestartSec=30
StartLimitIntervalSec=600
StartLimitBurst=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 4. Restart Service (führt den eigentlichen Neustart durch)
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
    systemctl restart pv-wattpilot.service && \
    echo "$(date): Wattpilot neugestartet" >> /tmp/pv_restart.log'
EOF

# 5. Timer: Alle 3 Tage um 00:05
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

# 6. Energy Checkpoint Service (täglich 00:01)
echo "→ pv-energy-checkpoint.service erstellen..."
sudo tee /etc/systemd/system/pv-energy-checkpoint.service > /dev/null <<EOF
[Unit]
Description=PV-System Daily Energy Counter Checkpoint
After=network-online.target pv-collector.service
Wants=network-online.target

[Service]
Type=oneshot
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/scripts/capture_energy_checkpoints.py --type day_start
StandardOutput=journal
StandardError=journal
EOF

echo "→ pv-energy-checkpoint.timer erstellen..."
sudo tee /etc/systemd/system/pv-energy-checkpoint.timer > /dev/null <<'EOF'
[Unit]
Description=PV-System Daily Energy Counter Checkpoint Timer

[Timer]
OnCalendar=*-*-* 00:01:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 7. Counter Check Service (täglich 00:10)
echo "→ pv-counter-check.service erstellen..."
sudo tee /etc/systemd/system/pv-counter-check.service > /dev/null <<EOF
[Unit]
Description=PV-System Daily Energy Counter Plausibility Check
After=network-online.target pv-energy-checkpoint.service
Wants=network-online.target

[Service]
Type=oneshot
User=admin
WorkingDirectory=${BASE}
ExecStart=/usr/bin/python3 ${BASE}/scripts/check_energy_counters.py --hours 36
StandardOutput=journal
StandardError=journal
EOF

echo "→ pv-counter-check.timer erstellen..."
sudo tee /etc/systemd/system/pv-counter-check.timer > /dev/null <<'EOF'
[Unit]
Description=PV-System Daily Energy Counter Check Timer

[Timer]
OnCalendar=*-*-* 00:10:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Services aktivieren
echo "→ systemd reload..."
sudo systemctl daemon-reload

echo "→ Services aktivieren..."
sudo systemctl enable pv-collector.service
sudo systemctl enable pv-web.service
sudo systemctl enable pv-wattpilot.service
sudo systemctl enable --now pv-restart.timer
sudo systemctl enable --now pv-energy-checkpoint.timer
sudo systemctl enable --now pv-counter-check.timer

# Alten manuellen Collector stoppen und durch systemd ersetzen
echo "→ Prüfe laufende Prozesse..."
for proc in "collector.py" "web_api.py" "wattpilot_collector.py"; do
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
sudo systemctl start pv-wattpilot.service

echo ""
echo "=== Status ==="
for svc in pv-collector pv-web pv-wattpilot; do
    echo "--- ${svc} ---"
    systemctl status ${svc}.service --no-pager | head -5
    echo ""
done
echo "--- Restart Timer ---"
systemctl status pv-restart.timer --no-pager | head -5
echo "--- Energy Checkpoint Timer ---"
systemctl status pv-energy-checkpoint.timer --no-pager | head -5
echo "--- Counter Check Timer ---"
systemctl status pv-counter-check.timer --no-pager | head -5
echo ""
echo "--- Nächster Restart ---"
systemctl list-timers pv-restart.timer --no-pager
echo "--- Nächster Checkpoint/Counter-Check ---"
systemctl list-timers pv-energy-checkpoint.timer --no-pager
systemctl list-timers pv-counter-check.timer --no-pager

echo ""
echo "✓ Installation abgeschlossen!"
echo "  Collector:   systemctl status pv-collector"
echo "  Web API:     systemctl status pv-web"
echo "  Wattpilot:   systemctl status pv-wattpilot"
echo "  Timer:       systemctl list-timers pv-*"
echo "  Logs:        journalctl -u pv-collector -f"
echo "  Web:         http://$(hostname -I | awk '{print $1}'):8000"
