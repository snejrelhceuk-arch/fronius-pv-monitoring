#!/usr/bin/env python3
"""
Erzeugt feste Energie-Checkpoints (insb. day_start) für Counter-basierte Prüfungen.

Quellen:
- raw_data: Inverter-/Smartmeter-Absolute (W_*)
- wattpilot_readings: energy_total_wh
- Fronius BMS API: Lifetime charged/discharged (Ws -> Wh)

Ablage:
- SQLite Tabelle energy_checkpoints (ts + checkpoint_type)
"""

import argparse
import json
import sqlite3
import time
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db_utils import get_db_connection


COUNTER_COLUMNS = [
    "W_AC_Inv",
    "W_DC1",
    "W_DC2",
    "W_Exp_Netz",
    "W_Imp_Netz",
    "W_Exp_F2",
    "W_Imp_F2",
    "W_Exp_F3",
    "W_Imp_F3",
    "W_Imp_WP",
]

EXTRA_COLUMNS = [
    "W_Batt_Charge_BMS",
    "W_Batt_Discharge_BMS",
    "W_Wattpilot_Total",
]


def local_day_start(ts_now: int) -> int:
    return int(time.mktime(time.localtime(ts_now)[:3] + (0, 0, 0, 0, 0, -1)))


def ensure_checkpoint_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS energy_checkpoints (
            ts INTEGER NOT NULL,
            checkpoint_type TEXT NOT NULL,
            W_AC_Inv REAL,
            W_DC1 REAL,
            W_DC2 REAL,
            W_Exp_Netz REAL,
            W_Imp_Netz REAL,
            W_Exp_F2 REAL,
            W_Imp_F2 REAL,
            W_Exp_F3 REAL,
            W_Imp_F3 REAL,
            W_Imp_WP REAL,
            W_Batt_Charge_BMS REAL,
            W_Batt_Discharge_BMS REAL,
            W_Wattpilot_Total REAL,
            source TEXT,
            created_at INTEGER,
            PRIMARY KEY (ts, checkpoint_type)
        )
        """
    )

    table_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(energy_checkpoints)").fetchall()
    }
    col_types = {col: "REAL" for col in COUNTER_COLUMNS + EXTRA_COLUMNS}
    col_types["source"] = "TEXT"
    col_types["created_at"] = "INTEGER"

    for col in COUNTER_COLUMNS + EXTRA_COLUMNS + ["source", "created_at"]:
        if col not in table_cols:
            conn.execute(f"ALTER TABLE energy_checkpoints ADD COLUMN {col} {col_types[col]}")


def fetch_raw_counters_for_day_start(conn: sqlite3.Connection, day_start_ts: int):
    c = conn.cursor()
    c.execute(
        """
        SELECT ts, W_AC_Inv, W_DC1, W_DC2, W_Exp_Netz, W_Imp_Netz,
               W_Exp_F2, W_Imp_F2, W_Exp_F3, W_Imp_F3, W_Imp_WP
        FROM raw_data
        WHERE ts >= ?
        ORDER BY ts ASC
        LIMIT 1
        """,
        (day_start_ts,),
    )
    row = c.fetchone()
    if not row:
        return None
    return {
        "measurement_ts": int(row[0]),
        "W_AC_Inv": row[1],
        "W_DC1": row[2],
        "W_DC2": row[3],
        "W_Exp_Netz": row[4],
        "W_Imp_Netz": row[5],
        "W_Exp_F2": row[6],
        "W_Imp_F2": row[7],
        "W_Exp_F3": row[8],
        "W_Imp_F3": row[9],
        "W_Imp_WP": row[10],
    }


def fetch_wattpilot_day_start(conn: sqlite3.Connection, day_start_ts: int):
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT ts, energy_total_wh
            FROM wattpilot_readings
            WHERE ts >= ?
            ORDER BY ts ASC
            LIMIT 1
            """,
            (day_start_ts,),
        )
        row = c.fetchone()
        if not row:
            return None
        return {"measurement_ts": int(row[0]), "value_wh": row[1]}
    except sqlite3.OperationalError:
        return None


def fetch_bms_lifetime_wh():
    try:
        url = f"http://{config.INVERTER_IP}/components/BatteryManagementSystem/readable"
        resp = requests.get(url, timeout=3)
        if resp.status_code != 200:
            return None
        data = resp.json().get("Body", {}).get("Data", {})
        channels = None
        if isinstance(data, dict):
            for comp in data.values():
                cand = (comp or {}).get("channels", {})
                if cand:
                    channels = cand
                    break
        if not channels:
            return None

        charged_ws = channels.get("BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64")
        discharged_ws = channels.get("BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64")
        if charged_ws is None or discharged_ws is None:
            return None

        return {
            "W_Batt_Charge_BMS": float(charged_ws) / 3600.0,
            "W_Batt_Discharge_BMS": float(discharged_ws) / 3600.0,
        }
    except Exception:
        return None


