#!/bin/bash
# Apply conservative production update policy: security auto-updates, no auto reboot.
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
echo "- python/sqlite/kernel packages blacklisted from unattended updates"
echo "- auto reboot disabled"
