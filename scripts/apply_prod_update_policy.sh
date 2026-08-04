#!/bin/bash
# Production update policy: security/routine updates run unattended on all hosts.
# App-critical packages (python/sqlite/kernel/firmware) are excluded from the
# UNATTENDED run only -- they are updated regularly via a confirmed interactive
# `sudo apt upgrade` (the Rueckfrage). No auto reboot (persist tmpfs-DB first).
# Since the Pi5/64-bit migration nothing is self-compiled anymore.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

apt-get update
apt-get install -y unattended-upgrades apt-listchanges

cat >/etc/apt/apt.conf.d/52pv-periodic <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

cat >/etc/apt/apt.conf.d/52pv-unattended <<'EOF'
Unattended-Upgrade::Origins-Pattern {
  "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};

Unattended-Upgrade::Package-Blacklist {
  // Nur aus dem UNBEAUFSICHTIGTEN Lauf ausgenommen (App-kritisch bzw. Reboot).
  // Regelmaessig via bestaetigtem `sudo apt upgrade` (Rueckfrage) mitgezogen.
  "python3";
  "python3-*";
  "sqlite3";
  "libsqlite3-0";
  "libsqlite3-dev";
  "linux-image-*";
  "raspi-firmware";
};

Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::MailReport "on-change";
EOF

systemctl enable --now unattended-upgrades.service >/dev/null 2>&1 || true

# --- Woechentlicher Wartungs-/Update-Melder (nur wo ein App-venv existiert) ---
BASE="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
if [[ -x "${BASE}/.venv/bin/python" ]]; then
  tee /etc/systemd/system/pv-weekly-maintenance.service >/dev/null <<EOF
[Unit]
Description=PV woechentlicher Wartungs-/Update-Melder (apt+pip Report per Mail)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${BASE}
ExecStart=${BASE}/.venv/bin/python ${BASE}/scripts/pv_weekly_maintenance_report.py
StandardOutput=journal
StandardError=journal
Nice=15
EOF
  tee /etc/systemd/system/pv-weekly-maintenance.timer >/dev/null <<EOF
[Unit]
Description=PV woechentlicher Wartungs-Melder — Trigger (So 09:00)

[Timer]
OnCalendar=Sun *-*-* 09:00:00
Persistent=true
RandomizedDelaySec=1800
Unit=pv-weekly-maintenance.service

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now pv-weekly-maintenance.timer >/dev/null 2>&1 || true
  WEEKLY_MSG="pv-weekly-maintenance.timer aktiv (So 09:00, apt+pip-Report per Mail)"
else
  WEEKLY_MSG="kein ${BASE}/.venv -> Wartungs-Melder uebersprungen (Host ohne App-venv)"
fi

echo "OK: production update policy applied."
echo "- security unattended-upgrades enabled"
echo "- app-critical pkgs (python/sqlite/kernel/firmware) excluded from UNATTENDED run only"
echo "  -> update them regularly via confirmed: sudo bash scripts/pv_maintenance_upgrade.sh"
echo "- auto reboot disabled"
echo "- ${WEEKLY_MSG}"
