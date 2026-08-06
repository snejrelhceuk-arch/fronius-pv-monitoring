"""
Blueprint: PAC4200 Netzqualitäts-Messgerät (read-only Live-Anzeige).

Enthält:
  /pac4200               — Gerätenachbildung (Live)
  /netzqualitaet/live    — Messwert-Tableau
  /netzqualitaet/analyse — Muster-Analyse (DFD, Tagesprofil, Wochenprofil)
  /api/pac4200/live      — Live-Snapshot JSON
    /api/nq/realtime_smart — 5min-Aggregat für Maschinenraum-Chart
  /api/nq/analyse/*      — Analyse-Daten (DFD, Tagesprofil, Wochenprofil, Events)

ABCD(EN)-Rollenmodell: Säule B (read-only Anzeige).
"""
import logging
import math
import os
import sqlite3
import time as _time
import calendar
from datetime import datetime, timedelta
from glob import glob

from flask import Blueprint, jsonify, render_template, request

import config
from nq import pac_live
from nq import tech_read
from nq.nq_common import load_config as _load_nq_config

bp = Blueprint('pac4200', __name__)

# Legacy NQ DB-Verzeichnis
_NQ_LEGACY_DIR = os.path.join(config.BASE_DIR, 'nq', 'legacy', 'db')
# Neue PAC4200 NQ DB-Verzeichnis
_NQ_PRIMARY_DIR = os.path.join(config.BASE_DIR, 'nq', 'db')

# Plausibilitätsgrenzen (nq_samples: L-L-Spannungen ~400–420 V)
_F_MIN, _F_MAX = 49.0, 51.0
_U_MIN, _U_MAX = 350.0, 460.0


# ---------------------------------------------------------------------------
# Helfer: Legacy-NQ-DBs öffnen
# ---------------------------------------------------------------------------

def _legacy_dbs_for_days(days: int) -> list[str]:
    """Listet Legacy-NQ-DB-Pfade (nq_YYYY-MM.db) auf, die die letzten `days` Tage abdecken."""
    needed: set[str] = set()
    d = datetime.now()
    for _ in range(days + 32):
        needed.add(os.path.join(_NQ_LEGACY_DIR, f"nq_{d.strftime('%Y-%m')}.db"))
        d -= timedelta(days=1)
        if len(needed) > 12:
            break
    return sorted(p for p in needed if os.path.exists(p))


def _open_legacy(path: str) -> sqlite3.Connection | None:
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:
        return None


def _ts_window(days: int) -> tuple[int, int]:
    end = int(_time.time())
    start = end - days * 86400
    return start, end


# ---------------------------------------------------------------------------
# Seiten-Routen
# ---------------------------------------------------------------------------

@bp.route('/pac4200')
def pac4200_page():
    return render_template('pac4200_view.html')


@bp.route('/netzqualitaet/live')
def nq_live_page():
    return render_template('nq_live_view.html')


@bp.route('/netzqualitaet/analyse')
def nq_analyse_page():
    """NQ-Analyse — Musterseite (DFD, Tagesprofil, Wochenprofil, Events)."""
    return render_template('nq_analyse_view.html')


# ---------------------------------------------------------------------------
# Live-API (PAC4200)
# ---------------------------------------------------------------------------

@bp.route('/api/pac4200/live')
def api_pac4200_live():
    """NQ2 WP1: Live-Snapshot **indirekt aus Tech-tmpfs** (Tech = einziger PAC-Leser).

    Kein PAC-Direktzugriff im Normalbetrieb (Clients pollen den Tech-Puffer).
    ``?direct=1`` liest ausnahmsweise direkt vom PAC — nur für Offline-Feldtests
    und nur wenn per ENV ``PV_PAC_ALLOW_DIRECT=1`` freigegeben.
    """
    allow_direct = os.environ.get('PV_PAC_ALLOW_DIRECT', '0') == '1'
    if allow_direct and request.args.get('direct') == '1':
        try:
            snap = pac_live.read_snapshot(host=config.PAC_IP,
                                          port=config.PAC_MODBUS_PORT,
                                          unit_id=config.PAC_UNIT_ID,
                                          timeout=3.0)
            return jsonify(snap), (200 if snap.get('ok') else 503)
        except Exception as exc:
            logging.exception("PAC4200 direct snapshot failed")
            return jsonify({"ok": False, "error": str(exc), "screens": []}), 503
    try:
        snap = tech_read.fetch_tech_snapshot()
        return jsonify(snap), (200 if snap.get('ok') else 503)
    except Exception as exc:
        logging.exception("PAC4200 tech snapshot failed")
        return jsonify({"ok": False, "error": str(exc), "screens": []}), 503


