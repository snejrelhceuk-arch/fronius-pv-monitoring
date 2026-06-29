"""
solar_openmeteo.py — Fehlertoleranter Open-Meteo API-Client (OpenMeteoClient).

Verbatim aus solar_forecast.py extrahiert (Architektur-Refactor 2026-06-29).
"""
import json
import logging
import time

import requests

from solar_cache import ForecastCache

# Standort (aus config.py mit Fallback)
try:
    import config as _cfg
    LATITUDE = _cfg.LATITUDE
    LONGITUDE = _cfg.LONGITUDE
    TIMEZONE = _cfg.TIMEZONE
except (ImportError, AttributeError):
    LATITUDE = 51.01
    LONGITUDE = 12.95
    TIMEZONE = "Europe/Berlin"

OPEN_METEO_BASE = "https://api.open-meteo.com/v1"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1"
API_TIMEOUT = 15
API_MAX_RETRIES = 3
API_BACKOFF_BASE = 2
CACHE_TTL_FORECAST = 3600
CACHE_TTL_HISTORICAL = 86400

LOG = logging.getLogger('solar_forecast')


class OpenMeteoClient:
    """Fehlertoleranter Client für Open-Meteo API."""

    HOURLY_PARAMS = [
        'temperature_2m',
        'windspeed_10m',
        'cloud_cover',
        'shortwave_radiation',
        'direct_radiation',
        'direct_normal_irradiance',
        'diffuse_radiation',
        'sunshine_duration',
        'weather_code',
        'is_day',
        'precipitation',
    ]

    DAILY_PARAMS = [
        'sunrise',
        'sunset',
        'daylight_duration',
        'sunshine_duration',
        'shortwave_radiation_sum',
        'weather_code',
        'temperature_2m_max',
        'temperature_2m_min',
        'precipitation_sum',
        'precipitation_probability_max',
    ]

    def __init__(self, cache=None):
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
        self.cache = cache or ForecastCache()
        self._last_error = None
        self._api_healthy = True

    def _api_call(self, url, params, cache_key, cache_ttl):
        """API-Aufruf mit Cache-Fallback und Retry."""
        # 1. Prüfe Cache (frische Daten)
        cached, is_fresh = self.cache.get(cache_key)
        if cached and is_fresh:
            LOG.debug(f"Cache HIT (fresh): {cache_key}")
            return cached

        # 2. API-Aufruf mit Retry
        last_error = None
        for attempt in range(API_MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=API_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()

                if 'error' in data:
                    raise ValueError(f"API-Fehler: {data.get('reason', 'unbekannt')}")

                # Erfolg → Cache aktualisieren
                self.cache.put(cache_key, data, cache_ttl)
                self._api_healthy = True
                self._last_error = None
                LOG.debug(f"API OK: {cache_key} (Versuch {attempt+1})")
                return data

            except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
                last_error = str(e)
                self._last_error = last_error
                wait = API_BACKOFF_BASE ** attempt
                LOG.warning(f"API-Fehler (Versuch {attempt+1}/{API_MAX_RETRIES}): {e}")
                if attempt < API_MAX_RETRIES - 1:
                    time.sleep(wait)

        # 3. Fallback: Abgelaufener Cache
        self._api_healthy = False
        if cached:
            LOG.warning(f"API nicht erreichbar — verwende Cache-Daten: {cache_key}")
            return cached

        # 4. Kein Cache, kein API
        LOG.error(f"Kein Cache und API-Fehler: {last_error}")
        return None

    def fetch_forecast(self, forecast_days=7):
        """Vollständige Prognose für N Tage.
        
        Open-Meteo 'best_match': nutzt automatisch das beste verfügbare Modell:
          - Tag 0-2: DWD ICON-D2 (2.2km Auflösung) wenn verfügbar
          - Tag 3-7: ICON-EU / GFS (globale Modelle)
        Kein models-Parameter → best_match = optimale Mischung.
        """
        params = {
            'latitude': LATITUDE,
            'longitude': LONGITUDE,
            'hourly': ','.join(self.HOURLY_PARAMS),
            'daily': ','.join(self.DAILY_PARAMS),
            'timezone': TIMEZONE,
            'forecast_days': forecast_days,
        }
        cache_key = f"forecast_{forecast_days}d"
        return self._api_call(
            f"{OPEN_METEO_BASE}/forecast", params,
            cache_key, CACHE_TTL_FORECAST
        )

    def fetch_historical(self, start_date, end_date):
        """Historische Wetterdaten für Kalibrierung."""
        params = {
            'latitude': LATITUDE,
            'longitude': LONGITUDE,
            'daily': 'shortwave_radiation_sum,sunshine_duration,weather_code,'
                     'temperature_2m_max,temperature_2m_min,precipitation_sum',
            'timezone': TIMEZONE,
            'start_date': start_date,
            'end_date': end_date,
        }
        cache_key = f"hist_{start_date}_{end_date}"
        return self._api_call(
            f"{OPEN_METEO_ARCHIVE}/archive", params,
            cache_key, CACHE_TTL_HISTORICAL
        )

    @property
    def healthy(self):
        return self._api_healthy

    @property
    def last_error(self):
        return self._last_error
