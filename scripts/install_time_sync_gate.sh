#!/usr/bin/env bash
#
# install_time_sync_gate.sh — Zeit-Sync-Gate fuer datenschreibende PV-Dienste.
#
# Zweck (endgueltiger Fix fuer die Uhr-Skew-Problematik, s. doc/audit/2026-09-08-blackout.md):
#   1. Aktiviert systemd-time-wait-sync.service → time-sync.target wird erst erreicht,
#      wenn die Systemuhr TATSAECHLICH NTP-synchronisiert ist (nicht nur timesyncd gestartet).
#   2. Legt fuer jeden auf DIESEM Host installierten datenschreibenden Dienst ein
#      drop-in (After/Wants=time-sync.target) an → der Dienst startet erst nach gueltiger Zeit.
#
# Eigenschaften: idempotent, role-AGNOSTISCH (gated wird nur, was installiert ist),
# neustartfest (drop-ins + enable ueberdauern Reboots), reversibel (drop-ins entfernbar),
# systemkonform (offizieller systemd-Mechanismus, kein Code-Hack, keine Aenderung an
# den vorhandenen Unit-Dateien → venv-Pfade etc. bleiben unberuehrt).
#
# Aufruf (auf jedem Host, wo PV-Dienste laufen):  bash scripts/install_time_sync_gate.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DROPIN_SRC="$REPO_DIR/config/systemd/dropins/10-time-sync-gate.conf"
DROPIN_NAME="10-time-sync-gate.conf"

# Datenschreibende Dienste (Messdaten mit Zeitstempel). Nur installierte werden gated.
CANDIDATES=(
  pv-collector.service     # raw_data (Fronius Modbus)          — Primary
  pv-automation.service    # automation_log + zeitbasierte Regeln — Primary
  pv-wattpilot.service     # wattpilot_readings                  — Primary
  pv-observer.service      # Beobachter-Zustand                  — Primary
  pv-nq-poller.service     # PAC4200 Rohdaten                    — Tech
  pv-nq-energy.service     # PAC4200 Energie-Snapshots           — Tech
)

if [[ ! -f "$DROPIN_SRC" ]]; then
  echo "FEHLER: drop-in-Vorlage fehlt: $DROPIN_SRC" >&2
  exit 1
fi

echo "== Zeit-Sync-Gate auf $(hostname) =="

# 1) Uhr-Sync-Barriere aktivieren (idempotent).
if ! systemctl is-enabled systemd-time-wait-sync.service >/dev/null 2>&1; then
  echo "-> aktiviere systemd-time-wait-sync.service"
  sudo -n systemctl enable systemd-time-wait-sync.service
else
  echo "-> systemd-time-wait-sync.service bereits aktiv"
fi

# 2) drop-in je installiertem Dienst anlegen.
changed=0
for svc in "${CANDIDATES[@]}"; do
  # Nur wenn die Unit auf diesem Host existiert.
  if ! systemctl cat "$svc" >/dev/null 2>&1; then
    continue
  fi
  dst_dir="/etc/systemd/system/${svc}.d"
  dst="$dst_dir/$DROPIN_NAME"
  if [[ -f "$dst" ]] && sudo -n cmp -s "$DROPIN_SRC" "$dst"; then
    echo "-> $svc: drop-in aktuell"
    continue
  fi
  echo "-> $svc: drop-in installieren ($dst)"
  sudo -n mkdir -p "$dst_dir"
  sudo -n cp "$DROPIN_SRC" "$dst"
  sudo -n chmod 0644 "$dst"
  changed=1
done

# 3) systemd neu einlesen, wenn etwas geaendert wurde.
echo "-> daemon-reload"
sudo -n systemctl daemon-reload

# 4) Verifikation.
echo "== Verifikation =="
printf '%-24s %s\n' "systemd-time-wait-sync:" "$(systemctl is-enabled systemd-time-wait-sync.service 2>/dev/null || echo '?')"
for svc in "${CANDIDATES[@]}"; do
  systemctl cat "$svc" >/dev/null 2>&1 || continue
  after="$(systemctl show -p After --value "$svc" 2>/dev/null | tr ' ' '\n' | grep -c '^time-sync.target$' || true)"
  if [[ "$after" == "1" ]]; then
    printf '%-24s %s\n' "$svc" "After=time-sync.target ✓"
  else
    printf '%-24s %s\n' "$svc" "NICHT gegated ✗"
  fi
done

echo "Fertig. Wirkung ab naechstem Boot (Ordering-Abhaengigkeit). [changed=$changed]"
