#!/usr/bin/env python3
"""
solar_forecast.py — Wetter- & Solar-Prognose für PV-Batterie-Management
=========================================================================
Open-Source Wetter- und Strahlungsprognose für Batterie-Strategien A–F.

Datenquellen:
  - Open-Meteo Forecast API (kostenlos, kein API-Key, 10k Calls/Tag)
  - Open-Meteo Historical API (für Kalibrierung/Vergleich)
  - SQLite-Cache als Fallback bei API-Ausfall

Features:
  - Sonnenauf-/untergang, Tageslicht- und Sonnenscheindauer
  - Globale Horizontalstrahlung (GHI), direkte + diffuse Strahlung
  - PV-Ertragsprognose via empirischer Kalibrierung aus data.db
  - Tagesqualität-Klassifizierung (gut/mittel/schlecht)
  - Stündliche Strahlungsprofile
  - Selbstprüfung: Forecast-Accuracy aus Vergangenheitsdaten
  - Fehlertoleranz: Cache-Fallback, Retry, Exponential Backoff

Anlagen-Konfiguration:
  Standort: Erlau, Mittelsachsen (51.01°N, 12.95°E, 315m)
  37.59 kWp in 7 Strings / 5 Orientierungen:
    F1: SSO-52° 6.9kWp + NNW-52° 6.9kWp + SSO-45° 2.76kWp + NNW-45° 2.76kWp
    F2: WSW-18° 6.75kWp + WSW-90° 5.67kWp
    F3: SSO-90° 5.85kWp
  BYD HVS 10kWh, Nulleinspeiser

Nutzung:
  # Tagesprognose
  python3 solar_forecast.py --today
  python3 solar_forecast.py --tomorrow
  
  # Stündliche Strahlung
  python3 solar_forecast.py --hourly
  python3 solar_forecast.py --hourly --date 2026-02-10
  
  # Mehrtagesübersicht
  python3 solar_forecast.py --week
  
  # JSON-Ausgabe (für Integration)
  python3 solar_forecast.py --today --json
  
  # Kalibrierung (vergleicht Prognose mit tatsächlicher Produktion)
  python3 solar_forecast.py --calibrate
  
  # Selbstprüfung
  python3 solar_forecast.py --check

Autor: PV-Anlage Batterie-Management
Datum: 2026-02-09
"""

import sys
import os
import json
import time
import sqlite3
import hashlib
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

# Encoding fix für RPi5
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import requests
except ImportError:
    print("FEHLER: 'requests' nicht installiert. pip3 install requests")
    sys.exit(1)

# Solar-Geometrie-Engine (per-String GTI-Berechnung)
try:
    import solar_geometry as _sg
    HAS_GEOMETRY = True
except ImportError:
    HAS_GEOMETRY = False


# ═══════════════════════════════════════════════════════════════
# KONFIGURATION (aus config.py + lokale Ergänzungen)
# ═══════════════════════════════════════════════════════════════

try:
    import config as _cfg
    LATITUDE   = _cfg.LATITUDE
    LONGITUDE  = _cfg.LONGITUDE
    ELEVATION  = _cfg.ELEVATION
    TIMEZONE   = _cfg.TIMEZONE
    PV_KWP_TOTAL = _cfg.PV_KWP_TOTAL
    _DATA_DB_PATH = _cfg.DB_PATH
except (ImportError, AttributeError):
    # Fallback wenn config.py nicht verfügbar
    LATITUDE   = 51.01
    LONGITUDE  = 12.95
    ELEVATION  = 315
    TIMEZONE   = "Europe/Berlin"
    PV_KWP_TOTAL = 37.59
    _DATA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.db')

# PV-String-Konfiguration → solar_geometry.PV_STRINGS (autoritativ)
# 7 Strings, 3 Orientierungen (SSO/NNW/WSW), Dach+Fassade, 37.59 kWp gesamt
# Details: solar_geometry.py Zeile 67ff / doc/PV_REFERENZSYSTEM_DOKUMENTATION.md

# Empirischer Faktor: GHI (MJ/m²/Tag) → PV (kWh/Tag)
# Wird durch Kalibrierung aus data.db überschrieben
# Startwert: ~6.5 kWh pro MJ/m² für 37.59kWp Multi-Orientierung
# (typisch: system_kwp * 0.2778 * PR ≈ 37.59 * 0.2778 * 0.65 ≈ 6.8)
DEFAULT_GHI_FACTOR = 6.5  # kWh pro MJ/m² Globalstrahlung

# Multi-Faktor-Modell: PV = a * GHI + b * Sunshine_h + c
# Bessere Genauigkeit für Multi-Orientierung als GHI-only
# Wird durch Kalibrierung befüllt
DEFAULT_MODEL_COEFFS = {
    'a': 4.0,       # kWh pro MJ/m²
    'b': 2.5,       # kWh pro Sonnenstunde
    'c': 1.0,       # Basis-Ertrag (diffuse Strahlung bei Bewölkung)
    'model': 'simple',  # 'simple' (nur GHI) oder 'multi' (GHI+Sunshine)
}

# Tagesqualität-Schwellen (kWh erwartet)
# Angepasst an 37.59 kWp Anlage
QUALITY_THRESHOLDS = {
    # Monat: (schlecht_bis, mittel_bis, gut_ab) in kWh
    1:  (10, 25, 40),
    2:  (15, 35, 55),
    3:  (25, 55, 85),
    4:  (35, 75, 115),
    5:  (45, 90, 140),
    6:  (50, 100, 150),
    7:  (50, 100, 150),
    8:  (40, 85, 130),
    9:  (30, 65, 100),
    10: (20, 45, 70),
    11: (10, 25, 40),
    12: (8, 20, 35),
}

# WMO Wetter-Codes → Klartext
WMO_CODES = {
    0: "Klar",
    1: "Überwiegend klar", 2: "Teilweise bewölkt", 3: "Bedeckt",
    45: "Nebel", 48: "Reifnebel",
    51: "Nieselregen leicht", 53: "Nieselregen mäßig", 55: "Nieselregen stark",
    56: "Gefrierender Nieselregen", 57: "Gefrierender Nieselregen stark",
    61: "Regen leicht", 63: "Regen mäßig", 65: "Regen stark",
    66: "Gefrierender Regen", 67: "Gefrierender Regen stark",
    71: "Schneefall leicht", 73: "Schneefall mäßig", 75: "Schneefall stark",
    77: "Schneegriesel",
    80: "Regenschauer leicht", 81: "Regenschauer mäßig", 82: "Regenschauer stark",
    85: "Schneeschauer leicht", 86: "Schneeschauer stark",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit starkem Hagel",
}

