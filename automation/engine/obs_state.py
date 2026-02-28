"""
obs_state.py — ObsState-Datenmodell und RAM-DB-Zugriff

Das zentrale Beobachtungsobjekt: Alle Sensordaten des Systems als
typisierter Snapshot.  Wird vom Observer geschrieben, von Engine gelesen.

Daten liegen in /dev/shm/automation_obs.db (SQLite WAL-Modus, tmpfs).
Siehe: doc/AUTOMATION_ARCHITEKTUR.md §4, §10
       doc/BEOBACHTUNGSKONZEPT.md §5
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

LOG = logging.getLogger('obs_state')

# ── RAM-DB Pfad ──────────────────────────────────────────────
RAM_DB_PATH = '/dev/shm/automation_obs.db'
OBS_HISTORY_MAX = 1000  # Ring-Puffer Größe


# ═════════════════════════════════════════════════════════════
# ObsState — Dataclass
# ═════════════════════════════════════════════════════════════

@dataclass
class ObsState:
    """Snapshot aller Systembeobachtungen zu einem Zeitpunkt.

    Felder mit None = Datenquelle noch nicht verfügbar oder Fehler.
    Regeln und Plugins müssen None-sicher sein.
    """

    # ── Zeitstempel ──────────────────────────────────────────
    ts: str = ''                          # ISO-8601

    # ── Erzeuger ─────────────────────────────────────────────
    pv_total_w: Optional[float] = None    # Summe F1+F2+F3 [W]
    pv_f1_w: Optional[float] = None
    pv_f2_w: Optional[float] = None
    pv_f3_w: Optional[float] = None
    pv_today_kwh: Optional[float] = None  # Bisherige PV-Erzeugung heute [kWh]
    forecast_kwh: Optional[float] = None  # Tagesprognose gesamt [kWh]
    forecast_rest_kwh: Optional[float] = None  # Rest-Prognose ab jetzt [kWh]
    pv_vs_forecast_pct: Optional[float] = None # IST/SOLL-Verhältnis [%] (>100 = besser)
    cloud_avg_pct: Optional[float] = None # Wolkenbedeckung Tagesdurchschnitt [%]
    cloud_now_pct: Optional[float] = None # Aktuelle Wolkenbedeckung [%]
    cloud_rest_avg_pct: Optional[float] = None # Wolken-Durchschnitt Resttag [%]

    # ── Speicher ─────────────────────────────────────────────
    batt_soc_pct: Optional[float] = None  # BYD SOC [0–100]
    batt_soh_pct: Optional[float] = None  # BYD SOH [0–100]
    batt_power_w: Optional[float] = None  # positiv=Laden, negativ=Entladen
    batt_temp_c: Optional[float] = None   # Zelltemperatur Mittel [°C]
    batt_temp_max_c: Optional[float] = None  # Zelltemp Maximum [°C]
    batt_temp_min_c: Optional[float] = None  # Zelltemp Minimum [°C]
    soc_min: Optional[int] = None         # Fronius SOC_MIN-Setting [%]
    soc_max: Optional[int] = None         # Fronius SOC_MAX-Setting [%]
    soc_mode: Optional[str] = None        # 'auto' | 'manual'
    storctl_mod: Optional[int] = None     # Modbus StorCtl_Mod (Bitfield)
    charge_rate_pct: Optional[float] = None   # InWRte [%]
    discharge_rate_pct: Optional[float] = None  # OutWRte [%]
    cha_state: Optional[int] = None       # Ladestatus (1=OFF..7=TEST)

    # ── Netz ─────────────────────────────────────────────────
    grid_power_w: Optional[float] = None  # positiv=Bezug, negativ=Einspeisung
    grid_freq_hz: Optional[float] = None
    grid_volt_v: Optional[float] = None

    # ── Verbraucher ──────────────────────────────────────────
    house_load_w: Optional[float] = None  # Hausverbrauch [W]
    ev_power_w: Optional[float] = None    # Wattpilot [W]
    ev_charging: Optional[bool] = None    # WattPilot lädt gerade (car==2)
    ev_eco_mode: Optional[bool] = None   # WattPilot Eco-Modus aktiv (lmo==4)
    ev_state: Optional[str] = None        # 'charging'|'waiting'|'ready'|'disconnected'
    wp_power_w: Optional[float] = None    # WP elektrisch [W] (aus SmartMeter WP)
    wp_active: Optional[bool] = None      # WP läuft gerade (P_WP > Schwelle)
    wp_power_avg30_w: Optional[float] = None  # WP 30-min Mittelwert [W]
    wp_today_kwh: Optional[float] = None  # WP-Verbrauch heute [kWh]
    ev_power_avg30_w: Optional[float] = None  # EV 30-min Mittelwert [W]
    ww_temp_c: Optional[float] = None     # Warmwasserspeicher [°C] — geplant
    heizpatrone_aktiv: bool = False        # Heizstab-Status (vorerst immer False)
    # ── Prognose (Tier-3 Forecast) ────────────────────────
    pv_at_sunrise_1h_w: Optional[float] = None  # Progn. PV-Leistung 1h nach Sunrise [W]
    forecast_quality: Optional[str] = None       # 'gut' | 'mittel' | 'schlecht'
    forecast_ts: Optional[str] = None            # ISO-8601 wann Forecast zuletzt geholt
    clearsky_peak_h: Optional[float] = None      # Clear-Sky-Peak Dezimalstunde
    forecast_power_profile: Optional[list] = None # [{hour, total_ac_w}…] Stundenleistung
    # ── Zeit / Geometrie ─────────────────────────────────────
    sunrise: Optional[float] = None       # Dezimalstunde
    sunset: Optional[float] = None
    is_day: Optional[bool] = None

    # ── Tier-1 Alarm-Flags ───────────────────────────────────
    alarm_batt_temp: bool = False          # True → Batterie-Temp kritisch
    alarm_batt_kritisch: bool = False      # True → SOC < 5%
    alarm_ueberlast: bool = False          # True → Netz > 24 kW
    alarm_uebertemp: bool = False          # True → WW-Speicher > 80°C
    alarm_frost: bool = False              # True → Außentemp < -5°C

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> 'ObsState':
        data = json.loads(json_str)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ═════════════════════════════════════════════════════════════
# RAM-DB Verwaltung
# ═════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    ts          TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    tier1_flags TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS obs_history (
    ts          TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS param_matrix (
    device      TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    loaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_plan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zyklus_id   TEXT NOT NULL,
    ts          TEXT NOT NULL,
    plan_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeat (
    component   TEXT PRIMARY KEY,
    ts          TEXT NOT NULL
);
"""


