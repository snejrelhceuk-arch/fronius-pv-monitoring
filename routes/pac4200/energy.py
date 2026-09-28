"""pac4200-Submodul: Energie-Fixpunkte + Vergleich PAC4200 ↔ Master-SM ↔ iMSys.

Aufgeteilt aus ``routes/pac4200.py`` (2026-09-28). Read-only (Säule B):
Zähler-Fixpunkte (Tag/Monat/Jahr) und der Energievergleich zwischen PAC4200,
Fronius-Primär-SM und iMSys (eichrechtlicher Netzbetreiber-Zähler).
"""
import os
import sqlite3
import time as _time
from datetime import datetime, timedelta
from glob import glob

from flask import jsonify, render_template, request

import config

from routes.pac4200 import bp
from routes.pac4200._shared import _NQ_PRIMARY_DIR, _open_legacy, _nq_primary_db


def _energy_payload_from_row(row) -> dict:
    def _kwh(wh):
        return round((wh or 0.0) / 1000.0, 3) if wh is not None else None

    return {
        'wh_imp_kwh': _kwh(row[0]),
        'wh_exp_kwh': _kwh(row[1]),
        'varh_imp_kvarh': _kwh(row[2]),
        'varh_exp_kvarh': _kwh(row[3]),
        'vah_kvah': _kwh(row[4]),
        'src': row[5],
    }


def _sum_daily_deltas(db_paths, day_like):
    """Summiert nq_energy_daily-Deltas (5 Zähler) über die Tage eines Zeitraums.

    Delta = Summe der Tages-Deltas (wie rollup_month), aber **live** direkt aus
    den Tages-Fixpunkten — auch für noch nicht gerollte, aktuelle Monate/Jahre.
    Rückgabe im Row-Format von ``_energy_payload_from_row`` oder ``None``.
    """
    agg = [0.0, 0.0, 0.0, 0.0, 0.0]
    have = [False, False, False, False, False]
    srcs: set[str] = set()
    found = False
    for path in db_paths:
        conn = _open_legacy(path)
        if not conn:
            continue
        try:
            rows = conn.execute(
                "SELECT wh_imp_delta, wh_exp_delta, varh_imp_delta, varh_exp_delta, vah_delta, src "
                "FROM nq_energy_daily WHERE day LIKE ?", (day_like,)).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for r in rows:
            found = True
            for i in range(5):
                if r[i] is not None:
                    agg[i] += r[i]
                    have[i] = True
            if r[5]:
                srcs.add(r[5])
    if not found:
        return None
    out = [round(agg[i], 3) if have[i] else None for i in range(5)]
    src = 'pv_backfill' if 'pv_backfill' in srcs else (next(iter(srcs)) if srcs else None)
    return out + [src]


@bp.route('/api/nq/energy/<period_type>/<period_key>')
def api_nq_energy(period_type, period_key):
    """Read-only Zähler-Fixpunkte für Tooltip-Spiegelung (Tag/Monat/Jahr).

    period_type: 'day' (YYYY-MM-DD) | 'month' (YYYY-MM) | 'year' (YYYY).
    Delta-Werte in kWh/kvarh (PAC4200-gemessen, für Intervall gültig).
    """
    if period_type == 'day':
        db_path, table, col = _nq_primary_db(period_key[:7]), 'nq_energy_daily', 'day'
    elif period_type == 'month':
        db_path, table, col = _nq_primary_db(period_key), 'nq_energy_monthly', 'month'
    elif period_type == 'year':
        db_path, table, col = _nq_primary_db(f"{period_key}-01"), 'nq_energy_yearly', 'year'
    else:
        return jsonify({'error': 'invalid period_type (day|month|year)'}), 400

    conn = _open_legacy(db_path)
    if not conn:
        return jsonify({'error': 'no data', 'period': period_key}), 404
    try:
        row = conn.execute(
            f"SELECT wh_imp_delta, wh_exp_delta, varh_imp_delta, varh_exp_delta, "
            f"vah_delta, src FROM {table} WHERE {col} = ?", (period_key,)).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if not row:
        return jsonify({'error': 'no data', 'period': period_key}), 404

    return jsonify({
        'period': period_key, 'period_type': period_type, 'from': 'PAC4200',
        **_energy_payload_from_row(row),
    })


