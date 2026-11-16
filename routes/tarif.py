"""
Blueprint: Dynamischer Börsentarif (Rolle B, read-only).

  /analyse/strompreis              HTML-Ansicht: Tarifvergleich Fix vs. dynamisch
  /api/tarif/tag?date=YYYY-MM-DD   15-min-Gesamtpreis-Kurve (ct/kWh) + Tagesbilanz
  /api/tarif/analyse               Vergleichstabelle (Monat/Jahr) + Methodik/Quellen

Datenbasis: spot_price_15min (EPEX Day-Ahead) + tariff_cost_{daily,monthly,yearly}
(verbrauchsgewichtete reale kWh-Kosten), beide read-only über die Tiered-Views.
Gesamtkosten-Modell: dynamic_tariff. Kein Hardware-Zugriff, kein DB-Write.
"""
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, jsonify, render_template, request

import config
import dynamic_tariff as dyn
from routes.helpers import get_db_connection, api_error_response

logger = logging.getLogger(__name__)

bp = Blueprint('tarif', __name__)

_MONTH_NAMES = ['', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
                'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']

# Quellen für die Gesamtkosten-Herleitung (Methodik-Panel der Analyse-Seite).
_QUELLEN = [
    {'name': 'Fraunhofer ISE — Energy-Charts (EPEX Day-Ahead DE-LU, 15-min)',
     'url': 'https://api.energy-charts.info/price?bzn=DE-LU'},
    {'name': 'MITNETZ STROM — Preisblatt Netznutzung 2026 (NS SLP, Arbeitspreis)',
     'url': 'https://www.mitnetz-strom.de/online-services/download-center/preise'},
    {'name': 'Bundesnetzagentur / EnFG — Umlagen 2026 (KWKG, Offshore, § 19 StromNEV)',
     'url': 'https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen'},
    {'name': 'Tibber — Preiskonditionen (Grundgebühr, Beschaffungsaufschlag)',
     'url': 'https://tibber.com/de/preise'},
]


def _nav_query():
    try:
        from routes.pages import _get_nav_context
        return urlencode(_get_nav_context(request.args))
    except Exception:
        return ''


@bp.route('/analyse/strompreis')
def strompreis_page():
    """Ansicht: Tarifvergleich Fixtarif vs. dynamischer Börsentarif (Tibber-Schiene)."""
    nav_query = _nav_query()
    return render_template('analyse_strompreis_view.html',
                           nav_query=('?' + nav_query) if nav_query else '')


