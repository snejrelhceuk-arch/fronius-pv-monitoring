#!/usr/bin/env python3
"""
PV-System - Fronius-basiertes Photovoltaik Monitoring & Management

Dieses System ist spezifisch für Fronius-Hardware konzipiert:
- Fronius Symo/Primo Wechselrichter (Modbus/Solar API)
- Fronius SmartMeter (4x Units: Netz, F2, F3, Wärmepumpe)
- Fronius BYD Battery-Box HVS (Batterie-Management)
- Fronius Wattpilot (Wallbox/WebSocket API)
"""

"""
solar_geometry.py — Solar-Geometrie-Engine für Multi-Orientierungs-PV
=====================================================================

Berechnet Sonnenstand, Einfallswinkel und PV-Ertrag für jeden String
der Anlage unter Berücksichtigung von Neigung, Ausrichtung und Wetter.

Architektur (Hybrid: dynamische Berechnung + gecachte Profiltabelle):
  1. Dynamischer Kern: Sonnenstand + GTI pro String für beliebige Zeitpunkte
  2. Clear-Sky-Profiltabelle: 365 Tage × 24h — generiert vom Kern, gecacht
  3. Wetterkorrektur: Clear-Sky × (tatsächliche/ClearSky-Strahlung) = Prognose
  4. Neigungstabelle: Jährl. Ertragsanteile (37×19), berechnet + validiert

Konventionen (gleich wie solar_forecast.py PV_STRINGS):
  - Azimut: 0° = Süd, -90° = Ost, +90° = West, ±180° = Nord
  - Neigung (Tilt): 0° = horizontal, 90° = vertikal (Fassade)
  - Sonnenazimut: 0° = Süd, positiv nach Westen

Wetterdaten-Auflösung:
  - Open-Meteo mit DWD ICON-D2: 2,2 km Raster, 15min (explizit: models=icon_d2)
  - Strahlung: GHI + DNI + DHI (alle 3 Komponenten für GTI-Berechnung)

Standort: Erlau, Mittelsachsen, 51.01°N 12.95°E, 315m NN

Autor: PV-Anlage Solar-Geometry-Engine
Datum: 2026-02-10
"""

import math
import json
import os
import logging
import sys
from datetime import datetime, date, timedelta, timezone

try:
    import numpy as np
    import pandas as pd
    import pvlib
    from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS
    HAS_PVLIB = True
except Exception:
    HAS_PVLIB = False

# Encoding fix für RPi5
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LOG = logging.getLogger('solar_geometry')


# ═══════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════

try:
    import config as _cfg
    LATITUDE   = _cfg.LATITUDE       # 51.01
    LONGITUDE  = _cfg.LONGITUDE      # 12.95
    ELEVATION  = _cfg.ELEVATION      # 315m
    TIMEZONE   = getattr(_cfg, 'TIMEZONE', 'Europe/Berlin')
except (ImportError, AttributeError):
    LATITUDE   = 51.01
    LONGITUDE  = 12.95
    ELEVATION  = 315
    TIMEZONE   = 'Europe/Berlin'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'config')
CLEARSKY_CACHE = os.path.join(CACHE_DIR, 'clearsky_profile.json')
EFFICIENCY_CACHE = os.path.join(CACHE_DIR, 'efficiency_table.json')


# ─── PV-String-Konfiguration ──────────────────────────────────
# Aus PV_REFERENZSYSTEM_DOKUMENTATION.md § String-Konfiguration Phase 3
# Azimut: 0°=Süd, -22.5°=SSO (150° Kompass), 67.5°=WSW (240°), 157.5°=NNW (330°)

PV_STRINGS = [
    {'kwp': 6.90, 'tilt': 52, 'azimuth': -22.5, 'name': 'F1-S1 SSO-52°',
     'inverter': 'F1', 'description': 'Satteldach Süd, 20× 345Wp'},
    {'kwp': 6.90, 'tilt': 52, 'azimuth': 157.5, 'name': 'F1-S2 NNW-52°',
     'inverter': 'F1', 'description': 'Satteldach Nord, 20× 345Wp'},
    {'kwp': 2.76, 'tilt': 45, 'azimuth': -22.5, 'name': 'F1-S3 SSO-45°',
     'inverter': 'F1', 'description': 'Gaube/Anbau Süd, 8× 345Wp'},
    {'kwp': 2.76, 'tilt': 45, 'azimuth': 157.5, 'name': 'F1-S4 NNW-45°',
     'inverter': 'F1', 'description': 'Gaube/Anbau Nord, 8× 345Wp'},
    {'kwp': 6.75, 'tilt': 18, 'azimuth':  67.5, 'name': 'F2-S5 WSW-18°',
     'inverter': 'F2', 'description': 'Flachdach West, 15× 450Wp'},
    {'kwp': 5.67, 'tilt': 90, 'azimuth':  67.5, 'name': 'F2-S6+7 WSW-90°',
     'inverter': 'F2', 'description': 'Fassade West, 8×450+6×345Wp + Optimierer'},
    {'kwp': 5.85, 'tilt': 90, 'azimuth': -22.5, 'name': 'F3-S8 SSO-90°',
     'inverter': 'F3', 'description': 'Fassade Süd, 13× 450Wp'},
]

# Wechselrichter-Maximalleistungen (AC, Watt)
INVERTER_LIMITS = {
    'F1': 12000,   # Gen24 12 kW
    'F2': 10000,   # Gen24 10 kW
    'F3':  4500,   # Symo 4.5 kW
}

# Physikalische Konstanten (Defaults — werden durch config/geometry_config.json überschrieben)
SOLAR_CONSTANT = 1361.0   # W/m² (Total Solar Irradiance, TSI)
GROUND_ALBEDO = 0.20      # Bodenreflexion (Wiese/Erdboden)
PERFORMANCE_RATIO = 0.85  # Systemverluste (Kabel, Mismatch, Verschmutzung, etc.)
TEMP_COEFF = -0.0035      # Temperaturkoeffizient (%/°C über 25°C, typisch Si)
DEFAULT_WIND_SPEED = 1.0  # m/s, falls Wetterdaten keine Windgeschwindigkeit liefern

# Atmosphäre (Defaults)
ATMOSPHERIC_TURBIDITY = 0.70    # τ bei AM=1
DHI_COEFFICIENT = 0.20          # Diffus-Koeffizient Clear-Sky
CLIMATE_DIFFUSE_FRACTION = 0.52 # Für Effizienztabelle

# Per-String-Korrekturfaktoren (1.0 = neutral)
STRING_FACTORS = {}

# Per-String Optimierer-Gain (1.0 = neutral)
OPTIMIZER_GAIN = {}

# Wechselrichter-Wirkungsgrade
INVERTER_EFFICIENCY = {}

# Globale Prognose-Korrekturen
FORECAST_GLOBAL_FACTOR = 1.0
FORECAST_CLOUD_ENHANCEMENT = 1.0
FORECAST_WINTER_BOOST = 1.0
FORECAST_SUMMER_FACTOR = 1.0

# Gebäude-Azimut-Korrektur (° negativ = Richtung Ost drehen)
# Dreht ALLE Strings gemeinsam, verschiebt Clear-Sky-Kurve zeitlich
AZIMUTH_OFFSET = 0.0

# Optional: Verschattungsmaske (Azimut/Elevation → Faktor 0..1)
SHADING_MASK = None

# Saisonale Modultemperatur für Clear-Sky-Kurve (°C pro Monat)
# Ersetzt den Default 25°C durch realistische Werte
CLEARSKY_TEMP_BY_MONTH = {
    1: 5,  2: 7,  3: 12,  4: 18,
    5: 22, 6: 28, 7: 30,  8: 28,
    9: 22, 10: 15, 11: 8, 12: 4
}

# ─── Konfiguration aus Datei laden ─────────────────────────────
GEOMETRY_CONFIG_FILE = os.path.join(CACHE_DIR, 'geometry_config.json')

def _load_geometry_config():
    """Lädt justierbare Parameter aus config/geometry_config.json."""
    global GROUND_ALBEDO, PERFORMANCE_RATIO, TEMP_COEFF
    global ATMOSPHERIC_TURBIDITY, DHI_COEFFICIENT, CLIMATE_DIFFUSE_FRACTION
    global STRING_FACTORS, INVERTER_EFFICIENCY
    global OPTIMIZER_GAIN
    global FORECAST_GLOBAL_FACTOR, FORECAST_CLOUD_ENHANCEMENT
    global FORECAST_WINTER_BOOST, FORECAST_SUMMER_FACTOR
    global AZIMUTH_OFFSET, CLEARSKY_TEMP_BY_MONTH, SHADING_MASK

    if not os.path.exists(GEOMETRY_CONFIG_FILE):
        LOG.info("Keine geometry_config.json — verwende Standard-Parameter")
        return

    try:
        with open(GEOMETRY_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)

        # System-Parameter
        sys_cfg = cfg.get('system', {})
        PERFORMANCE_RATIO = sys_cfg.get('performance_ratio', PERFORMANCE_RATIO)
        TEMP_COEFF = sys_cfg.get('temp_coeff', TEMP_COEFF)
        GROUND_ALBEDO = sys_cfg.get('ground_albedo', GROUND_ALBEDO)

        # Atmosphäre
        atm_cfg = cfg.get('atmosphere', {})
        ATMOSPHERIC_TURBIDITY = atm_cfg.get('turbidity', ATMOSPHERIC_TURBIDITY)
        DHI_COEFFICIENT = atm_cfg.get('dhi_coefficient', DHI_COEFFICIENT)
        CLIMATE_DIFFUSE_FRACTION = atm_cfg.get('climate_diffuse_fraction',
                                                 CLIMATE_DIFFUSE_FRACTION)

        # Per-String-Faktoren
        STRING_FACTORS = cfg.get('string_factors', {})

        # Per-String Optimierer-Gain
        OPTIMIZER_GAIN = cfg.get('optimizer_gain', {})

        # WR-Wirkungsgrade
        INVERTER_EFFICIENCY = cfg.get('inverter_efficiency', {})

        # Prognose-Korrekturen
        fc_cfg = cfg.get('forecast_adjustments', {})
        FORECAST_GLOBAL_FACTOR = fc_cfg.get('global_factor', 1.0)
        FORECAST_CLOUD_ENHANCEMENT = fc_cfg.get('cloud_enhancement', 1.0)
        FORECAST_WINTER_BOOST = fc_cfg.get('winter_boost', 1.0)
        FORECAST_SUMMER_FACTOR = fc_cfg.get('summer_factor', 1.0)

        # Gebäudeausrichtung-Korrektur
        AZIMUTH_OFFSET = cfg.get('azimuth_offset', 0.0)

        # Verschattungsmaske (optional)
        SHADING_MASK = cfg.get('shading_mask', None)

        # Saisonale Clear-Sky Modultemperatur
        cs_temp = cfg.get('clearsky_module_temp', {})
        if cs_temp:
            for m_str, t in cs_temp.items():
                try:
                    CLEARSKY_TEMP_BY_MONTH[int(m_str)] = t
                except (ValueError, TypeError):
                    pass  # _doc, _info etc. überspringen

        LOG.info(f"Geometrie-Konfiguration geladen: PR={PERFORMANCE_RATIO}, "
                 f"τ={ATMOSPHERIC_TURBIDITY}, Azimut-Offset={AZIMUTH_OFFSET}°, "
                 f"Strings={len(STRING_FACTORS)} Faktoren")
    except Exception as e:
        LOG.warning(f"geometry_config.json Ladefehler: {e} — verwende Defaults")

