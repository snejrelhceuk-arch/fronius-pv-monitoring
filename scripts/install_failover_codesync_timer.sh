#!/bin/bash
# =================================================================
# install_failover_codesync_timer.sh — wöchentlicher Code-/Config-
# Sync Primary → Failover als systemd-Timer einrichten.
#
# NUR auf dem Primary installieren. Hält den Failover-Host (Pi5-FB)
# code- und config-aktuell (git-tracked, inkl. config/*.json), damit
# er im Ernstfall nicht mit veralteter Automationslogik/Batterie-
# Kapazität zum Primary promoviert. Ruft scripts/sync_code_to_peer.sh
# (self-guarded primary, host-spezifische Dateien ausgeschlossen).
# =================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/role_guard.sh" 2>/dev/null || { echo "Nur auf role=primary erlaubt" >&2; exit 1; }
USER_NAME="$(id -un)"
SVC=/etc/systemd/system/pv-failover-codesync.service
TMR=/etc/systemd/system/pv-failover-codesync.timer

echo "== Failover-Codesync-Timer installieren (Host: $(hostname)) =="

sudo tee "$SVC" >/dev/null <<EOF
[Unit]
Description=PV Failover Code-/Config-Sync Primary -> FB (wöchentlich)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${USER_NAME}
WorkingDirectory=${REPO_ROOT}
ExecStart=/bin/bash ${REPO_ROOT}/scripts/sync_code_to_peer.sh --force
Nice=15
StandardOutput=journal
StandardError=journal
EOF

sudo tee "$TMR" >/dev/null <<EOF
[Unit]
Description=PV Failover Code-/Config-Sync wöchentlicher Trigger (Mo 04:30)

[Timer]
OnCalendar=Mon *-*-* 04:30:00
Persistent=true
RandomizedDelaySec=300
Unit=pv-failover-codesync.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pv-failover-codesync.timer
echo "== installiert. Nächste Läufe: =="
systemctl list-timers pv-failover-codesync.timer --no-pager 2>/dev/null | head -3
