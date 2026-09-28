"""pac4200-Submodul: NQ-Analyse-APIs (Rolle B, read-only).

Aufgeteilt aus ``routes/pac4200.py`` (2026-09-28). DFD-Statistik (15-min-
Handelsmuster), Tages-/Wochenprofil (Frequenz/Spannung) und Event-Liste aus
Legacy-NQ- bzw. PAC4200-DBs.
"""
import math
import os
from datetime import datetime
from glob import glob

from flask import jsonify, request

from routes.pac4200 import bp
from routes.pac4200._shared import (
    _F_MIN, _F_MAX, _U_MIN, _U_MAX,
    _NQ_PRIMARY_DIR,
    _legacy_dbs_for_days, _open_legacy, _ts_window,
)


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
