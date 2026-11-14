#!/bin/bash
# ============================================================
# recovery/rebuild_host.sh — Host-Rekonstruktion (Rolle R)
#
# Baut einen ZIEL-Host von einem QUELL-Host (Default: lokal) wieder auf, sobald
# auf dem Ziel ein SSH-faehiges Basis-System laeuft (Passwort bekannt, Key wird
# gepusht). Verallgemeinert das Reformation-Runbook zu einem wiederholbaren Tool.
#
# PRODUKTIONSSICHERHEIT:
#   * DRY-RUN ist DEFAULT. Echte Aenderungen nur mit --apply.
#   * Selbstschutz: der Host, auf dem das Skript laeuft, wird NIE Ziel.
#   * Kein Auto-Scharfschalten von Writern/Automation (Split-Brain-Schutz):
#     `.role=primary` + Writer-Start bleiben ein bewusster manueller Schritt.
#   * Idempotent: rsync/venv/Installer sind wiederholbar.
#
# Ablauf (je Stufe nur mit --apply):
#   0. --push-key : einmalig SSH-Key aufs Ziel bringen (ssh-copy-id, Passwort).
#   1. Code-rsync Quelle -> Ziel (tracked Working-Tree + .git, ohne Runtime).
#   2. Host-Identitaet setzen: .role (=Ziel-Rolle); .infra.local/.secrets aus
#      Recovery-Bundle (nur mit --with-secrets, Passphrase).
#   3. venv nativ bauen (requirements.txt).
#   4. systemd-Units/Timer + Cron per Manifest installieren (role-guarded).
#   5. Daten-Restore-Hinweis (gfs/mirror/none) + Smoke-Checks.
#
# Nutzung:
#   recovery/rebuild_host.sh <ziel-id> [--from <quell-id>] [--apply]
#                            [--push-key] [--with-secrets] [--yes]
#   recovery/rebuild_host.sh failover            # Dry-Run-Plan
#   recovery/rebuild_host.sh failover --apply     # tatsaechlich
# ============================================================
set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib/recovery_common.sh"
r_load_infra

TARGET_ID="${1:-}"; shift || true
[ -n "$TARGET_ID" ] || r_die "Ziel-Host-id fehlt. Bekannt: $(r_all_host_ids | tr '\n' ' ')"

FROM_ID=""; APPLY=""; PUSH_KEY=""; WITH_SECRETS=""; YES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) shift; FROM_ID="${1:-}" ;;
    --apply) APPLY=1 ;;
    --push-key) PUSH_KEY=1 ;;
    --with-secrets) WITH_SECRETS=1 ;;
    --yes|-y) YES=1 ;;
    *) r_die "unbekannter Parameter: $1" ;;
  esac; shift
done

[ -f "$R_HOSTS_DIR/$TARGET_ID.yaml" ] || r_die "kein Manifest fuer Ziel '$TARGET_ID'"
TARGET="$(r_target_for "$TARGET_ID")" || r_die "Ziel '$TARGET_ID' nicht aufloesbar (.infra.local?)"
TARGET_ROLE="$(r_role_for "$TARGET_ID")"
TARGET_SUB="$(r_repo_subpath_for "$TARGET_ID")"

# --- Selbstschutz: niemals den eigenen Host rekonstruieren ---------------
LOCAL_ROLE="$(head -1 "$R_REPO_ROOT/.role" 2>/dev/null | tr -d '[:space:]')"
if [ "$TARGET_ROLE" = "$LOCAL_ROLE" ]; then
  r_die "Ziel-Rolle '$TARGET_ROLE' == lokale Rolle. Ein Host rekonstruiert sich NICHT selbst."
fi

SRC_REPO="$R_REPO_ROOT"
if [ -n "$FROM_ID" ]; then
  r_warn "Remote-Quelle ($FROM_ID) nicht implementiert — nutze lokalen Working-Tree als Quelle."
fi

echo "=== R Rebuild: Ziel '$TARGET_ID' ($TARGET, role=$TARGET_ROLE) ==="
echo "Quelle: lokal $SRC_REPO  (HEAD $(r_head_short))"
echo "Ziel-Repo: ~/$TARGET_SUB"
[ -n "$APPLY" ] && echo "MODUS: --apply (echte Aenderungen)" || echo "MODUS: DRY-RUN (nur Plan; --apply fuer echt)"

do_or_echo() {  # fuehrt bei --apply aus, sonst nur anzeigen
  if [ -n "$APPLY" ]; then eval "$@"; else echo "  [dry-run] $*"; fi
}

# --- 0. Key-Push (einmalig, interaktiv mit Passwort) ---------------------
if [ -n "$PUSH_KEY" ]; then
  echo "--- 0. SSH-Key aufs Ziel bringen (Passwort wird abgefragt) ---"
  if r_ssh "$TARGET" true 2>/dev/null; then
    echo "  Key-Auth funktioniert bereits — nichts zu tun."
  else
    if [ -n "$APPLY" ]; then
      command -v ssh-copy-id >/dev/null 2>&1 || r_die "ssh-copy-id fehlt"
      ssh-copy-id "$TARGET" || r_die "Key-Push fehlgeschlagen"
    else
      echo "  [dry-run] ssh-copy-id $TARGET"
    fi
  fi
