"""
Blueprint: Prognose-APIs (Clear-Sky, Forecast Tag/Monat).

Enthält: /api/clearsky_day, /api/forecast_tag, /api/stored_forecast, /api/forecast_monat
"""
import logging
import time
from datetime import datetime, date, timedelta
from flask import Blueprint, jsonify, request
import config
from routes.helpers import (
    get_forecast,
    store_forecast_daily,
    get_stored_forecast,
    store_forecast_15min,
    _day_timestamps,
    _interpolate_series,
    api_error_response,
    validate_year_month,
)

bp = Blueprint('forecast', __name__)


@bp.route('/api/clearsky_day')
def api_clearsky_day():
    """
    Clear-Sky-Referenzkurve für einen Tag.
    Liefert die theoretische AC-Leistung bei wolkenlosem Himmel
    als Minutenwerte. Zum Unterlegen unter die realen Messdaten.

    Parameter:
      date=YYYY-MM-DD (default: heute)
      interval=1|5|15 (Minuten, default: 1)
    """
    try:
        import solar_geometry as sg
    except ImportError:
        return jsonify({"error": "Solar-Geometrie-Modul nicht verfügbar"}), 503

    try:
        date_param = request.args.get('date')
        interval = request.args.get('interval', 1, type=int)
        interval = max(1, min(60, interval))  # 1-60 Minuten

        if date_param:
            target = date.fromisoformat(date_param)
        else:
            target = date.today()

        curve = sg.get_clearsky_day_curve(target, interval_min=interval)

        # Tages-Energie berechnen
        total_kwh = sum(p['total_ac'] for p in curve) * (interval / 60.0) / 1000.0
        peak_w = max((p['total_ac'] for p in curve), default=0)

        return jsonify({
            'date': target.isoformat(),
            'interval_min': interval,
            'total_kwh': round(total_kwh, 1),
            'peak_w': round(peak_w, 0),
            'datapoints': curve,
        })
    except Exception as e:
        return api_error_response(e, "Clear-Sky")


