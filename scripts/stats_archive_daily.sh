#!/bin/bash
# stats_archive_daily.sh — Tages-Archiv der permanenten 5-min-STATS-DB.
#
# Führt den gestrigen Tag aus der Live-RAM-DB in data_stats.db nach (permanent,
# SD) und synct die STATS-DB best-effort nach Pi5 und zum Failover.
# Cron (Primary): 20 0 * * *  (nach Tageswechsel, data_1min noch vorhanden)
#
# Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md, tools/build_stats_db.py
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${BASE}/scripts/load_infra_env.sh" 2>/dev/null || true
cd "$BASE"

# Nur auf dem Primary archivieren (Failover erhält die DB per Sync).
ROLE_FILE="${BASE}/.role"
if [ -f "$ROLE_FILE" ] && [ "$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')" = "failover" ]; then
  echo "$(date '+%F %T') Failover-Rolle → kein lokales Archiv (Sync-Empfänger)"
  exit 0
fi

PYBIN="${BASE}/.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN="/usr/bin/python3"

echo "$(date '+%F %T') Archiv-Lauf gestern → data_stats.db"
"$PYBIN" tools/build_stats_db.py --archive-daily

STATS="${BASE}/data_stats.db"
[ -f "$STATS" ] || exit 0

# Best-effort-Sync (Fehler dürfen den Job nicht abbrechen)
if [ -n "${PV_PI5_BACKUP_HOST:-}" ] && [ -n "${PV_PI5_BACKUP_BASE:-}" ]; then
  if rsync -az --timeout=60 "$STATS" "${PV_PI5_BACKUP_HOST}:${PV_PI5_BACKUP_BASE}/../" 2>/dev/null; then
    echo "$(date '+%F %T')   ✓ Pi5-Sync"
  else
    echo "$(date '+%F %T')   ⚠ Pi5-Sync fehlgeschlagen"
  fi
fi

if [ -n "${PV_FAILOVER_USER:-}" ] && [ -n "${PV_FAILOVER_IP:-}" ] && [ -n "${PV_FAILOVER_PV_BASE:-}" ]; then
  if rsync -az --timeout=60 "$STATS" "${PV_FAILOVER_USER}@${PV_FAILOVER_IP}:${PV_FAILOVER_PV_BASE}/" 2>/dev/null; then
    echo "$(date '+%F %T')   ✓ Failover-Sync"
  else
    echo "$(date '+%F %T')   ⚠ Failover-Sync fehlgeschlagen"
  fi
fi
