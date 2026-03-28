"""
Blueprint: Visualisierungs-APIs.

Enthält: /api/tag_visualization, /api/monat_visualization,
         /api/jahr_visualization, /api/gesamt_visualization

Alle Perioden-APIs (monat/jahr/gesamt) liefern freq_extremes mit
Netzfrequenz-Min/Max inkl. Zeitstempel aus data_1min.
"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, api_error_response, validate_year_month

bp = Blueprint('visualization', __name__)

# Plausibilitätsfaktor: Counter-Delta darf max. diesen Faktor × Fallback betragen
_COUNTER_PLAUSIBILITY_FACTOR = 3.0
_MIN_DELTA_WH = 50.0


def _plausible_counter_delta(start, end, fallback):
    """Berechne Counter-Delta mit Plausibilitätsprüfung.

    Wenn Start/End vorhanden sind, wird End−Start berechnet.
    Falls das Ergebnis negativ ist oder um Faktor > 3 vom Fallback (SUM Δ)
    abweicht, wird der Fallback-Wert (bereits reset-korrigiert) verwendet.
    """
    if start is not None and end is not None:
        delta = end - start
        fb = fallback or 0
        # Negativer Counter → Zähler-Reset
        if delta < -_MIN_DELTA_WH:
            return fb
        # Counter viel größer als SUM(Δ) → Zähler-Sprint
        if abs(fb) > _MIN_DELTA_WH and delta > _COUNTER_PLAUSIBILITY_FACTOR * abs(fb):
            return fb
        # Plausibel
        return delta
    return fallback or 0


def _get_freq_extremes(cursor, ts_start, ts_end):
    """Ermittle Netzfrequenz-Extremwerte (Min/Max) mit Zeitstempel aus data_1min.

    Returns dict mit f_min, f_min_ts, f_max, f_max_ts oder None.
    """
    try:
        cursor.execute("""
            SELECT ts, f_Netz_min FROM data_1min
            WHERE ts >= ? AND ts < ? AND f_Netz_min IS NOT NULL
            ORDER BY f_Netz_min ASC LIMIT 1
        """, (ts_start, ts_end))
        min_row = cursor.fetchone()

        cursor.execute("""
            SELECT ts, f_Netz_max FROM data_1min
            WHERE ts >= ? AND ts < ? AND f_Netz_max IS NOT NULL
            ORDER BY f_Netz_max DESC LIMIT 1
        """, (ts_start, ts_end))
        max_row = cursor.fetchone()

        if not min_row and not max_row:
            return None

        result = {}
        if min_row:
            dt_min = datetime.fromtimestamp(min_row[0])
            result['f_min'] = round(min_row[1], 3)
            result['f_min_ts'] = min_row[0]
            result['f_min_date'] = dt_min.strftime('%d.%m.%y')
            result['f_min_time'] = dt_min.strftime('%H:%M')
        if max_row:
            dt_max = datetime.fromtimestamp(max_row[0])
            result['f_max'] = round(max_row[1], 3)
            result['f_max_ts'] = max_row[0]
            result['f_max_date'] = dt_max.strftime('%d.%m.%y')
            result['f_max_time'] = dt_max.strftime('%H:%M')
        return result
    except Exception as e:
        logging.warning(f"Freq-Extremwerte Fehler: {e}")
        return None


@bp.route('/api/tag_visualization')
def api_tag_visualization():
    """
    Liefert alle Daten für Tag-Visualisierung aus data_1min (falls vorhanden), sonst data_15min
    Mit berechneten Werten: P_Batt, P_Einspeis/Bezug, P_Direktverbrauch, etc.
    Inkl. counter_totals: Energiezähler-Differenzen (exakt, = Solarweb) für Tages-Summen.
    """
    try:
        date_param = request.args.get('date')  # Format: YYYY-MM-DD

        conn = get_db_connection()
        cursor = conn.cursor()

        # Basis-Query: Versuche erst data_1min, falls nicht verfügbar dann data_15min
        def _build_tag_query(table, energy_col, where_clause):
            """Baut die SELECT-Query tabellen-abhängig (data_1min vs data_15min)."""
            if table == 'data_1min':
                extra_cols = """P_Exp, P_Imp,
                    P_inBatt, P_outBatt, P_Direct,
                    P_inBatt_PV, P_inBatt_Grid,
                    W_Ertrag, W_Einspeis, W_Bezug,
                    W_inBatt, W_outBatt, W_Direct, W_Verbrauch,
                    W_inBatt_PV, W_inBatt_Grid"""
            else:
                # data_15min: Fehlende Spalten als NULL
                extra_cols = """NULL as P_Exp, NULL as P_Imp,
                    NULL as P_inBatt, NULL as P_outBatt, NULL as P_Direct,
                    P_inBatt_PV, P_inBatt_Grid,
                    NULL as W_Ertrag, NULL as W_Einspeis, NULL as W_Bezug,
                    NULL as W_inBatt, NULL as W_outBatt, NULL as W_Direct, NULL as W_Verbrauch,
                    W_inBatt_PV, W_inBatt_Grid"""
            return f"""
                SELECT
                    ts,
                    P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                    P_DC1_avg, P_DC1_min, P_DC1_max,
                    P_DC2_avg, P_DC2_min, P_DC2_max,
                    P_F2_avg, P_F2_min, P_F2_max,
                    P_F3_avg, P_F3_min, P_F3_max,
                    P_Netz_avg, P_Netz_min, P_Netz_max,
                    SOC_Batt_avg,
                    f_Netz_avg,
                    {energy_col} as W_Energy_delta,
                    W_Imp_Netz_delta,
                    W_Exp_Netz_delta,
                    W_DC1_delta,
                    W_DC2_delta,
                    {extra_cols}
                FROM {table}
                WHERE {where_clause}
                ORDER BY ts
            """

        if date_param:
            # Prüfe ob Daten in data_1min existieren
            cursor.execute("""
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
                  AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
            """, (date_param, date_param))
            count_1min = cursor.fetchone()[0]

            table = 'data_1min' if count_1min > 0 else 'data_15min'
            energy_col = 'W_AC_Inv_delta' if table == 'data_1min' else 'W_PV_total_delta'

            where = "datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')"
            query = _build_tag_query(table, energy_col, where)
            cursor.execute(query, (date_param, date_param))
        else:
            # Heute: Prüfe data_1min
            cursor.execute("""
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')
            """)
            count_1min = cursor.fetchone()[0]

            table = 'data_1min' if count_1min > 0 else 'data_15min'
            energy_col = 'W_AC_Inv_delta' if table == 'data_1min' else 'W_PV_total_delta'

            where = "datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')"
            query = _build_tag_query(table, energy_col, where)
            cursor.execute(query)

        rows = cursor.fetchall()

        # Berechne alle abgeleiteten Werte
        data_points = []
        for row in rows:
            ts, p_ac_avg, p_ac_min, p_ac_max, \
            p_dc1_avg, p_dc1_min, p_dc1_max, \
            p_dc2_avg, p_dc2_min, p_dc2_max, \
            p_f2_avg, p_f2_min, p_f2_max, \
            p_f3_avg, p_f3_min, p_f3_max, \
            p_netz_avg, p_netz_min, p_netz_max, \
            soc_avg, f_netz_avg, \
            w_energy_delta, w_imp_netz, w_exp_netz, w_dc1, w_dc2, \
            p_exp, p_imp, \
            p_inbatt, p_outbatt, p_direct, \
            p_inbatt_pv, p_inbatt_grid, \
            w_ertrag, w_einspeis, w_bezug, \
            w_inbatt, w_outbatt, w_direct, w_verbrauch, \
            w_inbatt_pv, w_inbatt_grid = row

            # Verwende die BERECHNETEN Werte aus der DB!
            p_produktion_avg = (p_direct or 0) + (p_inbatt_pv or 0) + (p_exp or 0)
            p_haushalt_avg = (p_direct or 0) + (p_outbatt or 0) + (p_imp or 0)

            data_points.append({
                'timestamp': ts,
                'soc': soc_avg,

                # Ertrag-Ansicht
                'p_exp': round(p_exp or 0, 1),
                'p_inbatt_pv': round(p_inbatt_pv or 0, 1),
                'p_inbatt_grid': round(p_inbatt_grid or 0, 1),
                'p_direct_ertrag': round(p_direct or 0, 1),
                'p_produktion': round(p_produktion_avg, 1),
                'w_ertrag': round(w_ertrag or 0, 2),

                # Verbrauch-Ansicht
                'p_imp': round(p_imp or 0, 1),
                'p_outbatt': round(p_outbatt or 0, 1),
                'p_direct_verbrauch': round(p_direct or 0, 1),
                'p_haushalt': round(p_haushalt_avg, 1),
                'w_verbrauch': round(w_verbrauch or 0, 2),

                # Zusätzliche Infos
                'f_netz_avg': round(f_netz_avg, 3) if f_netz_avg else 50.0,
                'w_einspeis': round(w_einspeis or 0, 2),
                'w_bezug': round(w_bezug or 0, 2)
            })

        # ─── Counter-basierte Tages-Totals (exakt wie Solarweb) ────────
        counter_totals = None
        try:
            if date_param:
                ct_query = """
                    SELECT
                        (MAX(W_DC1) - MIN(W_DC1)) / 1000.0,
                        (MAX(W_DC2) - MIN(W_DC2)) / 1000.0,
                        (MAX(W_Exp_F2) - MIN(W_Exp_F2)) / 1000.0,
                        (MAX(W_Exp_F3) - MIN(W_Exp_F3)) / 1000.0,
                        (MAX(W_Imp_Netz) - MIN(W_Imp_Netz)) / 1000.0,
                        (MAX(W_Exp_Netz) - MIN(W_Exp_Netz)) / 1000.0,
                        (MAX(W_AC_Inv) - MIN(W_AC_Inv)) / 1000.0,
                        (MAX(W_Imp_WP) - MIN(W_Imp_WP)) / 1000.0,
                        COUNT(*)
                    FROM raw_data
                    WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
                      AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
                """
                cursor.execute(ct_query, (date_param, date_param))
            else:
                ct_query = """
                    SELECT
                        (MAX(W_DC1) - MIN(W_DC1)) / 1000.0,
                        (MAX(W_DC2) - MIN(W_DC2)) / 1000.0,
                        (MAX(W_Exp_F2) - MIN(W_Exp_F2)) / 1000.0,
                        (MAX(W_Exp_F3) - MIN(W_Exp_F3)) / 1000.0,
                        (MAX(W_Imp_Netz) - MIN(W_Imp_Netz)) / 1000.0,
                        (MAX(W_Exp_Netz) - MIN(W_Exp_Netz)) / 1000.0,
                        (MAX(W_AC_Inv) - MIN(W_AC_Inv)) / 1000.0,
                        (MAX(W_Imp_WP) - MIN(W_Imp_WP)) / 1000.0,
                        COUNT(*)
                    FROM raw_data
                    WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')
                """
                cursor.execute(ct_query)

            ct_row = cursor.fetchone()
            if ct_row and ct_row[8] and ct_row[8] > 100:
                dc1, dc2, exp_f2, exp_f3, imp_netz, exp_netz, ac_inv, imp_wp, cnt = ct_row
                ertrag = (dc1 or 0) + (dc2 or 0) + (exp_f2 or 0) + (exp_f3 or 0)
                einspeis = exp_netz or 0
                bezug = imp_netz or 0
                verbrauch = ertrag + bezug - einspeis
                counter_totals = {
                    'ertrag_kwh': round(ertrag, 3),
                    'einspeis_kwh': round(einspeis, 3),
                    'bezug_kwh': round(bezug, 3),
                    'verbrauch_kwh': round(verbrauch, 3),
                    'dc1_kwh': round(dc1 or 0, 3),
                    'dc2_kwh': round(dc2 or 0, 3),
                    'exp_f2_kwh': round(exp_f2 or 0, 3),
                    'exp_f3_kwh': round(exp_f3 or 0, 3),
                    'ac_inv_kwh': round(ac_inv or 0, 3),
                    'waermepumpe_kwh': round(imp_wp or 0, 3),
                    'raw_count': cnt
                }
        except Exception as e:
            logging.warning(f"Counter-Totals Fehler: {e}")

        result = {
            'date': date_param or 'today',
            'datapoints': data_points
        }
        if counter_totals:
            result['counter_totals'] = counter_totals

        return jsonify(result)

    except Exception as e:
        return api_error_response(e, "Tag-Visualisierung")
    finally:
        if 'conn' in locals() and conn:
            try:
                conn.close()
            except Exception:
                pass


@bp.route('/api/monat_visualization')
def monat_visualization():
    """Liefert Tagesdaten für Monatsansicht - gestapelte Balken"""
    try:
        # Parameter: year, month (optional, default = aktueller Monat)
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        if not year or not month:
            now = datetime.now()
            year = now.year
            month = now.month

        valid, err = validate_year_month(year, month)
        if err:
            return err
        year, month = valid

        # Ersten und letzten Tag des Monats berechnen
        first_day = datetime(year, month, 1)
        if month == 12:
            last_day = datetime(year + 1, 1, 1)
        else:
            last_day = datetime(year, month + 1, 1)

        first_ts = int(first_day.timestamp())
        last_ts = int(last_day.timestamp())

        # RAM-DB als Quelle fuer konsistente API-Daten
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfuegbar"}), 500
        cursor = conn.cursor()

        logging.info(f"Monat {month}/{year}: first_ts={first_ts}, last_ts={last_ts}")

        # Hole Tagesdaten aus daily_data mit Zählerständen
        cursor.execute("""
            SELECT ts,
                   W_AC_Inv_start, W_AC_Inv_end,
                   W_Exp_Netz_start, W_Exp_Netz_end,
                   W_Imp_Netz_start, W_Imp_Netz_end,
                   W_Batt_Charge_total, W_PV_Direct_total,
                   W_Batt_Discharge_total, W_WP_total,
                   SOC_Batt_avg,
                 W_PV_total, W_Exp_Netz_total, W_Imp_Netz_total, W_Consumption_total,
                   f_Netz_avg, f_Netz_min, f_Netz_max,
                   forecast_kwh
            FROM daily_data
            WHERE ts >= ? AND ts < ?
            ORDER BY ts
        """, (first_ts, last_ts))

        rows = cursor.fetchall()
        logging.info(f"Query ergab {len(rows)} Zeilen für Monat {month}/{year}")
        if rows:
            logging.info(f"Erste Zeile: ts={rows[0][0]}, Letzte: ts={rows[-1][0]}")

        # Wattpilot-Tagesdaten laden (falls Tabelle existiert)
        wattpilot_by_day = {}
        try:
            cursor.execute("""
                SELECT ts, energy_wh, max_power_w, charging_hours, sessions
                FROM wattpilot_daily
                WHERE ts >= ? AND ts < ?
            """, (first_ts, last_ts))
            for wattpilot_row in cursor.fetchall():
                day_key = (int(wattpilot_row[0]) // 86400) * 86400
                wattpilot_by_day[day_key] = {
                    'energy_wh': wattpilot_row[1] or 0,
                    'max_power_w': wattpilot_row[2] or 0,
                    'charging_hours': wattpilot_row[3] or 0,
                    'sessions': wattpilot_row[4] or 0
                }
        except Exception:
            pass  # Tabelle existiert noch nicht

        # Forecast aus data_15min (W -> kWh pro Tag)
        forecast_by_day = {}
        try:
            cursor.execute("""
                SELECT
                    strftime('%s', datetime(ts, 'unixepoch', 'localtime', 'start of day')) as day_ts,
                    COALESCE(SUM(W_PV_FC_delta), 0) / 1000.0 as forecast_kwh,
                    COALESCE(SUM(W_PV_CS_delta), 0) / 1000.0 as clearsky_kwh
                FROM data_15min
                WHERE ts >= ? AND ts < ?
                  AND (W_PV_FC_delta IS NOT NULL OR W_PV_CS_delta IS NOT NULL)
                GROUP BY day_ts
            """, (first_ts, last_ts))
            for row in cursor.fetchall():
                day_ts = int(row[0])
                forecast_by_day[day_ts] = {
                    'forecast_kwh': row[1],
                    'clearsky_kwh': row[2]
                }
        except Exception:
            pass

        datapoints = []
        current_ts = datetime.now().replace(hour=1, minute=0, second=0, microsecond=0).timestamp()

        for row in rows:
            ts, w_ac_start, w_ac_end, w_exp_start, w_exp_end, w_imp_start, w_imp_end, \
                w_batt_charge, w_pv_direct, w_batt_discharge, w_wp, soc_avg, \
                w_pv_fallback, w_exp_fallback, w_imp_fallback, w_consumption_fallback, \
                f_netz_avg, f_netz_min, f_netz_max, forecast_kwh = row

            # Für LAUFENDE Tage (heute): Nutze Fallback (Deltas)
            is_current_day = (ts >= current_ts)

            if is_current_day:
                w_pv = w_pv_fallback or 0
                w_exp = w_exp_fallback or 0
                w_imp = w_imp_fallback or 0
            else:
                # PV: IMMER Fallback (W_PV_total) verwenden, da W_AC_Inv nur F1
                # (DC1+DC2) trackt, W_PV_total dagegen alle 3 Inverter enthält.
                w_pv = w_pv_fallback or 0
                w_exp = _plausible_counter_delta(w_exp_start, w_exp_end, w_exp_fallback)
                w_imp = _plausible_counter_delta(w_imp_start, w_imp_end, w_imp_fallback)

            # Verbrauchskomponenten berechnen
            w_erzeugung_kwh = (w_pv or 0) / 1000
            w_direktverbrauch_kwh = (w_pv_direct or 0) / 1000
            w_batterieentladung_kwh = (w_batt_discharge or 0) / 1000
            w_netzbezug_kwh = (w_imp or 0) / 1000

            # Wattpilot-Verbrauch für diesen Tag (Info-Feld, NICHT in Gesamtverbrauch!)
            # w_wattpilot ist der Wallbox-Gesamtzähler (PV + Netz-Anteil).
            # Der PV-Anteil steckt bereits in w_direktverbrauch (PV_Direct).
            day_key = (int(ts) // 86400) * 86400
            wattpilot_day = wattpilot_by_day.get(day_key, {})
            w_wattpilot_kwh = (wattpilot_day.get('energy_wh', 0) or 0) / 1000

            # Gesamtverbrauch und Autarkie berechnen
            w_einspeisung_kwh = (w_exp or 0) / 1000
            if w_consumption_fallback and w_consumption_fallback > 0:
                gesamtverbrauch = w_consumption_fallback / 1000
            else:
                gesamtverbrauch = w_netzbezug_kwh + w_batterieentladung_kwh + w_direktverbrauch_kwh

            # Eigenverbrauch = PV − Einspeisung (zähler-basiert, exakt)
            # NICHT Direct+BattDis+Wattpilot (Doppelzählung Wattpilot-PV-Anteil!)
            eigenverbrauch = w_erzeugung_kwh - w_einspeisung_kwh
            autarkie = (eigenverbrauch / gesamtverbrauch * 100) if gesamtverbrauch > 0 else 0

            fc_day = forecast_by_day.get(day_key)
            fc_kwh = fc_day['forecast_kwh'] if fc_day and fc_day['forecast_kwh'] else None

            datapoints.append({
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
                'day': datetime.fromtimestamp(ts).day,
                'w_einspeisung': round((w_exp or 0) / 1000, 2),
                'w_batterieladung': round((w_batt_charge or 0) / 1000, 2),
                'w_direktverbrauch': round(w_direktverbrauch_kwh, 2),
                'w_waermepumpe': round((w_wp or 0) / 1000, 2),
                'w_wattpilot': round(w_wattpilot_kwh, 2),
                'w_netzbezug': round(w_netzbezug_kwh, 2),
                'w_batterieentladung': round(w_batterieentladung_kwh, 2),
                'w_pv_total': round(w_erzeugung_kwh, 2),
                'w_gesamtverbrauch': round(gesamtverbrauch, 2),
                'autarkie': round(autarkie, 1),
                'soc_avg': round(soc_avg, 1) if soc_avg else 0,
                'f_netz_avg': round(f_netz_avg, 3) if f_netz_avg else None,
                'f_netz_min': round(f_netz_min, 3) if f_netz_min else None,
                'f_netz_max': round(f_netz_max, 3) if f_netz_max else None,
                'wattpilot_sessions': wattpilot_day.get('sessions', 0),
                'wattpilot_charging_hours': round(wattpilot_day.get('charging_hours', 0), 1),
                'forecast_kwh': round(fc_kwh, 1) if fc_kwh is not None else (round(forecast_kwh, 1) if forecast_kwh else None),
            })

        # Frequenz-Extremwerte für den Monat
        freq_extremes = _get_freq_extremes(cursor, first_ts, last_ts)

        response = {
            'year': year,
            'month': month,
            'datapoints': datapoints
        }
        if freq_extremes:
            response['freq_extremes'] = freq_extremes

        conn.close()
        return jsonify(response)

    except Exception as e:
        return api_error_response(e, "Monat-Visualisierung")
    finally:
        if 'conn' in locals() and conn:
            try:
                conn.close()
            except Exception:
                pass


@bp.route('/api/jahr_visualization')
def jahr_visualization():
    """Liefert Monatsdaten für Jahresansicht - gestapelte Balken (wie Monats-Chart)"""
    try:
        year = request.args.get('year', type=int)
        if not year:
            year = datetime.now().year

        valid, err = validate_year_month(year)
        if err:
            return err
        year, _ = valid

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500

        cursor = conn.cursor()
        cursor.execute("""
            SELECT month, solar_erzeugung_kwh, netz_bezug_kwh, netz_einspeisung_kwh,
                   batt_ladung_kwh, batt_entladung_kwh, direktverbrauch_kwh,
                   gesamt_verbrauch_kwh, heizpatrone_kwh, wattpilot_kwh, sonnenstunden
            FROM monthly_statistics
            WHERE year = ?
            ORDER BY month
        """, (year,))

        rows = cursor.fetchall()
        datapoints = []
        total_sonnenstunden = 0

        for row in rows:
            month, solar, bezug, einsp, batt_lad, batt_entl, direkt, gesamt, heiz, wattpilot, sonnenstd = row

            eigenverbrauch = (direkt or 0) + (batt_entl or 0)
            gesamtverbrauch = eigenverbrauch + (bezug or 0)
            autarkie = (eigenverbrauch / gesamtverbrauch * 100) if gesamtverbrauch > 0 else 0

            datapoints.append({
                'month': month,
                'label': f'{month:02d}/{year}',
                'w_einspeisung': round(einsp or 0, 2),
                'w_batterieladung': round(batt_lad or 0, 2),
                'w_direktverbrauch': round(direkt or 0, 2),
                'w_wattpilot': round(wattpilot or 0, 2),
                'w_netzbezug': round(bezug or 0, 2),
                'w_batterieentladung': round(batt_entl or 0, 2),
                'w_pv_total': round(solar or 0, 2),
                'w_gesamtverbrauch': round(gesamtverbrauch, 2),
                'autarkie': round(autarkie, 1),
                'sonnenstunden': round(sonnenstd, 1) if sonnenstd else None
            })
            if sonnenstd:
                total_sonnenstunden += sonnenstd

        # Frequenz-Extremwerte für das gesamte Jahr
        year_start_ts = int(datetime(year, 1, 1).timestamp())
        year_end_ts = int(datetime(year + 1, 1, 1).timestamp())
        freq_extremes = _get_freq_extremes(cursor, year_start_ts, year_end_ts)

        conn.close()
        response = {
            'year': year,
            'datapoints': datapoints,
            'sonnenstunden': round(total_sonnenstunden, 1) if total_sonnenstunden > 0 else None
        }
        if freq_extremes:
            response['freq_extremes'] = freq_extremes
        return jsonify(response)

    except Exception as e:
        return api_error_response(e, "Jahr-Visualisierung")


@bp.route('/api/gesamt_visualization')
def gesamt_visualization():
    """Liefert Jahresdaten für Gesamtansicht - gestapelte Balken (wie Monats-Chart)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500

        cursor = conn.cursor()
        cursor.execute("""
            SELECT year,
                   SUM(solar_erzeugung_kwh), SUM(netz_bezug_kwh), SUM(netz_einspeisung_kwh),
                   SUM(batt_ladung_kwh), SUM(batt_entladung_kwh), SUM(direktverbrauch_kwh),
                   SUM(gesamt_verbrauch_kwh), SUM(heizpatrone_kwh), SUM(wattpilot_kwh)
            FROM monthly_statistics
            GROUP BY year
            ORDER BY year
        """)

        rows = cursor.fetchall()
        datapoints = []

        for row in rows:
            year, solar, bezug, einsp, batt_lad, batt_entl, direkt, gesamt, heiz, wattpilot = row

            # Überspringe Jahre ohne nennenswerte Daten
            if not solar or solar < 1:
                continue

            eigenverbrauch = (direkt or 0) + (batt_entl or 0)
            gesamtverbrauch = eigenverbrauch + (bezug or 0)
            autarkie = (eigenverbrauch / gesamtverbrauch * 100) if gesamtverbrauch > 0 else 0

            datapoints.append({
                'year': year,
                'label': str(year),
                'w_einspeisung': round(einsp or 0, 2),
                'w_batterieladung': round(batt_lad or 0, 2),
                'w_direktverbrauch': round(direkt or 0, 2),
                'w_wattpilot': round(wattpilot or 0, 2),
                'w_netzbezug': round(bezug or 0, 2),
                'w_batterieentladung': round(batt_entl or 0, 2),
                'w_pv_total': round(solar or 0, 2),
                'w_gesamtverbrauch': round(gesamtverbrauch, 2),
                'autarkie': round(autarkie, 1)
            })

        # Frequenz-Extremwerte über gesamten Datenbestand
        cursor.execute("SELECT MIN(ts), MAX(ts) FROM data_1min WHERE f_Netz_min IS NOT NULL")
        range_row = cursor.fetchone()
        freq_extremes = None
        if range_row and range_row[0]:
            freq_extremes = _get_freq_extremes(cursor, range_row[0], range_row[1] + 1)

        conn.close()
        response = {
            'datapoints': datapoints
        }
        if freq_extremes:
            response['freq_extremes'] = freq_extremes
        return jsonify(response)

    except Exception as e:
        return api_error_response(e, "Gesamt-Visualisierung")
