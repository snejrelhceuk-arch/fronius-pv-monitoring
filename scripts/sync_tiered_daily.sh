#!/bin/bash
# =================================================================
# sync_tiered_daily.sh — Stage 2 Schatten-Writer der 3-Stufen-Datenhaltung
# =================================================================
#
# Hält die beiden permanenten SD-DBs parallel zur Produktion aktuell:
#   monitoring.db (Stufe 2, 5-min)  ← direkt aus RAM-DB (data_1min + readings)
#   analysis.db   (Stufe 3, Tag)    ← aus RAM-DB (daily_data etc., voller Rebuild)
#
# PARALLEL-BETRIEB: Solange der Cutover (Stage 4) nicht erfolgt ist, bleibt die
# bestehende Produktion (RAM-DB-Tabellen, data_stats.db via stats_archive_daily.sh)
# unverändert. Dieses Skript füttert nur die neuen Tier-DBs (Schattenbetrieb),
# damit sie Tag-über-Tag verifizierbar mitlaufen.
#
# Cron (Primary): 35 0 * * *   (nach stats_archive_daily.sh um 0:20)
#
# Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md, tools/build_tiered_dbs.py
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${BASE}/scripts/load_infra_env.sh" 2>/dev/null || true
cd "$BASE"

# Nur auf dem Primary (Failover/Tech sind Sync-Empfänger).
ROLE_FILE="${BASE}/.role"
if [ -f "$ROLE_FILE" ] && [ "$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')" != "primary" ]; then
  echo "$(date '+%F %T') Rolle != primary → kein Tier-Sync"
  exit 0
fi

PYBIN="${BASE}/.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN="/usr/bin/python3"

MON_DB="${BASE}/monitoring.db"
ANA_DB="${BASE}/analysis.db"

echo "$(date '+%F %T') Tier-Sync: monitoring.db (5-min, aus RAM) + analysis.db (Tag)"

# Stufe 2: gestrigen Tag (inkl. per-Gerät) aus der RAM-DB in monitoring.db.
"$PYBIN" tools/build_stats_db.py --archive-daily --stats-db "$MON_DB"

# Stufe 3: analysis.db komplett aus der RAM-DB neu aufbauen (winzig, idempotent).
"$PYBIN" tools/build_tiered_dbs.py --build --only analysis

# Best-effort-Sync zu Pi5 + Failover (Fehler brechen den Job nicht ab).
for DB in "$MON_DB" "$ANA_DB"; do
  [ -f "$DB" ] || continue
  if [ -n "${PV_PI5_BACKUP_HOST:-}" ] && [ -n "${PV_PI5_BACKUP_BASE:-}" ]; then
    rsync -az --timeout=60 "$DB" "${PV_PI5_BACKUP_HOST}:${PV_PI5_BACKUP_BASE}/../" 2>/dev/null \
      && echo "$(date '+%F %T')   ✓ Pi5-Sync $(basename "$DB")" \
      || echo "$(date '+%F %T')   ⚠ Pi5-Sync $(basename "$DB") fehlgeschlagen"
  fi
  if [ -n "${PV_FAILOVER_USER:-}" ] && [ -n "${PV_FAILOVER_IP:-}" ] && [ -n "${PV_FAILOVER_PV_BASE:-}" ]; then
    rsync -az --timeout=60 "$DB" "${PV_FAILOVER_USER}@${PV_FAILOVER_IP}:${PV_FAILOVER_PV_BASE}/" 2>/dev/null \
      && echo "$(date '+%F %T')   ✓ Failover-Sync $(basename "$DB")" \
      || echo "$(date '+%F %T')   ⚠ Failover-Sync $(basename "$DB") fehlgeschlagen"
  fi
done

echo "$(date '+%F %T') Tier-Sync abgeschlossen"