def upsert_checkpoint(conn: sqlite3.Connection, checkpoint_ts: int, checkpoint_type: str, payload: dict, replace: bool = True):
    cols = ["ts", "checkpoint_type"] + COUNTER_COLUMNS + EXTRA_COLUMNS + ["source", "created_at"]
    values = [
        checkpoint_ts,
        checkpoint_type,
        payload.get("W_AC_Inv"),
        payload.get("W_DC1"),
        payload.get("W_DC2"),
        payload.get("W_Exp_Netz"),
        payload.get("W_Imp_Netz"),
        payload.get("W_Exp_F2"),
        payload.get("W_Imp_F2"),
        payload.get("W_Exp_F3"),
        payload.get("W_Imp_F3"),
        payload.get("W_Imp_WP"),
        payload.get("W_Batt_Charge_BMS"),
        payload.get("W_Batt_Discharge_BMS"),
        payload.get("W_Wattpilot_Total"),
        payload.get("source"),
        int(time.time()),
    ]

    placeholders = ", ".join(["?"] * len(cols))
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    conn.execute(
        f"{verb} INTO energy_checkpoints ({', '.join(cols)}) VALUES ({placeholders})",
        values,
    )


def main():
    parser = argparse.ArgumentParser(description="Capture fixed energy checkpoints")
    parser.add_argument("--type", default="day_start", choices=["day_start", "manual"]) 
    parser.add_argument("--ts", type=int, default=None, help="Unix timestamp for manual checkpoint")
    args = parser.parse_args()

    now = int(time.time())
    checkpoint_ts = args.ts if args.ts is not None else local_day_start(now)

    if not str(config.DB_PATH).startswith('/dev/shm/'):
        raise SystemExit(f"Sicherheitsabbruch: DB_PATH ist nicht tmpfs (/dev/shm): {config.DB_PATH}")

    conn = get_db_connection()
    if not conn:
        raise SystemExit("DB nicht verfügbar")

    try:
        ensure_checkpoint_table(conn)

        if args.type == "day_start":
            raw = fetch_raw_counters_for_day_start(conn, checkpoint_ts)
            if not raw:
                raise SystemExit("Keine raw_data für day_start gefunden")
            payload = dict(raw)
            payload["source"] = "raw_data_first_of_day"

            wp = fetch_wattpilot_day_start(conn, checkpoint_ts)
            if wp and wp.get("value_wh") is not None:
                payload["W_Wattpilot_Total"] = wp["value_wh"]

            bms = fetch_bms_lifetime_wh()
            if bms:
                payload.update(bms)
        else:
            c = conn.cursor()
            c.execute(
                """
                SELECT W_AC_Inv, W_DC1, W_DC2, W_Exp_Netz, W_Imp_Netz,
                       W_Exp_F2, W_Imp_F2, W_Exp_F3, W_Imp_F3, W_Imp_WP
                FROM raw_data ORDER BY ts DESC LIMIT 1
                """
            )
            row = c.fetchone()
            if not row:
                raise SystemExit("Keine raw_data vorhanden")
            payload = {
                "W_AC_Inv": row[0],
                "W_DC1": row[1],
                "W_DC2": row[2],
                "W_Exp_Netz": row[3],
                "W_Imp_Netz": row[4],
                "W_Exp_F2": row[5],
                "W_Imp_F2": row[6],
                "W_Exp_F3": row[7],
                "W_Imp_F3": row[8],
                "W_Imp_WP": row[9],
                "source": "raw_data_latest",
            }
            wp = fetch_wattpilot_day_start(conn, local_day_start(now))
            if wp and wp.get("value_wh") is not None:
                payload["W_Wattpilot_Total"] = wp["value_wh"]
            bms = fetch_bms_lifetime_wh()
            if bms:
                payload.update(bms)

        upsert_checkpoint(conn, checkpoint_ts, args.type, payload, replace=(args.type != 'day_start'))
        conn.commit()

        print(json.dumps({
            "ok": True,
            "db_path": config.DB_PATH,
            "checkpoint_ts": checkpoint_ts,
            "checkpoint_type": args.type,
            "payload": payload,
        }, indent=2, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