# Beim Modul-Import laden
_load_geometry_config()


# ═══════════════════════════════════════════════════════════════
# JSON-CACHE HELPERS
# ═══════════════════════════════════════════════════════════════

def _load_json_cache(path, version=2, extra_check=None):
    """Lädt JSON-Cache falls vorhanden und Version stimmt.
    
    Args:
        path: Dateipfad
        version: Erwartete Version (geprüft über 'version' Key)
        extra_check: Optionale callable(data) → bool für zusätzliche Validierung
    Returns:
        dict oder None
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            cached = json.load(f)
        if cached.get('version') != version:
            return None
        if extra_check and not extra_check(cached):
            return None
        return cached
    except Exception as e:
        LOG.warning(f"Cache nicht lesbar ({path}): {e}")
        return None


def _save_json_cache(path, data, log_msg=None):
    """Speichert Daten als JSON-Cache."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        if log_msg:
            LOG.info(log_msg)
    except Exception as e:
        LOG.warning(f"Cache speichern fehlgeschlagen ({path}): {e}")


# ═══════════════════════════════════════════════════════════════
# ZEITZONEN-HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════

def _last_sunday_of_month(year, month):
    """Letzten Sonntag eines Monats finden."""
    # Letzter Tag des Monats
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    # Zurück zum letzten Sonntag (weekday: Mo=0, So=6)
    offset = (last_day.weekday() + 1) % 7  # Tage seit letztem Sonntag
    return last_day - timedelta(days=offset)


def utc_offset_hours(dt):
    """
    UTC-Offset für Europe/Berlin: +1 (CET) oder +2 (CEST).
    
    CEST: Letzter Sonntag im März 02:00 → Letzter Sonntag im Oktober 03:00
    """
    year = dt.year if isinstance(dt, (datetime, date)) else 2026
    
    dst_start = datetime(year, 3, _last_sunday_of_month(year, 3).day, 2)
    dst_end = datetime(year, 10, _last_sunday_of_month(year, 10).day, 3)
    
    dt_naive = dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') and dt.tzinfo else dt
    
    if dst_start <= dt_naive < dst_end:
        return 2   # CEST (Sommerzeit)
    return 1       # CET (Winterzeit)


def local_to_utc(dt_local):
    """Konvertiere Europe/Berlin Lokalzeit → UTC datetime."""
    offset = utc_offset_hours(dt_local)
    dt_naive = dt_local.replace(tzinfo=None) if hasattr(dt_local, 'tzinfo') else dt_local
    return dt_naive - timedelta(hours=offset)


# ═══════════════════════════════════════════════════════════════
# GEOMETRIE-SCAFFOLD (pvlib)
# ═══════════════════════════════════════════════════════════════

def _localize_times(times_local):
    if not HAS_PVLIB:
        raise RuntimeError("pvlib nicht verfuegbar")
    idx = pd.DatetimeIndex(times_local)
    if idx.tz is None:
        return idx.tz_localize(TIMEZONE)
    return idx.tz_convert(TIMEZONE)


def _shading_mask_series(azimuth_deg, elevation_deg, mask_cfg):
    if not mask_cfg:
        return pd.Series(1.0, index=azimuth_deg.index)

    try:
        az_bins = mask_cfg.get('azimuth_bins')
        el_bins = mask_cfg.get('elevation_bins')
        mask = np.array(mask_cfg.get('mask'))
        if not az_bins or not el_bins or mask.size == 0:
            return pd.Series(1.0, index=azimuth_deg.index)
    except Exception:
        return pd.Series(1.0, index=azimuth_deg.index)

    az_idx = np.digitize(azimuth_deg.to_numpy(), az_bins) - 1
    el_idx = np.digitize(elevation_deg.to_numpy(), el_bins) - 1

    az_idx = np.clip(az_idx, 0, mask.shape[0] - 1)
    el_idx = np.clip(el_idx, 0, mask.shape[1] - 1)

    factors = mask[az_idx, el_idx]
    return pd.Series(factors, index=azimuth_deg.index)


class GeometryScaffold:
    def __init__(self, times_local, strings, latitude=LATITUDE, longitude=LONGITUDE,
                 elevation=ELEVATION, shading_mask=None):
        if not HAS_PVLIB:
            raise RuntimeError("pvlib nicht verfuegbar")

        self.times = _localize_times(times_local)
        self.strings = strings
        self.shading_mask = shading_mask
        self.solar_position = pvlib.solarposition.get_solarposition(
            self.times,
            latitude=latitude,
            longitude=longitude,
            altitude=elevation,
        )
        self.solar_position['elevation'] = 90.0 - self.solar_position['apparent_zenith']

    def _string_shading(self, name):
        if isinstance(self.shading_mask, dict) and name in self.shading_mask:
            return _shading_mask_series(
                self.solar_position['azimuth'],
                self.solar_position['elevation'],
                self.shading_mask.get(name),
            )
        return _shading_mask_series(
            self.solar_position['azimuth'],
            self.solar_position['elevation'],
            self.shading_mask,
        )

    def compute_string_dc_power(self, weather_df):
        weather = weather_df.reindex(self.times).copy()
        strings_dc = {}

        temp_params = None
        if HAS_PVLIB:
            temp_params = TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']

        for s in self.strings:
            surface_azimuth = s['azimuth'] + AZIMUTH_OFFSET
            poa = pvlib.irradiance.get_total_irradiance(
                surface_tilt=s['tilt'],
                surface_azimuth=surface_azimuth,
                solar_zenith=self.solar_position['apparent_zenith'],
                solar_azimuth=self.solar_position['azimuth'],
                dni=weather['dni'],
                ghi=weather['ghi'],
                dhi=weather['dhi'],
                albedo=GROUND_ALBEDO,
                model='perez',
            )

            poa_global = poa['poa_global'].clip(lower=0)
            poa_global = poa_global * self._string_shading(s.get('name', ''))

            if temp_params:
                cell_temp = pvlib.temperature.sapm_cell(
                    poa_global,
                    weather['temp'],
                    weather['wind'],
                    **temp_params,
                )
            else:
                cell_temp = weather['temp'] + (poa_global / 800.0) * 20.0

            temp_factor = 1 + TEMP_COEFF * (cell_temp - 25)
            temp_factor = temp_factor.clip(lower=0.70, upper=1.10)

            string_factor = STRING_FACTORS.get(s.get('name', ''), 1.0)
            optimizer_gain = OPTIMIZER_GAIN.get(s.get('name', ''), 1.0)
            dc_power = (s['kwp'] * 1000.0) * (poa_global / 1000.0)
            dc_power = dc_power * PERFORMANCE_RATIO * temp_factor
            dc_power = dc_power * string_factor * optimizer_gain

            strings_dc[s['name']] = dc_power.clip(lower=0)

        return pd.DataFrame(strings_dc, index=self.times)

    def compute_inverter_power(self, strings_dc):
        inverter_ac = {}
        inverter_dc = {}
        inverter_clipped = {}

        for s in self.strings:
            inv = s['inverter']
            name = s['name']
            inverter_dc.setdefault(inv, 0.0)
            inverter_dc[inv] = inverter_dc[inv] + strings_dc[name]

        for inv, dc in inverter_dc.items():
            limit = INVERTER_LIMITS.get(inv, 99999)
            inv_eff = INVERTER_EFFICIENCY.get(inv, 1.0)
            clipped = dc > limit
            ac = dc.clip(upper=limit) * inv_eff
            inverter_ac[inv] = ac
            inverter_clipped[inv] = clipped

        return inverter_ac, inverter_dc, inverter_clipped


# ═══════════════════════════════════════════════════════════════
# SONNENPOSITION (Jean Meeus, Astronomical Algorithms)
# ═══════════════════════════════════════════════════════════════

