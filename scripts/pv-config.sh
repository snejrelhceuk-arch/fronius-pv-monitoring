#!/bin/bash
# =============================================================
# pv-config Launcher — interaktives Whiptail-Konfigurationsmenü
#
# Startet pv-config.py aus dem Repo-Root mit dem venv-Python
# (enthält cryptography für den Credential-Store).
#
# Normale Nutzung (Regelkreise, Parameter, Status, Test-Mail):
#   scripts/pv-config.sh
#
# "SMTP-Passwort setzen" schreibt nach /etc/pv-system/ und braucht root:
#   sudo scripts/pv-config.sh
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "Fehler: pv-config braucht ein interaktives Terminal (SSH mit -t/TTY)." >&2
    exit 1
fi

if [ ! -x /usr/bin/whiptail ]; then
    echo "Fehler: whiptail fehlt  ->  sudo apt install whiptail" >&2
    exit 1
fi

PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

exec "$PY" pv-config.py "$@"