def _day_bounds(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    t0 = int(d.timestamp())
    t1 = int((d + timedelta(days=1)).timestamp())
    return d, t0, t1


@bp.route('/api/tarif/tag')
def api_tarif_tag():
    """15-min-Gesamtpreis-Kurve (brutto ct/kWh) für einen Tag + Tagesbilanz.

    Die Kurve wird live aus spot_price_15min über das Gesamtkosten-Modell
    abgeleitet (unabhängig vom Verbrauch). Die Tagesbilanz (verbrauchsgewichtete
    Kosten, Fixtarif-Vergleich) stammt aus tariff_cost_daily.
    """
    try:
        date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
        d, t0, t1 = _day_bounds(date_str)

        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'DB nicht verfügbar'}), 503
        cur = conn.cursor()

        rows = cur.execute(
            "SELECT ts, price_eur_mwh FROM spot_price_15min "
            "WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()
        points = []
        for ts, eur_mwh in rows:
            spot_ct = dyn.spot_eur_mwh_to_ct_kwh(eur_mwh)
            points.append({'timestamp': int(ts),
                           'total_ct': dyn.total_price_ct(spot_ct),
                           'spot_ct': round(spot_ct, 4)})

        day = None
        drow = cur.execute(
            "SELECT bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct, "
            "dyn_cost_eur, fix_price_ct, fix_cost_eur, coverage_pct "
            "FROM tariff_cost_daily WHERE day_ts = ?", (t0,)).fetchone()
        if drow:
            day = {'bezug_kwh': drow[0], 'spot_avg_ct': drow[1],
                   'dyn_avg_ct': drow[2], 'dyn_simple_avg_ct': drow[3],
                   'dyn_cost_eur': drow[4], 'fix_price_ct': drow[5],
                   'fix_cost_eur': drow[6], 'coverage_pct': drow[7]}
        conn.close()

        fix_ct = dyn.fixtarif_ct(d.year, d.month, d.day)
        return jsonify({'date': date_str, 'points': points, 'day': day,
                        'fix_price_ct': fix_ct,
                        'has_data': bool(points)})
    except Exception as exc:
        return api_error_response(exc, 'tarif_tag')


def _shift_potential(cur, year):
    """Best-Case-Lastverschiebung: flexible Verbraucher (E-Auto, Heizpatrone) in die
    günstigsten Viertelstunden des Tages schieben → maximal mögliche dyn. Ersparnis.
    Grobmodell (Obergrenze): verschiebbare kWh/Tag = min(Gerätetagesenergie,
    Netzbezug), neu bepreist über die billigsten 15-min-Buckets (Leistungsdeckel
    shift_max_kw); Referenz = Tages-Ø der dyn. Gesamtkosten. Zeigt, wie viel ein
    optimiertes Verbrauchsprofil gegenüber dem IST-Profil sparen könnte.
    """
    cfg = config.DYN_TARIF
    devices = cfg.get('shiftable_devices', [])
    cap_kwh = max(0.1, cfg.get('shift_max_kw', 11.0)) * 0.25
    y0 = int(datetime(year, 1, 1).timestamp())
    y1 = int(datetime(year + 1, 1, 1).timestamp())

    dev_by_day = {}
    for dev in devices:
        try:
            for ds, wh in cur.execute(
                    f"SELECT date(ts,'unixepoch','localtime'), energy_wh FROM {dev}_daily "
                    f"WHERE ts >= ? AND ts < ?", (y0, y1)):
                dev_by_day[ds] = dev_by_day.get(ds, 0.0) + (wh or 0.0) / 1000.0
        except Exception:
            pass

    spot_by_day = {}
    for ts, eur in cur.execute(
            "SELECT ts, price_eur_mwh FROM spot_price_15min WHERE ts >= ? AND ts < ?", (y0, y1)):
        ds = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
        spot_by_day.setdefault(ds, []).append(dyn.total_price_ct(dyn.spot_eur_mwh_to_ct_kwh(eur)))

    months, yr = {}, {'shift_kwh': 0.0, 'savings_eur': 0.0}
    for day_ts, bezug, dyn_avg in cur.execute(
            "SELECT day_ts, bezug_kwh, dyn_avg_ct FROM tariff_cost_daily "
            "WHERE day_ts >= ? AND day_ts < ?", (y0, y1)):
        d = datetime.fromtimestamp(day_ts)
        ds = d.strftime('%Y-%m-%d')
        shift = min(dev_by_day.get(ds, 0.0), bezug or 0.0)
        prices = spot_by_day.get(ds)
        if shift <= 0 or not prices or not dyn_avg:
            continue
        need, cheap = shift, 0.0
        for p in sorted(prices):
            take = min(need, cap_kwh)
            cheap += take * p / 100.0
            need -= take
            if need <= 1e-9:
                break
        if need > 1e-9:
            cheap += need * max(prices) / 100.0
        sav = max(0.0, shift * dyn_avg / 100.0 - cheap)
        mm = months.setdefault(d.month, {'shift_kwh': 0.0, 'savings_eur': 0.0})
        mm['shift_kwh'] += shift
        mm['savings_eur'] += sav
        yr['shift_kwh'] += shift
        yr['savings_eur'] += sav
    return months, yr


@bp.route('/api/tarif/analyse')
def api_tarif_analyse():
    """Vergleichstabelle (Monat/Jahr) + Methodik/Quellen für die Analyse-Seite."""
    try:
        year = request.args.get('year', type=int) or datetime.now().year

        conn = get_db_connection()
        if conn is None:
            return jsonify({'error': 'DB nicht verfügbar'}), 503
        cur = conn.cursor()

        months = []
        for r in cur.execute(
            "SELECT month, bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct, "
            "dyn_cost_eur, dyn_fixkosten_eur, fix_price_ct, fix_cost_eur, "
            "fix_grundpreis_eur, coverage_pct FROM tariff_cost_monthly "
            "WHERE year = ? ORDER BY month", (year,)).fetchall():
            dyn_total = (r[5] or 0) + (r[6] or 0)
            fix_total = (r[8] or 0) + (r[9] or 0)
            months.append({
                'month': r[0], 'month_name': _MONTH_NAMES[r[0]],
                'bezug_kwh': r[1], 'spot_avg_ct': r[2], 'dyn_avg_ct': r[3],
                'dyn_simple_avg_ct': r[4], 'dyn_cost_eur': r[5],
                'dyn_fixkosten_eur': r[6], 'fix_price_ct': r[7],
                'fix_cost_eur': r[8], 'fix_grundpreis_eur': r[9],
                'coverage_pct': r[10],
                'dyn_total_eur': round(dyn_total, 2),
                'fix_total_eur': round(fix_total, 2),
                'delta_eur': round(dyn_total - fix_total, 2),
            })

        yr = cur.execute(
            "SELECT bezug_kwh, spot_avg_ct, dyn_avg_ct, dyn_simple_avg_ct, "
            "dyn_cost_eur, dyn_fixkosten_eur, fix_price_ct, fix_cost_eur, "
            "fix_grundpreis_eur, coverage_pct FROM tariff_cost_yearly "
            "WHERE year = ?", (year,)).fetchone()
        year_row = None
        if yr:
            dyn_total = (yr[4] or 0) + (yr[5] or 0)
            fix_total = (yr[7] or 0) + (yr[8] or 0)
            year_row = {
                'year': year, 'bezug_kwh': yr[0], 'spot_avg_ct': yr[1],
                'dyn_avg_ct': yr[2], 'dyn_simple_avg_ct': yr[3],
                'dyn_cost_eur': yr[4], 'dyn_fixkosten_eur': yr[5],
                'fix_price_ct': yr[6], 'fix_cost_eur': yr[7],
                'fix_grundpreis_eur': yr[8], 'coverage_pct': yr[9],
                'dyn_total_eur': round(dyn_total, 2),
                'fix_total_eur': round(fix_total, 2),
                'delta_eur': round(dyn_total - fix_total, 2),
                'empfehlung': 'fix' if dyn_total > fix_total else 'dynamisch',
            }

        avail_years = [r[0] for r in cur.execute(
            "SELECT DISTINCT year FROM tariff_cost_yearly ORDER BY year").fetchall()]

        # Best-Case-Lastverschiebung (flexible Verbraucher in Niedrigpreisfenster).
        shift_months, shift_year = _shift_potential(cur, year)
        for m in months:
            sm = shift_months.get(m['month'], {'shift_kwh': 0.0, 'savings_eur': 0.0})
            m['shift_kwh'] = round(sm['shift_kwh'], 1)
            m['shift_savings_eur'] = round(sm['savings_eur'], 2)
            m['dyn_opt_total_eur'] = round(m['dyn_total_eur'] - sm['savings_eur'], 2)
            m['delta_opt_eur'] = round(m['dyn_opt_total_eur'] - m['fix_total_eur'], 2)
        if year_row:
            year_row['shift_kwh'] = round(shift_year['shift_kwh'], 1)
            year_row['shift_savings_eur'] = round(shift_year['savings_eur'], 2)
            year_row['dyn_opt_total_eur'] = round(
                year_row['dyn_total_eur'] - shift_year['savings_eur'], 2)
            year_row['delta_opt_eur'] = round(
                year_row['dyn_opt_total_eur'] - year_row['fix_total_eur'], 2)
            year_row['empfehlung_opt'] = (
                'fix' if year_row['dyn_opt_total_eur'] > year_row['fix_total_eur']
                else 'dynamisch')
        conn.close()

        # Komponenten-Aufschlüsselung mit dem Jahres-Durchschnitts-Börsenpreis.
        ref_spot = (year_row or {}).get('spot_avg_ct') or 8.0
        breakdown = dyn.components_breakdown_ct(ref_spot)

        return jsonify({
            'year': year,
            'available_years': avail_years,
            'months': months,
            'year_total': year_row,
            'netto_adder_ct': dyn.netto_adder_ct(),
            'total_at_ref_spot_ct': dyn.total_price_ct(ref_spot),
            'ref_spot_ct': round(ref_spot, 2),
            'breakdown': breakdown,
            'dyn_fixkosten_eur_monat': dyn.dyn_fixkosten_eur_monat(),
            'dyn_fixkosten_breakdown': dyn.dyn_fixkosten_breakdown_eur_monat(),
            'mwst_pct': config.DYN_TARIF['mwst_pct'],
            'bidding_zone': config.DYN_TARIF['bidding_zone'],
            'shift_max_kw': config.DYN_TARIF.get('shift_max_kw'),
            'shiftable_devices': config.DYN_TARIF.get('shiftable_devices', []),
            'quellen': _QUELLEN,
        })
    except Exception as exc:
        return api_error_response(exc, 'tarif_analyse')
