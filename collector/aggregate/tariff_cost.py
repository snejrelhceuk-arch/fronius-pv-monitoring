#!/usr/bin/env python3
"""
Dynamischer Börsentarif — Kostenaggregation (Rolle A).

Verrechnet den 15-min-Börsenpreis (``spot_price_15min``) mit dem gemessenen
15-min-Netzbezug (``monitoring.db.data_5min_permanent.W_Bezug``, zu 15-min
gebucketet) über das Gesamtkosten-Modell (``dynamic_tariff``) und schreibt die
realen kWh-Kosten pro Tag/Monat/Jahr in ``tariff_cost_{daily,monthly,yearly}``.

Kernmetrik ``dyn_avg_ct`` = verbrauchsgewichtete Gesamtkosten einer bezogenen
kWh (brutto ct/kWh) — teurer Strom zur Spitzenlast schlägt stärker durch als die
reine Zeit-Mittelung (``dyn_simple_avg_ct``). Zusätzlich wird der Fixtarif
(``config.STROMTARIFE``) auf denselben Bezug gerechnet → direkter Kostenvergleich.

Rolle A: schreibt nur die eigenen Tarif-Tabellen in ``config.DB_PATH`` (RAM);
Tiered-Sync spiegelt nach analysis.db. Read-only ggü. Messdaten/Hardware.
Idempotent (self-healing: Tage/Monate werden bei jedem Lauf neu berechnet).
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

import config
import dynamic_tariff as dt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('tariff_cost')

_BUCKET = 900  # 15-min in Sekunden


def _day_bounds(d: date) -> tuple[int, int]:
    start = int(datetime(d.year, d.month, d.day).timestamp())
    end = int((datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp())
    return start, end


def _open(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=60.0)
    try:
        conn.execute("ATTACH DATABASE ? AS mon",
                     (f"file:{config.STATS_DB_PATH}?mode=ro",))
    except sqlite3.OperationalError as e:
        logger.warning("monitoring.db ATTACH fehlgeschlagen: %s", e)
    return conn


def _bezug_buckets(conn: sqlite3.Connection, t0: int, t1: int) -> dict[int, float]:
    """15-min-Bucket → Netzbezug (kWh) aus 5-min W_Bezug (Wh)."""
    buckets: dict[int, float] = {}
    try:
        rows = conn.execute(
            "SELECT ts, W_Bezug FROM mon.data_5min_permanent "
            "WHERE ts >= ? AND ts < ? AND W_Bezug IS NOT NULL",
            (t0, t1)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for ts, wh in rows:
        b = ts - (ts % _BUCKET)
        buckets[b] = buckets.get(b, 0.0) + (wh or 0.0) / 1000.0
    return buckets


def aggregate_day(conn: sqlite3.Connection, d: date) -> bool:
    t0, t1 = _day_bounds(d)
    spot = {ts - (ts % _BUCKET): p for ts, p in conn.execute(
        "SELECT ts, price_eur_mwh FROM spot_price_15min WHERE ts >= ? AND ts < ?",
        (t0, t1)).fetchall()}
    if not spot:
        return False
    bezug = _bezug_buckets(conn, t0, t1)

    dyn_cost_eur = 0.0
    fix_price_ct = dt.fixtarif_ct(d.year, d.month, d.day)
    priced_bezug = 0.0
    spot_cts, dyn_cts = [], []
    for b, eur_mwh in spot.items():
        spot_ct = dt.spot_eur_mwh_to_ct_kwh(eur_mwh)
        total_ct = dt.total_price_ct(spot_ct)
        spot_cts.append(spot_ct)
        dyn_cts.append(total_ct)
        kwh = bezug.get(b, 0.0)
        if kwh:
            dyn_cost_eur += kwh * total_ct / 100.0
            priced_bezug += kwh
    total_bezug = sum(bezug.values())

    spot_avg = round(sum(spot_cts) / len(spot_cts), 4) if spot_cts else None
    dyn_simple = round(sum(dyn_cts) / len(dyn_cts), 4) if dyn_cts else None
    dyn_avg = round(dyn_cost_eur / priced_bezug * 100.0, 4) if priced_bezug else dyn_simple
    fix_cost_eur = round(priced_bezug * fix_price_ct / 100.0, 4)
    coverage = round(priced_bezug / total_bezug * 100.0, 2) if total_bezug else 100.0

    conn.execute("""
        INSERT INTO tariff_cost_daily
          (day_ts, bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct,
           dyn_cost_eur, fix_price_ct, fix_cost_eur, coverage_pct, source, updated_ts)
        VALUES (?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))
        ON CONFLICT(day_ts) DO UPDATE SET
          bezug_kwh=excluded.bezug_kwh, spot_avg_ct=excluded.spot_avg_ct,
          dyn_avg_ct=excluded.dyn_avg_ct, dyn_simple_avg_ct=excluded.dyn_simple_avg_ct,
          dyn_cost_eur=excluded.dyn_cost_eur, fix_price_ct=excluded.fix_price_ct,
          fix_cost_eur=excluded.fix_cost_eur, coverage_pct=excluded.coverage_pct,
          updated_ts=strftime('%s','now')
    """, (t0, round(priced_bezug, 4), spot_avg, dyn_avg, dyn_simple,
          round(dyn_cost_eur, 4), fix_price_ct, fix_cost_eur, coverage, 'energy-charts'))
    conn.commit()
    return True


def rebuild_monthly(conn: sqlite3.Connection) -> int:
    rows = conn.execute("""
        SELECT CAST(strftime('%Y', day_ts, 'unixepoch', 'localtime') AS INT) y,
               CAST(strftime('%m', day_ts, 'unixepoch', 'localtime') AS INT) m,
               SUM(bezug_kwh), SUM(dyn_cost_eur), SUM(fix_cost_eur),
               SUM(spot_avg_ct*bezug_kwh), SUM(dyn_simple_avg_ct*bezug_kwh),
               SUM(CASE WHEN bezug_kwh>0 THEN bezug_kwh ELSE 0 END),
               AVG(spot_avg_ct), AVG(dyn_simple_avg_ct), AVG(coverage_pct)
        FROM tariff_cost_daily GROUP BY y, m
    """).fetchall()
    n = 0
    for (y, m, bezug, dyn_cost, fix_cost, spot_w, dynsimp_w, wsum,
         spot_simple, dynsimp_simple, cov) in rows:
        bezug = bezug or 0.0
        dyn_avg = round(dyn_cost / bezug * 100.0, 4) if bezug else round(dynsimp_simple or 0, 4)
        spot_avg = round(spot_w / wsum, 4) if wsum else round(spot_simple or 0, 4)
        dyn_simple = round(dynsimp_w / wsum, 4) if wsum else round(dynsimp_simple or 0, 4)
        fix_price = dt.fixtarif_ct(y, m, 15)
        dyn_fix = round(dt.dyn_fixkosten_eur_monat(), 4)
        fix_grund = round(dt.fix_grundpreis_eur_monat(y, m), 2)
        conn.execute("""
            INSERT INTO tariff_cost_monthly
              (year, month, bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct,
               dyn_cost_eur, dyn_fixkosten_eur, fix_price_ct, fix_cost_eur,
               fix_grundpreis_eur, coverage_pct, updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))
            ON CONFLICT(year, month) DO UPDATE SET
              bezug_kwh=excluded.bezug_kwh, spot_avg_ct=excluded.spot_avg_ct,
              dyn_avg_ct=excluded.dyn_avg_ct, dyn_simple_avg_ct=excluded.dyn_simple_avg_ct,
              dyn_cost_eur=excluded.dyn_cost_eur, dyn_fixkosten_eur=excluded.dyn_fixkosten_eur,
              fix_price_ct=excluded.fix_price_ct, fix_cost_eur=excluded.fix_cost_eur,
              fix_grundpreis_eur=excluded.fix_grundpreis_eur,
              coverage_pct=excluded.coverage_pct, updated_ts=strftime('%s','now')
        """, (y, m, round(bezug, 4), spot_avg, dyn_avg, dyn_simple,
              round(dyn_cost or 0, 4), dyn_fix, fix_price, round(fix_cost or 0, 4),
              fix_grund, round(cov or 100.0, 2)))
        n += 1
    conn.commit()
    return n


def rebuild_yearly(conn: sqlite3.Connection) -> int:
    rows = conn.execute("""
        SELECT year, SUM(bezug_kwh), SUM(dyn_cost_eur), SUM(dyn_fixkosten_eur),
               SUM(fix_cost_eur), SUM(fix_grundpreis_eur),
               SUM(spot_avg_ct*bezug_kwh), SUM(dyn_simple_avg_ct*bezug_kwh),
               SUM(CASE WHEN bezug_kwh>0 THEN bezug_kwh ELSE 0 END),
               AVG(spot_avg_ct), AVG(dyn_simple_avg_ct), AVG(coverage_pct)
        FROM tariff_cost_monthly GROUP BY year
    """).fetchall()
    n = 0
    for (y, bezug, dyn_cost, dyn_fix, fix_cost, fix_grund, spot_w, dynsimp_w,
         wsum, spot_simple, dynsimp_simple, cov) in rows:
        bezug = bezug or 0.0
        dyn_avg = round(dyn_cost / bezug * 100.0, 4) if bezug else round(dynsimp_simple or 0, 4)
        spot_avg = round(spot_w / wsum, 4) if wsum else round(spot_simple or 0, 4)
        dyn_simple = round(dynsimp_w / wsum, 4) if wsum else round(dynsimp_simple or 0, 4)
        fix_price = round(fix_cost / bezug * 100.0, 4) if bezug else dt.fixtarif_ct(y, 6, 15)
        conn.execute("""
            INSERT INTO tariff_cost_yearly
              (year, bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct,
               dyn_cost_eur, dyn_fixkosten_eur, fix_price_ct, fix_cost_eur,
               fix_grundpreis_eur, coverage_pct, updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,strftime('%s','now'))
            ON CONFLICT(year) DO UPDATE SET
              bezug_kwh=excluded.bezug_kwh, spot_avg_ct=excluded.spot_avg_ct,
              dyn_avg_ct=excluded.dyn_avg_ct, dyn_simple_avg_ct=excluded.dyn_simple_avg_ct,
              dyn_cost_eur=excluded.dyn_cost_eur, dyn_fixkosten_eur=excluded.dyn_fixkosten_eur,
              fix_price_ct=excluded.fix_price_ct, fix_cost_eur=excluded.fix_cost_eur,
              fix_grundpreis_eur=excluded.fix_grundpreis_eur,
              coverage_pct=excluded.coverage_pct, updated_ts=strftime('%s','now')
        """, (y, round(bezug, 4), spot_avg, dyn_avg, dyn_simple,
              round(dyn_cost or 0, 4), round(dyn_fix or 0, 4), fix_price,
              round(fix_cost or 0, 4), round(fix_grund or 0, 2), round(cov or 100.0, 2)))
        n += 1
    conn.commit()
    return n


def aggregate_range(conn: sqlite3.Connection, d0: date, d1: date) -> int:
    n = 0
    d = d0
    while d <= d1:
        if aggregate_day(conn, d):
            n += 1
        d += timedelta(days=1)
    rebuild_monthly(conn)
    rebuild_yearly(conn)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description='Tarif-Kosten aggregieren (Tag/Monat/Jahr)')
    ap.add_argument('--from', dest='dfrom', help='Startdatum YYYY-MM-DD')
    ap.add_argument('--to', dest='dto', help='Enddatum YYYY-MM-DD')
    ap.add_argument('--days-back', type=int, default=2,
                    help='Letzte N Tage neu aggregieren (Default 2)')
    ap.add_argument('--db', help='Ziel-DB (Default config.DB_PATH)')
    args = ap.parse_args()

    if args.dfrom:
        d0 = datetime.strptime(args.dfrom, '%Y-%m-%d').date()
        d1 = datetime.strptime(args.dto, '%Y-%m-%d').date() if args.dto else date.today()
    else:
        d1 = date.today()
        d0 = d1 - timedelta(days=max(0, args.days_back))

    conn = _open(args.db)
    try:
        t = time.time()
        n = aggregate_range(conn, d0, d1)
        logger.info("tariff_cost: %d Tage aggregiert (%s … %s) in %.1fs",
                    n, d0.isoformat(), d1.isoformat(), time.time() - t)
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
