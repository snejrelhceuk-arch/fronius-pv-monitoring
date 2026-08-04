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

echo "OK: production update policy applied."
echo "- security unattended-upgrades enabled"
echo "- app-critical pkgs (python/sqlite/kernel/firmware) excluded from UNATTENDED run only"
echo "  -> update them regularly via confirmed: sudo apt upgrade"
echo "- auto reboot disabled"
