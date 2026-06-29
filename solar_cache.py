"""
solar_cache.py — SQLite-Cache fuer Solar-Forecast (ForecastCache).

Verbatim aus solar_forecast.py extrahiert (Architektur-Refactor 2026-06-29).
solar_forecast importiert ForecastCache + CACHE_DB von hier (Re-Export; die
Importer von solar_forecast bleiben unveraendert).
"""
import json
import os
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DB = os.path.join(BASE_DIR, 'solar_cache.db')


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