@bp.route('/api/forecast_tag')
def api_forecast_tag():
    """
    Prognose-Daten für Tag-Visualisierung.
    Liefert stündliche PV-Leistungsprognose im gleichen Format wie tag_visualization.

    NEU: Nutzt Solar-Geometrie-Engine für physikalisch korrekte Leistungsprognose
    pro String (GTI-basiert) statt pauschaler GHI×Faktor-Verteilung.
    Fallback auf alte Methode wenn solar_geometry nicht verfügbar.

    Parameter: date=YYYY-MM-DD (max 7 Tage voraus)
    """
    try:
        date_param = request.args.get('date')
        if date_param:
            target = date.fromisoformat(date_param)
        else:
            target = date.today() + timedelta(days=1)

        days_ahead = (target - date.today()).days
        if days_ahead < 0:
            return jsonify({"error": "Prognose nur für zukünftige Tage"}), 400
        if days_ahead > 7:
            return jsonify({"error": "Prognose maximal 7 Tage voraus"}), 400

        fc = get_forecast()
        if not fc:
            return jsonify({"error": "Prognose-Modul nicht verfügbar"}), 503

        # Tagesprognose (expected_kwh, quality, sunrise/sunset, etc.)
        day_fc = fc.get_day_forecast(target)
        if not day_fc:
            return jsonify({"error": "Keine Prognose-Daten verfügbar"}), 503

        # ── Geometrie-basierte Leistungsprognose (primär) ──────────
        power_data = fc.get_hourly_power_forecast(target)
        p_15m = []
        if power_data:
            forecast_method = 'geometry'

            base_points = []
            cloud_points = []
            temp_points = []
            ghi_points = []
            for p in power_data:
                try:
                    hour_dt = datetime.strptime(p['time'], '%Y-%m-%dT%H:%M')
                    ts = int(time.mktime(hour_dt.timetuple()))
                except (ValueError, KeyError):
                    continue

                p_pv = round(p.get('total_ac', 0), 1)
                base_points.append((ts, p_pv))
                cloud_points.append((ts, p.get('cloud_cover', 0) or 0))
                temp_points.append((ts, p.get('temp', 0) or 0))
                ghi_points.append((ts, p.get('ghi', 0) or 0))

            day_15m = _day_timestamps(target.isoformat(), 900)
            day_5m = _day_timestamps(target.isoformat(), 300)

            p_15m = _interpolate_series(base_points, day_15m)
            p_5m = _interpolate_series(p_15m, day_5m)
            cloud_5m = _interpolate_series(cloud_points, day_5m)
            temp_5m = _interpolate_series(temp_points, day_5m)
            ghi_5m = _interpolate_series(ghi_points, day_5m)

            expected_kwh = round(sum(p for _, p in p_15m) * 0.25 / 1000.0, 1)

            data_points = []
            for idx, (ts, p_pv) in enumerate(p_5m):
                data_points.append({
                    'timestamp': ts,
                    'soc': None,
                    'p_exp': 0,
                    'p_inbatt_pv': 0,
                    'p_inbatt_grid': 0,
                    'p_direct_ertrag': p_pv,
                    'p_produktion': p_pv,
                    'w_ertrag': round(p_pv, 2),
                    'p_imp': 0,
                    'p_outbatt': 0,
                    'p_direct_verbrauch': 0,
                    'p_haushalt': 0,
                    'w_verbrauch': 0,
                    'f_netz_avg': 50.0,
                    'w_einspeis': 0,
                    'w_bezug': 0,
                    'is_forecast': True,
                    'cloud_cover': cloud_5m[idx][1] if idx < len(cloud_5m) else 0,
                    'temp': temp_5m[idx][1] if idx < len(temp_5m) else 0,
                    'ghi_wm2': ghi_5m[idx][1] if idx < len(ghi_5m) else 0,
                })

        else:
            # ── Fallback: alte GHI×Faktor-Methode ──────────────────
            forecast_method = 'ghi_factor'
            hourly = fc.get_hourly_forecast(target)
            if not hourly:
                return jsonify({"error": "Keine stündlichen Prognose-Daten"}), 503

            expected_kwh = day_fc['expected_kwh']
            weights = []
            for h in hourly:
                cloud = h.get('cloud_cover', 50) or 50
                cloud_factor = 1.0 - 0.7 * (cloud / 100.0)
                ghi = max(h['ghi'], 0)
                w = (ghi ** 0.5) * cloud_factor
                weights.append(w)
            total_weight = sum(weights) if sum(weights) > 0 else 1

            data_points = []
            for i, h in enumerate(hourly):
                hour_dt = datetime.strptime(h['time'], '%Y-%m-%dT%H:%M')
                ts = int(time.mktime(hour_dt.timetuple()))

                p_pv = round(expected_kwh * 1000 * (weights[i] / total_weight), 1)
                p_pv = min(p_pv, config.PV_INVERTER_KW * 1000)

                data_points.append({
                    'timestamp': ts,
                    'soc': None,
                    'p_exp': 0,
                    'p_inbatt_pv': 0,
                    'p_inbatt_grid': 0,
                    'p_direct_ertrag': p_pv,
                    'p_produktion': p_pv,
                    'w_ertrag': round(p_pv, 2),
                    'p_imp': 0,
                    'p_outbatt': 0,
                    'p_direct_verbrauch': 0,
                    'p_haushalt': 0,
                    'w_verbrauch': 0,
                    'f_netz_avg': 50.0,
                    'w_einspeis': 0,
                    'w_bezug': 0,
                    'is_forecast': True,
                    'cloud_cover': h.get('cloud_cover', 0),
                    'temp': h.get('temp', 0),
                    'ghi_wm2': h.get('ghi', 0),
                })

        response_data = {
            'date': target.isoformat(),
            'forecast': True,
            'forecast_method': forecast_method,
            'expected_kwh': expected_kwh,
            'quality': day_fc['quality'],
            'weather_text': day_fc['weather_text'],
            'weather_code': day_fc.get('weather_code', 0),
            'sunrise': day_fc['sunrise'],
            'sunset': day_fc['sunset'],
            'sunshine_hours': day_fc['sunshine_hours'],
            'temp_min': day_fc['temp_min'],
            'temp_max': day_fc['temp_max'],
            'precipitation_mm': day_fc.get('precipitation_mm', 0),
            'datapoints': data_points
        }

        # Prognose persistent speichern (für historischen Vergleich im Tag-Chart)
        try:
            cs_15m = None
            cs_data = None
            try:
                import solar_geometry as _sg_mod
                cs_curve_15 = _sg_mod.get_clearsky_day_curve(target, interval_min=15)
                cs_15m = [(dp['timestamp'], dp.get('total_ac', 0)) for dp in cs_curve_15]

                cs_curve = _sg_mod.get_clearsky_day_curve(target, interval_min=5)
                cs_kwh = sum(p['total_ac'] for p in cs_curve) * (5 / 60.0) / 1000.0
                cs_data = {
                    'total_kwh': round(cs_kwh, 1),
                    'datapoints': cs_curve,
                }
            except Exception:
                pass

            # Tages-Forecast in data_15min speichern (nur Update existierender Rows)
            if p_15m:
                store_forecast_15min(target.isoformat(), p_15m, cs_15m)
            store_forecast_daily(target.isoformat(), response_data, cs_data, forecast_method)
        except Exception as e:
            logging.debug(f"Forecast-Persistierung (non-critical): {e}")

        return jsonify(response_data)

    except Exception as e:
        return api_error_response(e, "Forecast Tag")


