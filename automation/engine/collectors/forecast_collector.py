"""
forecast_collector.py — Tier-3 Solar-Prognose (trigger-basiert)

Holt Forecast zu definierten Tageszeitpunkten statt blind per Intervall.

Trigger-Zeitpunkte:
  ① startup     → Initiale Datenbefüllung beim Daemon-Start
  ② sunrise     → Morgen-Entscheidung (SOC_MIN öffnen?)
  ③ 10:00       → Tagesverlauf-Update (SOC_MAX anpassen)
  ④ 14:00       → Abend-Reserve-Planung
  ⑤ fallback_6h → Safety-Net alle 6h

Schreibt Ergebnisse in ObsState UND in forecast_daily (für
Dashboard + Web-API Kompatibilität).

Siehe: doc/SOLAR_FORECAST_SCAFFOLD.md
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from automation.engine.obs_state import ObsState

LOG = logging.getLogger('forecast_collector')


class ForecastCollector:
    """Holt Solar-Prognose zu definierten Tageszeitpunkten.

    Trigger-Zeitpunkte:
      ① Sunrise - Vorlauf → Morgen-Entscheidung (SOC_MIN öffnen?)
      ② 10:00          → Tagesverlauf-Update (SOC_MAX anpassen)
      ③ 14:00          → Abend-Reserve-Planung
      + Initialer Fetch beim Daemon-Start
      + Fallback alle 6h, falls Trigger verpasst

    Schreibt Ergebnisse in ObsState UND in forecast_daily (für
    Dashboard + battery_scheduler Kompatibilität).
    """

    # Feste Trigger-Uhrzeiten (Dezimalstunden) — sunrise wird dynamisch gesetzt
    FIXED_TRIGGERS = [10.0, 14.0]
    FALLBACK_INTERVAL_S = 6 * 3600  # 6h

    def __init__(self, morgen_vorlauf_min: int = 15):
        self._sf = None               # SolarForecast Instanz (lazy)
        self._last_fetch_ts = 0       # Unix-Timestamp letzter Fetch
        self._sunrise_h = None        # Heutige Sunrise-Stunde (Dezimal)
        self._sunset_h = None
        self.morgen_vorlauf_min = morgen_vorlauf_min  # Sunrise-Trigger Vorlauf [min]
        self._triggers_today = set()  # Welche Trigger heute schon gelaufen
        self._last_date = None        # Für Tageswechsel-Erkennung
        self._hourly_profile = None   # Letztes hourly_profile (für _get_pv_at_hour)
        self._power_hourly = None     # Letzte power_hourly

    def _ensure_sf(self):
        """SolarForecast Singleton — lazy init."""
        if self._sf is None:
            from solar_forecast import SolarForecast
            self._sf = SolarForecast()
        return self._sf

    def collect(self, obs: ObsState):
        """Prüfe ob ein Fetch-Trigger fällig ist und aktualisiere ObsState.

        Wird vom Daemon im Tier-3-Loop aufgerufen (z.B. alle 30s prüfen,
        aber nur bei Trigger tatsächlich fetchen).
        """
        now = datetime.now()
        now_h = now.hour + now.minute / 60.0
        today_str = now.strftime('%Y-%m-%d')

        # ── Tageswechsel: Trigger-Set zurücksetzen ──────────
        if self._last_date != today_str:
            self._triggers_today = set()
            self._last_date = today_str
            self._sunrise_h = None  # Sunrise neu berechnen

        # ── Sunrise bestimmen (1× pro Tag) ──────────────────
        if self._sunrise_h is None:
            self._fetch_sunrise_sunset(obs)

        # ── Trigger-Prüfung ─────────────────────────────────
        should_fetch = False
        trigger_name = None

        # Initialer Fetch (noch nie geholt)
        if self._last_fetch_ts == 0:
            should_fetch = True
            trigger_name = 'startup'

        # Sunrise-Trigger (mit Vorlauf)
        elif (self._sunrise_h is not None
              and now_h >= self._sunrise_h - self.morgen_vorlauf_min / 60.0
              and 'sunrise' not in self._triggers_today):
            should_fetch = True
            trigger_name = 'sunrise'

        # Feste Trigger (10:00, 14:00)
        else:
            for trig_h in self.FIXED_TRIGGERS:
                key = f'fixed_{trig_h:.0f}'
                if now_h >= trig_h and key not in self._triggers_today:
                    should_fetch = True
                    trigger_name = key
                    break

        # Fallback: Alle 6h
        if (not should_fetch
                and time.time() - self._last_fetch_ts > self.FALLBACK_INTERVAL_S):
            should_fetch = True
            trigger_name = 'fallback_6h'

        if not should_fetch:
            return

        # ── Fetch durchführen ───────────────────────────────
        LOG.info(f"Tier-3 Forecast-Fetch ausgelöst: {trigger_name} "
                 f"(Uhrzeit {now.strftime('%H:%M')})")

        try:
            self._do_fetch(obs)
            if trigger_name:
                self._triggers_today.add(trigger_name)
            self._last_fetch_ts = time.time()
            LOG.info(f"  Forecast OK: {obs.forecast_kwh:.1f} kWh, "
                     f"PV@SR+1h={obs.pv_at_sunrise_1h_w or '?'}W, "
                     f"Qualität={obs.forecast_quality}")
        except Exception as e:
            LOG.error(f"Forecast-Fetch fehlgeschlagen: {e}", exc_info=True)

    def _fetch_sunrise_sunset(self, obs: ObsState):
        """Sunrise/Sunset aus SolarForecast holen und in ObsState setzen.

        Fallback: Vortageswerte aus forecast_daily DB, wenn API nicht erreichbar.
        Sunrise verschiebt sich max. ±2 Min pro Tag — Vortag ist gut genug.
        """
        try:
            sf = self._ensure_sf()
            strategy = sf.get_strategy_inputs()
            if strategy.get('valid'):
                self._sunrise_h = strategy.get('sunrise_hour', 7.0)
                self._sunset_h = strategy.get('sunset_hour', 17.0)
                obs.sunrise = self._sunrise_h
                obs.sunset = self._sunset_h
                now_h = datetime.now().hour + datetime.now().minute / 60.0
                obs.is_day = self._sunrise_h <= now_h <= self._sunset_h
                LOG.info(f"  Sunrise={self._sunrise_h:.2f}h, "
                         f"Sunset={self._sunset_h:.2f}h")
                return
        except Exception as e:
            LOG.warning(f"Sunrise/Sunset via API nicht ermittelbar: {e}")

        # ── Fallback: Vortageswerte aus forecast_daily ──────
        try:
            import sqlite3 as _sql
            import config as app_config
            from datetime import timedelta

            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            conn = _sql.connect(app_config.DB_PATH, timeout=3.0)
            row = conn.execute(
                "SELECT sunrise, sunset FROM forecast_daily WHERE date = ?",
                (yesterday,)
            ).fetchone()
            conn.close()

            if row and row[0] and row[1]:
                # Sunrise/Sunset sind ISO-Strings wie "2026-02-27T06:54"
                def _parse_h(iso_str):
                    try:
                        t = datetime.fromisoformat(iso_str)
                        return t.hour + t.minute / 60.0
                    except (ValueError, TypeError):
                        return None

                sr = _parse_h(row[0])
                ss = _parse_h(row[1])
                if sr is not None and ss is not None:
                    self._sunrise_h = sr
                    self._sunset_h = ss
                    obs.sunrise = sr
                    obs.sunset = ss
                    now_h = datetime.now().hour + datetime.now().minute / 60.0
                    obs.is_day = sr <= now_h <= ss
                    LOG.warning(f"  Sunrise/Sunset Fallback (Vortag {yesterday}): "
                                f"{sr:.2f}h / {ss:.2f}h")
                    return
        except Exception as e2:
            LOG.warning(f"Vortages-Fallback fehlgeschlagen: {e2}")

        # ── Letzter Fallback: Jahresmittel ──────────────────
        self._sunrise_h = 7.0
        self._sunset_h = 17.0
        obs.sunrise = 7.0
        obs.sunset = 17.0
        LOG.warning("  Sunrise/Sunset Fallback auf Defaults: 07:00 / 17:00")

    def _do_fetch(self, obs: ObsState):
        """Vollständiger Forecast-Fetch → ObsState + forecast_daily DB."""
        sf = self._ensure_sf()
        # Force frische Daten (Cache invalidieren)
        sf._forecast_data = None

        strategy = sf.get_strategy_inputs()
        hourly = sf.get_hourly_forecast()
        power_hourly = sf.get_hourly_power_forecast()

        # ── ObsState aktualisieren ──────────────────────────
        if strategy.get('valid'):
            obs.forecast_kwh = strategy.get('expected_kwh', 0)
            obs.cloud_avg_pct = strategy.get('cloud_cover_avg', 50)
            obs.forecast_quality = strategy.get('quality')
            obs.sunrise = strategy.get('sunrise_hour')
            obs.sunset = strategy.get('sunset_hour')
            self._sunrise_h = obs.sunrise
            self._sunset_h = obs.sunset

            now_h = datetime.now().hour + datetime.now().minute / 60.0
            obs.is_day = (self._sunrise_h or 7) <= now_h <= (self._sunset_h or 17)

        obs.forecast_ts = datetime.now().isoformat()

        # ── Wolken (aktuell + Resttag) ──────────────────────
        if hourly:
            now_h_int = datetime.now().hour
            for h in hourly:
                h_start = h.get('hour', 0)
                if h_start == now_h_int:
                    obs.cloud_now_pct = h.get('cloud_cover')
                    break
            rest_clouds = [h.get('cloud_cover', 50) for h in hourly
                           if h.get('hour', 0) >= now_h_int]
            if rest_clouds:
                obs.cloud_rest_avg_pct = round(sum(rest_clouds) / len(rest_clouds), 1)

        # ── Power-Profil für Engine-Regeln ──────────────────
        if power_hourly:
            def _safe_hour(hd):
                h = hd.get('hour')
                if h is not None:
                    return int(h)
                t = hd.get('time', '')
                try:
                    return int(t[11:13]) if len(t) >= 13 else 0
                except (ValueError, TypeError):
                    return 0

            obs.forecast_power_profile = [
                {'hour': _safe_hour(hd),
                 'total_ac_w': round(hd.get('total_ac', 0), 0)}
                for hd in power_hourly
            ]

        # ── IST/SOLL-Verhältnis ─────────────────────────────
        if obs.forecast_kwh and obs.pv_today_kwh is not None:
            obs.forecast_rest_kwh = max(0, round(obs.forecast_kwh - obs.pv_today_kwh, 1))
            if power_hourly:
                now_h_int = datetime.now().hour
                expected_so_far_kwh = 0.0
                for hd in power_hourly:
                    h_hour = hd.get('hour', 0)
                    if h_hour < now_h_int:
                        expected_so_far_kwh += hd.get('total_ac', 0) / 1000.0
                if expected_so_far_kwh > 0.5:
                    obs.pv_vs_forecast_pct = round(
                        (obs.pv_today_kwh / expected_so_far_kwh) * 100, 1)

        # ── Clear-Sky-Peak-Stunde ───────────────────────────
        try:
            from solar_geometry import get_clearsky_day_curve
            from datetime import date as _date
            cs_curve = get_clearsky_day_curve(_date.today(), interval_min=60)
            if cs_curve:
                peak_entry = max(cs_curve, key=lambda e: e.get('total_ac', 0))
                peak_ts = peak_entry['timestamp']
                peak_dt = datetime.fromtimestamp(peak_ts)
                obs.clearsky_peak_h = round(
                    peak_dt.hour + peak_dt.minute / 60.0, 1)
        except Exception as e:
            LOG.debug(f"clearsky_peak: {e}")

        # ── PV@Sunrise+1h berechnen ─────────────────────────
        self._power_hourly = power_hourly
        if self._sunrise_h is not None:
            target_h = self._sunrise_h + 1.0
            pv_at_sr1 = self._get_pv_at_hour(hourly, power_hourly, target_h)
            obs.pv_at_sunrise_1h_w = pv_at_sr1

        # ── forecast_daily in DB schreiben (Kompatibilität) ─
        self._store_forecast_daily(sf, hourly, power_hourly)

    def _get_pv_at_hour(self, hourly, power_hourly, target_hour):
        """PV-Leistung [W] zu bestimmter Stunde aus Forecast-Daten."""
        # Versuch 1: power_hourly (stündlich, Feld 'total_ac')
        if power_hourly:
            best_ac = None
            best_diff = 999
            for h in power_hourly:
                hr = h.get('hour')
                if hr is None:
                    t = h.get('time', '')
                    try:
                        hr = int(t[11:13]) + int(t[14:16]) / 60.0
                    except (ValueError, IndexError):
                        continue
                diff = abs(float(hr) - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best_ac = h.get('total_ac', 0)
            if best_ac is not None and best_diff < 0.75:
                return best_ac

        # Versuch 2: hourly (Open-Meteo roh, Feld 'shortwave_radiation')
        # → Grobe Schätzung: GHI [W/m²] × 37.59 kWp × 0.15 Eff ≈ PV [W]
        if hourly:
            best_ghi = None
            best_diff = 999
            for h in hourly:
                t = h.get('time', '')
                try:
                    hr = int(t[11:13]) + int(t[14:16]) / 60.0
                except (ValueError, IndexError):
                    continue
                diff = abs(hr - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best_ghi = h.get('shortwave_radiation', 0)
            if best_ghi is not None and best_diff < 0.75:
                return best_ghi * 37.59 * 0.15

        return None

    def _store_forecast_daily(self, sf, hourly, power_hourly):
        """Schreibe aufbereitete Prognose in forecast_daily (Haupt-DB).

        Damit Dashboard und battery_scheduler aktuelle Daten haben.
        Schreibt direkt per SQL — keine Abhängigkeit von routes/.
        """
        try:
            import sqlite3 as _sql
            import config as app_config

            today_str = datetime.now().strftime('%Y-%m-%d')
            day_fc = sf.get_day_forecast()
            if not day_fc:
                return

            # hourly_profile bauen (stündlich, JSON mit ts/p/cc/temp/ghi)
            hourly_json = None
            if power_hourly:
                points = []
                for p in power_hourly:
                    try:
                        hour_dt = datetime.strptime(p['time'], '%Y-%m-%dT%H:%M')
                        ts = int(time.mktime(hour_dt.timetuple()))
                    except (ValueError, KeyError):
                        continue
                    points.append({
                        'ts': ts,
                        'p': round(p.get('total_ac', 0), 1),
                        'cc': p.get('cloud_cover', 0) or 0,
                        'temp': p.get('temp', 0) or 0,
                        'ghi': p.get('ghi', 0) or 0,
                    })
                if points:
                    hourly_json = json.dumps(points, separators=(',', ':'))

            # Cloud-Durchschnitt
            cloud_avg = None
            if hourly:
                clouds = [h.get('cloud_cover', 0) for h in hourly
                          if h.get('cloud_cover') is not None]
                if clouds:
                    cloud_avg = round(sum(clouds) / len(clouds), 1)

            conn = _sql.connect(app_config.DB_PATH, timeout=5.0)
            conn.execute("""
                INSERT OR REPLACE INTO forecast_daily
                (date, expected_kwh, quality, weather_text, weather_code,
                 sunrise, sunset, sunshine_hours, temp_min, temp_max,
                 cloud_cover_avg, precipitation_mm,
                 hourly_profile, forecast_method, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today_str,
                day_fc.get('expected_kwh'),
                day_fc.get('quality'),
                day_fc.get('weather_text'),
                day_fc.get('weather_code'),
                day_fc.get('sunrise'),
                day_fc.get('sunset'),
                day_fc.get('sunshine_hours'),
                day_fc.get('temp_min'),
                day_fc.get('temp_max'),
                cloud_avg,
                day_fc.get('precipitation_mm'),
                hourly_json,
                'geometry' if power_hourly else 'ghi_factor',
                time.time(),
            ))
            conn.commit()
            conn.close()
            LOG.info(f"  forecast_daily geschrieben: {today_str} "
                     f"→ {day_fc.get('expected_kwh', '?')} kWh")
        except Exception as e:
            LOG.warning(f"forecast_daily Schreib-Fehler: {e}")
