"""
Gemeinsame Hilfsfunktionen für alle Blueprint-Module.

Enthält:
  - get_db_connection(): tmpfs-DB Verbindung
  - get_forecast(): SolarForecast Singleton
  - store_forecast_daily() / get_stored_forecast(): Prognose-Persistierung
  - get_fronius_api(): FroniusReadOnly Singleton (NUR Lesen, ABCD-konform)
  - get_strompreis_fuer_monat(): Strompreis-Delegation
  - Shared State: DB_FILE, ram_db_lock, Caches

ABCD-Rollentrennung:
  B (Web/API) darf NUR lesen — keine Schreiboperationen auf Hardware.
  Die Klasse FroniusReadOnly ist eine BEWUSSTE Code-Duplette aus
  fronius_api.py, reduziert auf reine Lesefähigkeit (kein POST/PUT).
  Siehe: doc/SYSTEM_BRIEFING.md §ABCD
"""
import sqlite3
import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime
from flask import jsonify
import requests
import config
import db_init

# ─── tmpfs-DB ──────────────────────────────────────────────
DB_FILE = config.DB_PATH  # /dev/shm/fronius_data.db

# Lock-Kompatibilität (Relikt, WAL regelt Concurrency)
ram_db_lock = threading.Lock()


def api_error_response(e: Exception, context: str = '') -> tuple:
    """Generische API-Fehlerantwort — loggt Details intern, gibt nur Typ zurück."""
    logging.error(f"API-Fehler{f' ({context})' if context else ''}: {e}", exc_info=True)
    return jsonify({"error": "Interner Serverfehler", "type": type(e).__name__}), 500


def validate_year_month(year, month=None):
    """Validiert year/month-Parameter. Gibt (year, month) oder (None, error_response) zurück."""
    now = datetime.now()
    if year is None:
        year = now.year
    if year < 2020 or year > now.year + 1:
        return None, (jsonify({"error": f"Ungültiges Jahr: {year}"}), 400)
    if month is not None:
        if month < 1 or month > 12:
            return None, (jsonify({"error": f"Ungültiger Monat: {month}"}), 400)
    return (year, month), None


def get_db_connection():
    """Verbindung zur tmpfs-DB (RAM-Dateisystem).

    Delegiert an db_utils.get_db_connection() — einzige kanonische Implementierung.
    Gibt None zurück bei Fehler (Kompatibilität mit bestehenden if-not-conn Checks).
    """
    try:
        from db_utils import get_db_connection as _canonical
        return _canonical()
    except Exception as e:
        logging.error(f"DB-Verbindungsfehler: {e}")
        return None


# ─── Solar-Prognose (Lazy Singleton) ────────────────────
_forecast_instance = None


def get_forecast():
    """Lazy Singleton für SolarForecast."""
    global _forecast_instance
    if _forecast_instance is None:
        try:
            from solar_forecast import SolarForecast
            _forecast_instance = SolarForecast()
            logging.info("SolarForecast initialisiert")
        except Exception as e:
            logging.error(f"SolarForecast Init Fehler: {e}")
            return None
    return _forecast_instance


# ─── Forecast-Persistierung ─────────────────────────────
def ensure_forecast_table():
    """Tabelle anlegen falls nötig (idempotent)."""
    try:
        db_init.ensure_forecast_table()
    except Exception:
        pass


