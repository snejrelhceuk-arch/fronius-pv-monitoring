#!/bin/bash
# ============================================================
# recovery/build_recovery_bundle.sh — Gesamtpaket-Builder (Rolle R)
#
# Erzeugt ein self-contained Disaster-Recovery-Paket je Host (auf jedem Host
# vorhaltbar), mit dem sich andere Pis umfassend rekonstruieren lassen:
#   * git-Bundle (volle History, --all) = Code + Doku + Manifeste
#   * requirements.txt-Schnappschuss
#   * Host-Manifeste + Recovery-Doku (sind im Bundle enthalten)
#   * MANIFEST.txt: Major-Version, HEAD, Zeit, sha256-Summen
#   * optional (--with-secrets): passphrase-verschluesseltes Secrets-Bundle
#
# Aktualitaet ist an die MAJOR-Version (Ganzzahl aus git-Tag vN) gekoppelt:
# der Dateiname traegt vN, der Selfcheck mahnt bei Major-Sprung.
#
# Ausgabe: backup/recovery/ (gitignored). Nutzung:
#   recovery/build_recovery_bundle.sh [--with-secrets]
# ============================================================
set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib/recovery_common.sh"

WITH_SECRETS=""
for a in "$@"; do [ "$a" = "--with-secrets" ] && WITH_SECRETS=1; done

OUT_DIR="$R_REPO_ROOT/backup/recovery"
mkdir -p "$OUT_DIR"
MAJOR="$(r_current_major)"
HEAD="$(r_head_short)"
STAMP="$(date +%Y%m%d)"
BASE="pv-system-recovery-v${MAJOR}-${HEAD}-${STAMP}"
WORK="$OUT_DIR/$BASE"
mkdir -p "$WORK"

r_log "Baue Recovery-Paket $BASE (Major v$MAJOR, HEAD $HEAD)"

# 1. git-Bundle (volle History inkl. aller Branches/Tags)
git -C "$R_REPO_ROOT" -c "safe.directory=$R_REPO_ROOT" bundle create "$WORK/repo.bundle" --all \
  || r_die "git bundle fehlgeschlagen"

# 2. requirements-Schnappschuss + Kurz-Readme
cp "$R_REPO_ROOT/requirements.txt" "$WORK/requirements.txt" 2>/dev/null || true
cat > "$WORK/README.txt" <<EOF
PV-System Recovery-Paket
Major-Version : v$MAJOR
HEAD          : $HEAD
Erstellt      : $(date '+%F %T')

Wiederherstellung (Kurz):
  git clone repo.bundle pv-system && cd pv-system
  git checkout main
  # .role/.infra.local/.secrets aus Secrets-Bundle (secrets_*.tar.gz.gpg)
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  # Rollen-Rollout: recovery/rebuild_host.sh <ziel> --apply
Vollstaendige Anleitung: doc/system/RECOVERY.md (im Bundle).
EOF

# 3. optional Secrets-Bundle beilegen
if [ -n "$WITH_SECRETS" ]; then
  bash "$SELF_DIR/secrets_bundle.sh" create || r_warn "Secrets-Bundle fehlgeschlagen"
  cp "$OUT_DIR"/secrets_*.tar.gz.gpg "$WORK/" 2>/dev/null || true
fi

# 4. MANIFEST.txt + Checksummen
{
  echo "major=v$MAJOR"
  echo "head=$HEAD"
  echo "created=$(date -u +%FT%TZ)"
  echo "with_secrets=${WITH_SECRETS:-0}"
  echo "--- sha256 ---"
  ( cd "$WORK" && sha256sum ./* 2>/dev/null )
} > "$WORK/MANIFEST.txt"

# 5. Paket packen + Versions-Marker fuer Selfcheck/USB
TAR="$OUT_DIR/$BASE.tar.gz"
tar -C "$OUT_DIR" -czf "$TAR" "$BASE"
sha256sum "$TAR" > "$TAR.sha256"
echo "v$MAJOR $HEAD $(date -u +%FT%TZ) $BASE.tar.gz" > "$OUT_DIR/LATEST_RECOVERY"
rm -rf "$WORK"

r_log "Fertig: $TAR"
r_log "Aktualitaets-Marker: $OUT_DIR/LATEST_RECOVERY (Major v$MAJOR)"