# API-Konfiguration
OPEN_METEO_BASE = "https://api.open-meteo.com/v1"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1"
API_TIMEOUT = 15       # Sekunden
API_MAX_RETRIES = 3
API_BACKOFF_BASE = 2   # Sekunden, exponentiell

# Cache-Konfiguration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DB = os.path.join(BASE_DIR, 'solar_cache.db')
DATA_DB = _DATA_DB_PATH  # tmpfs: /dev/shm/fronius_data.db
CALIBRATION_FILE = os.path.join(BASE_DIR, 'config', 'solar_calibration.json')

# Cache-TTL (Sekunden)
CACHE_TTL_FORECAST = 3600      # 1 Stunde für aktuelle Prognose
CACHE_TTL_DAILY = 14400        # 4 Stunden für Tagesprognose
CACHE_TTL_HISTORICAL = 86400   # 24 Stunden für historische Daten

# Logging
LOG = logging.getLogger('solar_forecast')


# ═══════════════════════════════════════════════════════════════
# CACHE LAYER
# ═══════════════════════════════════════════════════════════════

class ForecastCache:
    """SQLite-Cache für API-Antworten mit TTL."""

    def __init__(self, db_path=CACHE_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Cache-Tabelle erstellen."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    source TEXT DEFAULT 'api'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS forecast_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    date TEXT NOT NULL,
                    predicted_kwh REAL,
                    predicted_radiation_mj REAL,
                    actual_kwh REAL,
                    accuracy_pct REAL,
                    source TEXT DEFAULT 'open-meteo'
                )
            """)

    def get(self, key):
        """Lese aus Cache. Gibt (data, is_fresh) zurück oder (None, False)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT data, created_at, ttl_seconds FROM cache WHERE key = ?",
                (key,)
            ).fetchone()
        if row is None:
            return None, False
        data = json.loads(row[0])
        age = time.time() - row[1]
        is_fresh = age < row[2]
        return data, is_fresh

    def put(self, key, data, ttl_seconds, source='api'):
        """Schreibe in Cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache (key, data, created_at, ttl_seconds, source)
                VALUES (?, ?, ?, ?, ?)
            """, (key, json.dumps(data, ensure_ascii=False), time.time(), ttl_seconds, source))

    def log_forecast(self, date_str, predicted_kwh, predicted_radiation, actual_kwh=None):
        """Logge Prognose für spätere Accuracy-Analyse."""
        accuracy = None
        if actual_kwh and predicted_kwh and predicted_kwh > 0:
            accuracy = round(100 - abs(predicted_kwh - actual_kwh) / predicted_kwh * 100, 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO forecast_log (ts, date, predicted_kwh, predicted_radiation_mj, actual_kwh, accuracy_pct)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (time.time(), date_str, predicted_kwh, predicted_radiation, actual_kwh, accuracy))

    def get_accuracy_stats(self, days=30):
        """Accuracy-Statistik der letzten N Tage."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT date, predicted_kwh, actual_kwh, accuracy_pct
                FROM forecast_log
                WHERE actual_kwh IS NOT NULL AND accuracy_pct IS NOT NULL
                ORDER BY ts DESC LIMIT ?
            """, (days,)).fetchall()
        if not rows:
            return None
        accuracies = [r[3] for r in rows]
        return {
            'count': len(rows),
            'avg_accuracy': round(sum(accuracies) / len(accuracies), 1),
            'min_accuracy': round(min(accuracies), 1),
            'max_accuracy': round(max(accuracies), 1),
            'recent': [{'date': r[0], 'predicted': r[1], 'actual': r[2], 'accuracy': r[3]} for r in rows[:7]]
        }

    def cleanup(self, max_age_seconds=604800):
        """Lösche abgelaufene Cache-Einträge älter als max_age (default 7 Tage)."""
        cutoff = time.time() - max_age_seconds
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute("DELETE FROM cache WHERE created_at < ?", (cutoff,)).rowcount
        return deleted


# ═══════════════════════════════════════════════════════════════
# OPEN-METEO API CLIENT
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# PV PROGNOSE ENGINE
# ═══════════════════════════════════════════════════════════════

