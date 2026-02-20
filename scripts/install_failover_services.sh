#!/bin/bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
PRIMARY_SOURCE="${PRIMARY_SOURCE:-Pi4 Primär (192.168.2.181)}"

echo "=== Installiere Failover-Services (Mirror + 2-Tage-Backup) ==="

# Mirror Sync Service
sudo tee /etc/systemd/system/pv-mirror-sync.service >/dev/null <<EOF
[Unit]
Description=PV Failover Mirror Sync (DB Pull vom Primär-Pi)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${BASE}
ExecStart=${BASE}/scripts/failover_sync_db.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

# Mirror Sync Timer (alle 10 Minuten — schont SD-Karte, reicht für Failover)
sudo tee /etc/systemd/system/pv-mirror-sync.timer >/dev/null <<'EOF'
[Unit]
Description=PV Failover Mirror Sync Timer (alle 10 Minuten)

[Timer]
OnBootSec=15s
OnUnitActiveSec=10min
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Backup every 2 days wrapper service
sudo tee /etc/systemd/system/pv-backup-2d.service >/dev/null <<EOF
[Unit]
Description=PV Failover Local DB Backup (mindestens alle 2 Tage)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${BASE}
ExecStart=${BASE}/scripts/backup_db_every2d.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

# Daily timer, wrapper decides whether 2-day interval is due
sudo tee /etc/systemd/system/pv-backup-2d.timer >/dev/null <<'EOF'
[Unit]
Description=PV Failover Backup Timer (täglich, 2-Tage-Intervall via Wrapper)

[Timer]
OnCalendar=*-*-* 03:10:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
EOF

# Healthcheck Service (nur Empfehlung, kein Auto-Failover)
sudo tee /etc/systemd/system/pv-failover-health.service >/dev/null <<EOF
[Unit]
Description=PV Failover Health Check (nur Empfehlung)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${BASE}
ExecStart=${BASE}/scripts/failover_health_check.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

# Healthcheck Timer (jede Minute)
sudo tee /etc/systemd/system/pv-failover-health.timer >/dev/null <<'EOF'
[Unit]
Description=PV Failover Health Timer (jede Minute)

[Timer]
OnBootSec=60s
OnUnitActiveSec=1min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload

# Ensure executable scripts
sudo chmod +x \
  ${BASE}/scripts/failover_sync_db.sh \
  ${BASE}/scripts/backup_db_every2d.sh \
  ${BASE}/scripts/failover_health_check.sh \
  ${BASE}/scripts/failover_set_mode.sh \
  ${BASE}/scripts/failover_passive.sh \
  ${BASE}/scripts/failover_activate.sh

# Enable timers
sudo systemctl enable --now pv-mirror-sync.timer
sudo systemctl enable --now pv-backup-2d.timer
sudo systemctl enable --now pv-failover-health.timer

# Put node into passive mode by default
PRIMARY_SOURCE="$PRIMARY_SOURCE" ${BASE}/scripts/failover_passive.sh

echo ""
echo "=== Fertig ==="
echo "PASSIVE setzen:  ${BASE}/scripts/failover_passive.sh"
echo "ACTIVE setzen:   ${BASE}/scripts/failover_activate.sh"
echo "Mirror-Status:   systemctl status pv-mirror-sync.timer --no-pager"
echo "Backup-Status:   systemctl status pv-backup-2d.timer --no-pager"
echo "Health-Status:   systemctl status pv-failover-health.timer --no-pager"
echo "Empfehlung:      cat ${BASE}/.state/failover_recommendation"