@bp.route('/api/nq/energy_map/<period_type>/<period_key>')
def api_nq_energy_map(period_type, period_key):
    """Read-only Sammelabfrage für Tooltip-Spiegelungen im Monitoring.

    period_type:
      - day/<YYYY-MM>   -> alle Tages-Fixpunkte des Monats
      - month/<YYYY>    -> alle Monats-Fixpunkte des Jahres
      - year/all        -> alle Jahres-Fixpunkte der vorhandenen NQ-DBs
    """
    by_key: dict[str, dict] = {}

    if period_type == 'day':
        db_path = _nq_primary_db(period_key)
        conn = _open_legacy(db_path)
        if not conn:
            return jsonify({'error': 'no data', 'period_type': period_type, 'period_key': period_key}), 404
        try:
            rows = conn.execute(
                "SELECT day, wh_imp_delta, wh_exp_delta, varh_imp_delta, varh_exp_delta, vah_delta, src "
                "FROM nq_energy_daily WHERE day LIKE ? ORDER BY day",
                (f"{period_key}-%",),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for row in rows:
            by_key[row[0]] = _energy_payload_from_row(row[1:])

    elif period_type == 'month':
        # Live-Summe der Tages-Deltas je Monat (auch aktueller, noch nicht gerollter Monat).
        for month in range(1, 13):
            month_key = f"{period_key}-{month:02d}"
            row = _sum_daily_deltas([_nq_primary_db(month_key)], f"{month_key}-%")
            if row:
                by_key[month_key] = _energy_payload_from_row(row)

    elif period_type == 'year' and period_key == 'all':
        # Live-Summe der Tages-Deltas je Jahr über alle Monats-DBs (auch laufendes Jahr).
        years: set[str] = set()
        for db_path in glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db')):
            years.add(os.path.basename(db_path)[3:7])
        for year_key in sorted(years):
            month_dbs = [os.path.join(_NQ_PRIMARY_DIR, f"nq_{year_key}-{m:02d}.db") for m in range(1, 13)]
            row = _sum_daily_deltas(month_dbs, f"{year_key}-%")
            if row:
                by_key[year_key] = _energy_payload_from_row(row)
    else:
        return jsonify({'error': 'invalid period_type/key'}), 400

    return jsonify({
        'period_type': period_type,
        'period_key': period_key,
        'from': 'PAC4200',
        'by_key': by_key,
        'count': len(by_key),
    })


# ---------------------------------------------------------------------------
# Energie-Vergleich PAC4200 ↔ Master-SM (Fronius Primär-SM) — read-only (Säule B)
# ---------------------------------------------------------------------------

def _local_day_bounds(day: str) -> tuple[int, int]:
    t = _time.strptime(day, '%Y-%m-%d')
    t0 = int(_time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def _sm_day_kwh(t0: int, t1: int) -> dict | None:
    """Autoritativer Master-SM-Tageswert (Fronius Primär-SM) aus ``daily_data``
    (read-only): Import/Export in kWh aus den Zähler-Fixpunkten der Tagesgrenzen
    (``W_Imp/Exp_Netz_start/-end``)."""
    db = getattr(config, 'DB_PATH', None)
    if not db or not os.path.exists(db):
        return None
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        row = c.execute(
            "SELECT W_Imp_Netz_start, W_Imp_Netz_end, W_Exp_Netz_start, W_Exp_Netz_end "
            "FROM daily_data WHERE ts>=? AND ts<? ORDER BY ts LIMIT 1", (t0, t1)).fetchone()
        c.close()
    except Exception:
        return None
    if not row or row[0] is None or row[1] is None:
        return None
    return {'imp_kwh': round((row[1] - row[0]) / 1000.0, 3),
            'exp_kwh': round(abs((row[3] or 0.0) - (row[2] or 0.0)) / 1000.0, 3)}


def _metric_class(pac, sm, low_cov, thr):
    """Bewertung einer Metrik: 'na' (kein SM), 'low' (geringe Deckung),
    'outlier' (|Abw.| > thr trotz Deckung), sonst 'ok'. + Δ + Δ%."""
    if sm is None:
        return None, None, ('low' if low_cov else 'na')
    d = round(pac - sm, 3)
    pct = round(100.0 * d / sm, 1) if sm else None
    if low_cov:
        return d, pct, 'low'
    if pct is not None and abs(pct) > thr:
        return d, pct, 'outlier'
    return d, pct, 'ok'


@bp.route('/netzqualitaet/energievergleich')
def nq_energy_compare_page():
    """Vergleich der Energiezähler PAC4200 ↔ Fronius Primär-SM (Abweichungen markiert)."""
    return render_template('nq_energie_vergleich_view.html')


def _sm_days_kwh() -> dict:
    """Batch-Read: ``{day: {'imp_kwh','exp_kwh'}}`` für alle Tage aus ``daily_data``
    (read-only, Säule B). Tagesgrenzen-Fixpunkte ``W_Imp/Exp_Netz_start/-end``."""
    db = getattr(config, 'DB_PATH', None)
    out: dict[str, dict] = {}
    if not db or not os.path.exists(db):
        return out
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        cur = c.execute(
            "SELECT ts, W_Imp_Netz_start, W_Imp_Netz_end, W_Exp_Netz_start, W_Exp_Netz_end "
            "FROM daily_data WHERE W_Imp_Netz_start IS NOT NULL AND W_Imp_Netz_end IS NOT NULL")
        for ts, i0, i1, e0, e1 in cur.fetchall():
            day = _time.strftime('%Y-%m-%d', _time.localtime(ts))
            out[day] = {'imp_kwh': round((i1 - i0) / 1000.0, 3),
                        'exp_kwh': round(abs((e1 or 0.0) - (e0 or 0.0)) / 1000.0, 3)}
        c.close()
    except Exception:
        return out
    return out


def _pac_days_kwh() -> dict:
    """``{day: {'imp_kwh','exp_kwh','src','n'}}`` aller echten PAC-Zählertage
    (``nq_energy_daily``, ``src`` ≠ ``pv_backfill``). ``src`` macht Teil-Tage
    (``partial``) und SM-Ersatztage (``sm_substitute``) transparent."""
    out: dict[str, dict] = {}
    for db_path in sorted(glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db'))):
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            rows = conn.execute(
                "SELECT day, wh_imp_delta, wh_exp_delta, src, n_samples "
                "FROM nq_energy_daily WHERE src != 'pv_backfill'").fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for day, imp, exp, src, n in rows:
            out[day] = {'imp_kwh': round((imp or 0.0) / 1000.0, 3),
                        'exp_kwh': round((exp or 0.0) / 1000.0, 3),
                        'src': src, 'n': n}
    return out


def _energy_day_items(pac_by_day: dict, sm_by_day: dict) -> list:
    """Baue je Tag ein Vergleichs-Item (PAC vs Master-SM, Δ abs/%)."""
    items = []
    for day in sorted(pac_by_day):
        pac = pac_by_day[day]
        sm = sm_by_day.get(day)
        sm_imp = sm['imp_kwh'] if sm else None
        sm_exp = sm['exp_kwh'] if sm else None
        d_imp = round(pac['imp_kwh'] - sm_imp, 3) if sm_imp is not None else None
        d_exp = round(pac['exp_kwh'] - sm_exp, 3) if sm_exp is not None else None
        items.append({
            'label': day, 'day': day,
            'pac_imp_kwh': pac['imp_kwh'], 'sm_imp_kwh': sm_imp,
            'd_imp_kwh': d_imp,
            'd_imp_pct': round(100.0 * d_imp / sm_imp, 1) if (sm_imp and d_imp is not None) else None,
            'pac_exp_kwh': pac['exp_kwh'], 'sm_exp_kwh': sm_exp,
            'd_exp_kwh': d_exp,
            'd_exp_pct': round(100.0 * d_exp / sm_exp, 1) if (sm_exp and d_exp is not None) else None,
            'pac_src': pac.get('src'), 'pac_n': pac.get('n'),
        })
    return items


def _aggregate_energy(day_items: list, key_len: int) -> list:
    """Summiere Tages-Items auf Monat (key_len=7) bzw. Jahr (key_len=4).

    Δ nur über Tage mit PAC UND SM (fairer Vergleich); ``n_days`` = PAC-Tage,
    ``n_cmp`` = davon mit SM.
    """
    buckets: dict[str, dict] = {}
    order = []
    for it in day_items:
        key = it['day'][:key_len]
        if key not in buckets:
            buckets[key] = {'pac_imp': 0.0, 'pac_exp': 0.0, 'sm_imp': 0.0,
                            'sm_exp': 0.0, 'n_days': 0, 'n_cmp': 0}
            order.append(key)
        b = buckets[key]
        b['n_days'] += 1
        if it['sm_imp_kwh'] is None:
            continue
        b['pac_imp'] += it['pac_imp_kwh']
        b['pac_exp'] += it['pac_exp_kwh']
        b['sm_imp'] += it['sm_imp_kwh']
        b['sm_exp'] += it['sm_exp_kwh']
        b['n_cmp'] += 1
    items = []
    for key in order:
        b = buckets[key]
        has = b['n_cmp'] > 0
        pac_imp, sm_imp = round(b['pac_imp'], 2), round(b['sm_imp'], 2)
        pac_exp, sm_exp = round(b['pac_exp'], 2), round(b['sm_exp'], 2)
        d_imp = round(pac_imp - sm_imp, 2) if has else None
        d_exp = round(pac_exp - sm_exp, 2) if has else None
        items.append({
            'label': key, 'n_days': b['n_days'], 'n_cmp': b['n_cmp'],
            'pac_imp_kwh': pac_imp if has else None, 'sm_imp_kwh': sm_imp if has else None,
            'd_imp_kwh': d_imp,
            'd_imp_pct': round(100.0 * d_imp / sm_imp, 1) if (has and sm_imp) else None,
            'pac_exp_kwh': pac_exp if has else None, 'sm_exp_kwh': sm_exp if has else None,
            'd_exp_kwh': d_exp,
            'd_exp_pct': round(100.0 * d_exp / sm_exp, 1) if (has and sm_exp) else None,
        })
    return items


def _ims_readings() -> list:
    """Alle iMSys-Ablesungen (kumulative Zählerstände) aus ``nq_ims_reading``,
    dedupliziert und nach Zeit sortiert."""
    seen: dict[int, dict] = {}
    for db_path in sorted(glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db'))):
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            rows = conn.execute(
                "SELECT ts, day, imp_kwh, exp_kwh, source, note FROM nq_ims_reading").fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for ts, day, imp, exp, src, note in rows:
            seen[ts] = {'ts': ts, 'day': day, 'imp_kwh': imp, 'exp_kwh': exp,
                        'source': src, 'note': note}
    return [seen[k] for k in sorted(seen)]


def _ims_intervals(readings: list, pac_by_day: dict, sm_by_day: dict) -> list:
    """Intervall-Vergleich zwischen aufeinanderfolgenden iMSys-Fixpunkten.

    iMSys-Δ aus den Zählerständen; PAC/SM über die Tagesgrenzen ``[day_a, day_b)``
    summiert (Näherung — die präzisen synchronisierten Fixpunkte stehen in
    doc/MESSSYSTEM_FIXPUNKTE.md). Abweichung jeweils gegen iMSys (eichrechtl. Referenz).
    """
    def _dev(val, ref):
        if val is None or ref is None or ref == 0:
            return None, None
        return round(val - ref, 3), round(100.0 * (val - ref) / ref, 1)

    out = []
    for a, b in zip(readings, readings[1:]):
        try:
            d = datetime.strptime(a['day'], '%Y-%m-%d').date()
            end = datetime.strptime(b['day'], '%Y-%m-%d').date()
        except Exception:
            continue
        ims_imp = round(b['imp_kwh'] - a['imp_kwh'], 3) if (a['imp_kwh'] is not None and b['imp_kwh'] is not None) else None
        ims_exp = round(b['exp_kwh'] - a['exp_kwh'], 3) if (a['exp_kwh'] is not None and b['exp_kwh'] is not None) else None
        pac_imp = pac_exp = sm_imp = sm_exp = 0.0
        n_days = n_pac = n_sm = 0
        while d < end:
            ds = d.isoformat()
            n_days += 1
            pac = pac_by_day.get(ds)
            if pac:
                pac_imp += pac['imp_kwh']; pac_exp += pac['exp_kwh']; n_pac += 1
            sm = sm_by_day.get(ds)
            if sm:
                sm_imp += sm['imp_kwh']; sm_exp += sm['exp_kwh']; n_sm += 1
            d += timedelta(days=1)
        sm_imp_r = round(sm_imp, 3) if n_sm else None
        sm_exp_r = round(sm_exp, 3) if n_sm else None
        pac_imp_r = round(pac_imp, 3) if n_pac else None
        pac_exp_r = round(pac_exp, 3) if n_pac else None
        d_sm_imp, d_sm_imp_pct = _dev(sm_imp_r, ims_imp)
        d_sm_exp, d_sm_exp_pct = _dev(sm_exp_r, ims_exp)
        d_pac_imp, d_pac_imp_pct = _dev(pac_imp_r, ims_imp)
        d_pac_exp, d_pac_exp_pct = _dev(pac_exp_r, ims_exp)
        out.append({
            'from': a['day'], 'to': b['day'],
            'n_days': n_days, 'n_pac': n_pac, 'n_sm': n_sm,
            'ims_imp_kwh': ims_imp, 'ims_exp_kwh': ims_exp,
            'sm_imp_kwh': sm_imp_r, 'sm_exp_kwh': sm_exp_r,
            'pac_imp_kwh': pac_imp_r, 'pac_exp_kwh': pac_exp_r,
            'd_sm_imp_kwh': d_sm_imp, 'd_sm_imp_pct': d_sm_imp_pct,
            'd_sm_exp_kwh': d_sm_exp, 'd_sm_exp_pct': d_sm_exp_pct,
            'd_pac_imp_kwh': d_pac_imp, 'd_pac_imp_pct': d_pac_imp_pct,
            'd_pac_exp_kwh': d_pac_exp, 'd_pac_exp_pct': d_pac_exp_pct,
        })
    return out


@bp.route('/api/nq/energy_compare')
def api_nq_energy_compare():
    """Read-only Vergleich PAC4200 ↔ Master-SM (↔ iMSys).

    ``?agg=day|month|year|ims`` (Default ``day``). ``day``: ``?days=N`` (Default
    90, max 400) oder ``?all=1``. Monat/Jahr summieren die Tages-Deltas (Δ nur
    über Tage mit PAC UND SM). ``ims`` liefert die iMSys-Ablesungen + Intervall-
    Vergleich (iMSys ↔ SM ↔ PAC). Nur echte PAC-Zählertage. Keine Bewertung.
    """
    agg = (request.args.get('agg') or 'day').lower()
    pac_by_day = _pac_days_kwh()
    sm_by_day = _sm_days_kwh()

    if agg == 'ims':
        readings = _ims_readings()
        return jsonify({
            'agg': 'ims',
            'readings': readings,
            'intervals': _ims_intervals(readings, pac_by_day, sm_by_day),
            'from': 'iMSys ↔ PAC4200 ↔ Master-SM',
        })

    day_items = _energy_day_items(pac_by_day, sm_by_day)

    if agg == 'month':
        return jsonify({'agg': 'month', 'items': _aggregate_energy(day_items, 7),
                        'from': 'PAC4200 vs Master-SM (Monatssummen)'})
    if agg == 'year':
        return jsonify({'agg': 'year', 'items': _aggregate_energy(day_items, 4),
                        'from': 'PAC4200 vs Master-SM (Jahressummen)'})

    # Default: Tages-Ansicht mit Fenster (days/all)
    all_days = request.args.get('all', type=int, default=0)
    days = min(request.args.get('days', type=int, default=90), 400)
    if not all_days:
        start_day = _time.strftime('%Y-%m-%d', _time.localtime(_time.time() - days * 86400))
        day_items = [it for it in day_items if it['day'] >= start_day]
    return jsonify({'agg': 'day', 'items': day_items, 'from': 'PAC4200 vs Master-SM'})
