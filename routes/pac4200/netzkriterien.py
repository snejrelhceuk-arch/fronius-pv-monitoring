"""pac4200-Submodul: Langzeit-Aggregate, Chart-Seite und Netzkriterien-API.

Aufgeteilt aus ``routes/pac4200.py`` (2026-09-28). Read-only (Säule B):
Wide-Format-Aggregate (5min/hourly/daily), die feste NQ-Chart-Seite und die
Netzkriterien-Bewertung (Spannung L-L, Frequenz, Strom, THD, Leistung inkl.
Warnstufen) aus NQ-Primary-Aggregaten + permanenter SM-Historie.
"""
import calendar
import logging
import os
import sqlite3
import time as _time
from datetime import datetime, timedelta
from glob import glob

from flask import jsonify, render_template, request

import config
from nq import tech_read
from nq.nq_common import load_config as _load_nq_config

from routes.pac4200 import bp
from routes.pac4200._shared import _NQ_PRIMARY_DIR


@bp.route('/api/nq/aggregates')
def api_nq_aggregates():
    """Langzeit-Aggregate (5min|hourly|daily) aus Primary-SD im Wide-Format."""
    try:
        rng = request.args.get('range', default='5min')
        end = request.args.get('end', type=int) or int(_time.time())
        start = request.args.get('start', type=int)
        if not start:
            span = {'5min': 86400, 'hourly': 7 * 86400, 'daily': 366 * 86400}.get(rng, 86400)
            start = end - span
        res = tech_read.fetch_aggregates(rng, start, end)
        return jsonify(res), (200 if not res.get('error') else 400)
    except Exception as exc:
        logging.exception("NQ aggregates failed")
        return jsonify({'data': [], 'error': str(exc)}), 503


@bp.route('/netzqualitaet/chart')
def nq_chart_page():
    """NQ2 WP5: feste Tag-Ansicht (5-min-Raster) + Event-Marker/Drill-down."""
    return render_template('nq_chart_view.html')


