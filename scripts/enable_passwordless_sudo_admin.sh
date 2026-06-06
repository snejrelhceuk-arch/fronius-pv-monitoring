#!/bin/bash
# Enable passwordless sudo for local admin user (explicit production action).
set -euo pipefail

ADMIN_USER="${1:-admin}"
SUDOERS_FILE="/etc/sudoers.d/90-${ADMIN_USER}-nopasswd"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

cat >"${SUDOERS_FILE}" <<EOF
${ADMIN_USER} ALL=(ALL:ALL) NOPASSWD: ALL
EOF
chmod 0440 "${SUDOERS_FILE}"

if visudo -cf "${SUDOERS_FILE}" >/dev/null 2>&1; then
  echo "OK: ${SUDOERS_FILE} installed and syntax-valid."
else
  echo "ERROR: invalid sudoers file, rolling back." >&2
  rm -f "${SUDOERS_FILE}"
  exit 2
fi