@bp.route('/api/nq/realtime_smart')
def api_nq_realtime_smart():
    """NQ-Zeitreihe (PAC4200) fuer Maschinenraum-Chart.

    resolution>=300 s -> nq_5min (Tagesraster). resolution<300 s -> Hochaufloesung
    aus Techs RAW-RAM (nur die letzten ~12 h; aeltere Buckets im Fenster bleiben 5 min).
    """
    try:
        resolution = max(request.args.get('resolution', type=int, default=300), 5)
        start_ts = request.args.get('start', type=int)
        end_ts = request.args.get('end', type=int)
        end = end_ts if end_ts else int(_time.time())
        if start_ts and end_ts and start_ts < end_ts:
            start = start_ts
        else:
            hours = min(max(request.args.get('hours', type=float, default=24.0), 0.001), 168)
            start = end - int(hours * 3600)
        res = tech_read.fetch_agg(start, end, resolution)
        res["resolution"] = f"{resolution}s"
        return jsonify(res), (200 if not res.get("error") else 503)
    except Exception as exc:
        logging.exception("NQ realtime_smart failed")
        return jsonify({"data": [], "error": str(exc), "source": "nq_tech_5min"}), 503


# ---------------------------------------------------------------------------
# Analyse-APIs (Rolle B read-only)
# ---------------------------------------------------------------------------

