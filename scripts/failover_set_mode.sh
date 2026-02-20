#!/bin/bash
set -euo pipefail

MODE="${1:-}"
if [ "$MODE" != "active" ] && [ "$MODE" != "passive" ]; then
  echo "Usage: $0 active|passive"
  exit 1
fi

BASE="/srv/pv-system"
PRIMARY_SOURCE="${PRIMARY_SOURCE:-Pi4 Primär (192.0.2.181)}"
OVERRIDE_DIR="/etc/systemd/system/pv-web.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"

sudo mkdir -p "$OVERRIDE_DIR"

if [ "$MODE" = "passive" ]; then
  cat <<EOF | sudo tee "$OVERRIDE_FILE" >/dev/null
[Service]
Environment=PV_MIRROR_MODE=1
Environment=PV_MIRROR_SOURCE=${PRIMARY_SOURCE}
EOF

  sudo systemctl daemon-reload
  sudo systemctl restart pv-web.service || true
  sudo systemctl stop pv-collector.service || true
  sudo systemctl stop pv-wattpilot.service || true
  sudo systemctl enable --now pv-mirror-sync.timer || true

  echo "Failover-Modus PASSIVE aktiv: kein Collector-Traffic, nur DB-Mirror-Sync."
else
  cat <<EOF | sudo tee "$OVERRIDE_FILE" >/dev/null
[Service]
Environment=PV_MIRROR_MODE=0
EOF

  sudo systemctl daemon-reload
  sudo systemctl restart pv-web.service || true
  sudo systemctl disable --now pv-mirror-sync.timer || true
  sudo systemctl start pv-collector.service || true
  sudo systemctl start pv-wattpilot.service || true

  echo "Failover-Modus ACTIVE aktiv: Collector + Wattpilot laufen lokal."
fi
