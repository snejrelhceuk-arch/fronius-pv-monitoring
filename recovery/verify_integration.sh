#!/bin/bash
# ============================================================
# recovery/verify_integration.sh — Integrations-/Tagging-Drift-Verifier (Rolle R)
#
# Vergleicht die DEKLARIERTE Systemintegration (Host-Manifest + system_files.yaml)
# mit dem TATSAECHLICHEN OS-Zustand des LOKALEN Hosts:
#   * systemd pv-* Units: deklariert (Manifest role) <-> installiert (/etc/systemd)
#     -> "fehlend" (deklariert, nicht installiert) und "verwaist" (installiert,
#        nicht deklariert) werden gemeldet.
#   * /etc/pv-system (Secret-Store), ufw-Status, pv-relevante Crontab-Zeilen.
#
# Defensiv: Exit 0 (reine Meldung), ausser --strict -> Exit 1 bei Drift.
# Nutzung:  recovery/verify_integration.sh [--strict] [--role <id>]
# ============================================================
set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=recovery/lib/recovery_common.sh
. "$SELF_DIR/lib/recovery_common.sh"
r_load_infra

STRICT=""; FORCE_ROLE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) STRICT=1 ;;
    --role) shift; FORCE_ROLE="${1:-}" ;;
  esac; shift
done

ROLE="${FORCE_ROLE:-$(head -1 "$R_REPO_ROOT/.role" 2>/dev/null | tr -d '[:space:]')}"
ROLE="${ROLE:-primary}"
MANIFEST="$R_HOSTS_DIR/$ROLE.yaml"
PY="$R_REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "=== R Integrations-Verifier — Host-Rolle: $ROLE ==="
[ -f "$MANIFEST" ] || { r_warn "kein Manifest fuer Rolle '$ROLE' — Abbruch (kein Fehler)"; exit 0; }

declared() {  # $1 = services|timers -> eine Zeile je Eintrag
  "$PY" - "$MANIFEST" "$1" <<'PY'
import sys, yaml
m = yaml.safe_load(open(sys.argv[1])) or {}
for x in (m.get(sys.argv[2]) or []):
    s = str(x).split('#')[0].strip()
    if s and (s.endswith('.service') or s.endswith('.timer')):
        print(s)
PY
}

DRIFT=0

check_units() {
  local kind="$1" suffix="$2" decl inst
  decl="$(declared "$kind")"
  # Backing-Services deklarierter Timer gelten als deklariert (pv-x.timer -> pv-x.service).
  if [ "$kind" = "services" ]; then
    local timer_svcs
    timer_svcs="$(declared timers | sed 's/\.timer$/.service/')"
    decl="$(printf '%s\n%s\n' "$decl" "$timer_svcs" | sort -u | sed '/^$/d')"
  fi
  inst="$(ls /etc/systemd/system/pv-*."$suffix" 2>/dev/null | xargs -r -n1 basename)"
  echo ""
  echo "--- $kind ($suffix) ---"
  # fehlend: deklariert, aber nicht installiert
  while IFS= read -r u; do
    [ -z "$u" ] && continue
    if ! grep -qxF "$u" <<<"$inst"; then
      echo "  FEHLT (deklariert, nicht installiert): $u"; DRIFT=$((DRIFT+1))
    fi
  done <<<"$decl"
  # verwaist: installiert, aber nicht deklariert (Info — evtl. anderer Installer)
  while IFS= read -r u; do
    [ -z "$u" ] && continue
    if ! grep -qxF "$u" <<<"$decl"; then
      echo "  verwaist? (installiert, nicht im Manifest): $u"
    fi
  done <<<"$inst"
}

check_units services service
check_units timers   timer

echo ""
echo "--- weitere Integration ---"
[ -d /etc/pv-system ] && echo "  /etc/pv-system: vorhanden" || { echo "  /etc/pv-system: FEHLT (Secret-Store)"; DRIFT=$((DRIFT+1)); }
if command -v ufw >/dev/null 2>&1; then
  ufw status 2>/dev/null | grep -qi 'Status: active' && echo "  ufw: active" || echo "  ufw: INAKTIV"
fi
CRON_PV="$(crontab -l 2>/dev/null | grep -cE 'pv-system|aggregate|backup_.*gfs|wp_thermal' || true)"
echo "  Crontab pv-Zeilen: ${CRON_PV:-0}"

echo ""
if [ "$DRIFT" -eq 0 ]; then
  echo "=== Ergebnis: Integration konsistent zum Manifest ==="
  exit 0
fi
echo "=== Ergebnis: $DRIFT Integrations-Drift(s) — Re-Install pruefen ==="
[ -n "$STRICT" ] && exit 1
exit 0
