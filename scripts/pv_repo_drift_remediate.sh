#!/bin/bash
# ============================================================
# scripts/pv_repo_drift_remediate.sh
# Repo-Drift-Automatik (Primary <-> Pis), Intervall 10 Tage.
#
# Politik (vom Betreiber festgelegt):
#   * Auto-COMMIT lokaler tracked-Drift auf Primary: JA (lokal, mit Hook).
#   * Auto-PUSH: NEIN. origin bleibt unberuehrt.
#   * Peers (FB/Tech/Kueche) werden per rsync auf den Primary-Stand gebracht
#     (Deploy-Policy autorisiert) und ihre Dienste ueber die vorhandenen
#     Sync-Skripte neu gestartet.
#   * Ergebnis geht per Mail raus.
#
# Nur auf Primary sinnvoll. Vollstaendig defensiv: Einzelfehler brechen den Lauf
# nicht ab; Exit immer 0 (Oneshot-Timer soll nie "failed" melden). Selbstpruefend:
# fehlende Peers/Skripte werden gemeldet, nicht als Fehler gewertet.
#
# Nutzung:
#   bash scripts/pv_repo_drift_remediate.sh [--dry-run] [--no-mail]
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"
# shellcheck disable=SC1090
[ -f "$BASE/.infra.local" ] && { set -a; . "$BASE/.infra.local"; set +a; }

DRY=""; NOMAIL=""
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY="1" ;;
    --no-mail) NOMAIL="1" ;;
  esac
done

ROLE="$(head -1 "$BASE/.role" 2>/dev/null | tr -d '[:space:]')"
REPORT="$(mktemp)"
trap 'rm -f "$REPORT"' EXIT

log() { echo "$@" | tee -a "$REPORT"; }

log "=== PV Repo-Drift-Remediation $(date '+%F %T') ==="
log "Host-Rolle: ${ROLE:-?}"

if [ "$ROLE" != "primary" ]; then
  log "Nur auf Primary vorgesehen — Abbruch (kein Fehler)."
  exit 0
fi

GITSAFE=(git -c "safe.directory=$BASE")

# --- 1. Lokale tracked-Drift auf Primary -> Auto-Commit (kein Push) -------
DIRTY="$("${GITSAFE[@]}" status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
log ""
log "1) Lokale tracked-Drift auf Primary: $DIRTY Datei(en)"
if [ "$DIRTY" -gt 0 ]; then
  "${GITSAFE[@]}" status --short --untracked-files=no | sed 's/^/   /' | tee -a "$REPORT"
  if [ -n "$DRY" ]; then
    log "   [dry-run] wuerde 'git add -u' + lokalen Commit anlegen (kein Push)."
  else
    "${GITSAFE[@]}" add -u
    MSG="chore(drift): Auto-Commit lokaler tracked-Drift (Repo-Drift-Automatik)

Automatisch durch scripts/pv_repo_drift_remediate.sh erzeugt.
Kein Push — origin bleibt unberuehrt (Betreiber-Policy).

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    if "${GITSAFE[@]}" commit -m "$MSG" >>"$REPORT" 2>&1; then
      log "   -> lokaler Commit angelegt: $("${GITSAFE[@]}" rev-parse --short HEAD)"
    else
      log "   -> Commit FEHLGESCHLAGEN (z. B. pre-commit-Hook). Drift bleibt liegen, bitte manuell."
    fi
  fi
else
  log "   keine lokale Drift."
fi

LOCAL_HEAD="$("${GITSAFE[@]}" rev-parse HEAD 2>/dev/null || echo '?')"
log ""
log "2) Primary HEAD: ${LOCAL_HEAD:0:12}"
UNPUSHED="$("${GITSAFE[@]}" log --oneline '@{u}..HEAD' 2>/dev/null | wc -l | tr -d ' ' || echo '?')"
log "   Nicht gepushte Commits (nur Info, KEIN Auto-Push): $UNPUSHED"

# --- 3. Peers auf Primary-Stand bringen ----------------------------------
log ""
log "3) Peers angleichen (rsync via vorhandene Sync-Skripte)"
run_sync() {
  local label="$1"; shift
  log "   -> $label"
  if [ -n "$DRY" ]; then
    log "      [dry-run] $*"
    return 0
  fi
  if "$@" >>"$REPORT" 2>&1; then
    log "      OK"
  else
    log "      FEHLER/uebersprungen (siehe Log)"
  fi
}
[ -x "$BASE/scripts/sync_code_to_peer.sh" ] && run_sync "Failover (FB)"  bash "$BASE/scripts/sync_code_to_peer.sh" --force
[ -x "$BASE/scripts/sync_code_to_tech.sh" ] && run_sync "Tech"           bash "$BASE/scripts/sync_code_to_tech.sh" --force

# --- 4. HEAD-Parität aller Sync-Hosts prüfen -----------------------------
log ""
log "4) Commit-Parität der Peers:"
REMOTE_PATH="${PV_SYNC_REMOTE_PATH:-Dokumente/PVAnlage/pv-system}"
DRIFT_HOSTS=0
for hostspec in ${PV_SYNC_HOSTS:-}; do
  rh="$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$hostspec" \
        "git -c safe.directory='\$HOME/$REMOTE_PATH' -C \"\$HOME/$REMOTE_PATH\" rev-parse HEAD" 2>/dev/null || echo '')"
  if [ -z "$rh" ]; then
    log "   $hostspec: nicht erreichbar / kein Repo (uebersprungen)"
  elif [ "$rh" = "$LOCAL_HEAD" ]; then
    log "   $hostspec: OK (${rh:0:12})"
  else
    DRIFT_HOSTS=$((DRIFT_HOSTS+1))
    log "   $hostspec: DRIFT (${rh:0:12} != ${LOCAL_HEAD:0:12})"
  fi
done

log ""
log "=== Ergebnis: $([ "$DRIFT_HOSTS" -eq 0 ] && echo 'alle Peers synchron' || echo "$DRIFT_HOSTS Peer(s) weiterhin mit Drift") ==="

# --- 5. Mail ------------------------------------------------------------
if [ -z "$NOMAIL" ] && [ -z "$DRY" ]; then
  SUBJECT="[PV-Repo-Drift] $(hostname): $([ "$DRIFT_HOSTS" -eq 0 ] && echo 'synchron' || echo "$DRIFT_HOSTS Peer-Drift")"
  "$BASE/.venv/bin/python" - "$SUBJECT" <<PY 2>/dev/null || true
import sys
sys.path.insert(0, "$BASE/scripts"); sys.path.insert(0, "$BASE")
from pv_notify import send_mail
body = open("$REPORT", encoding="utf-8", errors="replace").read()
send_mail(sys.argv[1], body, event="repo_drift")
PY
fi
exit 0