def sun_position(dt_utc, lat=LATITUDE, lon=LONGITUDE):
    """
    Berechne Sonnenposition für einen UTC-Zeitpunkt.
    
    Algorithmus: Meeus (vereinfacht), Genauigkeit ~0.01° für 2000-2100.
    
    Args:
        dt_utc: datetime in UTC (oder naive, wird als UTC behandelt)
        lat: Breitengrad (°N positiv)
        lon: Längengrad (°E positiv)
    
    Returns:
        (elevation_deg, azimuth_deg)
        elevation: 0°=Horizont, 90°=Zenit, negativ=unter Horizont
        azimuth: 0°=Süd, +90°=West, -90°=Ost, ±180°=Nord
    """
    # Julian Day Number
    a = (14 - dt_utc.month) // 12
    y = dt_utc.year + 4800 - a
    m = dt_utc.month + 12 * a - 3
    jdn = (dt_utc.day + (153 * m + 2) // 5 + 365 * y
           + y // 4 - y // 100 + y // 400 - 32045)
    jd = jdn + (dt_utc.hour - 12) / 24.0 + dt_utc.minute / 1440.0 + dt_utc.second / 86400.0
    
    # Julian Century seit J2000.0
    n = jd - 2451545.0
    jc = n / 36525.0
    
    # Geometrische mittlere Länge der Sonne (°)
    L0 = (280.46646 + jc * (36000.76983 + 0.0003032 * jc)) % 360
    
    # Mittlere Anomalie der Sonne (°)
    M = (357.52911 + jc * (35999.05029 - 0.0001537 * jc)) % 360
    M_rad = math.radians(M)
    
    # Exzentrizität der Erdbahn
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    
    # Mittelpunktsgleichung (°)
    C = ((1.914602 - jc * (0.004817 + 0.000014 * jc)) * math.sin(M_rad)
         + (0.019993 - 0.000101 * jc) * math.sin(2 * M_rad)
         + 0.000289 * math.sin(3 * M_rad))
    
    # Wahre Länge der Sonne
    sun_lon = L0 + C
    
    # Nutation & Aberration
    omega = 125.04 - 1934.136 * jc
    sun_lambda = sun_lon - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    sun_lambda_rad = math.radians(sun_lambda)
    
    # Schiefe der Ekliptik (korrigiert)
    eps0 = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    epsilon = eps0 + 0.00256 * math.cos(math.radians(omega))
    eps_rad = math.radians(epsilon)
    
    # Deklination
    decl = math.asin(math.sin(eps_rad) * math.sin(sun_lambda_rad))
    decl_deg = math.degrees(decl)
    
    # Zeitgleichung (Equation of Time) in Minuten
    y_eot = math.tan(eps_rad / 2) ** 2
    L0_rad = math.radians(L0)
    eot = 4 * math.degrees(
        y_eot * math.sin(2 * L0_rad)
        - 2 * e * math.sin(M_rad)
        + 4 * e * y_eot * math.sin(M_rad) * math.cos(2 * L0_rad)
        - 0.5 * y_eot ** 2 * math.sin(4 * L0_rad)
        - 1.25 * e ** 2 * math.sin(2 * M_rad)
    )
    
    # Stundenwinkel
    time_offset = eot + 4 * lon   # Minuten
    tst = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60.0 + time_offset
    ha = (tst / 4.0) - 180.0     # Stundenwinkel in Grad
    ha_rad = math.radians(ha)
    
    lat_rad = math.radians(lat)
    
    # Sonnenhöhe (Elevation)
    sin_elev = (math.sin(lat_rad) * math.sin(decl)
                + math.cos(lat_rad) * math.cos(decl) * math.cos(ha_rad))
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elevation = math.degrees(math.asin(sin_elev))
    
    # Sonnenazimut (vom Süden gemessen, 0°=Süd, +=West, -=Ost)
    # Formel: cos(A) = [sin(α)sin(φ) - sin(δ)] / [cos(α)cos(φ)]
    cos_elev = math.cos(math.radians(elevation))
    if cos_elev < 1e-10:
        azimuth = 0.0  # Sonne im Zenit (kommt bei 51°N nicht vor)
    else:
        cos_az = ((sin_elev * math.sin(lat_rad) - math.sin(decl))
                  / (cos_elev * math.cos(lat_rad)))
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
    
    # Vorzeichen: ha > 0 → Nachmittag → Westen (positiv)
    if ha > 0:
        pass  # azimuth bleibt positiv (West)
    else:
        azimuth = -azimuth  # Ost = negativ
    
    # Atmosphärische Refraktion (Bennett 1982)
    if elevation > -0.575:
        refraction = 1.02 / math.tan(math.radians(elevation + 10.3 / (elevation + 5.11))) / 60.0
    else:
        refraction = 0.0
    
    return elevation + refraction, azimuth


# ═══════════════════════════════════════════════════════════════
# EINFALLSWINKEL & GTI (Global Tilted Irradiance)
# ═══════════════════════════════════════════════════════════════

def angle_of_incidence(sun_elevation, sun_azimuth, tilt, surface_azimuth):
    """
    Einfallswinkel der Sonne auf eine geneigte Fläche.
    
    Args:
        sun_elevation: Sonnenhöhe (°, 0°=Horizont)
        sun_azimuth: Sonnenazimut (°, 0°=Süd, +=West)
        tilt: Modulneigung (°, 0°=horizontal, 90°=vertikal)
        surface_azimuth: Flächenazimut (°, 0°=Süd, +=West)
    
    Returns:
        Einfallswinkel θ in Grad (0°=senkrecht, 90°=streifend)
    """
    sun_zen_rad = math.radians(90 - sun_elevation)
    tilt_rad = math.radians(tilt)
    delta_az_rad = math.radians(sun_azimuth - surface_azimuth)
    
    cos_aoi = (math.cos(sun_zen_rad) * math.cos(tilt_rad)
               + math.sin(sun_zen_rad) * math.sin(tilt_rad) * math.cos(delta_az_rad))
    
    cos_aoi = max(-1.0, min(1.0, cos_aoi))
    return math.degrees(math.acos(cos_aoi))


def gti_from_components(dni, dhi, ghi, sun_elevation, sun_azimuth,
                        tilt, surface_azimuth):
    """
    Berechne Global Tilted Irradiance auf geneigter Fläche.
    
    Modell: Isotropes Diffusstrahlungsmodell (Liu & Jordan, 1963)
            + anisotrope Korrektur nach Klucher (1979) für Klarheitsfaktor
            + Bodenreflexion
    
    Args:
        dni: Direct Normal Irradiance (W/m²)
        dhi: Diffuse Horizontal Irradiance (W/m²)
        ghi: Global Horizontal Irradiance (W/m²)
        sun_elevation, sun_azimuth: Sonnenposition (°)
        tilt: Modulneigung (°)
        surface_azimuth: Flächenazimut (°, 0°=Süd)
    
    Returns:
        GTI in W/m²
    """
    if sun_elevation <= 0 or ghi <= 0:
        return 0.0
    
    tilt_rad = math.radians(tilt)
    
    # 1. Direktstrahlung auf geneigte Fläche
    aoi = angle_of_incidence(sun_elevation, sun_azimuth, tilt, surface_azimuth)
    if aoi >= 90:
        b_tilted = 0.0   # Rückseite der Fläche → kein Direktanteil
    else:
        b_tilted = max(0.0, dni * math.cos(math.radians(aoi)))
    
    # 2. Diffusstrahlung (Klucher-Modell, besser als rein isotrop)
    # Klarheitsindex F = 1 - (DHI/GHI)²
    if ghi > 0 and dhi >= 0:
        f_clarity = 1.0 - (dhi / ghi) ** 2
        f_clarity = max(0.0, min(1.0, f_clarity))
    else:
        f_clarity = 0.0
    
    # Isotroper Anteil
    d_iso = dhi * (1 + math.cos(tilt_rad)) / 2
    
    # Klucher-Anpassung: zusätzlicher Beitrag bei klarem Himmel
    sin_elev = math.sin(math.radians(sun_elevation))
    if aoi < 90 and sin_elev > 0:
        cos_aoi = math.cos(math.radians(aoi))
        sin_half_tilt = math.sin(tilt_rad / 2)
        klucher_factor = (1 + f_clarity * sin_half_tilt ** 3) * \
                         (1 + f_clarity * cos_aoi ** 2 * (1 / sin_elev - 1) * \
                          max(0, math.cos(math.radians(aoi))))
        # Begrenze den Faktor auf vernünftige Werte
        klucher_factor = max(1.0, min(2.5, klucher_factor))
    else:
        klucher_factor = 1.0
    
    d_tilted = d_iso * klucher_factor
    
    # 3. Bodenreflexion (isotrop)
    r_tilted = ghi * GROUND_ALBEDO * (1 - math.cos(tilt_rad)) / 2
    
    return max(0.0, b_tilted + d_tilted + r_tilted)


# ═══════════════════════════════════════════════════════════════
# CLEAR-SKY-MODELL (Ineichen-Perez vereinfacht / Meinel)
# ═══════════════════════════════════════════════════════════════

def clear_sky_irradiance(sun_elevation, elevation_m=ELEVATION):
    """
    Clear-Sky-Strahlung nach Meinel & Meinel mit Höhenkorrektur.
    
    Berechnet GHI, DNI und DHI bei wolkenlosem Himmel.
    Genauigkeit: ±5-10% gegenüber gemessenen Clear-Sky-Werten.
    
    Args:
        sun_elevation: Sonnenhöhe (°)
        elevation_m: Standorthöhe (m NN)
    
    Returns:
        (ghi, dni, dhi) in W/m²
    """
    if sun_elevation <= 0:
        return 0.0, 0.0, 0.0
    
    # Air Mass (Kasten & Young, 1989)
    zenith = 90.0 - sun_elevation
    if zenith < 87:
        zenith_rad = math.radians(zenith)
        am = 1.0 / (math.cos(zenith_rad) + 0.50572 * (96.07995 - zenith) ** (-1.6364))
    else:
        am = 40.0   # Grenzwert bei Horizontnähe
    
    # Höhenkorrektur: dünnere Atmosphäre bei 315m
    pressure_ratio = math.exp(-elevation_m / 8500)
    am_corrected = am * pressure_ratio
    
    # DNI: Meinel-Modell
    # Atmosphärische Transmission τ bei AM=1 (aus geometry_config.json)
    dni = SOLAR_CONSTANT * ATMOSPHERIC_TURBIDITY ** (am_corrected ** 0.678)
    
    # Begrenze bei sehr niedrigem Sonnenstand
    if sun_elevation < 2:
        dni *= sun_elevation / 2.0
    
    sin_elev = math.sin(math.radians(sun_elevation))
    
    # DHI: Empirisch, Koeffizient aus geometry_config.json
    # bei klarem Himmel (diffus: Rayleigh-Streuung + Aerosole)
    dhi = DHI_COEFFICIENT * SOLAR_CONSTANT * sin_elev * pressure_ratio ** 0.5
    
    # GHI = DNI × sin(elevation) + DHI
    ghi = dni * sin_elev + dhi
    
    return round(ghi, 1), round(dni, 1), round(dhi, 1)


# ═══════════════════════════════════════════════════════════════
# PV-ANLAGE: STRING-WEISE LEISTUNG
# ═══════════════════════════════════════════════════════════════

def string_power_w(dni, dhi, ghi, sun_elevation, sun_azimuth,
                   string_config, temp_c=25):
    """
    DC-Leistung eines PV-Strings in Watt.
    
    Args:
        dni, dhi, ghi: Strahlungskomponenten (W/m²)
        sun_elevation, sun_azimuth: Sonnenposition (°)
        string_config: dict mit 'kwp', 'tilt', 'azimuth'
        temp_c: Zelltemperatur (°C)
    
    Returns:
        DC-Leistung in Watt
    """
    gti = gti_from_components(dni, dhi, ghi, sun_elevation, sun_azimuth,
                               string_config['tilt'], string_config['azimuth'])
    if gti <= 0:
        return 0.0
    
    # Nennleistung bei STC (1000 W/m²)
    kwp = string_config['kwp']
    
    # Temperaturkoeffizient
    temp_factor = 1 + TEMP_COEFF * (temp_c - 25)
    temp_factor = max(0.70, min(1.10, temp_factor))
    
    # DC-Leistung = kWp × (GTI/1000) × PR × Temp-Korrektur × String-Faktor
    string_factor = STRING_FACTORS.get(string_config.get('name', ''), 1.0)
    optimizer_gain = OPTIMIZER_GAIN.get(string_config.get('name', ''), 1.0)
    power_w = kwp * 1000 * (gti / 1000.0) * PERFORMANCE_RATIO * temp_factor
    power_w = power_w * string_factor * optimizer_gain
    
    return max(0.0, power_w)


def plant_power_w(dni, dhi, ghi, sun_elevation, sun_azimuth, temp_c=25):
    """
    Gesamtleistung der PV-Anlage (DC → AC mit Inverter-Clipping).
    
    Returns:
        dict mit:
          'total_ac': Gesamt-AC-Leistung (W), nach Inverter-Clipping
          'total_dc': Gesamt-DC-Leistung (W), vor Clipping
          'strings': {name: dc_watts} pro String
          'inverters': {name: {'dc': W, 'ac': W, 'clipped': bool}}
    """
    strings = {}
    inverters = {}
    
    for s in PV_STRINGS:
        # Azimut-Offset anwenden (Gebäuseausrichtung-Korrektur)
        s_adj = s
        if AZIMUTH_OFFSET != 0.0:
            s_adj = dict(s)
            s_adj['azimuth'] = s['azimuth'] + AZIMUTH_OFFSET
        p_dc = string_power_w(dni, dhi, ghi, sun_elevation, sun_azimuth, s_adj, temp_c)
        strings[s['name']] = p_dc
        
        inv = s['inverter']
        if inv not in inverters:
            inverters[inv] = {'dc': 0.0, 'ac': 0.0, 'clipped': False}
        inverters[inv]['dc'] += p_dc
    
    # Inverter-Clipping (AC-Begrenzung) + Wechselrichter-Wirkungsgrad
    total_ac = 0.0
    for inv, data in inverters.items():
        limit = INVERTER_LIMITS.get(inv, 99999)
        inv_eff = INVERTER_EFFICIENCY.get(inv, 1.0)
        if data['dc'] > limit:
            data['ac'] = float(limit) * inv_eff
            data['clipped'] = True
        else:
            data['ac'] = data['dc'] * inv_eff
        total_ac += data['ac']
    
    total_dc = sum(strings.values())
    
    return {
        'total_ac': round(total_ac, 1),
        'total_dc': round(total_dc, 1),
        'strings': {k: round(v, 1) for k, v in strings.items()},
        'inverters': {k: {kk: round(vv, 1) if isinstance(vv, float) else vv
                          for kk, vv in v.items()}
                      for k, v in inverters.items()},
    }


def _clearsky_power_at(dt_local, temp_c=25):
    """Berechnet Clear-Sky-Leistung für einen lokalen Zeitpunkt.
    
    Returns:
        (elev, az, ghi, power_dict) — power_dict ist None wenn Sonne unter Horizont
    """
    dt_utc = local_to_utc(dt_local)
    elev, az = sun_position(dt_utc)
    if elev <= 0:
        return elev, az, 0.0, None
    ghi, dni, dhi = clear_sky_irradiance(elev)
    power = plant_power_w(dni, dhi, ghi, elev, az, temp_c)
    return elev, az, ghi, power


# ═══════════════════════════════════════════════════════════════
# STÜNDLICHE PROGNOSE AUS WETTERDATEN
# ═══════════════════════════════════════════════════════════════

def _estimate_hourly_power_legacy(hourly_forecast_data):
    """Legacy-Pfad ohne pvlib (bleibt als Fallback erhalten)."""
    results = []

    for h in hourly_forecast_data:
        dt_str = h.get('time', '')

        try:
            dt_end = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M')
            dt_mid = dt_end - timedelta(minutes=30)
            dt_local = dt_mid
        except (ValueError, TypeError):
            continue

        dt_utc = local_to_utc(dt_local)
        elev, az = sun_position(dt_utc)

        report_time = dt_mid.strftime('%Y-%m-%dT%H:%M')

        if elev <= 0:
            results.append({
                'time': report_time,
                'total_ac': 0.0,
                'total_dc': 0.0,
                'strings': {},
                'sun_elevation': round(elev, 1),
                'sun_azimuth': round(az, 1),
                'ghi': 0, 'dni': 0, 'dhi': 0,
                'cloud_cover': h.get('cloud_cover', 0),
            })
            continue

        ghi = h.get('ghi', 0) or 0
        dni = h.get('dni', 0) or 0
        dhi = h.get('diffuse', 0) or 0
        temp = h.get('temp', 25) or 25

        if dni <= 0 < ghi and elev > 2:
            sin_elev = math.sin(math.radians(elev))
            if dhi > 0:
                dni = max(0, (ghi - dhi) / sin_elev) if sin_elev > 0.05 else 0
            else:
                dhi = ghi * 0.40
                dni = max(0, (ghi - dhi) / sin_elev) if sin_elev > 0.05 else 0

        power = plant_power_w(dni, dhi, ghi, elev, az, temp)

        month = dt_local.month
        seasonal = 1.0
        if month in (11, 12, 1, 2):
            seasonal = FORECAST_WINTER_BOOST
        elif month in (5, 6, 7, 8):
            seasonal = FORECAST_SUMMER_FACTOR

        cloud = h.get('cloud_cover', 0) or 0
        cloud_boost = 1.0
        if 20 < cloud < 70:
            cloud_boost = FORECAST_CLOUD_ENHANCEMENT

        adj = FORECAST_GLOBAL_FACTOR * seasonal * cloud_boost
        power['total_ac'] = round(power['total_ac'] * adj, 1)
        power['total_dc'] = round(power['total_dc'] * adj, 1)

        power['time'] = report_time
        power['sun_elevation'] = round(elev, 1)
        power['sun_azimuth'] = round(az, 1)
        power['ghi'] = ghi
        power['dni'] = dni
        power['dhi'] = dhi
        power['cloud_cover'] = cloud
        power['temp'] = temp
        power['adjustment_factor'] = round(adj, 3)

        results.append(power)

    return results


def estimate_hourly_power(hourly_forecast_data):
    """
    PV-Leistungsprognose pro Stunde aus Open-Meteo-Wetterdaten.

    pvlib-basierte Modellkette mit vorkalkulierter Geometrie (Scaffold):
      - Sonnenposition + AOI (statisch)
      - Perez-Transposition (POA)
      - Zelltemperatur (SAPM)
      - Inverter-Clipping
    """
    if not HAS_PVLIB:
        LOG.warning("pvlib nicht verfuegbar — Fallback auf Legacy-Implementierung")
        return _estimate_hourly_power_legacy(hourly_forecast_data)

    if not hourly_forecast_data:
        return []

    df = pd.DataFrame(hourly_forecast_data)
    if df.empty:
        return []

    times_mid = pd.to_datetime(df['time']) - pd.Timedelta(minutes=30)
    scaffold = GeometryScaffold(times_mid, PV_STRINGS, shading_mask=SHADING_MASK)

    weather = pd.DataFrame(index=scaffold.times)
    weather['ghi'] = df.get('ghi', 0).fillna(0).to_numpy()
    weather['dni'] = df.get('dni', 0).fillna(0).to_numpy()
    weather['dhi'] = df.get('diffuse', 0).fillna(0).to_numpy()
    weather['temp'] = df.get('temp', 25).fillna(25).to_numpy()
    weather['wind'] = df.get('wind', DEFAULT_WIND_SPEED).fillna(DEFAULT_WIND_SPEED).to_numpy()
    weather['cloud_cover'] = df.get('cloud_cover', 0).fillna(0).to_numpy()

    elev = scaffold.solar_position['elevation']
    sin_elev = np.sin(np.deg2rad(elev)).clip(min=0.0)

    dni = weather['dni'].copy()
    dhi = weather['dhi'].copy()
    ghi = weather['ghi'].copy()

    mask = (dni <= 0) & (ghi > 0) & (elev > 2)
    use_dhi = mask & (dhi > 0)
    if use_dhi.any():
        dni.loc[use_dhi] = (ghi[use_dhi] - dhi[use_dhi]) / sin_elev[use_dhi].clip(lower=0.05)

    use_est = mask & (dhi <= 0)
    if use_est.any():
        dhi.loc[use_est] = ghi[use_est] * 0.40
        dni.loc[use_est] = (ghi[use_est] - dhi[use_est]) / sin_elev[use_est].clip(lower=0.05)

    weather['dni'] = dni.clip(lower=0)
    weather['dhi'] = dhi.clip(lower=0)

    strings_dc = scaffold.compute_string_dc_power(weather)
    inverter_ac, inverter_dc, inverter_clipped = scaffold.compute_inverter_power(strings_dc)

    total_dc = strings_dc.sum(axis=1)
    total_ac = sum(inverter_ac.values())

    results = []
    for idx, ts in enumerate(scaffold.times):
        report_time = ts.tz_localize(None).strftime('%Y-%m-%dT%H:%M')
        month = ts.month
        seasonal = 1.0
        if month in (11, 12, 1, 2):
            seasonal = FORECAST_WINTER_BOOST
        elif month in (5, 6, 7, 8):
            seasonal = FORECAST_SUMMER_FACTOR

        cloud = float(weather['cloud_cover'].iloc[idx])
        cloud_boost = 1.0
        if 20 < cloud < 70:
            cloud_boost = FORECAST_CLOUD_ENHANCEMENT

        adj = FORECAST_GLOBAL_FACTOR * seasonal * cloud_boost

        inv_dict = {}
        for inv in inverter_ac:
            inv_dict[inv] = {
                'dc': round(float(inverter_dc[inv].iloc[idx]), 1),
                'ac': round(float(inverter_ac[inv].iloc[idx]), 1),
                'clipped': bool(inverter_clipped[inv].iloc[idx]),
            }

        strings_dict = {
            name: round(float(strings_dc[name].iloc[idx]), 1)
            for name in strings_dc.columns
        }

        results.append({
            'time': report_time,
            'total_ac': round(float(total_ac.iloc[idx]) * adj, 1),
            'total_dc': round(float(total_dc.iloc[idx]) * adj, 1),
            'strings': strings_dict,
            'inverters': inv_dict,
            'sun_elevation': round(float(elev.iloc[idx]), 1),
            'sun_azimuth': round(float(scaffold.solar_position['azimuth'].iloc[idx]), 1),
            'ghi': float(weather['ghi'].iloc[idx]),
            'dni': float(weather['dni'].iloc[idx]),
            'dhi': float(weather['dhi'].iloc[idx]),
            'cloud_cover': cloud,
            'temp': float(weather['temp'].iloc[idx]),
            'wind': float(weather['wind'].iloc[idx]),
            'adjustment_factor': round(adj, 3),
        })

    return results


def estimate_daily_kwh(hourly_power_data):
    """
    Tages-kWh aus stündlicher Leistungsprognose.
    
    Args:
        hourly_power_data: Ergebnis von estimate_hourly_power()
    
    Returns:
        dict mit:
          'total_kwh': Gesamtertrag (kWh)
          'peak_w': Maximale AC-Leistung (W)
          'strings_kwh': {name: kWh} pro String
          'inverters_kwh': {name: kWh} pro Wechselrichter
          'hours_with_sun': Anzahl Stunden mit Ertrag
    """
    total_kwh = 0.0
    peak_w = 0.0
    strings_kwh = {}
    inv_kwh = {}
    hours_with_sun = 0
    
    for hp in hourly_power_data:
        ac = hp.get('total_ac', 0)
        total_kwh += ac / 1000.0   # W → kWh (1h-Intervalle)
        peak_w = max(peak_w, ac)
        if ac > 0:
            hours_with_sun += 1
        
        for name, w in hp.get('strings', {}).items():
            strings_kwh[name] = strings_kwh.get(name, 0) + w / 1000.0
        
        for inv, data in hp.get('inverters', {}).items():
            if isinstance(data, dict):
                inv_kwh[inv] = inv_kwh.get(inv, 0) + data.get('ac', 0) / 1000.0
    
    return {
        'total_kwh': round(total_kwh, 2),
        'peak_w': round(peak_w, 0),
        'strings_kwh': {k: round(v, 2) for k, v in strings_kwh.items()},
        'inverters_kwh': {k: round(v, 2) for k, v in inv_kwh.items()},
        'hours_with_sun': hours_with_sun,
    }


# ═══════════════════════════════════════════════════════════════
# CLEAR-SKY-PROFILTABELLE (365×24)
# ═══════════════════════════════════════════════════════════════

def generate_clear_sky_profile(year=2026, force=False):
    """
    Generiere Clear-Sky-Leistungsprofil für jede Stunde des Jahres.
    
    Ergebnis wird als JSON gecacht (config/clearsky_profile.json).
    Bei 37.59 kWp und 51°N erwarten wir ~45.000 kWh/Jahr clear-sky
    (realer Ertrag ist ~35-45% davon wegen Bewölkung).
    
    Args:
        year: Referenzjahr
        force: True = Cache ignorieren, neu berechnen
    
    Returns:
        dict mit profiles, daily_totals, monthly_totals, annual_kwh
    """
    # Cache prüfen
    cached = _load_json_cache(CLEARSKY_CACHE, version=2,
                              extra_check=lambda d: d.get('year') == year)
    if not force and cached:
        LOG.info(f"Clear-Sky-Profil aus Cache geladen ({cached.get('annual_kwh', '?')} kWh/a)")
        return cached
    
    LOG.info(f"Generiere Clear-Sky-Profil für {year}...")
    
    is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    n_days = 366 if is_leap else 365
    
    profiles = {}
    daily_totals = {}
    monthly_kwh = {}
    
    for doy in range(1, n_days + 1):
        day_dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
        month = day_dt.month
        date_str = day_dt.strftime('%Y-%m-%d')
        
        daily_profile = {}
        day_kwh = 0.0
        day_peak = 0.0
        
        for hour in range(24):
            # Berechne für Mitte der Stunde (xx:30) für bessere Genauigkeit
            dt_local = day_dt.replace(hour=hour, minute=30)
            elev, az, ghi, power = _clearsky_power_at(dt_local)
            
            if power is not None:
                ac_w = power['total_ac']
                
                daily_profile[str(hour)] = {
                    'ac': round(ac_w, 0),
                    'dc': round(power['total_dc'], 0),
                    'elev': round(elev, 1),
                    'az': round(az, 1),
                    'ghi': ghi,
                }
                
                day_kwh += ac_w / 1000.0
                day_peak = max(day_peak, ac_w)
        
        profiles[str(doy)] = daily_profile
        daily_totals[str(doy)] = {
            'kwh': round(day_kwh, 2),
            'peak_w': round(day_peak, 0),
            'date': date_str,
            'month': month,
        }
        
        if month not in monthly_kwh:
            monthly_kwh[month] = {'kwh': 0.0, 'days': 0}
        monthly_kwh[month]['kwh'] += day_kwh
        monthly_kwh[month]['days'] += 1
    
    monthly_totals = {}
    for m, data in monthly_kwh.items():
        monthly_totals[str(m)] = {
            'total_kwh': round(data['kwh'], 1),
            'avg_daily_kwh': round(data['kwh'] / data['days'], 1),
            'days': data['days'],
        }
    
    annual_kwh = sum(d['kwh'] for d in monthly_kwh.values())
    
    result = {
        'version': 2,
        'year': year,
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'elevation': ELEVATION,
        'kwp_total': sum(s['kwp'] for s in PV_STRINGS),
        'n_strings': len(PV_STRINGS),
        'profiles': profiles,
        'daily_totals': daily_totals,
        'monthly_totals': monthly_totals,
        'annual_kwh': round(annual_kwh, 1),
    }
    
    # Cache speichern
    _save_json_cache(CLEARSKY_CACHE, result,
                     f"Clear-Sky-Profil gespeichert: {round(annual_kwh)} kWh/Jahr, "
                     f"Peak: {max(float(d['peak_w']) for d in daily_totals.values()):.0f} W")
    
    return result


# ═══════════════════════════════════════════════════════════════
# NEIGUNGSWINKEL-EFFIZIENZTABELLE
# (Äquivalent zur DGS-Tabelle im Bild, berechnet für 51°N)
# ═══════════════════════════════════════════════════════════════

AZIMUTH_RANGE = list(range(-180, 190, 10))   # -180° bis 180° in 10°-Schritten
TILT_RANGE = list(range(0, 95, 5))           # 0° bis 90° in 5°-Schritten


def compute_efficiency_table(year=2026, force=False):
    """
    Berechne die jährliche Ertrags-Effizienztabelle (Azimut × Neigung).
    
    Zeigt für jede Kombination aus Azimut und Neigung den jährlichen
    Ertrag als Prozent des Optimums (100% = bestmögliche Ausrichtung).
    
    Dies ist die physikalisch korrekte Version der DGS/HTW-Neigungstabelle,
    berechnet für unseren exakten Standort (51°N, 13°E, 315m).
    
    Referenzwerte aus der Standard-Tabelle (Bild) zur Validierung:
      - Horizontal (Tilt=0°):  ~86.8% (alle Azimute)
      - Süd/35°:              ~100%  (Optimum)
      - Süd/90° (Fassade):    ~71%
      - Ost oder West/90°:    ~55%
      - Nord/90°:             ~30%
    
    Args:
        year: Referenzjahr
        force: True = Cache ignorieren
    
    Returns:
        dict mit 'table' (37×19 Array), 'optimal', 'our_strings'
    """
    # Cache prüfen
    cached = _load_json_cache(EFFICIENCY_CACHE, version=2)
    if not force and cached:
        LOG.info("Effizienztabelle aus Cache geladen")
        return cached
    
    LOG.info("Berechne Neigungswinkel-Effizienztabelle (dauert ~30s)...")
    
    is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    n_days = 366 if is_leap else 365
    
    # Deutscher Klima-Diffusanteil aus geometry_config.json
    # (Jahresmittel Mitteldeutschland, berücksichtigt Bewölkung)
    # Die DGS/HTW-Tabelle basiert auf realem Klima, nicht Clear-Sky.
    diffuse_frac = CLIMATE_DIFFUSE_FRACTION
    
    # Phase 1: Stündliche Sonnenposition + klimakorrigierte Strahlung
    sun_data = []   # [(elev, az, ghi, dni, dhi), ...]
    for doy in range(1, n_days + 1):
        day_dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
        for hour in range(5, 21):   # Nur Tageslichtstunden (spart ~60% Rechenzeit)
            dt_local = day_dt.replace(hour=hour, minute=30)
            dt_utc = local_to_utc(dt_local)
            elev, az = sun_position(dt_utc)
            if elev > 0:
                ghi_cs, dni_cs, dhi_cs = clear_sky_irradiance(elev)
                # Klimakorrektur: Diffusanteil auf Konfigurationswert anheben
                dhi_climate = ghi_cs * diffuse_frac
                dni_climate = max(0, (ghi_cs - dhi_climate) / max(0.05, math.sin(math.radians(elev))))
                sun_data.append((elev, az, ghi_cs, dni_climate, dhi_climate))
    
    LOG.info(f"  {len(sun_data)} Sonnenstunden berechnet")
    
    # Phase 2: Für jede Azimut/Tilt-Kombination den Jahresertrag berechnen
    annual_gti = {}
    for az_idx, az in enumerate(AZIMUTH_RANGE):
        for tilt_idx, tilt in enumerate(TILT_RANGE):
            total = 0.0
            for elev, sun_az, ghi, dni, dhi in sun_data:
                total += gti_from_components(dni, dhi, ghi, elev, sun_az, tilt, az)
            annual_gti[(az, tilt)] = total
    
    # Phase 3: Normierung auf Maximum (= 100%)
    max_gti = max(annual_gti.values())
    optimal_az = None
    optimal_tilt = None
    for (az, tilt), val in annual_gti.items():
        if val == max_gti:
            optimal_az = az
            optimal_tilt = tilt
    
    # Tabelle als 2D-Array
    table = []
    for az in AZIMUTH_RANGE:
        row = []
        for tilt in TILT_RANGE:
            pct = round(100.0 * annual_gti[(az, tilt)] / max_gti, 1)
            row.append(pct)
        table.append(row)
    
    # Phase 4: Unsere Strings bewerten
    our_strings = []
    for s in PV_STRINGS:
        total = 0.0
        for elev, sun_az, ghi, dni, dhi in sun_data:
            total += gti_from_components(dni, dhi, ghi, elev, sun_az,
                                          s['tilt'], s['azimuth'])
        pct = round(100.0 * total / max_gti, 1)
        our_strings.append({
            'name': s['name'],
            'kwp': s['kwp'],
            'tilt': s['tilt'],
            'azimuth': s['azimuth'],
            'efficiency_pct': pct,
            'effective_kwp': round(s['kwp'] * pct / 100, 2),
        })
    
    # Gewichteter Durchschnitt
    total_eff_kwp = sum(s['effective_kwp'] for s in our_strings)
    total_kwp = sum(s['kwp'] for s in PV_STRINGS)
    weighted_efficiency = round(100 * total_eff_kwp / total_kwp, 1)
    
    result = {
        'version': 2,
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'year': year,
        'azimuth_range': AZIMUTH_RANGE,
        'tilt_range': TILT_RANGE,
        'table': table,
        'optimal': {
            'azimuth': optimal_az,
            'tilt': optimal_tilt,
            'description': f"Optimum bei Azimut {optimal_az}° / Neigung {optimal_tilt}°"
        },
        'our_strings': our_strings,
        'plant_weighted_efficiency': weighted_efficiency,
        'reference_validation': {
            'horizontal_tilt0': table[AZIMUTH_RANGE.index(0)][TILT_RANGE.index(0)],
            'south_35': table[AZIMUTH_RANGE.index(0)][TILT_RANGE.index(35)],
            'south_90': table[AZIMUTH_RANGE.index(0)][TILT_RANGE.index(90)],
            'east_90': table[AZIMUTH_RANGE.index(-90)][TILT_RANGE.index(90)],
            'west_90': table[AZIMUTH_RANGE.index(90)][TILT_RANGE.index(90)],
            'north_90': table[AZIMUTH_RANGE.index(180)][TILT_RANGE.index(90)],
            'expected_horizontal': '~86-87%',
            'expected_south35': '~100%',
            'expected_south90': '~70-72%',
            'expected_east90': '~54-56%',
            'expected_west90': '~54-56%',
            'expected_north90': '~30%',
        },
    }
    
    # Cache speichern
    _save_json_cache(EFFICIENCY_CACHE, result,
                     f"Effizienztabelle gespeichert: Optimum={optimal_az}°/{optimal_tilt}°, "
                     f"Anlage={weighted_efficiency}%")
    
    return result


def lookup_efficiency(azimuth, tilt, table_data=None):
    """
    Effizienz (%) für beliebige Azimut/Tilt-Kombination (bilineare Interpolation).
    
    Args:
        azimuth: Flächenazimut (°, 0°=Süd)
        tilt: Modulneigung (°)
        table_data: Vorberechnete Tabelle (oder None → aus Cache laden)
    
    Returns:
        Effizienz in Prozent (0-100)
    """
    if table_data is None:
        table_data = compute_efficiency_table()
    
    table = table_data['table']
    az_range = table_data['azimuth_range']
    tilt_range = table_data['tilt_range']
    
    # Azimut normalisieren auf [-180, 180]
    az = ((azimuth + 180) % 360) - 180
    tl = max(0, min(90, tilt))
    
    # Indizes für bilineare Interpolation
    az_step = az_range[1] - az_range[0]   # 10°
    tl_step = tilt_range[1] - tilt_range[0]   # 5°
    
    az_frac = (az - az_range[0]) / az_step
    tl_frac = (tl - tilt_range[0]) / tl_step
    
    az_i = int(az_frac)
    tl_i = int(tl_frac)
    az_f = az_frac - az_i
    tl_f = tl_frac - tl_i
    
    # Grenzen
    az_i = max(0, min(az_i, len(az_range) - 2))
    tl_i = max(0, min(tl_i, len(tilt_range) - 2))
    
    # Bilineare Interpolation
    v00 = table[az_i][tl_i]
    v10 = table[az_i + 1][tl_i]
    v01 = table[az_i][tl_i + 1]
    v11 = table[az_i + 1][tl_i + 1]
    
    result = (v00 * (1 - az_f) * (1 - tl_f)
              + v10 * az_f * (1 - tl_f)
              + v01 * (1 - az_f) * tl_f
              + v11 * az_f * tl_f)
    
    return round(result, 1)


# ═══════════════════════════════════════════════════════════════
# CLEAR-SKY-VERGLEICH (für Wetterkorrektur)
# ═══════════════════════════════════════════════════════════════

def get_clearsky_reference(dt_local):
    """
    Clear-Sky-AC-Leistung für einen bestimmten Zeitpunkt (Lokalzeit).
    
    Nützlich für den Vergleich: Ist-Leistung / Clear-Sky = Wolkenfaktor
    
    Returns:
        dict mit total_ac, strings, sun_elevation, sun_azimuth, ghi
    """
    elev, az, ghi, power = _clearsky_power_at(dt_local)
    
    if power is None:
        return {
            'total_ac': 0, 'sun_elevation': round(elev, 1),
            'sun_azimuth': round(az, 1), 'ghi': 0, 'is_day': False
        }
    power['sun_elevation'] = round(elev, 1)
    power['sun_azimuth'] = round(az, 1)
    power['ghi'] = ghi
    power['is_day'] = True
    
    return power


def get_clearsky_day_curve(target_date, interval_min=1):
    """
    Clear-Sky-Leistungskurve für einen ganzen Tag.
    
    Erzeugt eine hochauflösende Referenzkurve (AC-Leistung) unter der
    Annahme von wolkenlosem Himmel. Ideal zum Unterlegen unter Realdaten.
    
    Args:
        target_date: date-Objekt oder 'YYYY-MM-DD'
        interval_min: Zeitauflösung in Minuten (1 = Minutenwerte)
    
    Returns:
        list von dicts mit:
          'timestamp': Unix-Timestamp
          'total_ac': AC-Leistung (W) bei Clear Sky
          'total_dc': DC-Leistung (W)
          'sun_elevation': Sonnenhöhe (°)
          'ghi': Clear-Sky GHI (W/m²)
          'strings': {name: W} pro String
    """
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    
    import time as _time
    
    results = []
    # Tageslichtbereich: 5:00 bis 22:00 (UTC+1/+2 → genug Marge)
    dt_start = datetime(target_date.year, target_date.month, target_date.day, 5, 0)
    dt_end = datetime(target_date.year, target_date.month, target_date.day, 21, 30)
    
    step = timedelta(minutes=interval_min)
    dt = dt_start
    
    while dt <= dt_end:
        # Saisonale Modultemperatur statt pauschal 25°C
        module_temp = CLEARSKY_TEMP_BY_MONTH.get(target_date.month, 25)
        elev, az, ghi, power = _clearsky_power_at(dt, module_temp)
        
        ts = int(_time.mktime(dt.timetuple()))
        
        if power is None:
            results.append({
                'timestamp': ts,
                'total_ac': 0.0,
                'total_dc': 0.0,
                'sun_elevation': round(elev, 1),
                'ghi': 0,
            })
        else:
            results.append({
                'timestamp': ts,
                'total_ac': power['total_ac'],
                'total_dc': power['total_dc'],
                'sun_elevation': round(elev, 1),
                'sun_azimuth': round(az, 1),
                'ghi': ghi,
                'strings': power.get('strings', {}),
            })
        
        dt += step
    
    return results


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _format_table_row(values, widths):
    """Formatiere eine Tabellenzeile."""
    return ' '.join(f'{v:>{w}}' for v, w in zip(values, widths))


def main():
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    parser = argparse.ArgumentParser(description='Solar-Geometrie-Engine für PV-Prognose')
    parser.add_argument('--now', action='store_true',
                        help='Aktuelle Sonnenposition und PV-Leistung (Clear-Sky)')
    parser.add_argument('--today', action='store_true',
                        help='Clear-Sky-Profil für heute (stündlich)')
    parser.add_argument('--date', type=str,
                        help='Clear-Sky-Profil für Datum (YYYY-MM-DD)')
    parser.add_argument('--clearsky', action='store_true',
                        help='Clear-Sky-Jahresprofil generieren/aktualisieren')
    parser.add_argument('--table', action='store_true',
                        help='Neigungswinkel-Effizienztabelle berechnen')
    parser.add_argument('--strings', action='store_true',
                        help='String-Effizienz der Anlage anzeigen')
    parser.add_argument('--force', action='store_true',
                        help='Cache ignorieren, neu berechnen')
    parser.add_argument('--json', action='store_true',
                        help='Ausgabe als JSON')
    parser.add_argument('--config', action='store_true',
                        help='Aktuelle Konfiguration und Parameter anzeigen')
    parser.add_argument('--validate', action='store_true',
                        help='Prognose gegen reale Daten validieren (Nulleinspeiser-tauglich)')
    parser.add_argument('--reload', action='store_true',
                        help='Konfiguration neu laden (nach Änderung)')
    
    args = parser.parse_args()
    
    if args.reload:
        _load_geometry_config()
        print("Konfiguration neu geladen.")
    
    if args.config:
        _cmd_config(args)
    elif args.now:
        _cmd_now(args)
    elif args.today or args.date:
        _cmd_day(args)
    elif args.clearsky:
        _cmd_clearsky(args)
    elif args.table:
        _cmd_table(args)
    elif args.strings:
        _cmd_strings(args)
    elif args.validate:
        _cmd_validate(args)
    else:
        parser.print_help()
        print("\nBeispiele:")
        print("  python3 solar_geometry.py --now")
        print("  python3 solar_geometry.py --today")
        print("  python3 solar_geometry.py --date 2026-06-21")
        print("  python3 solar_geometry.py --clearsky")
        print("  python3 solar_geometry.py --table")
        print("  python3 solar_geometry.py --strings")
        print("  python3 solar_geometry.py --config")


def _cmd_config(args):
    """Aktuelle Konfiguration und alle justierbaren Parameter anzeigen."""
    config_exists = os.path.exists(GEOMETRY_CONFIG_FILE)
    
    print(f"\n⚙️  Solar-Geometrie Konfiguration")
    print(f"   Config-Datei: {GEOMETRY_CONFIG_FILE}")
    print(f"   Status: {'✓ geladen' if config_exists else '✗ nicht vorhanden (Defaults)'}")
    
    print(f"\n   ── System ──────────────────────────────")
    print(f"   Performance Ratio:    {PERFORMANCE_RATIO}")
    print(f"   Temperaturkoeffizient:{TEMP_COEFF} /°C")
    print(f"   Bodenreflexion:       {GROUND_ALBEDO}")
    
    print(f"\n   ── Atmosphäre ──────────────────────────")
    print(f"   Trübungsfaktor τ:     {ATMOSPHERIC_TURBIDITY}")
    print(f"   DHI-Koeffizient:      {DHI_COEFFICIENT}")
    print(f"   Klima-Diffusanteil:   {CLIMATE_DIFFUSE_FRACTION} ({CLIMATE_DIFFUSE_FRACTION*100:.0f}%)")
    
    print(f"\n   ── Prognose-Korrekturen ────────────────")
    print(f"   Global-Faktor:        {FORECAST_GLOBAL_FACTOR}")
    print(f"   Wolkenlinsen-Boost:   {FORECAST_CLOUD_ENHANCEMENT}")
    print(f"   Winter-Boost (Nov-Feb):{FORECAST_WINTER_BOOST}")
    print(f"   Sommer-Faktor (Mai-Aug):{FORECAST_SUMMER_FACTOR}")
    
    print(f"\n   ── String-Korrekturfaktoren ────────────")
    if STRING_FACTORS:
        for name, factor in STRING_FACTORS.items():
            if name.startswith('_'):
                continue
            marker = '' if factor == 1.0 else f'  ← angepasst!'
            print(f"   {name:24s} {factor:.3f}{marker}")
    else:
        print(f"   (keine — alle Strings 1.000)")

    print(f"\n   ── Optimierer-Gain ───────────────────")
    if OPTIMIZER_GAIN:
        for name, gain in OPTIMIZER_GAIN.items():
            if name.startswith('_'):
                continue
            marker = '' if gain == 1.0 else f'  ← angepasst!'
            print(f"   {name:24s} {gain:.3f}{marker}")
    else:
        print(f"   (keine — alle Strings 1.000)")
    
    print(f"\n   ── WR-Wirkungsgrade ────────────────────")
    for inv in sorted(INVERTER_LIMITS.keys()):
        eff = INVERTER_EFFICIENCY.get(inv, 1.0)
        limit = INVERTER_LIMITS[inv]
        print(f"   {inv}: η={eff:.2f}, AC-Limit={limit}W")
    
    print(f"\n   ── Strings ({len(PV_STRINGS)} konfiguriert) ────────")
    total_kwp = sum(s['kwp'] for s in PV_STRINGS)
    for s in PV_STRINGS:
        sf = STRING_FACTORS.get(s['name'], 1.0)
        og = OPTIMIZER_GAIN.get(s['name'], 1.0)
        eff_kwp = s['kwp'] * sf * og
        print(f"   {s['name']:24s} {s['kwp']:.2f} kWp × {sf:.3f} × {og:.3f} = {eff_kwp:.2f} kWp  "
              f"(Az={s['azimuth']:+.1f}° Tilt={s['tilt']}°)")
    print(f"   {'Gesamt':24s} {total_kwp:.2f} kWp")

    print(f"\n   ── Verschattung ───────────────────────")
    if SHADING_MASK:
        print("   Verschattungsmaske: aktiv")
    else:
        print("   Verschattungsmaske: deaktiviert")
    
    print(f"\n   Zum Anpassen: {GEOMETRY_CONFIG_FILE} editieren,")
    print(f"   dann --table --force / --clearsky --force neu generieren.\n")
    
    if args.json:
        data = {
            'config_file': GEOMETRY_CONFIG_FILE,
            'loaded': config_exists,
            'system': {
                'performance_ratio': PERFORMANCE_RATIO,
                'temp_coeff': TEMP_COEFF,
                'ground_albedo': GROUND_ALBEDO,
            },
            'atmosphere': {
                'turbidity': ATMOSPHERIC_TURBIDITY,
                'dhi_coefficient': DHI_COEFFICIENT,
                'climate_diffuse_fraction': CLIMATE_DIFFUSE_FRACTION,
            },
            'forecast_adjustments': {
                'global_factor': FORECAST_GLOBAL_FACTOR,
                'cloud_enhancement': FORECAST_CLOUD_ENHANCEMENT,
                'winter_boost': FORECAST_WINTER_BOOST,
                'summer_factor': FORECAST_SUMMER_FACTOR,
            },
            'string_factors': {k: v for k, v in STRING_FACTORS.items()
                               if not k.startswith('_')},
            'optimizer_gain': {k: v for k, v in OPTIMIZER_GAIN.items()
                               if not k.startswith('_')},
            'inverter_efficiency': dict(INVERTER_EFFICIENCY),
            'shading_mask': SHADING_MASK,
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_now(args):
    """Aktuelle Sonnenposition und Clear-Sky-Leistung."""
    now_local = datetime.now()
    now_utc = local_to_utc(now_local)
    offset = utc_offset_hours(now_local)
    
    elev, az = sun_position(now_utc)
    
    print(f"\n☀️  Sonnenstand — {now_local.strftime('%Y-%m-%d %H:%M')} "
          f"({'CEST' if offset == 2 else 'CET'})")
    print(f"   Standort:  {LATITUDE:.4f}°N  {LONGITUDE:.4f}°E  {ELEVATION}m")
    print(f"   Elevation: {elev:.1f}°")
    print(f"   Azimut:    {az:.1f}° ({'Ost' if az < 0 else 'West' if az > 0 else 'Süd'})")
    
    if elev > 0:
        ghi, dni, dhi = clear_sky_irradiance(elev)
        power = plant_power_w(dni, dhi, ghi, elev, az)
        
        print(f"\n   Clear-Sky-Strahlung:")
        print(f"     GHI: {ghi:.0f} W/m²  (Global Horizontal)")
        print(f"     DNI: {dni:.0f} W/m²  (Direct Normal)")
        print(f"     DHI: {dhi:.0f} W/m²  (Diffuse Horizontal)")
        
        print(f"\n   Clear-Sky-Leistung:")
        print(f"     DC gesamt: {power['total_dc']:.0f} W")
        print(f"     AC gesamt: {power['total_ac']:.0f} W")
        
        print(f"\n   Pro Wechselrichter:")
        for inv, data in sorted(power['inverters'].items()):
            clip = " ⚡CLIPPING" if data.get('clipped') else ""
            print(f"     {inv}: {data['dc']:.0f} W DC → {data['ac']:.0f} W AC{clip}")
        
        print(f"\n   Pro String:")
        for name, w in sorted(power['strings'].items()):
            aoi = "--"
            for s in PV_STRINGS:
                if s['name'] == name:
                    aoi_val = angle_of_incidence(elev, az, s['tilt'], s['azimuth'])
                    aoi = f"{aoi_val:.0f}°"
            print(f"     {name:25s}  {w:7.0f} W  (AOI: {aoi})")
    else:
        print(f"\n   🌙 Sonne unter dem Horizont ({elev:.1f}°)")


def _cmd_day(args):
    """Clear-Sky-Tagesprofil stündlich."""
    if args.date:
        target = datetime.strptime(args.date, '%Y-%m-%d')
    else:
        target = datetime.now()
    
    date_str = target.strftime('%Y-%m-%d')
    print(f"\n☀️  Clear-Sky-Profil — {date_str}")
    print(f"   Standort: {LATITUDE:.4f}°N  {LONGITUDE:.4f}°E  {ELEVATION}m")
    print()
    
    total_kwh = 0
    peak_w = 0
    hours_data = []
    
    for hour in range(24):
        dt_local = target.replace(hour=hour, minute=30)
        elev, az, ghi, power = _clearsky_power_at(dt_local)
        
        if power is not None:
            ac = power['total_ac']
            total_kwh += ac / 1000
            peak_w = max(peak_w, ac)
            
            # String-Details für die 3 Wechselrichter
            f1 = sum(power['strings'].get(s['name'], 0) for s in PV_STRINGS if s['inverter'] == 'F1')
            f2 = sum(power['strings'].get(s['name'], 0) for s in PV_STRINGS if s['inverter'] == 'F2')
            f3 = sum(power['strings'].get(s['name'], 0) for s in PV_STRINGS if s['inverter'] == 'F3')
            
            hours_data.append((hour, elev, az, ghi, ac, f1, f2, f3))
    
    # Tabelle ausgeben
    print(f"  {'Std':>3s}  {'Elev':>5s}  {'Azim':>5s}  {'GHI':>5s}  {'AC-Ges':>7s}  "
          f"{'F1':>6s}  {'F2':>6s}  {'F3':>6s}")
    print(f"  {'':>3s}  {'(°)':>5s}  {'(°)':>5s}  {'W/m²':>5s}  {'(W)':>7s}  "
          f"{'(W)':>6s}  {'(W)':>6s}  {'(W)':>6s}")
    print("  " + "─" * 56)
    
    for h, elev, az, ghi, ac, f1, f2, f3 in hours_data:
        az_dir = 'O' if az < -45 else ('W' if az > 45 else 'S')
        print(f"  {h:2d}:30  {elev:5.1f}  {az:+5.1f}{az_dir}  {ghi:5.0f}  {ac:7.0f}  "
              f"{f1:6.0f}  {f2:6.0f}  {f3:6.0f}")
    
    print("  " + "─" * 56)
    print(f"  Tagesertrag (Clear-Sky): {total_kwh:.1f} kWh")
    print(f"  Spitzenleistung:         {peak_w:.0f} W")
    
    if args.json:
        import json
        print(json.dumps({'date': date_str, 'kwh': round(total_kwh, 2),
                          'peak_w': round(peak_w, 0), 'hours': hours_data}, indent=2))


def _cmd_clearsky(args):
    """Clear-Sky-Jahresprofil generieren."""
    result = generate_clear_sky_profile(force=args.force)
    
    print(f"\n☀️  Clear-Sky-Jahresprofil {result['year']}")
    print(f"   Anlage: {result['kwp_total']:.1f} kWp, {result['n_strings']} Strings")
    print(f"   Jahresertrag (Clear-Sky): {result['annual_kwh']:.0f} kWh")
    print()
    
    print(f"  {'Monat':>6s}  {'kWh':>8s}  {'Ø kWh/Tag':>10s}  {'Tage':>5s}")
    print("  " + "─" * 35)
    for m in range(1, 13):
        data = result['monthly_totals'].get(str(m), {})
        print(f"  {m:6d}  {data.get('total_kwh', 0):8.0f}  "
              f"{data.get('avg_daily_kwh', 0):10.1f}  {data.get('days', 0):5d}")
    print("  " + "─" * 35)
    print(f"  {'Gesamt':>6s}  {result['annual_kwh']:8.0f}")


def _cmd_table(args):
    """Neigungswinkel-Effizienztabelle."""
    result = compute_efficiency_table(force=args.force)
    
    print(f"\n📊  Neigungswinkel-Effizienztabelle ({LATITUDE:.1f}°N)")
    print(f"   Optimum: {result['optimal']['description']}")
    print(f"   Anlage (gewichtet): {result['plant_weighted_efficiency']}%")
    print()
    
    # Validierung
    v = result['reference_validation']
    print("   Validierung gegen Referenztabelle:")
    print(f"     Horizontal (0°):   {v['horizontal_tilt0']}%  (erwartet: {v['expected_horizontal']})")
    print(f"     Süd/35°:           {v['south_35']}%  (erwartet: {v['expected_south35']})")
    print(f"     Süd/90° Fassade:   {v['south_90']}%  (erwartet: {v['expected_south90']})")
    print(f"     Ost/90°:           {v['east_90']}%  (erwartet: {v['expected_east90']})")
    print(f"     West/90°:          {v['west_90']}%  (erwartet: {v['expected_west90']})")
    print(f"     Nord/90°:          {v['north_90']}%  (erwartet: {v['expected_north90']})")
    print()
    
    # Kompakte Tabellenausgabe (jede 2. Spalte)
    header = 'Az\\Tilt'
    print(f"  {header:>8s}", end='')
    for t_idx, t in enumerate(TILT_RANGE):
        if t_idx % 2 == 0:
            print(f"  {t:>4d}°", end='')
    print()
    print("  " + "─" * 68)
    
    table = result['table']
    for az_idx, az in enumerate(AZIMUTH_RANGE):
        if az_idx % 2 == 0:   # Jede 2. Zeile
            print(f"  {az:>+5d}°  ", end='')
            for t_idx in range(0, len(TILT_RANGE), 2):
                val = table[az_idx][t_idx]
                print(f"  {val:5.1f}", end='')
            print()
    
    if args.json:
        print(json.dumps(result, indent=1))


def _cmd_strings(args):
    """String-Effizienz der Anlage."""
    result = compute_efficiency_table(force=args.force)
    
    print(f"\n🔋  String-Effizienz — Anlage {sum(s['kwp'] for s in PV_STRINGS):.1f} kWp")
    print(f"   Gewichtete Gesamt-Effizienz: {result['plant_weighted_efficiency']}%")
    print()
    
    print(f"  {'String':25s}  {'kWp':>5s}  {'Tilt':>5s}  {'Azim':>5s}  {'Eff%':>5s}  {'eff.kWp':>7s}")
    print("  " + "─" * 60)
    
    for s in result['our_strings']:
        print(f"  {s['name']:25s}  {s['kwp']:5.2f}  {s['tilt']:4d}°  {s['azimuth']:+5.1f}°  "
              f"{s['efficiency_pct']:5.1f}  {s['effective_kwp']:7.2f}")
    
    total_kwp = sum(s['kwp'] for s in result['our_strings'])
    total_eff = sum(s['effective_kwp'] for s in result['our_strings'])
    print("  " + "─" * 60)
    print(f"  {'Gesamt':25s}  {total_kwp:5.2f}  {'':>5s}  {'':>5s}  "
          f"{result['plant_weighted_efficiency']:5.1f}  {total_eff:7.2f}")


def _cmd_validate(args):
    """
    Validierung gegen reale Produktionsdaten.
    
    Strategie für Nulleinspeiser:
    - Nur Tage verwenden, wo Verbrauch >> Erzeugung (keine Abregelung)
    - Bevorzugt Wintertage (Nov-Feb) oder stark bewölkte Tage
    - Tage mit "runder Sonnenkurve" (keine Lastwechsel-Einbrüche)
    """
    import sqlite3
    
    try:
        db_path = _cfg.DB_PATH  # tmpfs: /dev/shm/fronius_data.db
    except (NameError, AttributeError):
        db_path = os.path.join(BASE_DIR, 'data.db')
    if not os.path.exists(db_path):
        print(f"❌ DB nicht gefunden: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    try:
        # Tage finden, wo Verbrauch > Erzeugung (= keine Abregelung)
        # W_PV_total = tatsächliche PV-Produktion (Wh)
        # W_Consumption_total = Gesamtverbrauch (Wh)
        # Bei Nulleinspeiser: wenn PV < Verbrauch, wurde alles genutzt → kein Clipping
        query = """
            SELECT ts, W_PV_total, W_Consumption_total
            FROM daily_data 
            WHERE ts > strftime('%s', 'now', '-365 days')
              AND W_PV_total > 1000
            ORDER BY ts
        """
        rows = conn.execute(query).fetchall()
        
        if not rows:
            print("❌ Keine daily_data-Einträge gefunden")
            return
        
        # Kategorisiere Tage
        usable_days = []     # Verbrauch > Erzeugung → keine Abregelung
        clipped_days = []    # Erzeugung ≈ Verbrauch → möglicherweise abgeregelt
        
        for ts, wpv, wverbrauch in rows:
            dt = datetime.fromtimestamp(ts)
            kwh_pv = wpv / 1000.0
            kwh_verb = (wverbrauch or 0) / 1000.0
            
            if kwh_verb <= 0:
                continue
            
            ratio = kwh_pv / kwh_verb if kwh_verb > 0 else 999
            month = dt.month
            
            # Nulleinspeiser-Logik:
            # ratio < 0.8 → PV deutlich unter Verbrauch → kaum Abregelung
            # ratio > 0.9 → PV nah am Verbrauch → wahrscheinlich abgeregelt
            if ratio < 0.80:
                clipping = 'nein'
            elif ratio < 0.95:
                clipping = 'wenig'
            else:
                clipping = 'wahrscheinlich'
            
            usable_days.append({
                'date': dt.strftime('%Y-%m-%d'),
                'month': month,
                'kwh_pv': kwh_pv,
                'kwh_verb': kwh_verb,
                'ratio': ratio,
                'clipping': clipping,
                'ts': ts,
            })
        
        # Sortiere: beste Validierungstage zuerst (niedrigstes PV/Verbrauch-Ratio)
        usable_days.sort(key=lambda d: d['ratio'])
        
        # Zeige Ergebnis
        no_clip = [d for d in usable_days if d['clipping'] == 'nein']
        low_clip = [d for d in usable_days if d['clipping'] == 'wenig']
        high_clip = [d for d in usable_days if d['clipping'] == 'wahrscheinlich']
        
        print(f"\n📊  Validierung: Tage-Qualität für Nulleinspeiser")
        print(f"   Gesamt: {len(usable_days)} Tage mit PV > 1 kWh")
        print(f"   ✓ Keine Abregelung (PV/Verbr < 80%): {len(no_clip)} Tage")
        print(f"   ~ Wenig Abregelung (80-95%):          {len(low_clip)} Tage")
        print(f"   ✗ Wahrscheinlich abgeregelt (>95%):   {len(high_clip)} Tage")
        
        # Winter-Validierungstage (Nov-Feb) ohne Abregelung
        winter_good = [d for d in no_clip if d['month'] in (11, 12, 1, 2)]
        
        print(f"\n   ── Winter-Validierungstage (Nov-Feb, keine Abregelung) ──")
        print(f"   {'Datum':>12s}  {'PV kWh':>7s}  {'Verbr.':>7s}  {'Ratio':>6s}  Bewertung")
        print("   " + "─" * 54)
        
        for d in winter_good[:20]:
            marker = '★' if d['ratio'] < 0.5 else '●'
            print(f"   {d['date']:>12s}  {d['kwh_pv']:>6.1f}  {d['kwh_verb']:>6.1f}  "
                  f"{d['ratio']:>5.0%}  {marker} {'ideal' if d['ratio'] < 0.5 else 'gut'}")
        
        if not winter_good:
            # Fallback: zeige alle Tage ohne Clipping
            print("   (Keine reinen Wintertage — zeige beste Tage aller Monate)")
            for d in no_clip[:15]:
                print(f"   {d['date']:>12s}  {d['kwh_pv']:>6.1f}  {d['kwh_verb']:>6.1f}  "
                      f"{d['ratio']:>5.0%}")
        
        # Wenn historische Wetterdaten verfügbar, berechne Geometrie-Prognose
        # für die besten Validierungstage
        print(f"\n   ── Alte Methode (GHI×Faktor) vs. Real (beste {min(10, len(no_clip))} Tage) ──")
        print(f"   {'Datum':>12s}  {'Real':>7s}  {'GHI-F':>7s}  {'Fehler':>7s}  Clip?")
        print("   " + "─" * 50)
        
        errors = []
        try:
            from solar_forecast import SolarForecast
            sf = SolarForecast()
            
            for d in no_clip[:10]:
                dt = datetime.strptime(d['date'], '%Y-%m-%d')
                target = date(dt.year, dt.month, dt.day)
                
                # Historische Wetterdaten holen
                hist = sf.api.fetch_historical(d['date'], d['date'])
                if not hist or 'daily' not in hist:
                    continue
                
                daily = hist['daily']
                if not daily.get('time'):
                    continue
                
                ghi = daily['shortwave_radiation_sum'][0]
                sunshine_s = daily['sunshine_duration'][0]
                if ghi is None:
                    continue
                sunshine_h = sunshine_s / 3600 if sunshine_s else 0
                
                # Alt: GHI×Faktor
                kwh_old = sf.estimate_kwh(ghi, sunshine_hours=sunshine_h,
                                           month=int(d['date'][5:7]))
                
                # Fehlerberechnung
                kwh_real = d['kwh_pv']
                err = kwh_real - kwh_old  # positiv = Real > Prognose (Unterschätzung)
                err_pct = err / kwh_real * 100 if kwh_real > 0 else 0
                
                errors.append({'date': d['date'], 'real': kwh_real, 'old': kwh_old,
                               'err': err, 'err_pct': err_pct})
                
                arrow = '↑' if err > 0 else '↓'
                print(f"   {d['date']:>12s}  {kwh_real:>6.1f}  {kwh_old:>6.1f}  "
                      f"{err_pct:>+5.0f}% {arrow}  {d['clipping']}")
        except Exception as e:
            print(f"   (Wetterdaten nicht verfügbar: {e})")
        
        if errors:
            avg_err = sum(e['err_pct'] for e in errors) / len(errors)
            abs_avg = sum(abs(e['err_pct']) for e in errors) / len(errors)
            print("   " + "─" * 50)
            print(f"   Mittlerer Fehler (GHI×Faktor): {avg_err:+.1f}% "
                  f"({'Unterschätzung' if avg_err > 0 else 'Überschätzung'})")
            print(f"   Mittlerer Absolutfehler:        {abs_avg:.1f}%")
            print(f"\n   Hinweis: Das ist die ALTE Methode (GHI×Multi-Faktor).")
            print(f"   Die neue Geometrie-Methode validiert sich ab jetzt")
            print(f"   Tag für Tag gegen die reale Produktion.")
            print(f"\n   Parameter anpassen: config/geometry_config.json editieren,")
            print(f"   z.B. 'performance_ratio', 'global_factor' oder String-Faktoren.")
    
    except Exception as e:
        print(f"❌ Validierungsfehler: {e}")
    finally:
        conn.close()
    print()


if __name__ == '__main__':
    main()