# ---------------------------------------------------------------------------
# Netzkriterien-API (NQ/PAC4200-Quelle, ohne Legacy data_15min-Pfad)
# ---------------------------------------------------------------------------
def _safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _period_start_end(period: str, date_param: str | None) -> tuple[int, int]:
    now = datetime.now()
    if period == 'tag':
        d = datetime.strptime(date_param, '%Y-%m-%d') if date_param else now
        s = datetime(d.year, d.month, d.day, 0, 0, 0)
        e = s + timedelta(days=1)
        return int(s.timestamp()), int(e.timestamp())
    if period == 'monat':
        if date_param:
            d = datetime.strptime(date_param, '%Y-%m-%d')
        else:
            d = now
        s = datetime(d.year, d.month, 1, 0, 0, 0)
        _, last_day = calendar.monthrange(d.year, d.month)
        e = datetime(d.year, d.month, last_day, 23, 59, 59) + timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if period == 'jahr':
        y = int(date_param[:4]) if date_param else now.year
        s = datetime(y, 1, 1, 0, 0, 0)
        e = datetime(y + 1, 1, 1, 0, 0, 0)
        return int(s.timestamp()), int(e.timestamp())
    # gesamt: über alle vorhandenen NQ-Monats-DBs
    years = sorted({int(os.path.basename(p)[3:7]) for p in glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db'))})
    if years:
        s = datetime(years[0], 1, 1, 0, 0, 0)
    else:
        s = datetime(now.year - 1, 1, 1, 0, 0, 0)
    e = datetime(now.year + 1, 1, 1, 0, 0, 0)
    return int(s.timestamp()), int(e.timestamp())


def _pct_toward(value: float | None, lo: float, hi: float) -> tuple[float | None, str | None]:
    """Ausschöpfung in % zur nächstliegenden Grenze bezogen auf nominale Mitte."""
    if value is None:
        return None, None
    nom = (lo + hi) / 2.0
    if value >= nom:
        span = hi - nom
        return (((value - nom) / span) * 100.0 if span > 0 else None), 'hi'
    span = nom - lo
    return (((nom - value) / span) * 100.0 if span > 0 else None), 'lo'


def _core_fallback_rows(start: int, end: int) -> list[dict]:
    """Fallback aus Kern-DB: liefert U_L-L + f aus data_15min.

    Wird nur genutzt, wenn NQ-Daten für das angefragte Fenster leer sind.
    """
    rows_out: list[dict] = []
    try:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except Exception:
        return rows_out
    try:
        rows = conn.execute(
            "SELECT ts, "
            "U_L1_N_Netz_avg, U_L1_N_Netz_min, U_L1_N_Netz_max, "
            "U_L2_N_Netz_avg, U_L2_N_Netz_min, U_L2_N_Netz_max, "
            "U_L3_N_Netz_avg, U_L3_N_Netz_min, U_L3_N_Netz_max, "
            "f_Netz_avg, f_Netz_min, f_Netz_max "
            "FROM data_15min WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start, end),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    rt3 = 1.7320508075688772
    for ts, u1n_avg, u1n_min, u1n_max, u2n_avg, u2n_min, u2n_max, u3n_avg, u3n_min, u3n_max, f_avg, f_min, f_max in rows:
        u12_avg = (u1n_avg * rt3) if u1n_avg is not None else None
        u12_min = (u1n_min * rt3) if u1n_min is not None else None
        u12_max = (u1n_max * rt3) if u1n_max is not None else None
        u23_avg = (u2n_avg * rt3) if u2n_avg is not None else None
        u23_min = (u2n_min * rt3) if u2n_min is not None else None
        u23_max = (u2n_max * rt3) if u2n_max is not None else None
        u31_avg = (u3n_avg * rt3) if u3n_avg is not None else None
        u31_min = (u3n_min * rt3) if u3n_min is not None else None
        u31_max = (u3n_max * rt3) if u3n_max is not None else None
        rows_out.append({
            'ts': int(ts),
            'U_L12': u12_avg, 'U_L23': u23_avg, 'U_L31': u31_avg,
            'U_L12_min': u12_min, 'U_L12_max': u12_max,
            'U_L23_min': u23_min, 'U_L23_max': u23_max,
            'U_L31_min': u31_min, 'U_L31_max': u31_max,
            'FREQ': _safe_float(f_avg), 'FREQ_min': _safe_float(f_min), 'FREQ_max': _safe_float(f_max),
        })
    return rows_out


def _nq_sm_history_rows(start: int, end: int, rng: str) -> list[dict]:
    """Permanente SM-Netzqualitaets-Historie (nq_sm_15min) fuer den Vor-PAC-Zeitraum.

    Liest die retention-freie SM-15-min-Historie aus den NQ-Monats-DBs
    (`nq/db/nq_YYYY-MM.db`, Tabelle `nq_sm_15min`, gefuellt via
    `nq/transfer/nq_sm_backfill.py`) und verdichtet sie auf die Zielaufloesung:
    5min→15-min-Durchreichung, hourly→Stundenbuckets, daily→Tagesbuckets
    (min/avg/max energieneutral gemerged). Wide-Format wie `_core_fallback_rows`.
    """
    # Monats-DBs im Fenster einsammeln.
    month_dbs: list[str] = []
    d = datetime.fromtimestamp(start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_dt = datetime.fromtimestamp(end)
    guard = 0
    while d <= end_dt and guard < 130:
        guard += 1
        p = os.path.join(_NQ_PRIMARY_DIR, f"nq_{d.strftime('%Y-%m')}.db")
        if os.path.exists(p):
            month_dbs.append(p)
        d = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)

    raw: list[tuple] = []
    for db_path in month_dbs:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        except Exception:
            continue
        try:
            raw.extend(conn.execute(
                "SELECT ts, u_l12,u_l12_min,u_l12_max, u_l23,u_l23_min,u_l23_max, "
                "u_l31,u_l31_min,u_l31_max, freq,freq_min,freq_max "
                "FROM nq_sm_15min WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start, end),
            ).fetchall())
        except Exception:
            pass
        finally:
            conn.close()
    if not raw:
        return []

    def _bucket_ts(ts: int) -> int:
        if rng == 'hourly':
            return ts - (ts % 3600)
        if rng == 'daily':
            dt = datetime.fromtimestamp(ts)
            return int(datetime(dt.year, dt.month, dt.day).timestamp())
        return int(ts)  # 5min: 15-min-Raster durchreichen

    # Bucket-Aggregation: avg = Mittel der avg, min = min der min, max = max der max.
    acc: dict[int, dict] = {}
    for (ts, u12, u12n, u12x, u23, u23n, u23x, u31, u31n, u31x, f, fn, fx) in raw:
        bts = _bucket_ts(int(ts))
        b = acc.setdefault(bts, {'ts': bts, '_n': 0,
                                 'u12': [], 'u23': [], 'u31': [], 'f': [],
                                 'u12n': [], 'u12x': [], 'u23n': [], 'u23x': [],
                                 'u31n': [], 'u31x': [], 'fn': [], 'fx': []})
        b['_n'] += 1
        for key, val in (('u12', u12), ('u23', u23), ('u31', u31), ('f', f),
                         ('u12n', u12n), ('u12x', u12x), ('u23n', u23n), ('u23x', u23x),
                         ('u31n', u31n), ('u31x', u31x), ('fn', fn), ('fx', fx)):
            if val is not None:
                b[key].append(val)

    def _avg(xs):
        return (sum(xs) / len(xs)) if xs else None

    rows_out: list[dict] = []
    for bts in sorted(acc):
        b = acc[bts]
        rows_out.append({
            'ts': bts,
            'U_L12': _avg(b['u12']), 'U_L23': _avg(b['u23']), 'U_L31': _avg(b['u31']),
            'U_L12_min': min(b['u12n']) if b['u12n'] else None,
            'U_L12_max': max(b['u12x']) if b['u12x'] else None,
            'U_L23_min': min(b['u23n']) if b['u23n'] else None,
            'U_L23_max': max(b['u23x']) if b['u23x'] else None,
            'U_L31_min': min(b['u31n']) if b['u31n'] else None,
            'U_L31_max': max(b['u31x']) if b['u31x'] else None,
            'FREQ': _avg(b['f']),
            'FREQ_min': min(b['fn']) if b['fn'] else None,
            'FREQ_max': max(b['fx']) if b['fx'] else None,
        })
    return rows_out


@bp.route('/api/nq/netzkriterien')
def api_nq_netzkriterien():
    """Netzkriterien-Daten aus NQ-Primary-Aggregaten (PAC4200).

    period=tag|monat|jahr|gesamt, date=YYYY-MM-DD.
    Liefert Spannung L-L + Frequenz inkl. Warnstufen 50/70/90.
    """
    period = request.args.get('period', 'tag')
    if period not in ('tag', 'monat', 'jahr', 'gesamt'):
        return jsonify({'error': 'invalid period'}), 400
    date_param = request.args.get('date')
    start, end = _period_start_end(period, date_param)
    rng = {'tag': '5min', 'monat': 'hourly', 'jahr': 'daily', 'gesamt': 'daily'}[period]

    raw = tech_read.fetch_aggregates(rng, start, end)
    pac_rows = raw.get('data', [])
    sm_rows = _nq_sm_history_rows(start, end, rng)
    if pac_rows and sm_rows:
        # SM-Historie (Vor-PAC) als Basis, echte PAC-Aggregate ueberlagern je ts
        # (PAC ist ab Inbetriebnahme die autoritative Quelle). Deckt Perioden ab,
        # die die PAC-Grenze ueberspannen (z. B. Juni mit PAC-Anlaufzeile 30.06).
        by_ts = {int(r['ts']): r for r in sm_rows}
        for r in pac_rows:
            by_ts[int(r['ts'])] = r
        rows = [by_ts[k] for k in sorted(by_ts)]
        source = 'nq_primary_agg+sm_15min'
    elif pac_rows:
        rows = pac_rows
        source = raw.get('source', f'nq_{rng}')
    elif sm_rows:
        rows = sm_rows
        source = 'nq_sm_15min'
    else:
        rows = _core_fallback_rows(start, end)
        source = 'core_data15min_fallback' if rows else raw.get('source', f'nq_{rng}')

    cfg = _load_nq_config()
    gw = cfg.get('grenzwerte', {})
    lv = gw.get('warning_levels', {})
    warn_pct = float(lv.get('warn_pct', 50))
    high_pct = float(lv.get('high_pct', 70))
    crit_pct = float(lv.get('crit_pct', 90))
    lvl2 = gw.get('warning_levels_load', {})
    warn_pct_l = float(lvl2.get('warn_pct', 80))
    high_pct_l = float(lvl2.get('high_pct', 100))
    crit_pct_l = float(lvl2.get('crit_pct', 120))
    u_ll_lo = float(gw.get('u_ll_min_v', 360.0))
    u_ll_hi = float(gw.get('u_ll_max_v', 440.0))
    f_lo = float(gw.get('freq_min_hz', 47.0))
    f_hi = float(gw.get('freq_max_hz', 52.0))
    i_hi = float(gw.get('i_max_a', 35.0))
    thd_hi = float(gw.get('thd_u_max_pct', 8.0))
    p_hi = float(gw.get('p_max_w', 24000.0))

    datapoints = []
    warnings = []
    level_counts = {'warn': 0, 'high': 0, 'crit': 0}

    # Strom + Leistung (Anschlussgrößen) nutzen die Last-Warnstufen (80/100/120%),
    # Spannung/Frequenz/THD die Norm-Warnstufen (50/70/90%).
    _LOAD_KINDS = {'i_max', 'p_max'}
    _RANK = {'warn': 1, 'high': 2, 'crit': 3}

    def _level(pct: float | None, kind: str | None = None) -> str | None:
        if pct is None:
            return None
        w, h, c = ((warn_pct_l, high_pct_l, crit_pct_l) if kind in _LOAD_KINDS
                   else (warn_pct, high_pct, crit_pct))
        if pct >= c:
            return 'crit'
        if pct >= h:
            return 'high'
        if pct >= w:
            return 'warn'
        return None

    for r in rows:
        ts = int(r.get('ts', 0))
        u12 = _safe_float(r.get('U_L12'))
        u23 = _safe_float(r.get('U_L23'))
        u31 = _safe_float(r.get('U_L31'))
        f = _safe_float(r.get('FREQ'))
        u12_min, u12_max = _safe_float(r.get('U_L12_min')), _safe_float(r.get('U_L12_max'))
        u23_min, u23_max = _safe_float(r.get('U_L23_min')), _safe_float(r.get('U_L23_max'))
        u31_min, u31_max = _safe_float(r.get('U_L31_min')), _safe_float(r.get('U_L31_max'))
        f_min, f_max = _safe_float(r.get('FREQ_min')), _safe_float(r.get('FREQ_max'))

        v_candidates_hi = [v for v in (u12_max, u23_max, u31_max, u12, u23, u31) if v is not None]
        v_candidates_lo = [v for v in (u12_min, u23_min, u31_min, u12, u23, u31) if v is not None]
        f_candidates_hi = [v for v in (f_max, f) if v is not None]
        f_candidates_lo = [v for v in (f_min, f) if v is not None]

        v_pct_hi, _ = _pct_toward(max(v_candidates_hi) if v_candidates_hi else None, u_ll_lo, u_ll_hi)
        v_pct_lo, _ = _pct_toward(min(v_candidates_lo) if v_candidates_lo else None, u_ll_lo, u_ll_hi)
        f_pct_hi, _ = _pct_toward(max(f_candidates_hi) if f_candidates_hi else None, f_lo, f_hi)
        f_pct_lo, _ = _pct_toward(min(f_candidates_lo) if f_candidates_lo else None, f_lo, f_hi)

        i_l1 = _safe_float(r.get('Is_L1'))
        i_l2 = _safe_float(r.get('Is_L2'))
        i_l3 = _safe_float(r.get('Is_L3'))
        i_l1_max = _safe_float(r.get('Is_L1_max'))
        i_l2_max = _safe_float(r.get('Is_L2_max'))
        i_l3_max = _safe_float(r.get('Is_L3_max'))
        i_candidates = [abs(v) for v in (i_l1, i_l2, i_l3, i_l1_max, i_l2_max, i_l3_max) if v is not None]
        i_pct_hi = ((max(i_candidates) / i_hi) * 100.0) if (i_candidates and i_hi > 0) else None

        thd1 = _safe_float(r.get('THDu_L1'))
        thd2 = _safe_float(r.get('THDu_L2'))
        thd3 = _safe_float(r.get('THDu_L3'))
        thd1_max = _safe_float(r.get('THDu_L1_max'))
        thd2_max = _safe_float(r.get('THDu_L2_max'))
        thd3_max = _safe_float(r.get('THDu_L3_max'))
        thd_candidates = [v for v in (thd1, thd2, thd3, thd1_max, thd2_max, thd3_max) if v is not None]
        thd_pct_hi = ((max(thd_candidates) / thd_hi) * 100.0) if (thd_candidates and thd_hi > 0) else None

        p_tot = _safe_float(r.get('P_tot'))
        p_tot_min = _safe_float(r.get('P_tot_min'))
        p_tot_max = _safe_float(r.get('P_tot_max'))
        p_candidates = [abs(v) for v in (p_tot, p_tot_min, p_tot_max) if v is not None]
        p_pct_hi = ((max(p_candidates) / p_hi) * 100.0) if (p_candidates and p_hi > 0) else None

        candidates = []
        if v_pct_hi is not None:
            candidates.append(('u_ll_max', v_pct_hi, max(v_candidates_hi) if v_candidates_hi else None))
        if v_pct_lo is not None:
            candidates.append(('u_ll_min', v_pct_lo, min(v_candidates_lo) if v_candidates_lo else None))
        if f_pct_hi is not None:
            candidates.append(('freq_max', f_pct_hi, max(f_candidates_hi) if f_candidates_hi else None))
        if f_pct_lo is not None:
            candidates.append(('freq_min', f_pct_lo, min(f_candidates_lo) if f_candidates_lo else None))
        if i_pct_hi is not None:
            candidates.append(('i_max', i_pct_hi, max(i_candidates) if i_candidates else None))
        if thd_pct_hi is not None:
            candidates.append(('thd_u_max', thd_pct_hi, max(thd_candidates) if thd_candidates else None))
        if p_pct_hi is not None:
            candidates.append(('p_max', p_pct_hi, max(p_candidates) if p_candidates else None))

        # Schlimmste Stufe wählen (je Kriterium eigene Warnstufen); bei Gleichstand höchstes %.
        warn_level = None
        warn_kind = None
        warn_pct_val = None
        warn_value = None
        best_rank = 0
        for kind, pct, val in candidates:
            lvl = _level(pct, kind)
            if not lvl:
                continue
            rank = _RANK[lvl]
            if rank > best_rank or (rank == best_rank and (warn_pct_val is None or pct > warn_pct_val)):
                best_rank = rank
                warn_level, warn_kind, warn_pct_val, warn_value = lvl, kind, pct, val
        if warn_level:
            level_counts[warn_level] += 1
            warnings.append({
                'ts': ts,
                'level': warn_level,
                'kind': warn_kind,
                'pct': round(warn_pct_val, 1),
                'value': round(float(warn_value), 3) if warn_value is not None else None,
            })

        datapoints.append({
            'ts': ts,
            'u_l1_l2': u12, 'u_l2_l3': u23, 'u_l3_l1': u31,
            'u_l1_l2_min': u12_min, 'u_l1_l2_max': u12_max,
            'u_l2_l3_min': u23_min, 'u_l2_l3_max': u23_max,
            'u_l3_l1_min': u31_min, 'u_l3_l1_max': u31_max,
            'f_netz': f, 'f_netz_min': f_min, 'f_netz_max': f_max,
            'warn_level': warn_level,
            'warn_kind': warn_kind,
            'warn_pct': round(warn_pct_val, 1) if warn_pct_val is not None else None,
        })

    maxima = {'u_voltage_max': None, 'u_voltage_min': None, 'f_netz_max': None, 'f_netz_min': None}
    for dp in datapoints:
        ts = dp['ts']
        for key, field in (
            ('u_voltage_max', ('u_l1_l2_max', 'u_l2_l3_max', 'u_l3_l1_max', 'u_l1_l2', 'u_l2_l3', 'u_l3_l1')),
            ('u_voltage_min', ('u_l1_l2_min', 'u_l2_l3_min', 'u_l3_l1_min', 'u_l1_l2', 'u_l2_l3', 'u_l3_l1')),
        ):
            vals = [dp[f] for f in field if dp.get(f) is not None]
            if not vals:
                continue
            cand = max(vals) if key.endswith('max') else min(vals)
            cur = maxima[key]
            if cur is None or (cand > cur['value'] if key.endswith('max') else cand < cur['value']):
                maxima[key] = {'value': float(cand), 'ts': ts}
        if dp.get('f_netz_max') is not None:
            cand = dp['f_netz_max']
            cur = maxima['f_netz_max']
            if cur is None or cand > cur['value']:
                maxima['f_netz_max'] = {'value': float(cand), 'ts': ts}
        if dp.get('f_netz_min') is not None:
            cand = dp['f_netz_min']
            cur = maxima['f_netz_min']
            if cur is None or cand < cur['value']:
                maxima['f_netz_min'] = {'value': float(cand), 'ts': ts}

    return jsonify({
        'period': period,
        'date': date_param,
        'window_start_ts': start,
        'window_end_ts': end,
        'datapoints': datapoints,
        'warnings': warnings,
        'warning_counts': level_counts,
        'warning_levels': {'warn_pct': warn_pct, 'high_pct': high_pct, 'crit_pct': crit_pct},
        'warning_levels_load': {'warn_pct': warn_pct_l, 'high_pct': high_pct_l, 'crit_pct': crit_pct_l},
        'limits': {
            'u_ll_min_v': u_ll_lo, 'u_ll_max_v': u_ll_hi,
            'freq_min_hz': f_lo, 'freq_max_hz': f_hi,
            'i_max_a': i_hi, 'thd_u_max_pct': thd_hi, 'p_max_w': p_hi,
        },
        'maxima': maxima,
        'marks': raw.get('marks', []),
        'filtered': raw.get('filtered', False),
        'available': bool(datapoints),
        'source': source,
    })