class SolarForecast:
    """Hauptklasse für Wetter- und PV-Prognose."""

    def __init__(self):
        self.cache = ForecastCache()
        self.api = OpenMeteoClient(self.cache)
        self._ghi_factor = self._load_calibration()
        self._forecast_data = None

    # ─── Kalibrierung ──────────────────────────────────────

    def _load_calibration(self):
        """Lade kalibrierten GHI-Faktor und Multi-Faktor-Koeffizienten."""
        try:
            if os.path.exists(CALIBRATION_FILE):
                with open(CALIBRATION_FILE, 'r') as f:
                    self._cal_data = json.load(f)
                factor = self._cal_data.get('ghi_factor', DEFAULT_GHI_FACTOR)
                cal_date = self._cal_data.get('calibrated_at', '?')
                model = self._cal_data.get('model', 'simple')
                LOG.info(f"Kalibrierung geladen: Faktor={factor:.2f}, Modell={model} (vom {cal_date})")
                return factor
        except Exception as e:
            LOG.warning(f"Kalibrierung nicht lesbar: {e}")
        self._cal_data = {}
        return DEFAULT_GHI_FACTOR

    def _save_calibration(self, factor, stats):
        """Speichere Kalibrierungsergebnis."""
        os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
        cal = {
            'ghi_factor': round(factor, 3),
            'model': stats.get('model', 'simple'),
            'model_coeffs': stats.get('model_coeffs', {}),
            'calibrated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'data_points': stats.get('count', 0),
            'r_squared': stats.get('r_squared', None),
            'r_squared_multi': stats.get('r_squared_multi', None),
            'avg_error_pct': stats.get('avg_error_pct', None),
            'monthly_factors': stats.get('monthly_factors', {}),
        }
        self._cal_data = cal
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump(cal, f, indent=2, ensure_ascii=False)
        LOG.info(f"Kalibrierung gespeichert: Faktor={factor:.3f}, Modell={stats.get('model')}")

    def calibrate(self, days=90):
        """
        Kalibriere GHI→PV-Faktor aus historischen Daten.
        
        Zwei Modelle:
          1. Einfach: PV_kWh = factor * GHI_MJ
          2. Multi:   PV_kWh = a * GHI_MJ + b * Sunshine_h + c
          
        Das bessere Modell (höheres R²) wird gespeichert.
        Vergleicht Open-Meteo Wetterdaten mit tatsächlicher PV-Produktion aus data.db.
        """
        if not os.path.exists(DATA_DB):
            return {'error': f'{DATA_DB} nicht gefunden'}

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # 1. Lade tatsächliche PV-Produktion aus data.db
        with sqlite3.connect(DATA_DB) as conn:
            rows = conn.execute("""
                SELECT ts, W_PV_total FROM daily_data
                WHERE ts >= ? AND ts <= ? AND W_PV_total > 1000
                ORDER BY ts
            """, (
                int(datetime.combine(start_date, datetime.min.time()).timestamp()),
                int(datetime.combine(end_date, datetime.min.time()).timestamp())
            )).fetchall()

        if len(rows) < 7:
            return {'error': f'Zu wenig Daten: {len(rows)} Tage (mind. 7 nötig)'}

        actual_kwh = {}
        for ts, wpv in rows:
            dt = datetime.fromtimestamp(ts)
            date_str = dt.strftime('%Y-%m-%d')
            actual_kwh[date_str] = wpv / 1000.0

        # 2. Lade historische GHI + Sonnenscheindauer von Open-Meteo
        hist = self.api.fetch_historical(start_date.isoformat(), end_date.isoformat())
        if not hist or 'daily' not in hist:
            return {'error': 'Historische Wetterdaten nicht verfügbar'}

        # 3. Paare bilden: (GHI, Sunshine_h, PV_kWh)
        daily = hist['daily']
        pairs = []  # [(ghi, sunshine_h, pv_kwh, date_str, month)]
        for i, date_str in enumerate(daily['time']):
            ghi = daily['shortwave_radiation_sum'][i]
            sunshine_s = daily['sunshine_duration'][i]
            if ghi is None or ghi < 0.3:
                continue
            if date_str not in actual_kwh:
                continue
            sunshine_h = (sunshine_s or 0) / 3600.0
            pv = actual_kwh[date_str]
            month = int(date_str[5:7])
            pairs.append((ghi, sunshine_h, pv, date_str, month))

        if len(pairs) < 5:
            return {'error': f'Zu wenig Vergleichspaare: {len(pairs)}'}

        # 4. Modell 1: Einfacher GHI-Faktor (Median)
        factors = [p[2] / p[0] for p in pairs]
        factors_sorted = sorted(factors)
        n = len(factors_sorted)
        median_factor = (factors_sorted[n//2-1] + factors_sorted[n//2]) / 2 if n % 2 == 0 else factors_sorted[n//2]
        mean_factor = sum(factors) / n

        # R² für einfaches Modell
        pv_vals = [p[2] for p in pairs]
        pv_mean = sum(pv_vals) / len(pv_vals)
        ss_tot = sum((p - pv_mean)**2 for p in pv_vals)
        ss_res_simple = sum((p[2] - p[0] * median_factor)**2 for p in pairs)
        r2_simple = 1 - ss_res_simple / ss_tot if ss_tot > 0 else 0

        # 5. Modell 2: Multi-Faktor (Least Squares ohne numpy)
        #    PV = a * GHI + b * Sunshine_h + c
        #    Normalengleichungen lösen: (X^T X) beta = X^T y
        r2_multi = 0
        coeffs_a, coeffs_b, coeffs_c = median_factor, 0, 0
        try:
            nn = len(pairs)
            # Summen berechnen
            sx = sum(p[0] for p in pairs)       # sum(GHI)
            sy = sum(p[1] for p in pairs)       # sum(Sunshine)
            sz = sum(p[2] for p in pairs)       # sum(PV)
            sxx = sum(p[0]**2 for p in pairs)
            syy = sum(p[1]**2 for p in pairs)
            sxy = sum(p[0]*p[1] for p in pairs)
            sxz = sum(p[0]*p[2] for p in pairs)
            syz = sum(p[1]*p[2] for p in pairs)

            # 3x3 Gleichungssystem: [[sxx,sxy,sx],[sxy,syy,sy],[sx,sy,n]] * [a,b,c] = [sxz,syz,sz]
            # Cramer's Rule
            det = sxx*(syy*nn - sy*sy) - sxy*(sxy*nn - sy*sx) + sx*(sxy*sy - syy*sx)
            if abs(det) > 1e-10:
                coeffs_a = (sxz*(syy*nn - sy*sy) - sxy*(syz*nn - sy*sz) + sx*(syz*sy - syy*sz)) / det
                coeffs_b = (sxx*(syz*nn - sy*sz) - sxz*(sxy*nn - sy*sx) + sx*(sxy*sz - syz*sx)) / det
                coeffs_c = (sxx*(syy*sz - syz*sy) - sxy*(sxy*sz - syz*sx) + sxz*(sxy*sy - syy*sx)) / det

                # R² für Multi-Modell
                ss_res_multi = sum((p[2] - (coeffs_a*p[0] + coeffs_b*p[1] + coeffs_c))**2 for p in pairs)
                r2_multi = 1 - ss_res_multi / ss_tot if ss_tot > 0 else 0

                # Plausibilitäts-Check: Koeffizienten müssen sinnvoll sein
                if coeffs_a < 0 or coeffs_b < -5 or coeffs_c < -10 or coeffs_c > 30:
                    LOG.warning(f"Multi-Modell unplausibel: a={coeffs_a:.2f}, b={coeffs_b:.2f}, c={coeffs_c:.2f}")
                    r2_multi = 0  # Erzwinge Fallback auf einfaches Modell
        except Exception as e:
            LOG.warning(f"Multi-Faktor-Berechnung fehlgeschlagen: {e}")

        # 6. Bestes Modell wählen
        use_multi = r2_multi > r2_simple + 0.02  # Multi muss deutlich besser sein
        if use_multi:
            model = 'multi'
            model_coeffs = {'a': round(coeffs_a, 3), 'b': round(coeffs_b, 3), 'c': round(coeffs_c, 3)}
            # Fehler mit Multi-Modell berechnen
            errors = [abs(p[2] - (coeffs_a*p[0] + coeffs_b*p[1] + coeffs_c)) / p[2] * 100
                      for p in pairs if p[2] > 0]
        else:
            model = 'simple'
            model_coeffs = {'factor': round(median_factor, 3)}
            errors = [abs(p[2] - p[0] * median_factor) / p[2] * 100 for p in pairs if p[2] > 0]

        avg_error = sum(errors) / len(errors) if errors else 0

        # 7. Monatliche Faktoren
        monthly_factors = {}
        for p in pairs:
            m = p[4]
            if m not in monthly_factors:
                monthly_factors[m] = []
            monthly_factors[m].append(p[2] / p[0])
        monthly_medians = {}
        for m, facs in monthly_factors.items():
            facs_s = sorted(facs)
            nm = len(facs_s)
            monthly_medians[str(m)] = round(
                (facs_s[nm//2-1] + facs_s[nm//2]) / 2 if nm % 2 == 0 else facs_s[nm//2], 3)

        stats = {
            'count': len(pairs),
            'model': model,
            'model_coeffs': model_coeffs,
            'median_factor': round(median_factor, 3),
            'mean_factor': round(mean_factor, 3),
            'std_dev': round((sum((f - mean_factor)**2 for f in factors) / len(factors))**0.5, 3),
            'r_squared': round(r2_simple, 3),
            'r_squared_multi': round(r2_multi, 3),
            'avg_error_pct': round(avg_error, 1),
            'monthly_factors': monthly_medians,
            'date_range': f"{start_date} bis {end_date}",
        }

        self._ghi_factor = median_factor
        self._save_calibration(median_factor, stats)

        # Log für Accuracy-Tracking
        for p in pairs:
            if use_multi:
                predicted = coeffs_a * p[0] + coeffs_b * p[1] + coeffs_c
            else:
                predicted = p[0] * median_factor
            self.cache.log_forecast(p[3], round(predicted, 1), p[0], round(p[2], 1))

        return stats

    # ─── Daten holen ───────────────────────────────────────

    def _ensure_forecast(self, days=7):
        """Stelle sicher, dass Forecast-Daten geladen sind."""
        if self._forecast_data is None:
            self._forecast_data = self.api.fetch_forecast(days)
        return self._forecast_data

    def _day_index(self, target_date=None):
        """Finde Index für Zieldatum in den daily-Daten."""
        data = self._ensure_forecast()
        if not data or 'daily' not in data:
            return None, None
        daily = data['daily']
        if target_date is None:
            target_str = date.today().isoformat()
        elif isinstance(target_date, date):
            target_str = target_date.isoformat()
        else:
            target_str = str(target_date)

        try:
            idx = daily['time'].index(target_str)
            return daily, idx
        except ValueError:
            return daily, None

    # ─── Hochlevel-Methoden ────────────────────────────────

    def estimate_kwh(self, radiation_mj, sunshine_hours=None, month=None):
        """
        Schätze PV-Ertrag aus Wetterdaten.
        
        Nutzt Multi-Faktor-Modell (GHI + Sonnenscheindauer) wenn kalibriert,
        sonst Fallback auf einfachen GHI-Faktor.
        """
        if radiation_mj is None or radiation_mj <= 0:
            return 0.0

        # Versuche Multi-Faktor-Modell
        cal = getattr(self, '_cal_data', {})
        if cal.get('model') == 'multi' and sunshine_hours is not None:
            coeffs = cal.get('model_coeffs', {})
            a = coeffs.get('a', self._ghi_factor)
            b = coeffs.get('b', 0)
            c = coeffs.get('c', 0)
            result = a * radiation_mj + b * sunshine_hours + c
            return round(max(result, 0), 1)

        # Fallback: Einfacher Faktor (monatsspezifisch wenn vorhanden)
        factor = self._ghi_factor
        if month:
            mf = cal.get('monthly_factors', {})
            if str(month) in mf:
                factor = mf[str(month)]

        return round(radiation_mj * factor, 1)

    def classify_day(self, expected_kwh, month=None):
        """Klassifiziere einen Tag als gut/mittel/schlecht."""
        if month is None:
            month = date.today().month
        thresholds = QUALITY_THRESHOLDS.get(month, (15, 40, 70))
        if expected_kwh < thresholds[0]:
            return 'schlecht'
        elif expected_kwh < thresholds[1]:
            return 'mittel'
        else:
            return 'gut'

    def get_day_forecast(self, target_date=None):
        """
        Tagesprognose.
        Returns dict mit sunrise, sunset, expected_kwh, quality, etc.
        Nutzt Geometrie-Engine wenn verfügbar (genauere kWh-Berechnung).
        """
        daily, idx = self._day_index(target_date)
        if daily is None or idx is None:
            return None

        d = daily
        month = int(d['time'][idx][5:7])
        radiation_mj = d['shortwave_radiation_sum'][idx]
        sunshine_h = d['sunshine_duration'][idx] / 3600 if d['sunshine_duration'][idx] else 0
        daylight_h = d['daylight_duration'][idx] / 3600 if d['daylight_duration'][idx] else 0
        
        # Primär: Geometrie-basierte kWh (per-String GTI)
        geo_result = self.get_daily_power_kwh(target_date)
        if geo_result:
            expected_kwh = round(geo_result['total_kwh'], 1)
            forecast_model = 'geometry'
        else:
            expected_kwh = self.estimate_kwh(radiation_mj, sunshine_hours=sunshine_h, month=month)
            forecast_model = 'multi' if getattr(self, '_cal_data', {}).get('model') == 'multi' else 'simple'
        
        quality = self.classify_day(expected_kwh, month)

        return {
            'date': d['time'][idx],
            'sunrise': d['sunrise'][idx],
            'sunset': d['sunset'][idx],
            'daylight_hours': round(daylight_h, 1),
            'sunshine_hours': round(sunshine_h, 1),
            'sunshine_pct': round(sunshine_h / daylight_h * 100, 0) if daylight_h > 0 else 0,
            'radiation_mj': radiation_mj,
            'expected_kwh': expected_kwh,
            'quality': quality,
            'forecast_model': forecast_model,
            'weather_code': d['weather_code'][idx],
            'weather_text': WMO_CODES.get(d['weather_code'][idx], f"Code {d['weather_code'][idx]}"),
            'temp_min': d['temperature_2m_min'][idx],
            'temp_max': d['temperature_2m_max'][idx],
            'precipitation_mm': d['precipitation_sum'][idx],
            'rain_probability': d['precipitation_probability_max'][idx],
            'ghi_factor': round(self._ghi_factor, 2),
            'api_healthy': self.api.healthy,
        }

    def get_hourly_forecast(self, target_date=None):
        """
        Stündliche Strahlungsprognose.
        Inkludiert alle Stunden mit Strahlung > 0, plus je 1h Padding 
        damit die Kurve sauber bei 0 beginnt/endet.
        Erfasst so auch Dämmerungsproduktion vor offiziellem Sonnenaufgang.
        """
        data = self._ensure_forecast()
        if not data or 'hourly' not in data:
            return None

        if target_date is None:
            target_str = date.today().isoformat()
        elif isinstance(target_date, date):
            target_str = target_date.isoformat()
        else:
            target_str = str(target_date)

        h = data['hourly']

        # Sammle alle Stunden des Tages mit Indices
        day_indices = []
        for i, t in enumerate(h['time']):
            if t.startswith(target_str):
                day_indices.append(i)

        if not day_indices:
            return []

        # Finde erste und letzte Stunde mit GHI > 0 (robust gegen None)
        first_radiation = None
        last_radiation = None
        for i in day_indices:
            ghi_val = h['shortwave_radiation'][i]
            if ghi_val is not None and ghi_val > 0:
                if first_radiation is None:
                    first_radiation = i
                last_radiation = i

        if first_radiation is None:
            return []  # Kein Sonnenlicht (z.B. Polarnacht)

        # Padding: 1 Stunde vor erster Strahlung, 1 Stunde nach letzter
        start_idx = max(first_radiation - 1, day_indices[0])
        end_idx = min(last_radiation + 1, day_indices[-1])

        hours = []
        for i in day_indices:
            if i < start_idx or i > end_idx:
                continue

            wind = 0
            if 'windspeed_10m' in h and i < len(h['windspeed_10m']):
                wind = h['windspeed_10m'][i] or 0

            hours.append({
                'time': h['time'][i],
                'hour': int(h['time'][i][11:13]),
                'ghi': h['shortwave_radiation'][i] or 0,           # W/m²
                'dni': h['direct_normal_irradiance'][i] or 0,      # W/m²
                'direct': h['direct_radiation'][i] or 0,           # W/m² (horizontal)
                'diffuse': h['diffuse_radiation'][i] or 0,         # W/m²
                'cloud_cover': h['cloud_cover'][i] or 0,           # %
                'sunshine_min': round((h['sunshine_duration'][i] or 0) / 60, 1),  # Minuten
                'temp': h['temperature_2m'][i] or 0,               # °C
                'wind': wind,                                      # m/s
                'weather_code': h['weather_code'][i] or 0,
                'precipitation': h['precipitation'][i] or 0,       # mm
            })

        return hours

    def get_hourly_power_forecast(self, target_date=None):
        """
        Stündliche PV-LEISTUNGS-Prognose (Watt) via Solar-Geometrie-Engine.
        
        Berechnet pro Stunde die AC-Leistung jedes Strings unter Berücksichtigung
        von Sonnenstand, Einfallswinkel, DNI/DHI-Aufteilung und Inverter-Clipping.
        
        Fallback: Wenn solar_geometry nicht verfügbar, gibt None zurück.
        
        Args:
            target_date: date oder 'YYYY-MM-DD' (default: morgen)
        
        Returns:
            list von dicts mit 'time', 'total_ac', 'total_dc', 'strings',
            'sun_elevation', 'sun_azimuth', 'ghi', 'dni', 'dhi', ...
            oder None bei Fehler.
        """
        if not HAS_GEOMETRY:
            LOG.warning("solar_geometry nicht verfügbar — Fallback auf GHI×Faktor")
            return None
        
        hourly = self.get_hourly_forecast(target_date)
        if not hourly:
            return None
        
        try:
            return _sg.estimate_hourly_power(hourly)
        except Exception as e:
            LOG.error(f"Geometrie-Leistungsprognose fehlgeschlagen: {e}")
            return None

    def get_daily_power_kwh(self, target_date=None):
        """
        Tages-Ertrag (kWh) via Geometrie-Engine (per-String GTI).
        
        Wesentlich genauer als estimate_kwh() weil:
          - Physikalische GTI pro String statt pauschaler GHI×Faktor
          - Inverter-Clipping berücksichtigt
          - Temperaturkorrektur
          - Morgen/Abend-Asymmetrie der Multi-Orientierung korrekt
        
        Returns:
            dict mit 'total_kwh', 'peak_w', 'strings_kwh', etc.
            oder None bei Fehler → Fallback auf estimate_kwh.
        """
        if not HAS_GEOMETRY:
            return None
        
        power_data = self.get_hourly_power_forecast(target_date)
        if not power_data:
            return None
        
        try:
            return _sg.estimate_daily_kwh(power_data)
        except Exception as e:
            LOG.error(f"Tages-kWh-Berechnung fehlgeschlagen: {e}")
            return None

    def get_sunrise_sunset(self, target_date=None):
        """Sonnenauf- und untergang. Returns (sunrise_str, sunset_str)."""
        daily, idx = self._day_index(target_date)
        if daily is None or idx is None:
            return None, None
        return daily['sunrise'][idx], daily['sunset'][idx]

    def get_week_forecast(self):
        """7-Tage-Übersicht."""
        self._forecast_data = None  # Force refresh
        data = self._ensure_forecast(days=7)
        if not data or 'daily' not in data:
            return None

        days = []
        d = data['daily']
        for i, date_str in enumerate(d['time']):
            month = int(date_str[5:7])
            radiation = d['shortwave_radiation_sum'][i]
            sunshine_h = d['sunshine_duration'][i] / 3600 if d['sunshine_duration'][i] else 0
            kwh = self.estimate_kwh(radiation, sunshine_hours=sunshine_h, month=month)

            days.append({
                'date': date_str,
                'weekday': _weekday_de(date_str),
                'sunrise': d['sunrise'][i][11:] if d['sunrise'][i] else '?',
                'sunset': d['sunset'][i][11:] if d['sunset'][i] else '?',
                'sunshine_hours': round(sunshine_h, 1),
                'radiation_mj': radiation,
                'expected_kwh': kwh,
                'quality': self.classify_day(kwh, month),
                'weather_code': d['weather_code'][i],
                'weather_text': WMO_CODES.get(d['weather_code'][i], '?'),
                'temp_min': d['temperature_2m_min'][i],
                'temp_max': d['temperature_2m_max'][i],
                'precipitation_mm': d['precipitation_sum'][i],
            })

        return days

    # ─── Für Batterie-Strategien ───────────────────────────

    def get_strategy_inputs(self, target_date=None):
        """
        Kompakte Eingabedaten für battery_scheduler.py.
        Returns dict mit allen Daten die die Strategien A-F brauchen.
        """
        today = self.get_day_forecast(target_date)
        if not today:
            # Fallback bei Fehler: konservative Werte
            return {
                'valid': False,
                'source': 'fallback',
                'sunrise': '07:30',
                'sunset': '17:00',
                'expected_kwh': 20.0,
                'quality': 'mittel',
                'cloud_cover_avg': 50,
                'is_good_day': False,
                'is_bad_day': False,
            }

        # Durchschnittliche Bewölkung tagsüber
        hourly = self.get_hourly_forecast(target_date)
        cloud_avg = 50
        if hourly:
            clouds = [h['cloud_cover'] for h in hourly if h['cloud_cover'] is not None]
            cloud_avg = round(sum(clouds) / len(clouds)) if clouds else 50

        return {
            'valid': True,
            'source': 'open-meteo' if self.api.healthy else 'cache',
            'date': today['date'],
            'sunrise': today['sunrise'],
            'sunset': today['sunset'],
            'sunrise_hour': _parse_hour(today['sunrise']),
            'sunset_hour': _parse_hour(today['sunset']),
            'daylight_hours': today['daylight_hours'],
            'sunshine_hours': today['sunshine_hours'],
            'sunshine_pct': today['sunshine_pct'],
            'radiation_mj': today['radiation_mj'],
            'expected_kwh': today['expected_kwh'],
            'quality': today['quality'],
            'cloud_cover_avg': cloud_avg,
            'weather_code': today['weather_code'],
            'weather_text': today['weather_text'],
            'temp_min': today['temp_min'],
            'temp_max': today['temp_max'],
            'precipitation_mm': today['precipitation_mm'],
            'is_good_day': today['quality'] == 'gut',
            'is_bad_day': today['quality'] == 'schlecht',
            'ghi_factor': today['ghi_factor'],
            'api_healthy': today['api_healthy'],
        }

    # ─── Selbstprüfung ────────────────────────────────────

    def self_check(self):
        """
        Prüfe Systemgesundheit:
        - API erreichbar?
        - Cache intakt?
        - Kalibrierung aktuell?
        - Forecast-Accuracy?
        """
        results = {
            'timestamp': datetime.now().isoformat(),
            'checks': [],
            'healthy': True,
        }

        # 1. API-Erreichbarkeit
        try:
            resp = requests.get(
                f"{OPEN_METEO_BASE}/forecast",
                params={'latitude': LATITUDE, 'longitude': LONGITUDE,
                        'daily': 'sunrise', 'timezone': TIMEZONE, 'forecast_days': 1},
                timeout=10
            )
            api_ok = resp.status_code == 200 and 'daily' in resp.json()
        except Exception as e:
            api_ok = False
        results['checks'].append({
            'name': 'API-Erreichbarkeit',
            'status': 'OK' if api_ok else 'FEHLER',
            'detail': 'Open-Meteo antwortet' if api_ok else f'API nicht erreichbar'
        })
        if not api_ok:
            results['healthy'] = False

        # 2. Cache prüfen
        cache_ok = os.path.exists(CACHE_DB)
        cached, is_fresh = self.cache.get('forecast_7d')
        cache_detail = 'Kein Cache' if not cached else ('aktuell' if is_fresh else 'abgelaufen')
        results['checks'].append({
            'name': 'Cache-Status',
            'status': 'OK' if cached else 'WARNUNG',
            'detail': f'Cache {cache_detail}'
        })

        # 3. Kalibrierung
        cal_ok = os.path.exists(CALIBRATION_FILE)
        cal_detail = f'Nicht kalibriert (Default-Faktor {DEFAULT_GHI_FACTOR})'
        if cal_ok:
            try:
                with open(CALIBRATION_FILE) as f:
                    cal = json.load(f)
                cal_date = cal.get('calibrated_at', '?')
                cal_factor = cal.get('ghi_factor', '?')
                cal_detail = f'Faktor {cal_factor}, kalibriert am {cal_date}'
            except Exception:
                cal_ok = False
                cal_detail = 'Kalibrierungsdatei fehlerhaft'
        results['checks'].append({
            'name': 'Kalibrierung',
            'status': 'OK' if cal_ok else 'WARNUNG',
            'detail': cal_detail
        })

        # 4. Forecast-Accuracy
        accuracy = self.cache.get_accuracy_stats(30)
        if accuracy:
            acc_ok = accuracy['avg_accuracy'] > 60
            results['checks'].append({
                'name': 'Prognose-Genauigkeit',
                'status': 'OK' if acc_ok else 'WARNUNG',
                'detail': f"Ø {accuracy['avg_accuracy']}% ({accuracy['count']} Tage)"
            })
            if not acc_ok:
                results['healthy'] = False
        else:
            results['checks'].append({
                'name': 'Prognose-Genauigkeit',
                'status': 'INFO',
                'detail': 'Noch keine Accuracy-Daten gesammelt'
            })

        # 5. Koordinaten-Plausibilität
        coord_ok = (50. < LATITUDE < 52.) and (12. < LONGITUDE < 14.)
        results['checks'].append({
            'name': 'Standort',
            'status': 'OK' if coord_ok else 'FEHLER',
            'detail': f'{LATITUDE:.4f}°N, {LONGITUDE:.4f}°E, {ELEVATION}m'
        })

        # 6. data.db verfügbar?
        db_ok = os.path.exists(DATA_DB)
        results['checks'].append({
            'name': 'Produktions-DB',
            'status': 'OK' if db_ok else 'WARNUNG',
            'detail': f'{DATA_DB} verfügbar' if db_ok else f'{DATA_DB} nicht gefunden'
        })

        return results


# ═══════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════

def _weekday_de(date_str):
    """ISO-Datum → deutscher Wochentag."""
    wdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return wdays[dt.weekday()]
    except Exception:
        return '??'


def _parse_hour(time_str):
    """'2026-02-09T07:31' oder '07:31' → 7.52 (dezimal)."""
    try:
        if 'T' in str(time_str):
            t = time_str.split('T')[1]
        else:
            t = str(time_str)
        parts = t.split(':')
        return int(parts[0]) + int(parts[1]) / 60
    except Exception:
        return 12.0  # Fallback: Mittag


def _quality_emoji(quality):
    """Qualität → Emoji."""
    return {'gut': '☀️', 'mittel': '⛅', 'schlecht': '☁️'}.get(quality, '❓')


def _quality_bar(radiation_mj, max_mj=30):
    """Strahlungssumme als ASCII-Balken."""
    if radiation_mj is None:
        return '???'
    bars = int(min(radiation_mj / max_mj, 1.0) * 20)
    return '█' * bars + '░' * (20 - bars)


# ═══════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════

def print_day_forecast(forecast, sf):
    """Formatierte Tagesprognose ausgeben."""
    if not forecast:
        print("FEHLER: Keine Prognose-Daten verfügbar")
        return

    f = forecast
    emoji = _quality_emoji(f['quality'])
    bar = _quality_bar(f['radiation_mj'])

    print(f"\n{'═' * 60}")
    print(f"  {emoji} SOLAR-PROGNOSE: {f['date']} ({_weekday_de(f['date'])})")
    print(f"{'═' * 60}")
    print()
    print(f"  Wetter:     {f['weather_text']} (WMO {f['weather_code']})")
    print(f"  Temperatur: {f['temp_min']:.0f}°C / {f['temp_max']:.0f}°C")
    if f['precipitation_mm'] > 0:
        print(f"  Niederschl: {f['precipitation_mm']:.1f} mm (P={f['rain_probability']}%)")
    print()
    print(f"  Sonnenaufg: {f['sunrise'][11:]}")
    print(f"  Sonnenuntg: {f['sunset'][11:]}")
    print(f"  Tageslicht: {f['daylight_hours']}h")
    print(f"  Sonnenschn: {f['sunshine_hours']}h ({f['sunshine_pct']:.0f}%)")
    print()
    print(f"  Strahlung:  {f['radiation_mj']:.1f} MJ/m²")
    print(f"  {bar}")
    print()
    print(f"  Erwarteter PV-Ertrag: {f['expected_kwh']:.0f} kWh")
    print(f"  Tagesqualität:        {f['quality'].upper()} {emoji}")
    print(f"  Kalibr.-Faktor:       {f['ghi_factor']}")
    print()

    if not f['api_healthy']:
        print(f"  ⚠️  Daten aus Cache (API nicht erreichbar)")
    print()


def print_hourly_forecast(hours):
    """Stündliche Strahlung als Tabelle."""
    if not hours:
        print("Keine stündlichen Daten verfügbar")
        return

    print(f"\n{'═' * 72}")
    print(f"  STÜNDLICHE STRAHLUNG")
    print(f"{'═' * 72}")
    print(f"  {'Zeit':>5}  {'GHI':>6}  {'DNI':>6}  {'Diff':>5}  {'Wolken':>6}  {'Sonne':>5}  {'Temp':>5}  WMO")
    print(f"  {'':>5}  {'W/m²':>6}  {'W/m²':>6}  {'W/m²':>5}  {'%':>6}  {'min':>5}  {'°C':>5}")
    print(f"  {'─' * 66}")

    total_ghi = 0
    for h in hours:
        ghi_bar = '▓' * min(int(h['ghi'] / 50), 15)
        print(f"  {h['time'][11:16]:>5}  {h['ghi']:>6.0f}  {h['dni']:>6.0f}  "
              f"{h['diffuse']:>5.0f}  {h['cloud_cover']:>5.0f}%  "
              f"{h['sunshine_min']:>5.1f}  {h['temp']:>5.1f}  "
              f"{h['weather_code']:>3} {ghi_bar}")
        total_ghi += h['ghi']

    print(f"  {'─' * 66}")
    print(f"  Summe GHI: {total_ghi:.0f} W/m² (stündl. Summe)")
    print()


def print_week_forecast(days):
    """7-Tage-Übersicht."""
    if not days:
        print("Keine 7-Tage-Prognose verfügbar")
        return

    print(f"\n{'═' * 78}")
    print(f"  7-TAGE SOLAR-PROGNOSE — Erlau ({LATITUDE:.2f}°N, {LONGITUDE:.2f}°E)")
    print(f"{'═' * 78}")
    print(f"  {'Datum':>10}  {'WT':>2}  {'↑':>5}  {'↓':>5}  {'☀h':>5}  {'MJ/m²':>5}  "
          f"{'kWh':>5}  {'Qual':>8}  {'Wetter'}")
    print(f"  {'─' * 72}")

    total_kwh = 0
    for d in days:
        emoji = _quality_emoji(d['quality'])
        rain = f" {d['precipitation_mm']:.0f}mm" if d['precipitation_mm'] > 0.5 else ""
        print(f"  {d['date']:>10}  {d['weekday']:>2}  {d['sunrise']:>5}  {d['sunset']:>5}  "
              f"{d['sunshine_hours']:>5.1f}  {d['radiation_mj']:>5.1f}  "
              f"{d['expected_kwh']:>5.0f}  {emoji} {d['quality']:<6}  "
              f"{d['weather_text']}{rain}  {d['temp_min']:.0f}/{d['temp_max']:.0f}°C")
        total_kwh += d['expected_kwh']

    print(f"  {'─' * 72}")
    print(f"  {'Gesamt':>10}  {'':>2}  {'':>5}  {'':>5}  {'':>5}  {'':>5}  {total_kwh:>5.0f}")
    print()


def print_calibration(stats):
    """Kalibrierungsergebnis anzeigen."""
    if 'error' in stats:
        print(f"\n  FEHLER: {stats['error']}")
        return

    print(f"\n{'=' * 60}")
    print(f"  KALIBRIERUNG: GHI -> PV-Ertrag")
    print(f"{'=' * 60}")
    print(f"  Zeitraum:         {stats['date_range']}")
    print(f"  Datenpunkte:      {stats['count']}")
    print()
    print(f"  --- Einfaches Modell (PV = factor * GHI) ---")
    print(f"  Median-Faktor:    {stats['median_factor']:.3f} kWh / (MJ/m2)")
    print(f"  Mittelwert:       {stats['mean_factor']:.3f}")
    print(f"  Standardabw.:     {stats['std_dev']:.3f}")
    print(f"  R2:               {stats['r_squared']:.3f}")
    print()
    r2m = stats.get('r_squared_multi', 0)
    if r2m and r2m > 0:
        coeffs = stats.get('model_coeffs', {})
        print(f"  --- Multi-Faktor (PV = a*GHI + b*Sunshine_h + c) ---")
        print(f"  a (GHI):          {coeffs.get('a', '?')}")
        print(f"  b (Sonnenstd):    {coeffs.get('b', '?')}")
        print(f"  c (Basis):        {coeffs.get('c', '?')}")
        print(f"  R2:               {r2m:.3f}")
        print()
    chosen = stats.get('model', 'simple')
    print(f"  ==> Gewaehltes Modell: {chosen.upper()}")
    print(f"  Oe Fehler:         {stats['avg_error_pct']:.1f}%")
    print()
    print(f"  Monatliche Faktoren:")
    for m, f in sorted(stats.get('monthly_factors', {}).items(), key=lambda x: int(x[0])):
        mname = ['', 'Jan', 'Feb', 'Maer', 'Apr', 'Mai', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'][int(m)]
        print(f"    {mname}: {f:.3f}")
    print()
    print(f"  -> Kalibrierung gespeichert in: {CALIBRATION_FILE}")
    print()


def print_self_check(results):
    """Selbstprüfung anzeigen."""
    print(f"\n{'═' * 60}")
    emoji = '✅' if results['healthy'] else '⚠️'
    print(f"  {emoji} SELBSTPRÜFUNG: {'GESUND' if results['healthy'] else 'PROBLEME'}")
    print(f"{'═' * 60}")
    for check in results['checks']:
        icon = {'OK': '✅', 'WARNUNG': '⚠️', 'FEHLER': '❌', 'INFO': 'ℹ️'}[check['status']]
        print(f"  {icon} {check['name']}: {check['detail']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Solar-Prognose für PV-Batterie-Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Beispiele:
  %(prog)s --today           Tagesprognose
  %(prog)s --tomorrow        Morgen
  %(prog)s --hourly          Stündliche Strahlung heute
  %(prog)s --week            7-Tage-Übersicht
  %(prog)s --calibrate       Kalibrierung aus Produktionsdaten
  %(prog)s --check           Systemprüfung
  %(prog)s --strategy        Daten für Batterie-Strategien
""")
    parser.add_argument('--today', action='store_true', help='Tagesprognose')
    parser.add_argument('--tomorrow', action='store_true', help='Prognose für morgen')
    parser.add_argument('--hourly', action='store_true', help='Stündliche Strahlung')
    parser.add_argument('--week', action='store_true', help='7-Tage-Übersicht')
    parser.add_argument('--date', type=str, help='Zieldatum (YYYY-MM-DD)')
    parser.add_argument('--calibrate', action='store_true', help='GHI→PV Kalibrierung')
    parser.add_argument('--calibrate-days', type=int, default=90,
                        help='Tage für Kalibrierung (default: 90)')
    parser.add_argument('--check', action='store_true', help='Systemprüfung')
    parser.add_argument('--strategy', action='store_true', help='Batterie-Strategie-Daten')
    parser.add_argument('--json', action='store_true', help='JSON-Ausgabe')
    parser.add_argument('--debug', action='store_true', help='Debug-Logging')

    args = parser.parse_args()

    # Logging
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    sf = SolarForecast()

    # Default: --today wenn nichts angegeben
    if not any([args.today, args.tomorrow, args.hourly, args.week,
                args.calibrate, args.check, args.strategy]):
        args.today = True

    # Zieldatum
    target_date = None
    if args.date:
        target_date = args.date
    elif args.tomorrow:
        target_date = (date.today() + timedelta(days=1)).isoformat()

    if args.check:
        results = sf.self_check()
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print_self_check(results)

    if args.calibrate:
        stats = sf.calibrate(days=args.calibrate_days)
        if args.json:
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            print_calibration(stats)

    if args.today or args.tomorrow:
        forecast = sf.get_day_forecast(target_date)
        if args.json:
            print(json.dumps(forecast, indent=2, ensure_ascii=False))
        else:
            print_day_forecast(forecast, sf)

    if args.hourly:
        hours = sf.get_hourly_forecast(target_date or date.today().isoformat())
        if args.json:
            print(json.dumps(hours, indent=2, ensure_ascii=False))
        else:
            print_hourly_forecast(hours)

    if args.week:
        days = sf.get_week_forecast()
        if args.json:
            print(json.dumps(days, indent=2, ensure_ascii=False))
        else:
            print_week_forecast(days)

    if args.strategy:
        inputs = sf.get_strategy_inputs(target_date)
        if args.json:
            print(json.dumps(inputs, indent=2, ensure_ascii=False))
        else:
            print(f"\n  Strategie-Eingabedaten ({inputs.get('source', '?')}):")
            for k, v in inputs.items():
                print(f"    {k}: {v}")
            print()


if __name__ == '__main__':
    main()