def store_forecast_daily(date_str, fc_response, clearsky_data=None, forecast_method='geometry'):
    """Speichert/aktualisiert Tagesprognose + Clear-Sky in forecast_daily.

    Wird automatisch aufgerufen wenn /api/forecast_tag Daten liefert.
    Args:
        date_str: 'YYYY-MM-DD'
        fc_response: dict mit expected_kwh, quality, weather_text, datapoints, ...
        clearsky_data: dict mit total_kwh, datapoints, ... (optional)
        forecast_method: 'geometry' oder 'ghi_factor'
    """
    import json as _json
    try:
        conn = get_db_connection()
        if not conn:
            return

        # Stündliche Profile als kompaktes JSON
        hourly_json = None
        if fc_response.get('datapoints'):
            hourly_json = _json.dumps([{
                'ts': dp['timestamp'],
                'p': round(dp.get('p_produktion', 0), 1),
                'cc': dp.get('cloud_cover', 0),
                'temp': dp.get('temp', 0),
                'ghi': dp.get('ghi_wm2', 0),
            } for dp in fc_response['datapoints']], separators=(',', ':'))

        clearsky_json = None
        clearsky_kwh = None
        if clearsky_data and clearsky_data.get('datapoints'):
            clearsky_kwh = clearsky_data.get('total_kwh')
            clearsky_json = _json.dumps([{
                'ts': dp['timestamp'],
                'ac': round(dp.get('total_ac', 0), 1),
            } for dp in clearsky_data['datapoints'] if dp.get('total_ac', 0) > 0],
            separators=(',', ':'))

        # Ø Bewölkung aus Prognose-Datapoints
        cloud_avg = None
        if fc_response.get('datapoints'):
            clouds = [dp.get('cloud_cover', 0) for dp in fc_response['datapoints']
                      if dp.get('cloud_cover') is not None]
            if clouds:
                cloud_avg = round(sum(clouds) / len(clouds), 1)

        conn.execute("""
            INSERT OR REPLACE INTO forecast_daily
            (date, expected_kwh, clearsky_kwh, quality, weather_text, weather_code,
             sunrise, sunset, sunshine_hours, temp_min, temp_max,
             cloud_cover_avg, precipitation_mm,
             hourly_profile, clearsky_profile, forecast_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date_str,
            fc_response.get('expected_kwh'),
            clearsky_kwh,
            fc_response.get('quality'),
            fc_response.get('weather_text'),
            fc_response.get('weather_code'),
            fc_response.get('sunrise'),
            fc_response.get('sunset'),
            fc_response.get('sunshine_hours'),
            fc_response.get('temp_min'),
            fc_response.get('temp_max'),
            cloud_avg,
            fc_response.get('precipitation_mm'),
            hourly_json,
            clearsky_json,
            forecast_method,
            time.time(),
        ))
        conn.commit()
        conn.close()
        logging.info(f"Prognose gespeichert: {date_str} → {fc_response.get('expected_kwh', '?')} kWh"
                     f" (CS: {clearsky_kwh or '?'} kWh)")
    except Exception as e:
        logging.warning(f"Forecast-Speicherung fehlgeschlagen: {e}")


def _day_timestamps(date_str, step_seconds):
    day = datetime.strptime(date_str, '%Y-%m-%d')
    start = int(time.mktime(day.timetuple()))
    return [start + i * step_seconds for i in range(int(86400 / step_seconds))]


def _interpolate_series(points, target_ts):
    if not points:
        return []

    points = sorted(points, key=lambda p: p[0])
    result = []
    idx = 0
    min_ts = points[0][0]
    max_ts = points[-1][0]

    for ts in target_ts:
        if ts < min_ts or ts > max_ts:
            result.append((ts, 0.0))
            continue
        while idx + 1 < len(points) and points[idx + 1][0] < ts:
            idx += 1

        if idx + 1 < len(points):
            t0, v0 = points[idx]
            t1, v1 = points[idx + 1]
            if t1 == t0:
                val = v0
            else:
                ratio = (ts - t0) / (t1 - t0)
                ratio = max(0.0, min(1.0, ratio))
                val = v0 + (v1 - v0) * ratio
        else:
            val = points[-1][1]

        result.append((ts, val))

    return result


def store_forecast_15min(date_str, forecast_points, clearsky_points=None):
    """Speichert 15min Forecast/Clear-Sky in data_15min (nur Update vorhandener Rows)."""
    try:
        conn = get_db_connection()
        if not conn:
            return

        try:
            conn.execute("SELECT 1 FROM data_15min LIMIT 1")
        except sqlite3.OperationalError:
            conn.close()
            return

        by_ts = {}
        for ts, p in (forecast_points or []):
            by_ts.setdefault(ts, {})['p_fc'] = p
        for ts, p in (clearsky_points or []):
            by_ts.setdefault(ts, {})['p_cs'] = p

        updates = []
        for ts, vals in by_ts.items():
            p_fc = vals.get('p_fc')
            p_cs = vals.get('p_cs')
            w_fc = (p_fc or 0) * 0.25
            w_cs = (p_cs or 0) * 0.25
            updates.append((p_fc, w_fc, p_cs, w_cs, ts))

        if not updates:
            conn.close()
            return

        conn.executemany("""
            UPDATE data_15min
            SET P_PV_FC_avg = ?,
                W_PV_FC_delta = ?,
                P_PV_CS_avg = ?,
                W_PV_CS_delta = ?
            WHERE ts = ?
        """, updates)
        conn.commit()
        conn.close()
    except Exception as e:
        logging.warning(f"Forecast 15min Speicherung fehlgeschlagen: {e}")


def get_stored_forecast_from_15min(date_str):
    """Lädt gespeicherte 15min Forecast/Clear-Sky und interpoliert auf 5min.

    Gibt None zurück wenn die gespeicherten Daten unvollständig sind
    (z.B. nur Nachtstunden mit 0 W), damit der Fallback auf
    forecast_daily mit vollständigem Tagesprofil greifen kann.
    """
    try:
        conn = get_db_connection()
        if not conn:
            return None

        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT ts, P_PV_FC_avg, P_PV_CS_avg, W_PV_FC_delta, W_PV_CS_delta
            FROM data_15min
            WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
              AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
              AND (P_PV_FC_avg IS NOT NULL OR P_PV_CS_avg IS NOT NULL)
            ORDER BY ts ASC
        """, (date_str, date_str)).fetchall()
        conn.close()

        if not rows:
            return None

        fc_points = [(int(r['ts']), r['P_PV_FC_avg'] or 0) for r in rows if r['P_PV_FC_avg'] is not None]
        cs_points = [(int(r['ts']), r['P_PV_CS_avg'] or 0) for r in rows if r['P_PV_CS_avg'] is not None]

        # ── Qualitätsprüfung: nur verwenden wenn Daten aussagekräftig sind ──
        # Mindestens 20 Forecast-Punkte mit Wert > 0 UND über mind. 5h verteilt
        fc_nonzero = [ts for ts, p in fc_points if p > 0]
        if len(fc_nonzero) < 20:
            logging.debug(f"15min-Prognose {date_str}: nur {len(fc_nonzero)} "
                          f"non-zero Punkte → Fallback auf forecast_daily")
            return None
        fc_span_h = (max(fc_nonzero) - min(fc_nonzero)) / 3600.0
        if fc_span_h < 5.0:
            logging.debug(f"15min-Prognose {date_str}: nur {fc_span_h:.1f}h Abdeckung "
                          f"→ Fallback auf forecast_daily")
            return None

        targets_5m = _day_timestamps(date_str, 300)
        fc_5m = _interpolate_series(fc_points, targets_5m)
        cs_5m = _interpolate_series(cs_points, targets_5m)

        expected_kwh = sum((r['W_PV_FC_delta'] or 0) for r in rows) / 1000.0
        clearsky_kwh = sum((r['W_PV_CS_delta'] or 0) for r in rows) / 1000.0

        result = {
            'date': date_str,
            'forecast': True,
            'stored': True,
            'expected_kwh': round(expected_kwh, 2) if expected_kwh > 0 else None,
            'clearsky_kwh': round(clearsky_kwh, 2) if clearsky_kwh > 0 else None,
            'forecast_method': 'data_15min',
            'datapoints': [
                {
                    'timestamp': ts,
                    'p_produktion': p,
                    'is_forecast': True,
                } for ts, p in fc_5m
            ]
        }

        if cs_5m:
            result['clearsky_datapoints'] = [
                {'timestamp': ts, 'total_ac': p}
                for ts, p in cs_5m
            ]

        return result
    except Exception as e:
        logging.warning(f"Gespeicherte 15min Prognose laden fehlgeschlagen: {e}")
        return None