@bp.route('/api/stored_forecast')
def api_stored_forecast():
    """
    Gespeicherte Prognose aus forecast_daily für einen beliebigen Tag.
    Liefert Prognose + Clear-Sky als Hintergrund-Overlay für das Tag-Chart,
    auch für vergangene Tage.

    Parameter: date=YYYY-MM-DD
    Returns: {forecast, clearsky} oder {error} wenn nicht gespeichert.
    """
    try:
        date_param = request.args.get('date')
        if not date_param:
            return jsonify({"error": "Parameter 'date' fehlt"}), 400

        stored = get_stored_forecast(date_param)
        if not stored:
            return jsonify({"error": "Keine gespeicherte Prognose", "date": date_param}), 404

        return jsonify(stored)

    except Exception as e:
        return api_error_response(e, "Stored Forecast")


@bp.route('/api/forecast_monat')
def api_forecast_monat():
    """
    Prognose-Tagesdaten für Monatsansicht.
    Liefert erwartete Tageswerte für die nächsten 2 Tage im gleichen Format wie monat_visualization.
    Parameter: year=YYYY, month=MM
    """
    try:
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

        fc = get_forecast()
        if not fc:
            return jsonify({"year": year, "month": month, "datapoints": []})

        today = date.today()
        datapoints = []

        for offset in range(1, 3):  # morgen + übermorgen
            target = today + timedelta(days=offset)

            # Nur Tage im gewünschten Monat
            if target.year != year or target.month != month:
                continue

            day_fc = fc.get_day_forecast(target)
            if not day_fc:
                continue

            ts = int(datetime(target.year, target.month, target.day, 1, 0).timestamp())
            kwh = day_fc['expected_kwh']

            datapoints.append({
                'timestamp': ts,
                'date': target.isoformat(),
                'day': target.day,
                'w_einspeisung': 0,
                'w_batterieladung': 0,
                'w_direktverbrauch': round(kwh, 2),  # Gesamte Prognose als Direkt
                'w_waermepumpe': 0,
                'w_netzbezug': 0,
                'w_batterieentladung': 0,
                'w_pv_total': round(kwh, 2),
                'w_gesamtverbrauch': 0,
                'autarkie': 0,
                'soc_avg': 0,
                'is_forecast': True,
                'quality': day_fc['quality'],
                'weather_text': day_fc['weather_text'],
            })

        return jsonify({
            'year': year,
            'month': month,
            'datapoints': datapoints
        })

    except Exception as e:
        logging.error(f"Forecast Monat Fehler: {e}")
        return jsonify({"year": year if 'year' in dir() else 0,
                        "month": month if 'month' in dir() else 0,
                        "datapoints": []})
