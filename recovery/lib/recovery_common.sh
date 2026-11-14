#!/bin/bash
# ============================================================
# recovery/lib/recovery_common.sh — gemeinsame Helfer der Rolle R
# Wird von recovery/*.sh gesourct. Keine Seiteneffekte beim Sourcen
# ausser Variablen/Funktionsdefinitionen.
# ============================================================

# Repo-Root robust bestimmen (lib liegt in recovery/lib/).
if [ -z "${R_REPO_ROOT:-}" ]; then
  R_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
R_RECOVERY_DIR="$R_REPO_ROOT/recovery"
R_HOSTS_DIR="$R_RECOVERY_DIR/hosts"

# Infra-Env laden (echte IPs/User/Pfade liegen NUR hier, gitignored).
r_load_infra() {
  if [ -f "$R_REPO_ROOT/.infra.local" ]; then
    set -a; # shellcheck disable=SC1091
    . "$R_REPO_ROOT/.infra.local"; set +a
  fi
}

r_log() { echo "[R $(date '+%F %T')] $*"; }
r_warn() { echo "[R WARN] $*" >&2; }
r_die()  { echo "[R FEHLER] $*" >&2; exit 1; }

# Login-Ziel (user@ip) fuer eine Host-id aus Manifest + .infra.local aufloesen.
# Echo: "user@ip" oder leer, wenn nicht aufloesbar.
r_target_for() {
  local id="$1" manifest="$R_HOSTS_DIR/$1.yaml" user ipenv ip
  [ -f "$manifest" ] || { r_warn "kein Manifest: $manifest"; return 1; }
  user="$(awk -F': *' '/^user:/{print $2; exit}' "$manifest" | tr -d '[:space:]')"
  ipenv="$(awk -F': *' '/^ip_env:/{print $2; exit}' "$manifest" | tr -d '[:space:]')"
  ip="${!ipenv:-}"
  [ -n "$user" ] && [ -n "$ip" ] || return 1
  echo "${user}@${ip}"
}

# Repo-Pfad (relativ zum Home) aus Manifest.
r_repo_subpath_for() {
  awk -F': *' '/^repo_subpath:/{print $2; exit}' "$R_HOSTS_DIR/$1.yaml" | tr -d '[:space:]'
}

r_role_for() {
  awk -F': *' '/^role:/{print $2; exit}' "$R_HOSTS_DIR/$1.yaml" | tr -d '[:space:]'
}

# SSH mit sicheren Defaults (Key-Auth, BatchMode). Zusatzargumente moeglich.
r_ssh() {
  local target="$1"; shift
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$target" "$@"
}

# Aktuelle Major-Version (Ganzzahl) aus git-Tags vN.x.y; Fallback 0.
r_current_major() {
  local tag
  tag="$(git -C "$R_REPO_ROOT" tag 2>/dev/null | grep -E '^v[0-9]+\.' | sort -V | tail -1)"
  [ -n "$tag" ] && echo "${tag#v}" | cut -d. -f1 || echo 0
}

r_head_short() {
  git -C "$R_REPO_ROOT" -c "safe.directory=$R_REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?'
}

r_all_host_ids() {
  local f
  for f in "$R_HOSTS_DIR"/*.yaml; do
    [ -e "$f" ] || continue
    basename "$f" .yaml
  done
}
