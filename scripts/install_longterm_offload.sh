#!/bin/bash
# =================================================================
# install_longterm_offload.sh — systemd-Timer für den Großvater-
# Longterm-Offload (monthly/yearly → Pi4-Küche) einrichten.
#
# NUR auf dem Backup-Host (Pi5-FB) installieren. Der Timer ruft
# scripts/backup_longterm_offload.sh täglich auf; der eigentliche
# Offload überspringt sich selbst, solange PV_KUECHE_HOST nicht
# gesetzt oder Pi4-Küche nicht erreichbar ist (fail-safe).
# =================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_NAME="$(id -un)"
SVC=/etc/systemd/system/pv-longterm-offload.service
TMR=/etc/systemd/system/pv-longterm-offload.timer

echo "== Longterm-Offload Timer installieren (Host: $(hostname)) =="

sudo tee "$SVC" >/dev/null <<EOF
[Unit]
Description=PV Longterm-Offload (Grossvater monthly/yearly -> Pi4-Kueche)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${USER_NAME}
WorkingDirectory=${REPO_ROOT}
ExecStart=/bin/bash ${REPO_ROOT}/scripts/backup_longterm_offload.sh
Nice=15
StandardOutput=journal
StandardError=journal
EOF

sudo tee "$TMR" >/dev/null <<EOF
[Unit]
Description=PV Longterm-Offload taeglicher Trigger (03:40)

[Timer]
OnCalendar=*-*-* 03:40:00
Persistent=true
Unit=pv-longterm-offload.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pv-longterm-offload.timer
echo "== installiert. Nächste Läufe: =="
systemctl list-timers pv-longterm-offload.timer --no-pager 2>/dev/null | head -3