def get_stored_forecast(date_str):
    """Lädt gespeicherte Prognose aus forecast_daily.

    Returns:
        dict mit forecast + clearsky Daten im API-kompatiblen Format,
        oder None wenn nicht vorhanden.
    """
    import json as _json
    try:
        stored_15min = get_stored_forecast_from_15min(date_str)
        if stored_15min:
            return stored_15min

        conn = get_db_connection()
        if not conn:
            return None

        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM forecast_daily WHERE date = ?", (date_str,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        result = {
            'date': row['date'],
            'forecast': True,
            'stored': True,
            'expected_kwh': row['expected_kwh'],
            'clearsky_kwh': row['clearsky_kwh'],
            'quality': row['quality'],
            'weather_text': row['weather_text'],
            'weather_code': row['weather_code'],
            'sunrise': row['sunrise'],
            'sunset': row['sunset'],
            'sunshine_hours': row['sunshine_hours'],
            'temp_min': row['temp_min'],
            'temp_max': row['temp_max'],
            'cloud_cover_avg': row['cloud_cover_avg'],
            'precipitation_mm': row['precipitation_mm'],
            'forecast_method': row['forecast_method'],
            'actual_kwh': row['actual_kwh'],
        }

        # Stündliche Profile dekodieren
        if row['hourly_profile']:
            raw = _json.loads(row['hourly_profile'])
            result['datapoints'] = [{
                'timestamp': dp['ts'],
                'p_produktion': dp.get('p', 0),
                'cloud_cover': dp.get('cc', 0),
                'temp': dp.get('temp', 0),
                'ghi_wm2': dp.get('ghi', 0),
                'is_forecast': True,
            } for dp in raw]

        if row['clearsky_profile']:
            raw = _json.loads(row['clearsky_profile'])
            result['clearsky_datapoints'] = [{
                'timestamp': dp['ts'],
                'total_ac': dp.get('ac', 0),
            } for dp in raw]

        return result
    except Exception as e:
        logging.warning(f"Gespeicherte Prognose laden fehlgeschlagen: {e}")
        return None


