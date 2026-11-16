#!/usr/bin/env python3
"""
Rückrekonstruktion & Pflege der dynamischen Tarif-Schiene (Rolle A, Orchestrierung).

Führt in einem Lauf aus:
  1. Spot-Preise holen  (collector.dynamic_price)
  2. Kosten aggregieren (collector.aggregate.tariff_cost)
  3. Permanent spiegeln  (tools.build_tiered_dbs --sync der 4 Tarif-Tabellen)

Damit ist die Historie nach dem Backfill sofort in analysis.db persistent (nicht
nur in der RAM-DB). Default-Range = config.DYN_TARIF_START … heute (volle
2026-Rekonstruktion). Idempotent.

Beispiele:
  python -m tools.backfill_dynamic_price                 # ganzes 2026 bis heute
  python -m tools.backfill_dynamic_price --from 2026-10-01
  python -m tools.backfill_dynamic_price --no-sync       # ohne analysis.db-Spiegel
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import date, datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config  # noqa: E402
from collector import dynamic_price  # noqa: E402
from collector.aggregate import tariff_cost  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('backfill_dynamic_price')

_TARIFF_TABLES = ['spot_price_15min', 'tariff_cost_daily',
                  'tariff_cost_monthly', 'tariff_cost_yearly']


def _sync_to_analysis() -> None:
    """Spiegelt die Tarif-Tabellen RAM→analysis.db (Upsert, Historie bewahrt)."""
    from tools import build_tiered_dbs as btd
    btd.sync(config.ANALYSIS_DB_PATH, config.DB_PATH, _TARIFF_TABLES)


def main() -> int:
    ap = argparse.ArgumentParser(description='Dynamische Tarif-Schiene rückrekonstruieren')
    ap.add_argument('--from', dest='dfrom', help='Startdatum YYYY-MM-DD (Default DYN_TARIF_START)')
    ap.add_argument('--to', dest='dto', help='Enddatum YYYY-MM-DD (Default heute)')
    ap.add_argument('--no-sync', action='store_true', help='analysis.db-Spiegel überspringen')
    args = ap.parse_args()

    if args.dfrom:
        d0 = datetime.strptime(args.dfrom, '%Y-%m-%d').date()
    else:
        y, m, d = config.DYN_TARIF_START
        d0 = date(y, m, d)
    d1 = datetime.strptime(args.dto, '%Y-%m-%d').date() if args.dto else date.today()

    logger.info("Spot-Preise holen %s … %s", d0, d1)
    dynamic_price.run(d0, d1)

    logger.info("Kosten aggregieren %s … %s", d0, d1)
    conn = tariff_cost._open()
    try:
        n = tariff_cost.aggregate_range(conn, d0, d1)
    finally:
        conn.close()
    logger.info("%d Tage aggregiert", n)

    if not args.no_sync:
        logger.info("Spiegeln nach analysis.db")
        _sync_to_analysis()

    logger.info("Rückrekonstruktion abgeschlossen.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
