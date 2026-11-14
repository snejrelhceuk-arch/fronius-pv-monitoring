#!/bin/bash
# ============================================================
# recovery/secrets_bundle.sh — portables, passphrase-verschluesseltes Secrets-Bundle
#
# Loest das machine-id-Problem: credential_store ist an /etc/machine-id gebunden
# und auf Ersatz-HW NICHT entschluesselbar. Dieses Bundle buendelt die
# Host-Identitaets-Geheimnisse (.infra.local, .secrets) passphrase-verschluesselt
# (gpg AES256) — unabhaengig von machine-id, damit sie auf neuer HW wiederher-
# stellbar sind. Danach wird der SMTP-Pass auf dem Ziel neu im (machine-id-
# gebundenen) credential_store hinterlegt (scripts/set_smtp_password.py).
#
# Ausgabe liegt in backup/recovery/ (gitignored!). NIEMALS ins git.
#
# Nutzung:
#   recovery/secrets_bundle.sh create                 # aus LOKALEM Host
#   recovery/secrets_bundle.sh restore --target u@ip --subpath <repo-subpath>
# ============================================================
set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib/recovery_common.sh"

OUT_DIR="$R_REPO_ROOT/backup/recovery"
mkdir -p "$OUT_DIR"; chmod 700 "$OUT_DIR"

SUB_CMD="${1:-}"; shift || true
command -v gpg >/dev/null 2>&1 || r_die "gpg fehlt"

case "$SUB_CMD" in
  create)
    HOSTROLE="$(head -1 "$R_REPO_ROOT/.role" 2>/dev/null | tr -d '[:space:]')"; HOSTROLE="${HOSTROLE:-unknown}"
    FILES=()
    for f in .infra.local .secrets; do [ -f "$R_REPO_ROOT/$f" ] && FILES+=("$f"); done
    [ "${#FILES[@]}" -gt 0 ] || r_die "keine Secrets-Dateien gefunden"
    OUT="$OUT_DIR/secrets_${HOSTROLE}.tar.gz.gpg"
    r_log "Erzeuge $OUT (Passphrase wird abgefragt) — Dateien: ${FILES[*]}"
    tar -C "$R_REPO_ROOT" -czf - "${FILES[@]}" \
      | gpg --symmetric --cipher-algo AES256 -o "$OUT"
    chmod 600 "$OUT"
    sha256sum "$OUT" | tee "$OUT.sha256"
    r_log "Fertig. Hinweis: SMTP-Pass auf dem ZIEL neu setzen (set_smtp_password.py)."
    ;;
  restore)
    TARGET=""; SUB=""
    while [ $# -gt 0 ]; do case "$1" in
      --target) shift; TARGET="${1:-}" ;;
      --subpath) shift; SUB="${1:-}" ;;
    esac; shift; done
    [ -n "$TARGET" ] && [ -n "$SUB" ] || r_die "restore benoetigt --target u@ip --subpath <pfad>"
    # Neuestes passendes Bundle waehlen
    BUNDLE="$(ls -1t "$OUT_DIR"/secrets_*.tar.gz.gpg 2>/dev/null | head -1)"
    [ -n "$BUNDLE" ] || r_die "kein Secrets-Bundle in $OUT_DIR"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    r_log "Entschluessle $BUNDLE (Passphrase)..."
    gpg -d "$BUNDLE" | tar -C "$TMP" -xzf - || r_die "Entschluesselung fehlgeschlagen"
    r_log "Uebertrage .infra.local/.secrets -> $TARGET:$SUB/ (0600)"
    for f in .infra.local .secrets; do
      [ -f "$TMP/$f" ] || continue
      rsync -a --chmod=F600 "$TMP/$f" "$TARGET:$SUB/$f"
    done
    r_log "Fertig. SMTP-Pass auf dem Ziel neu setzen: .venv/bin/python scripts/set_smtp_password.py"
    ;;
  *)
    echo "Nutzung: $0 {create|restore --target u@ip --subpath <pfad>}"; exit 2 ;;
esac
