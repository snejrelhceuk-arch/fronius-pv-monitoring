#!/usr/bin/env python3
"""Importiere Heizpatronen-Referenzwerte aus Fritz-Box in die DB.

Quelle: config/heizpatrone_fritz_reference.json
Zieltabellen:
  - heizpatrone_monthly
  - heizpatrone_daily
"""

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import config
from db_utils import get_db_connection

REFERENCE_FILE = os.path.join(PROJECT_ROOT, 'config', 'heizpatrone_fritz_reference.json')


def date_to_daily_ts(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    dt_utc = dt.replace(hour=0, minute=0, second=0, tzinfo=timezone.utc)
    return int(dt_utc.timestamp())


def main():
    with open(REFERENCE_FILE, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)

    source = payload.get('source', 'manual')
    monthly_rows = payload.get('monthly', [])
    daily_rows = payload.get('daily', [])

    conn = get_db_connection()
    cursor = conn.cursor()

    monthly_count = 0
    for entry in monthly_rows:
        cursor.execute(
            """
            INSERT INTO heizpatrone_monthly (year, month, energy_kwh, source, note)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(year, month) DO UPDATE SET
                energy_kwh = excluded.energy_kwh,
                source = excluded.source,
                note = excluded.note,
                created_at = strftime('%s','now')
            """,
            (
                int(entry['year']),
                int(entry['month']),
                float(entry['energy_kwh']),
                source,
                entry.get('note', ''),
            ),
        )
        monthly_count += 1

    daily_count = 0
    for entry in daily_rows:
        ts = date_to_daily_ts(entry['date'])
        cursor.execute(
            """
            INSERT INTO heizpatrone_daily (ts, energy_wh, source, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ts) DO UPDATE SET
                energy_wh = excluded.energy_wh,
                source = excluded.source,
                note = excluded.note,
                created_at = strftime('%s','now')
            """,
            (
                ts,
                round(float(entry['energy_kwh']) * 1000.0, 1),
                source,
                entry.get('note', ''),
            ),
        )
        daily_count += 1

    conn.commit()
    conn.close()

    print(f'Heizpatrone-Import: {monthly_count} Monatswerte, {daily_count} Tageswerte')
    print(f'DB: {config.DB_PATH}')


if __name__ == '__main__':
    main()