# ─── Fronius Read-Only Client (ABCD: B darf nur lesen) ────────────
#
# BEWUSSTE CODE-DUPLETTE aus fronius_api.py:
# Nur GET-Fähigkeit, kein POST/PUT, keine write()/set_*() Methoden.
# Grund: Rollentrennung B (Web) ↔ C (Automation) — DRY < ABCD.
#
# Wenn die API gehackt wird, kann über diesen Client KEIN Schreibvorgang
# auf dem Wechselrichter ausgelöst werden.
#

# Fronius-Konstanten (dupliziert — absichtlich kein Import von fronius_api)
_FRONIUS_HOST = f"http://{config.INVERTER_IP}"
_FRONIUS_REALM = "Webinterface area"
_FRONIUS_USER = "technician"
_API_BATTERIES = "/api/config/batteries"


def _load_fronius_password_readonly():
    """Passwort laden (identisch mit fronius_api — ABCD-Duplette)."""
    try:
        pw = config.load_secret('FRONIUS_PASS')
    except Exception:
        pw = os.environ.get('FRONIUS_PASS')
    return pw


class _FroniusAuthReadOnly:
    """Fronius Hybrid Digest Auth — NUR GET, kein PUT/POST.

    Dupliziert aus fronius_api.FroniusAuth, reduziert auf Lesezugriff.
    """

    def __init__(self):
        pw = _load_fronius_password_readonly()
        if not pw:
            raise RuntimeError("Kein Fronius-Passwort für Read-Only Client")
        ha1_input = f"{_FRONIUS_USER}:{_FRONIUS_REALM}:{pw}"
        self._ha1 = hashlib.md5(ha1_input.encode()).hexdigest()
        self._nonce = None
        self._nc = 0

    def _get_nonce(self, uri):
        r = requests.get(f"{_FRONIUS_HOST}{uri}", timeout=5)
        match = re.search(r'nonce="([^"]+)"', r.headers.get("X-WWW-Authenticate", ""))
        if not match:
            raise ConnectionError(f"Keine Nonce: HTTP {r.status_code}")
        self._nonce = match.group(1)
        self._nc = 0

    def get(self, uri, retry=True):
        """Authentifizierter GET — einzige erlaubte HTTP-Methode."""
        if not self._nonce:
            self._get_nonce(uri)
        self._nc += 1
        nc = f"{self._nc:08x}"
        cnonce = hashlib.md5(f"{time.time()}:{os.getpid()}".encode()).hexdigest()[:16]
        ha2 = hashlib.sha256(f"GET:{uri}".encode()).hexdigest()
        resp_data = f"{self._ha1}:{self._nonce}:{nc}:{cnonce}:auth:{ha2}"
        response = hashlib.sha256(resp_data.encode()).hexdigest()
        auth = (
            f'Digest username="{_FRONIUS_USER}", realm="{_FRONIUS_REALM}", '
            f'nonce="{self._nonce}", uri="{uri}", response="{response}", '
            f'qop=auth, nc={nc}, cnonce="{cnonce}"'
        )
        r = requests.get(
            f"{_FRONIUS_HOST}{uri}",
            headers={"Authorization": auth},
            timeout=5,
        )
        if r.status_code == 401 and retry:
            self._nonce = None
            return self.get(uri, retry=False)
        return r

    # KEIN put(), KEIN post() — by design (ABCD)


