#!/usr/bin/env python3
"""
Dynamischer Börsentarif — Spot-Preis-Collector (Rolle A).

Holt die EPEX Day-Ahead Preise (Marktgebiet DE-LU, 15-min) von der freien
Fraunhofer-ISE-API ``api.energy-charts.info`` (CC BY 4.0, kein Key) und schreibt
sie in ``spot_price_15min`` (EUR/MWh, permanent). Das ist die Börsen-Basis, die
auch Tibber/aWATTar abrechnen.

Rolle A: schreibt ausschliesslich die eigene Preis-Tabelle in der Daten-DB
(``config.DB_PATH``, RAM) — die Tiered-Sync spiegelt sie nach analysis.db. KEIN
Hardware-Zugriff, keine Aktorik.

Betrieb:
  * Täglich (Day-Ahead erscheint ~13:00 für den Folgetag): ``--days-forward 1``
    holt heute+morgen, ``--backfill-days N`` schliesst Lücken rückwirkend.
  * Rückrekonstruktion 2026: ``--from 2026-01-01 --to 2026-11-15``.
Idempotent (INSERT OR REPLACE auf ts).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('dynamic_price')

_API = 'https://api.energy-charts.info/price'
_UA = 'pv-system/dynamic-price (energy-charts CC BY 4.0)'


def _bzn() -> str:
    return config.DYN_TARIF.get('bidding_zone', 'DE-LU')


def fetch_prices(day_from: date, day_to: date, retries: int = 4) -> dict[int, float]:
    """Holt EPEX Day-Ahead Preise [day_from, day_to] → {ts: EUR/MWh}.

    energy-charts liefert pro Request mehrere Tage; wir fragen in Blöcken ≤31 Tage
    ab und respektieren Rate-Limits (Sleep + Retry bei leerer/Fehler-Antwort).
    """
    out: dict[int, float] = {}
    block_start = day_from
    while block_start <= day_to:
        block_end = min(block_start + timedelta(days=30), day_to)
        url = f"{_API}?bzn={_bzn()}&start={block_start.isoformat()}&end={block_end.isoformat()}"
        data = _fetch_json(url, retries)
        ut = (data or {}).get('unix_seconds') or []
        pr = (data or {}).get('price') or []
        for ts, p in zip(ut, pr):
            if p is not None:
                out[int(ts)] = float(p)
        block_start = block_end + timedelta(days=1)
        time.sleep(1.5)  # energy-charts Rate-Limit schonen
    return out


def _fetch_json(url: str, retries: int) -> dict | None:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8')
            if not raw.strip():
                raise ValueError('leere Antwort')
            return json.loads(raw)
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as e:
            wait = 2.0 * attempt
            logger.warning("energy-charts Fetch-Fehler (%d/%d): %s — retry in %.0fs",
                           attempt, retries, e, wait)
            time.sleep(wait)
    logger.error("energy-charts Fetch endgültig fehlgeschlagen: %s", url)
    return None


def store(conn: sqlite3.Connection, prices: dict[int, float]) -> int:
    if not prices:
        return 0
    rows = [(ts, eur_mwh, 'energy-charts') for ts, eur_mwh in sorted(prices.items())]
    conn.executemany(
        "INSERT OR REPLACE INTO spot_price_15min (ts, price_eur_mwh, source) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def _open(db_path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=30.0)
    # Tabelle sicherstellen (falls db_init noch nicht lief).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spot_price_15min (
            ts INTEGER PRIMARY KEY,
            price_eur_mwh REAL NOT NULL,
            source TEXT DEFAULT 'energy-charts',
            inserted_ts INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    return conn


def run(day_from: date, day_to: date, db_path: str | None = None) -> int:
    conn = _open(db_path)
    try:
        prices = fetch_prices(day_from, day_to)
        n = store(conn, prices)
        logger.info("spot_price_15min: %d Punkte gespeichert (%s … %s)",
                    n, day_from.isoformat(), day_to.isoformat())
        return n
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description='EPEX Day-Ahead Spot-Preise sammeln')
    ap.add_argument('--from', dest='dfrom', help='Startdatum YYYY-MM-DD')
    ap.add_argument('--to', dest='dto', help='Enddatum YYYY-MM-DD')
    ap.add_argument('--days-forward', type=int, default=1,
                    help='Tage voraus ab heute (Day-Ahead), Default 1')
    ap.add_argument('--backfill-days', type=int, default=3,
                    help='Tage rückwirkend (Lückenschluss), Default 3')
    ap.add_argument('--db', help='Ziel-DB (Default config.DB_PATH)')
    args = ap.parse_args()

    if args.dfrom:
        d0 = datetime.strptime(args.dfrom, '%Y-%m-%d').date()
        d1 = datetime.strptime(args.dto, '%Y-%m-%d').date() if args.dto else d0
    else:
        today = date.today()
        d0 = today - timedelta(days=max(0, args.backfill_days))
        d1 = today + timedelta(days=max(0, args.days_forward))
    run(d0, d1, args.db)
    return 0


if __name__ == '__main__':
    sys.exit(main())
