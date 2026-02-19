#!/usr/bin/env python3
"""
Prüft alle relevanten Energie-Counter auf Plausibilität und Resets.

Geprüft werden:
- Inverter + 4 Smartmeter Counter aus raw_data
- BMS-Lifetime-Counter (gegen day_start-Checkpoint)
- Wattpilot Gesamtzähler (gegen day_start-Checkpoint / wattpilot_daily)
"""

import argparse
import json
import sqlite3
import time
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db_utils import get_db_connection

COUNTERS = [
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


def local_day_start(ts_now: int) -> int:
    return int(time.mktime(time.localtime(ts_now)[:3] + (0, 0, 0, 0, 0, -1)))


def fetch_bms_lifetime_wh():
    import requests

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
            "charge_wh": float(charged_ws) / 3600.0,
            "discharge_wh": float(discharged_ws) / 3600.0,
        }
    except Exception:
        return None


def check_raw_monotonic(conn: sqlite3.Connection, start_ts: int):
    c = conn.cursor()
    c.execute(
        f"SELECT ts, {', '.join(COUNTERS)} FROM raw_data WHERE ts >= ? ORDER BY ts ASC",
        (start_ts,),
    )
    rows = c.fetchall()

    result = {k: {"negative_steps": 0, "max_negative_wh": 0.0, "max_positive_step_wh": 0.0} for k in COUNTERS}
    if len(rows) < 2:
        return result, 0

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        cur = rows[i]
        for idx, key in enumerate(COUNTERS, start=1):
            a = prev[idx]
            b = cur[idx]
            if a is None or b is None:
                continue
            delta = b - a
            if delta < 0:
                result[key]["negative_steps"] += 1
                result[key]["max_negative_wh"] = min(result[key]["max_negative_wh"], delta)
            if delta > result[key]["max_positive_step_wh"]:
                result[key]["max_positive_step_wh"] = delta

    return result, len(rows)


def main():
    parser = argparse.ArgumentParser(description="Check energy counters")
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--with-live-bms", action="store_true", help="Optional: aktuelle BMS-Lifetime-Werte live vom Inverter holen")
    args = parser.parse_args()

    now = int(time.time())
    start_ts = now - args.hours * 3600
    day_start = local_day_start(now)

    if not str(config.DB_PATH).startswith('/dev/shm/'):
        raise SystemExit(f"Sicherheitsabbruch: DB_PATH ist nicht tmpfs (/dev/shm): {config.DB_PATH}")

    conn = get_db_connection()
    if not conn:
        raise SystemExit("DB nicht verfügbar")

    report = {
        "timestamp": now,
        "local_time": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "db_path": config.DB_PATH,
        "window_hours": args.hours,
        "mode": "db_only" if not args.with_live_bms else "db_plus_live_bms",
    }

    try:
        monotonic, rows = check_raw_monotonic(conn, start_ts)
        report["raw_data_rows_checked"] = rows
        report["raw_counter_monotonic"] = monotonic

        c = conn.cursor()
        checkpoint = None
        try:
            c.execute(
                """
                SELECT W_Batt_Charge_BMS, W_Batt_Discharge_BMS, W_Wattpilot_Total,
                       W_AC_Inv, W_DC1, W_DC2, W_Exp_Netz, W_Imp_Netz,
                       W_Exp_F2, W_Imp_F2, W_Exp_F3, W_Imp_F3, W_Imp_WP
                FROM energy_checkpoints
                WHERE ts = ? AND checkpoint_type = 'day_start'
                """,
                (day_start,),
            )
            cp = c.fetchone()
            if cp:
                checkpoint = {
                    "bms_charge_wh": cp[0],
                    "bms_discharge_wh": cp[1],
                    "wattpilot_wh": cp[2],
                    "raw": {
                        "W_AC_Inv": cp[3],
                        "W_DC1": cp[4],
                        "W_DC2": cp[5],
                        "W_Exp_Netz": cp[6],
                        "W_Imp_Netz": cp[7],
                        "W_Exp_F2": cp[8],
                        "W_Imp_F2": cp[9],
                        "W_Exp_F3": cp[10],
                        "W_Imp_F3": cp[11],
                        "W_Imp_WP": cp[12],
                    },
                }
        except sqlite3.OperationalError:
            checkpoint = None

        report["day_start_checkpoint"] = checkpoint

        c.execute(
            f"SELECT {', '.join(COUNTERS)} FROM raw_data ORDER BY ts DESC LIMIT 1"
        )
        latest_raw = c.fetchone()
        if latest_raw and checkpoint:
            delta_raw = {}
            for i, key in enumerate(COUNTERS):
                cp_val = checkpoint["raw"].get(key)
                cur_val = latest_raw[i]
                if cp_val is None or cur_val is None:
                    delta_raw[key] = None
                else:
                    delta_raw[key] = round(cur_val - cp_val, 3)
            report["day_delta_from_checkpoint_raw_wh"] = delta_raw

        if args.with_live_bms:
            bms_now = fetch_bms_lifetime_wh()
            if bms_now and checkpoint and checkpoint.get("bms_discharge_wh") is not None:
                report["bms_day_delta_wh"] = {
                    "charge": round(max(0.0, bms_now["charge_wh"] - checkpoint["bms_charge_wh"]), 3)
                    if checkpoint.get("bms_charge_wh") is not None else None,
                    "discharge": round(max(0.0, bms_now["discharge_wh"] - checkpoint["bms_discharge_wh"]), 3),
                }
        else:
            report["bms_day_delta_wh"] = None

        try:
            c.execute("SELECT energy_total_wh FROM wattpilot_readings ORDER BY ts DESC LIMIT 1")
            wp_latest = c.fetchone()
            wp_latest_wh = wp_latest[0] if wp_latest else None
            if checkpoint and checkpoint.get("wattpilot_wh") is not None and wp_latest_wh is not None:
                wp_delta = max(0.0, wp_latest_wh - checkpoint["wattpilot_wh"])
                report["wattpilot_day_delta_wh"] = round(wp_delta, 3)

            c.execute("SELECT energy_wh FROM wattpilot_daily WHERE ts = ?", (day_start,))
            wp_day = c.fetchone()
            if wp_day:
                report["wattpilot_daily_wh"] = round(wp_day[0] or 0.0, 3)
                if "wattpilot_day_delta_wh" in report:
                    report["wattpilot_delta_diff_wh"] = round(
                        abs(report["wattpilot_day_delta_wh"] - (wp_day[0] or 0.0)), 3
                    )
        except sqlite3.OperationalError:
            pass

        severe = []
        for key, stat in monotonic.items():
            if stat["negative_steps"] > 0 and stat["max_negative_wh"] < -5:
                severe.append({"counter": key, "negative_steps": stat["negative_steps"], "max_negative_wh": stat["max_negative_wh"]})
        report["severe_findings"] = severe
        report["ok"] = len(severe) == 0

        print(json.dumps(report, indent=2, ensure_ascii=False))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
