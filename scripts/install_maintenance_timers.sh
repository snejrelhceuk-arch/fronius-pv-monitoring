#!/bin/bash
# ============================================================
# scripts/install_maintenance_timers.sh
# Installiert die Drift-/Abgleich-Automatik-Timer (nur Primary):
#   pv-repo-drift.{service,timer}        ~10 Tage  — Repo-Drift-Remediation
#   pv-doc-drift-report.{service,timer}  ~20 Tage  — Doku-Drift-Report (Mail)
#   pv-solarweb-compare.{service,timer}  monatlich — Solarweb-Abgleich
#
# Die Update/Upgrade-Strategie (pv-auto-update) gehoert zu Rolle R und wird von
# recovery/install_recovery.sh installiert.
#
# Idempotent (install -m 0644 + daemon-reload + enable --now), spiegelt die
# Konvention von install_nq_services.sh. Alle Timer Persistent=true -> Catch-up
# nach Downtime (neustart-fest). Aufruf:  scripts/install_maintenance_timers.sh
# ============================================================
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$BASE/config/systemd"
DST="/etc/systemd/system"

PV_ROLE_GUARD_AUTO=0 source "${BASE}/scripts/role_guard.sh"
ROLE="$PV_ROLE"
echo "=== Wartungs-/Drift-Timer installieren (Rolle: $ROLE) ==="
if [ "$ROLE" != "primary" ]; then
  echo "Nur auf Primary vorgesehen (Quelle der Wahrheit). Nichts zu tun."
  exit 0
fi

_BASE_REAL="$(readlink -f "$BASE")"

validate_working_directory() {
  local unit="$1" wd
  wd="$(awk -F= '/^WorkingDirectory=/ {print $2; exit}' "$SRC/$unit")"
  [ -z "$wd" ] && return 0
  wd="${wd//%h/$HOME}"
  [ -d "$wd" ] || { echo "  ✗ $unit: WorkingDirectory fehlt: $wd" >&2; return 1; }
  [ "$(readlink -f "$wd")" = "$_BASE_REAL" ] || {
    echo "  ✗ $unit: WorkingDirectory != Workspace: $wd" >&2; return 1; }
}

install_unit() {
  local unit="$1"
  [ -f "$SRC/$unit" ] || { echo "  ✗ $unit fehlt in $SRC"; return 1; }
  validate_working_directory "$unit"
  sudo install -m 0644 "$SRC/$unit" "$DST/$unit"
  echo "  ✓ $unit installiert"
}

TIMERS=()
for u in \
  pv-repo-drift.service        pv-repo-drift.timer \
  pv-doc-drift-report.service  pv-doc-drift-report.timer \
  pv-solarweb-compare.service  pv-solarweb-compare.timer; do
  install_unit "$u" || true
  [[ "$u" == *.timer ]] && TIMERS+=("$u")
done

sudo systemctl daemon-reload
for t in "${TIMERS[@]}"; do
  sudo systemctl enable --now "$t"
  echo "  ▶ $t enabled+started"
done

echo ""
echo "=== Status ==="
systemctl list-timers 'pv-repo-drift*' 'pv-doc-drift-report*' 'pv-solarweb-compare*' --no-pager || true
echo ""
echo "Hinweis: pv-auto-update (Update/Upgrade-Strategie) wird von Rolle R installiert:"
echo "  bash recovery/install_recovery.sh"
echo "=== fertig ==="