class FroniusReadOnly:
    """Fronius Batterie-Konfiguration — NUR LESEN.

    Dupliziert aus fronius_api.BatteryConfig, aber ohne write()/set_*().
    B-Rolle (Web/API) bekommt ausschließlich diese Klasse.
    """

    def __init__(self):
        self._auth = _FroniusAuthReadOnly()
        self._cache = None
        self._cache_time = 0

    def read(self, force=False):
        """Lese aktuelle Batterie-Konfiguration (HTTP GET)."""
        if not force and self._cache and (time.time() - self._cache_time < 5):
            return self._cache
        r = self._auth.get(_API_BATTERIES)
        if r.status_code != 200:
            raise ConnectionError(
                f"Batterie-Konfiguration nicht lesbar: HTTP {r.status_code}"
            )
        self._cache = r.json()
        self._cache_time = time.time()
        return self._cache

    def get_values(self):
        """Nur die Parameter-Werte (ohne _meta)."""
        data = self.read()
        return {k: v for k, v in data.items() if not k.startswith('_')}

    # KEIN write(), KEIN set_soc_min(), KEIN set_soc_max(),
    # KEIN set_soc_mode(), KEIN set_grid_charge() — by design (ABCD)


# ─── Batterie-API (Lazy Singleton, Read-Only) ──────────────────
_fronius_api_instance = None


def get_fronius_api():
    """Lazy Singleton für Fronius Read-Only Client.

    ABCD: B (Web/API) bekommt FroniusReadOnly — keine Schreibmethoden.
    Schreibzugriff nur über C (Automation Engine) via fronius_api.BatteryConfig.
    """
    global _fronius_api_instance
    if _fronius_api_instance is None:
        try:
            _fronius_api_instance = FroniusReadOnly()
            logging.info("FroniusReadOnly initialisiert (ABCD: nur Lesen)")
        except Exception as e:
            logging.error(f"FroniusReadOnly Init Fehler: {e}")
            return None
    return _fronius_api_instance


# ─── Caches (shared across blueprints) ──────────────────
battery_cache = {'data': None, 'ts': 0}
wattpilot_cache = {'data': None, 'ts': 0}


# ─── Strompreis ─────────────────────────────────────────
def get_strompreis_fuer_monat(year, month):
    """Delegiert an config.get_strompreis() — zentrale Tarif-Tabelle (PRIMAT)."""
    return config.get_strompreis(year, month)