fi

# SSH-Erreichbarkeit (Key) ab hier Voraussetzung.
if ! r_ssh "$TARGET" true 2>/dev/null; then
  r_warn "Key-Auth zum Ziel noch nicht moeglich. Zuerst:  $0 $TARGET_ID --push-key --apply"
  [ -n "$APPLY" ] && r_die "Abbruch: keine Key-Auth."
fi

# Bestaetigung bei scharfem Lauf (Primary besonders).
if [ -n "$APPLY" ] && [ -z "$YES" ]; then
  [ "$TARGET_ROLE" = "primary" ] && echo "!! Ziel ist PRIMARY — besondere Vorsicht (Writer bleiben AUS)."
  read -r -p "Rebuild von '$TARGET_ID' ($TARGET) jetzt ausfuehren? (ja/N) " a
  [ "$a" = "ja" ] || { echo "Abgebrochen."; exit 0; }
fi

RSYNC_EXCLUDES=(
  --exclude='.venv/' --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal'
  --exclude='.state/' --exclude='*.log' --exclude='*.pid'
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='backup/' --exclude='imports/'
  --exclude='.role' --exclude='.secrets' --exclude='config/tls/'
)

# --- 1. Code-rsync (inkl. .git, ohne Runtime; .role/.secrets separat) ----
echo "--- 1. Code-Sync Quelle -> $TARGET:~/$TARGET_SUB ---"
do_or_echo "rsync -az --delete ${RSYNC_EXCLUDES[*]} '$SRC_REPO/' '$TARGET:$TARGET_SUB/'"

# --- 2. Host-Identitaet --------------------------------------------------
echo "--- 2. Host-Identitaet (.role=$TARGET_ROLE) ---"
do_or_echo "r_ssh '$TARGET' \"printf '%s\\n' '$TARGET_ROLE' > '$TARGET_SUB/.role'\""
if [ -n "$WITH_SECRETS" ]; then
  echo "  .infra.local/.secrets aus Recovery-Bundle (Passphrase):"
  do_or_echo "bash '$SELF_DIR/secrets_bundle.sh' restore --target '$TARGET' --subpath '$TARGET_SUB'"
else
  echo "  (ohne --with-secrets: .infra.local/.secrets manuell bereitstellen,"
  echo "   SMTP-Pass via scripts/set_smtp_password.py auf dem Ziel setzen)"
fi

# --- 3. venv nativ -------------------------------------------------------
echo "--- 3. venv nativ bauen ---"
do_or_echo "r_ssh '$TARGET' 'cd $TARGET_SUB && python3 -m venv .venv && .venv/bin/pip install -q -U pip && .venv/bin/pip install -q -r requirements.txt'"

# --- 4. Units/Timer/Cron per Manifest ------------------------------------
echo "--- 4. systemd/Installer (role-guarded) ---"
case "$TARGET_ROLE" in
  primary)
    do_or_echo "r_ssh '$TARGET' 'cd $TARGET_SUB && bash scripts/install_services.sh && bash scripts/install_nq_services.sh && bash scripts/install_maintenance_timers.sh && bash recovery/install_recovery.sh'"
    echo "  !! Writer/Automation NICHT automatisch — bewusst manuell nach Verifikation."
    ;;
  failover)
    do_or_echo "r_ssh '$TARGET' 'cd $TARGET_SUB && bash scripts/install_failover_services.sh'"
    ;;
  tech)
    do_or_echo "r_ssh '$TARGET' 'cd $TARGET_SUB && bash scripts/install_nq_services.sh'"
    echo "  Bridge (pv-wp-bridge) separat gemaess PI4_TECH_BRIDGE_HANDBUCH."
    ;;
  kueche)
    do_or_echo "r_ssh '$TARGET' 'cd $TARGET_SUB && bash scripts/install_kiosk_autostart.sh'"
    ;;
esac

# --- 5. Daten-Restore-Hinweis + Smoke ------------------------------------
DR="$(awk -F': *' '/data_restore:/{print $2; exit}' "$R_HOSTS_DIR/$TARGET_ID.yaml" | sed 's/#.*//' | tr -d '[:space:]')"
echo "--- 5. Daten-Restore: $DR ---"
case "$DR" in
  mirror) echo "  data.db kommt per pv-mirror-sync vom Primary (automatisch)." ;;
  gfs)    echo "  data.db aus GFS wiederherstellen (doc/system/BACKUP_STRATEGY.md §4)." ;;
  none)   echo "  keine Produktions-DB auf diesem Host." ;;
esac
echo "  Smoke: r_ssh $TARGET 'systemctl is-active ...'; recovery/verify_integration.sh auf dem Ziel."

echo ""
echo "=== Rebuild-Plan $([ -n "$APPLY" ] && echo 'AUSGEFUEHRT' || echo '(Dry-Run)') fuer '$TARGET_ID' abgeschlossen ==="
