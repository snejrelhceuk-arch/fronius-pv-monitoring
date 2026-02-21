#!/bin/bash
set -euo pipefail

# =============================================================
# Repo-Paritätscheck: Primary ↔ Failover
#
# Prüft NUR versionierte Systemdateien (tracked files):
# - Commit-Gleichstand
# - lokale tracked Änderungen auf beiden Seiten
#
# Ignoriert bewusst Runtime-Daten/Untracked (DB, .state, Logs, .role, ...).
#
# Nutzung:
#   ./scripts/check_repo_parity.sh
#   ./scripts/check_repo_parity.sh /mnt/failover-pv
# =============================================================

PEER_REPO="${1:-/mnt/failover-pv}"

LOCAL_REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$LOCAL_REPO" ]; then
  echo "FEHLER: Aktuelles Verzeichnis ist kein Git-Repository."
  exit 2
fi

if [ ! -d "$PEER_REPO/.git" ]; then
  echo "FEHLER: Peer-Repository nicht gefunden: $PEER_REPO"
  echo "Hinweis: SSHFS-Mount aktiv? (z.B. /mnt/failover-pv)"
  exit 2
fi

if ! git -C "$PEER_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FEHLER: Peer-Pfad ist kein gültiges Git-Repo: $PEER_REPO"
  exit 2
fi

local_branch="$(git -C "$LOCAL_REPO" branch --show-current || echo '-')"
peer_branch="$(git -C "$PEER_REPO" branch --show-current || echo '-')"
local_head="$(git -C "$LOCAL_REPO" rev-parse HEAD)"
peer_head="$(git -C "$PEER_REPO" rev-parse HEAD)"

local_tracked_changes="$(git -C "$LOCAL_REPO" status --porcelain --untracked-files=no | wc -l | tr -d ' ')"
peer_tracked_changes="$(git -C "$PEER_REPO" status --porcelain --untracked-files=no | wc -l | tr -d ' ')"

echo "=== Repo-Paritätscheck (tracked Systemdateien) ==="
echo "Local: $LOCAL_REPO"
echo "Peer : $PEER_REPO"
echo
echo "Branch local : $local_branch"
echo "Branch peer  : $peer_branch"
echo "HEAD local   : ${local_head:0:12}"
echo "HEAD peer    : ${peer_head:0:12}"
echo

commit_ok=1
if [ "$local_head" = "$peer_head" ]; then
  echo "Commit-Stand : OK (identisch)"
  commit_ok=0
else
  echo "Commit-Stand : DRIFT (nicht identisch)"

  local_only="?"
  peer_only="?"

  if local_only_tmp=$(git -C "$LOCAL_REPO" rev-list --count "$peer_head..$local_head" 2>/dev/null); then
    local_only="$local_only_tmp"
  fi
  if peer_only_tmp=$(git -C "$PEER_REPO" rev-list --count "$local_head..$peer_head" 2>/dev/null); then
    peer_only="$peer_only_tmp"
  fi

  echo "  Commits nur local: $local_only"
  echo "  Commits nur peer : $peer_only"
fi

echo
echo "Tracked Änderungen local: $local_tracked_changes"
if [ "$local_tracked_changes" -gt 0 ]; then
  git -C "$LOCAL_REPO" status --short --untracked-files=no | sed 's/^/  local: /'
fi

echo "Tracked Änderungen peer : $peer_tracked_changes"
if [ "$peer_tracked_changes" -gt 0 ]; then
  git -C "$PEER_REPO" status --short --untracked-files=no | sed 's/^/  peer : /'
fi

echo
if [ "$commit_ok" -eq 0 ] && [ "$local_tracked_changes" -eq 0 ] && [ "$peer_tracked_changes" -eq 0 ]; then
  echo "ERGEBNIS: ✅ Systemdateien synchron (clone-parität OK)."
  exit 0
fi

echo "ERGEBNIS: ❌ Drift vorhanden (Commit- und/oder tracked Dateidifferenzen)."
echo "Empfehlung:"
echo "  1) Auf 181 tracked Änderungen committen/stashen"
echo "  2) Push auf origin"
echo "  3) Auf 182 fast-forward pull"
echo "  4) Check erneut ausführen"
exit 1