def init_ram_db(db_path: str = RAM_DB_PATH) -> sqlite3.Connection:
    """Erstelle/öffne RAM-DB mit WAL-Modus und Schema.

    check_same_thread=False: Observer nutzt Threads für Tier-2/3 Collectors,
    die alle auf dieselbe Connection schreiben. Zugriff wird vom Observer
    per Lock serialisiert (_obs_lock).
    """
    conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    LOG.info(f"RAM-DB initialisiert: {db_path}")
    return conn


def write_obs_state(conn: sqlite3.Connection, obs: ObsState):
    """Schreibe aktuellen ObsState in RAM-DB (upsert)."""
    now = obs.ts or datetime.now().isoformat()
    flags = json.dumps({
        k: v for k, v in asdict(obs).items()
        if k.startswith('alarm_') and v
    })
    json_str = obs.to_json()

    conn.execute(
        "INSERT INTO obs_state (id, ts, state_json, tier1_flags) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET ts=?, state_json=?, tier1_flags=?",
        (now, json_str, flags, now, json_str, flags)
    )

    # History Ring-Puffer
    conn.execute(
        "INSERT OR REPLACE INTO obs_history (ts, state_json) VALUES (?, ?)",
        (now, json_str)
    )
    # Alte Einträge kürzen
    conn.execute(
        "DELETE FROM obs_history WHERE ts NOT IN "
        "(SELECT ts FROM obs_history ORDER BY ts DESC LIMIT ?)",
        (OBS_HISTORY_MAX,)
    )

    conn.commit()


def read_obs_state(conn: sqlite3.Connection) -> Optional[ObsState]:
    """Lese aktuellen ObsState aus RAM-DB."""
    row = conn.execute(
        "SELECT state_json FROM obs_state WHERE id = 1"
    ).fetchone()
    if row:
        return ObsState.from_json(row[0])
    return None


def write_heartbeat(conn: sqlite3.Connection, component: str):
    """Heartbeat für Watchdog."""
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO heartbeat (component, ts) VALUES (?, ?) "
        "ON CONFLICT(component) DO UPDATE SET ts=?",
        (component, now, now)
    )
    conn.commit()


def load_param_matrix(conn: sqlite3.Connection, device: str,
                      config_path: str) -> dict:
    """Lade Config-JSON in RAM-DB und gib dict zurück."""
    if not os.path.exists(config_path):
        LOG.warning(f"Config nicht gefunden: {config_path}")
        return {}
    with open(config_path, 'r') as f:
        cfg = json.load(f)
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO param_matrix (device, config_json, loaded_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(device) DO UPDATE SET config_json=?, loaded_at=?",
        (device, json.dumps(cfg), now, json.dumps(cfg), now)
    )
    conn.commit()
    return cfg
