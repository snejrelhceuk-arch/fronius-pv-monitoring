#!/bin/bash
# ============================================================
# scripts/pv_maintenance_upgrade.sh
# Bestaetigtes Voll-Upgrade fuer einen PV-Host (auf Zuruf/woechentlich).
#
# Ablauf:
#   1. tmpfs-DB zuerst auf SD persistieren (Datensicherheit vor apt-Risiko).
#   2. `apt update` + `apt full-upgrade` MIT Rueckfrage — zieht bewusst auch die
#      app-kritischen Pakete (python/sqlite/kernel/firmware) mit, die aus dem
#      UNbeaufsichtigten Lauf ausgenommen sind.
#   3. pip-Updates im venv NUR als Report (Pins bleiben manuell — siehe aider-
#      Vorfall 2026-08: Auto-pip-Upgrade hob numpy und brach Reproduzierbarkeit).
#   4. Reboot NICHT automatisch — nur Hinweis, falls Kernel/Firmware neu.
#
# Kein `set -e` beim Upgrade-Teil, damit ein einzelnes apt-Warning nicht abbricht.
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Bitte als root ausfuehren:  sudo bash $0" >&2
  exit 1
fi

echo "=== PV-Wartungs-Upgrade auf $(hostname) ==="
echo "Repo: ${BASE}"

# --- 1. tmpfs-DB sichern -------------------------------------------------
PERSIST="${BASE}/scripts/persist_on_shutdown.sh"
if [[ -x "$PERSIST" || -f "$PERSIST" ]]; then
  echo "→ 1/4 tmpfs-DB persistieren (${PERSIST})…"
  bash "$PERSIST" || echo "  ⚠ Persist meldete einen Fehler — trotzdem fortfahren? (Ctrl-C zum Abbruch)"
else
  echo "→ 1/4 Kein persist_on_shutdown.sh gefunden — uebersprungen (Host ohne tmpfs-DB?)."
fi

# --- 2. Kernel-Stand vor Upgrade merken ----------------------------------
KREV_BEFORE="$(dpkg -l 'linux-image-*' 2>/dev/null | grep '^ii' | awk '{print $2"="$3}' | sort)"
FW_BEFORE="$(dpkg -l 'raspi-firmware' 2>/dev/null | grep '^ii' | awk '{print $3}')"

# --- 3. apt full-upgrade (mit Rueckfrage) --------------------------------
echo "→ 2/4 apt update…"
apt-get update
echo "→ 3/4 apt full-upgrade (bestaetigen; app-kritische Pakete werden mitgezogen)…"
apt-get full-upgrade
apt-get --purge autoremove -y

# --- 4. pip-Report (kein Auto-Upgrade) -----------------------------------
echo "→ 4/4 pip-Updates im venv (NUR Report — Pins manuell pflegen):"
if [[ -x "${BASE}/.venv/bin/pip" ]]; then
  "${BASE}/.venv/bin/pip" list --outdated --format=columns || true
  echo "  (Anwenden gezielt/gepinnt: .venv/bin/pip install 'paket==version')"
else
  echo "  Kein venv gefunden — uebersprungen."
fi

# --- 4b. requirements.txt an realen venv-Stand angleichen ----------------
if [[ -x "${BASE}/scripts/pv_freeze_requirements.sh" || -f "${BASE}/scripts/pv_freeze_requirements.sh" ]]; then
  bash "${BASE}/scripts/pv_freeze_requirements.sh" || true
  echo "  (requirements.txt ggf. aktualisiert — bei Aenderung committen)"
fi

# --- 5. Reboot-Hinweis ---------------------------------------------------
KREV_AFTER="$(dpkg -l 'linux-image-*' 2>/dev/null | grep '^ii' | awk '{print $2"="$3}' | sort)"
FW_AFTER="$(dpkg -l 'raspi-firmware' 2>/dev/null | grep '^ii' | awk '{print $3}')"
echo ""
if [[ "$KREV_BEFORE" != "$KREV_AFTER" || "$FW_BEFORE" != "$FW_AFTER" || -f /var/run/reboot-required ]]; then
  echo "⚠ Kernel/Firmware wurde aktualisiert ODER /var/run/reboot-required existiert."
  echo "  REBOOT empfohlen — bewusst NICHT automatisch. Wenn passend:"
  echo "    sudo reboot"
  echo "  (tmpfs-DB ist bereits persistiert; persist_on_shutdown laeuft beim Reboot erneut.)"
else
  echo "✓ Kein Reboot noetig."
fi
echo "=== Wartungs-Upgrade abgeschlossen ==="