@bp.route('/api/nq/analyse/dfd')
def api_nq_dfd():
    """DFD-Statistik (15-min-Handelsmuster) aus Legacy NQ-DBs.

    Gibt zurück: DFD-Amplitude nach Grenztyp + Tagesverlauf + Hinweistexte.
    """
    days = min(int(request.args.get('days', 60)), 180)
    ts_start, ts_end = _ts_window(days)

    by_type: dict[str, list] = {'full_hour': [], 'half_hour': [], 'quarter_hour': []}
    daily: dict[str, dict] = {}  # date → {full_hour, half_hour, quarter_hour}

    for db_path in _legacy_dbs_for_days(days):
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            rows = conn.execute(
                "SELECT boundary_ts, boundary_type, dfd_amplitude, f_pre_avg, f_post_avg, "
                "f_nadir, local_impact_score "
                "FROM nq_boundary_events "
                "WHERE boundary_ts >= ? AND boundary_ts < ? "
                "AND dfd_amplitude IS NOT NULL",
                (ts_start, ts_end),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        for bts, btype, amp, f_pre, f_post, f_nadir, local_score in rows:
            if btype not in by_type:
                continue
            if not math.isfinite(amp):
                continue
            by_type[btype].append(amp)
            day_str = datetime.fromtimestamp(bts).strftime('%Y-%m-%d')
            daily.setdefault(day_str, {'full_hour': [], 'half_hour': [], 'quarter_hour': []})
            daily[day_str][btype].append(amp)

    def _stats(vals: list) -> dict:
        if not vals:
            return {'count': 0, 'avg': None, 'max': None, 'p75': None}
        n = len(vals)
        avg = sum(vals) / n
        vals_s = sorted(vals)
        p75 = vals_s[int(n * 0.75)]
        return {'count': n, 'avg': round(avg * 1000, 2), 'max': round(max(vals) * 1000, 2),
                'p75': round(p75 * 1000, 2)}

    result_by_type = {k: _stats(v) for k, v in by_type.items()}

    # Tagesverlauf: pro Tag Mittel je Grenztyp
    trend = []
    for day_str in sorted(daily.keys())[-30:]:
        d = daily[day_str]
        trend.append({
            'day': day_str,
            'full_hour': round(sum(d['full_hour']) / len(d['full_hour']) * 1000, 2) if d['full_hour'] else None,
            'half_hour': round(sum(d['half_hour']) / len(d['half_hour']) * 1000, 2) if d['half_hour'] else None,
            'quarter_hour': round(sum(d['quarter_hour']) / len(d['quarter_hour']) * 1000, 2) if d['quarter_hour'] else None,
        })

    total = sum(len(v) for v in by_type.values())
    return jsonify({
        'by_type': result_by_type,
        'trend': trend,
        'n_total': total,
        'days': days,
        'source': 'legacy_nq_boundary_events',
    })


@bp.route('/api/nq/analyse/tagesprofil')
def api_nq_tagesprofil():
    """Stündliches Frequenz- und Spannungsprofil (avg ± std je Stunde des Tages).

    Datenquelle: Legacy NQ nq_samples (f_netz, u_l1_l2, u_l2_l3, u_l3_l1).
    Zeigt Tag-Nacht-Effekt der PV und Netzfrequenzverhalten.
    """
    days = min(int(request.args.get('days', 30)), 120)
    weekday_filter = request.args.get('weekday')  # 'work' | 'weekend' | None
    ts_start, ts_end = _ts_window(days)

    # hour → [f_values, u_values]
    hour_f: dict[int, list[float]] = {h: [] for h in range(24)}
    hour_u: dict[int, list[float]] = {h: [] for h in range(24)}

    for db_path in _legacy_dbs_for_days(days):
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            if weekday_filter == 'work':
                wd_filter = "AND CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT) BETWEEN 1 AND 5"
            elif weekday_filter == 'weekend':
                wd_filter = "AND CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT) IN (0, 6)"
            else:
                wd_filter = ""
            rows = conn.execute(
                f"SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INT) h, "
                f"AVG(f_netz) f_avg, AVG((u_l1_l2+u_l2_l3+u_l3_l1)/3.0) u_avg, "
                f"AVG(f_netz*f_netz) f_sq, AVG(((u_l1_l2+u_l2_l3+u_l3_l1)/3.0)*((u_l1_l2+u_l2_l3+u_l3_l1)/3.0)) u_sq, "
                f"COUNT(*) n "
                f"FROM nq_samples "
                f"WHERE ts >= ? AND ts < ? "
                f"AND f_netz BETWEEN ? AND ? AND u_l1_l2 BETWEEN ? AND ? "
                f"{wd_filter} "
                f"GROUP BY h",
                (ts_start, ts_end, _F_MIN, _F_MAX, _U_MIN, _U_MAX),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        for h, f_avg, u_avg, f_sq, u_sq, n in rows:
            if 0 <= h <= 23 and f_avg and math.isfinite(f_avg):
                # Accumulate weighted sums for combined std calculation
                hour_f[h].append((f_avg, f_sq, n))
                if u_avg and math.isfinite(u_avg):
                    hour_u[h].append((u_avg, u_sq, n))

    def _weighted_stats(buckets: list[tuple]) -> tuple[float | None, float | None]:
        if not buckets:
            return None, None
        total_n = sum(b[2] for b in buckets)
        if total_n == 0:
            return None, None
        wavg = sum(b[0] * b[2] for b in buckets) / total_n
        wsq = sum(b[1] * b[2] for b in buckets) / total_n
        wvar = max(wsq - wavg ** 2, 0.0)
        return round(wavg, 4), round(math.sqrt(wvar), 4)

    hours = list(range(24))
    f_avg_list, f_std_list, u_avg_list, u_std_list = [], [], [], []
    for h in hours:
        fa, fs = _weighted_stats(hour_f[h])
        ua, us = _weighted_stats(hour_u[h])
        f_avg_list.append(fa)
        f_std_list.append(fs)
        u_avg_list.append(ua)
        u_std_list.append(us)

    return jsonify({
        'hours': hours,
        'f_avg': f_avg_list,
        'f_std': f_std_list,
        'u_avg': u_avg_list,
        'u_std': u_std_list,
        'days': days,
        'weekday_filter': weekday_filter,
        'source': 'legacy_nq_samples',
    })


@bp.route('/api/nq/analyse/wochenprofil')
def api_nq_wochenprofil():
    """Frequenz- und Spannungsprofil nach Wochentag (Mo=0 … So=6).

    Zeigt Wochenend-Effekt: weniger Industrielast → höhere Frequenz Sa/So.
    """
    days = min(int(request.args.get('days', 90)), 365)
    ts_start, ts_end = _ts_window(days)

    # SQLite %w: 0=So, 1=Mo … 6=Sa → mapping to Mo=0..So=6
    _WD_SQLITE_TO_ISO = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 0: 6}

    wd_f: dict[int, list] = {d: [] for d in range(7)}
    wd_u: dict[int, list] = {d: [] for d in range(7)}

    for db_path in _legacy_dbs_for_days(days):
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            rows = conn.execute(
                "SELECT CAST(strftime('%w', ts, 'unixepoch', 'localtime') AS INT) wd, "
                "AVG(f_netz) f_avg, AVG((u_l1_l2+u_l2_l3+u_l3_l1)/3.0) u_avg, "
                "AVG(f_netz*f_netz) f_sq, AVG(((u_l1_l2+u_l2_l3+u_l3_l1)/3.0)*((u_l1_l2+u_l2_l3+u_l3_l1)/3.0)) u_sq, "
                "COUNT(*) n "
                "FROM nq_samples "
                "WHERE ts >= ? AND ts < ? "
                "AND f_netz BETWEEN ? AND ? AND u_l1_l2 BETWEEN ? AND ? "
                "GROUP BY wd",
                (ts_start, ts_end, _F_MIN, _F_MAX, _U_MIN, _U_MAX),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        for wd_sq, f_avg, u_avg, f_sq, u_sq, n in rows:
            iso = _WD_SQLITE_TO_ISO.get(wd_sq, wd_sq)
            if f_avg and math.isfinite(f_avg):
                wd_f[iso].append((f_avg, f_sq, n))
            if u_avg and math.isfinite(u_avg):
                wd_u[iso].append((u_avg, u_sq, n))

    def _wstats(buckets: list) -> tuple:
        if not buckets:
            return None, None, 0
        total_n = sum(b[2] for b in buckets)
        if not total_n:
            return None, None, 0
        wa = sum(b[0] * b[2] for b in buckets) / total_n
        ws = sum(b[1] * b[2] for b in buckets) / total_n
        std = math.sqrt(max(ws - wa ** 2, 0.0))
        return round(wa, 4), round(std, 4), total_n

    day_names = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    f_avg_l, f_std_l, u_avg_l, u_std_l, counts = [], [], [], [], []
    for d in range(7):
        fa, fs, nf = _wstats(wd_f[d])
        ua, us, _ = _wstats(wd_u[d])
        f_avg_l.append(fa); f_std_l.append(fs)
        u_avg_l.append(ua); u_std_l.append(us)
        counts.append(nf)

    return jsonify({
        'days': day_names,
        'f_avg': f_avg_l,
        'f_std': f_std_l,
        'u_avg': u_avg_l,
        'u_std': u_std_l,
        'sample_counts': counts,
        'query_days': days,
        'source': 'legacy_nq_samples',
    })


@bp.route('/api/nq/analyse/events')
def api_nq_events():
    """Letzte NQ-Events aus nq_events (PAC4200) oder Legacy nq_boundary_events."""
    days = min(int(request.args.get('days', 7)), 60)
    band = request.args.get('band')  # 'HF_local' | 'NF_global' | 'VLF' | None
    ts_start, ts_end = _ts_window(days)

    events = []
    # Versuche zuerst neue PAC4200 nq_events
    for nq_path in sorted(glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db')), reverse=True)[:3]:
        conn = _open_legacy(nq_path)
        if not conn:
            continue
        try:
            band_filter = "AND band = ?" if band else ""
            params = [ts_start, ts_end]
            if band:
                params.append(band)
            rows = conn.execute(
                f"SELECT ts_start, ts_end, band, kind, trigger, severity, "
                f"peak_quantity, peak_value, origin, metrics, event_id, has_snippet "
                f"FROM nq_events "
                f"WHERE ts_start >= ? AND ts_start < ? {band_filter} "
                f"ORDER BY ts_start DESC LIMIT 200",
                params,
            ).fetchall()
            for row in rows:
                ts_s, ts_e, ev_band, kind, trigger, sev, pq, pv, origin, metrics_j, eid, hs = row
                events.append({
                    'event_id': eid,
                    'month': datetime.fromtimestamp(ts_s).strftime('%Y-%m'),
                    'has_snippet': hs,
                    'ts': ts_s,
                    'ts_end': ts_e,
                    'band': ev_band,
                    'kind': kind,
                    'trigger': trigger,
                    'severity': round(sev, 3) if sev else None,
                    'peak_qty': pq,
                    'peak_val': round(pv, 3) if pv else None,
                    'origin': origin,
                    'metrics': metrics_j,
                })
        except Exception:
            pass
        finally:
            conn.close()

    # Fallback: Legacy nq_boundary_events wenn keine PAC4200-Events
    if not events:
        for db_path in _legacy_dbs_for_days(days):
            conn = _open_legacy(db_path)
            if not conn:
                continue
            try:
                rows = conn.execute(
                    "SELECT boundary_ts, boundary_type, dfd_amplitude, f_nadir, local_impact_score "
                    "FROM nq_boundary_events "
                    "WHERE boundary_ts >= ? AND boundary_ts < ? "
                    "AND dfd_amplitude IS NOT NULL "
                    "ORDER BY boundary_ts DESC LIMIT 100",
                    (ts_start, ts_end),
                ).fetchall()
                for bts, btype, amp, f_nadir, local_score in rows:
                    sev = min(amp / 0.2, 1.0) if amp else 0.0
                    events.append({
                        'ts': bts,
                        'ts_end': bts + 360,
                        'band': 'NF_global',
                        'kind': 'dfd_normal' if amp < 0.1 else 'dfd_anomaly',
                        'trigger': 'df_step',
                        'severity': round(sev, 3),
                        'peak_qty': 'f',
                        'peak_val': round(f_nadir, 4) if f_nadir else None,
                        'origin': 'lokal' if (local_score or 0) > 0.5 else 'netzseitig',
                        'metrics': None,
                    })
            except Exception:
                pass
            finally:
                conn.close()

    events.sort(key=lambda e: e['ts'], reverse=True)
    return jsonify({'events': events[:200], 'n': len(events), 'source': 'nq_events' if events and events[0].get('band') != 'NF_global' else 'legacy'})


# ---------------------------------------------------------------------------
# NQ2 WP3: Zähler-Fixpunkte (Tooltip-Spiegelung PAC4200 ↔ Master-SM)
# ---------------------------------------------------------------------------

def _nq_primary_db(month: str) -> str:
    return os.path.join(_NQ_PRIMARY_DIR, f"nq_{month}.db")


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
# Musteranalyse-Datensatz (residual-bereinigt, nq_pattern_5min) — read-only
# ---------------------------------------------------------------------------

def _months_in_range(start, end):
    import datetime as _dt
    out = []
    d = _dt.date.fromtimestamp(start).replace(day=1)
    last = _dt.date.fromtimestamp(max(start, end - 1))
    while d <= last:
        out.append(d.strftime('%Y-%m'))
        d = (d.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    return out


@bp.route('/api/nq/pattern')
def api_nq_pattern():
    """Sauberer Musteranalyse-Datensatz (`nq_pattern_5min`): netzseitige U, f, PF, phi.

    Read-only. Parameter: ``?day=YYYY-MM-DD`` ODER ``?start=&end=`` (Unix-s).
    Interne (hinter dem PCC liegende) Lasteffekte sind residual-bereinigt.
    """
    day = request.args.get('day')
    if day:
        try:
            t = _time.strptime(day, '%Y-%m-%d')
            start = int(_time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
            end = start + 86400
        except Exception:
            return jsonify({'error': 'invalid day'}), 400
    else:
        end = request.args.get('end', type=int) or int(_time.time())
        start = request.args.get('start', type=int) or (end - 86400)
    cols = ['ts', 'u_clean_l1', 'u_clean_l2', 'u_clean_l3', 'u_meas_l1', 'u_meas_l2', 'u_meas_l3',
            'freq', 'pf_l1', 'pf_l2', 'pf_l3', 'phi_l1', 'phi_l2', 'phi_l3', 'du_int_max', 'origin']
    data = []
    for month in _months_in_range(start, end):
        conn = _open_legacy(_nq_primary_db(month))
        if not conn:
            continue
        try:
            rows = conn.execute(
                f"SELECT {','.join(cols)} FROM nq_pattern_5min WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start, end)).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for r in rows:
            data.append(dict(zip(cols, r)))
    return jsonify({'data': data, 'points': len(data), 'start': start, 'end': end,
                    'source': 'nq_pattern_5min', 'columns': cols})


# ---------------------------------------------------------------------------
# NQ2 WP4: Event-Schnipsel-Drill-down (200-ms-RAW-Serie je Event)
# ---------------------------------------------------------------------------

@bp.route('/api/nq/event/<int:event_id>')
def api_nq_event(event_id):
    """RAW-Schnipsel (Wide-Format) eines Events. ?month=YYYY-MM engt die DB ein."""
    month = request.args.get('month')
    if month:
        candidates = [_nq_primary_db(month)]
    else:
        candidates = sorted(glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db')), reverse=True)[:6]

    for db_path in candidates:
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            ev = conn.execute(
                "SELECT event_id, ts_start, ts_end, duration_s, band, kind, trigger, "
                "severity, peak_quantity, peak_value, origin, has_snippet "
                "FROM nq_events WHERE event_id = ?", (event_id,)).fetchone()
            if not ev:
                continue
            fast = conn.execute(
                "SELECT ts_ms, u_l1, u_l2, u_l3, u_l12, u_l23, u_l31, "
                "i_l1, i_l2, i_l3, p_tot, q_tot, s_tot, pf, f "
                "FROM nq_event_fast WHERE event_id = ? ORDER BY ts_ms", (event_id,)).fetchall()
            med = conn.execute(
                "SELECT ts, thd_u_l1, thd_u_l2, thd_u_l3, thd_i_l1, thd_i_l2, thd_i_l3 "
                "FROM nq_event_medium WHERE event_id = ? ORDER BY ts", (event_id,)).fetchall()
        except Exception:
            conn.close()
            continue
        conn.close()

        fcols = ['ts_ms', 'u_l1', 'u_l2', 'u_l3', 'u_l12', 'u_l23', 'u_l31',
                 'i_l1', 'i_l2', 'i_l3', 'p_tot', 'q_tot', 's_tot', 'pf', 'f']
        mcols = ['ts', 'thd_u_l1', 'thd_u_l2', 'thd_u_l3', 'thd_i_l1', 'thd_i_l2', 'thd_i_l3']
        return jsonify({
            'event': {
                'event_id': ev[0], 'ts_start': ev[1], 'ts_end': ev[2],
                'duration_s': ev[3], 'band': ev[4], 'kind': ev[5], 'trigger': ev[6],
                'severity': ev[7], 'peak_quantity': ev[8], 'peak_value': ev[9],
                'origin': ev[10], 'has_snippet': ev[11],
            },
            'fast': [dict(zip(fcols, r)) for r in fast],
            'medium': [dict(zip(mcols, r)) for r in med],
            'count': len(fast),
        })
    return jsonify({'error': 'event not found', 'event_id': event_id}), 404


# ---------------------------------------------------------------------------
# NQ2 WP5: Langzeit-Aggregate-API + feste Chart-Seite
# ---------------------------------------------------------------------------

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
            "SELECT ts, U_L1_N_Netz, U_L2_N_Netz, U_L3_N_Netz, f_Netz "
            "FROM data_15min WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start, end),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    rt3 = 1.7320508075688772
    for ts, u1n, u2n, u3n, f in rows:
        u12 = (u1n * rt3) if u1n is not None else None
        u23 = (u2n * rt3) if u2n is not None else None
        u31 = (u3n * rt3) if u3n is not None else None
        rows_out.append({
            'ts': int(ts),
            'U_L12': u12, 'U_L23': u23, 'U_L31': u31,
            'U_L12_min': u12, 'U_L12_max': u12,
            'U_L23_min': u23, 'U_L23_max': u23,
            'U_L31_min': u31, 'U_L31_max': u31,
            'FREQ': _safe_float(f), 'FREQ_min': _safe_float(f), 'FREQ_max': _safe_float(f),
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
    rows = raw.get('data', [])
    source = raw.get('source', f'nq_{rng}')
    if not rows:
        rows = _core_fallback_rows(start, end)
        if rows:
            source = 'core_data15min_fallback'

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
