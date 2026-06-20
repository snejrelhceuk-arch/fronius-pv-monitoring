#!/usr/bin/env python3
"""
Synchronisiert die Mai-Rekonstruktion (Wattpilot + Heizpatrone) in die
LIVE-RAM-DB (/dev/shm/fronius_data.db).

Warum nötig:
    Die primäre DB liegt im tmpfs (/dev/shm/fronius_data.db) und wird von
    Web-App und Collector gelesen/geschrieben. Die Disk-Kopie data.db wird
    NUR per Persist (Shutdown / 2-Tage-Backup) aus dem RAM überschrieben.

    Die frühere Wattpilot-Rekonstruktion hatte versehentlich nur die
    Disk-DB beschrieben → in der Web-Ansicht (RAM) unsichtbar, und beim
    nächsten Persist drohte Verlust.

Dieses Skript:
  1. Wattpilot: übernimmt die bestätigten Tageswerte (23./24./25./27.05.)
     aus der Disk-DB in die RAM-DB und dedupliziert den 27.05.
  2. Heizpatrone: rekonstruiert 22.–31.05. aus den Zähler-Sprüngen, die in
     den note-Feldern überlebt haben (Fritz-Zähler-Freeze, siehe
     heizpatrone_reconstruct_may.py).

Danach separat ausführen:
    python3 -m collector.aggregate.statistics       # monthly/yearly neu (RAM)
    sqlite3 /dev/shm/fronius_data.db ".backup data.db"   # RAM -> Disk sichern

Usage:
    python3 scripts/sync_may_reconstruction_to_ram.py          # Dry-Run
    python3 scripts/sync_may_reconstruction_to_ram.py --apply
"""

import os
import re
import sys
import sqlite3
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISK_DB   = os.path.join(REPO_ROOT, 'data.db')
RAM_DB    = '/dev/shm/fronius_data.db'

WATTPILOT_DAYS = [datetime.date(2026, 5, d) for d in (23, 24, 25, 27)]
HP_RANGE_START = datetime.date(2026, 5, 22)
HP_RANGE_END   = datetime.date(2026, 6, 1)   # exklusiv


def _counter_start(note):
    m = re.search(r'(\d+)\D+(\d+)\s*Wh', note or '')
    return int(m.group(1)) if m else None


def _counter_end(note):
    m = re.search(r'(\d+)\D+(\d+)\s*Wh', note or '')
    return int(m.group(2)) if m else None


def copy_wattpilot(ram, apply):
    """Übernimmt bestätigte Wattpilot-Tageswerte aus der Disk-DB in den RAM."""
    disk = sqlite3.connect('file:%s?mode=ro' % DISK_DB, uri=True)
    dc = disk.cursor()
    rc = ram.cursor()

    print('== Wattpilot: Disk -> RAM ==')
    for day in WATTPILOT_DAYS:
        ts0 = int(datetime.datetime.combine(day, datetime.time.min).timestamp())
        ts1 = ts0 + 86400
        # Bestätigte Disk-Zeile mit der höchsten energy_wh (echte Rekonstruktion,
        # nicht die 0-Dublette)
        dc.execute(
            'SELECT ts, energy_wh, energy_start_wh, energy_end_wh, '
            '       max_power_w, charging_hours, sessions '
            'FROM wattpilot_daily WHERE ts >= ? AND ts < ? '
            'ORDER BY energy_wh DESC LIMIT 1',
            (ts0, ts1)
        )
        row = dc.fetchone()
        if not row or (row[1] or 0) <= 0:
            print(f'  {day}: keine bestätigte Disk-Zeile – übersprungen')
            continue

        # Vorhandene RAM-Zeilen dieses Tages anzeigen
        rc.execute('SELECT ts, energy_wh FROM wattpilot_daily WHERE ts >= ? AND ts < ?',
                   (ts0, ts1))
        existing = rc.fetchall()
        print(f'  {day}: RAM alt={[(int(e[0]), e[1]) for e in existing]} -> neu {row[1]:.0f} Wh')

        if apply:
            # Tag deduplizieren: alle Zeilen des Tages löschen, eine saubere setzen
            rc.execute('DELETE FROM wattpilot_daily WHERE ts >= ? AND ts < ?', (ts0, ts1))
            rc.execute(
                'INSERT INTO wattpilot_daily '
                '(ts, energy_wh, energy_start_wh, energy_end_wh, max_power_w, charging_hours, sessions) '
                'VALUES (?,?,?,?,?,?,?)',
                row
            )
    disk.close()


def reconstruct_hp(ram, apply):
    """Rekonstruiert heizpatrone_daily 22.–31.05. aus Zähler-Differenzen (RAM)."""
    rc = ram.cursor()
    ts0 = int(datetime.datetime.combine(HP_RANGE_START, datetime.time.min).timestamp())
    ts1 = int(datetime.datetime.combine(HP_RANGE_END + datetime.timedelta(days=1),
                                        datetime.time.min).timestamp())
    rc.execute('SELECT ts, energy_wh, source, note FROM heizpatrone_daily '
               'WHERE ts >= ? AND ts < ? ORDER BY ts', (ts0, ts1))
    by_day = {}
    for ts, ewh, source, note in rc.fetchall():
        day = datetime.date.fromtimestamp(ts)
        by_day[day] = {'ts': ts, 'energy': ewh, 'source': source,
                       'cstart': _counter_start(note), 'cend': _counter_end(note)}

    print('== Heizpatrone: Interday-Rekonstruktion (RAM) ==')
    total_old = total_new = 0.0
    d = HP_RANGE_START
    while d < HP_RANGE_END:
        nxt = d + datetime.timedelta(days=1)
        cur, nx = by_day.get(d), by_day.get(nxt)
        if not cur or not nx:
            d = nxt; continue
        frozen = (cur['cstart'] is not None and cur['cstart'] == cur['cend'])
        if not frozen:
            print(f'  {d}: OK (Intraday gültig, {cur["energy"]:.0f} Wh) – unverändert')
            d = nxt; continue
        if cur['cstart'] is None or nx['cstart'] is None:
            d = nxt; continue
        new_wh = nx['cstart'] - cur['cstart']
        if new_wh < 0:
            d = nxt; continue
        old = cur['energy'] or 0
        total_old += old; total_new += new_wh
        print(f'  {d}: {old:.0f} -> {new_wh} Wh')
        if apply:
            note = (f'Interday-Rekonstruktion (Fritz-Zähler-Freeze): '
                    f'{cur["cstart"]}->{nx["cstart"]} Wh = {new_wh} Wh; alt={old:.0f}')
            rc.execute(
                "UPDATE heizpatrone_daily SET energy_wh=?, source='counter_interday_recon', "
                "note=?, created_at=strftime('%s','now') WHERE ts=?",
                (float(new_wh), note, cur['ts'])
            )
        d = nxt
    print(f'  Summe: {total_old:.0f} -> {total_new:.0f} Wh (+{total_new-total_old:.0f})')


def main():
    apply = '--apply' in sys.argv
    if not os.path.exists(RAM_DB):
        print(f'FEHLER: RAM-DB {RAM_DB} nicht gefunden.')
        sys.exit(1)

    ram = sqlite3.connect(RAM_DB, timeout=15)
    try:
        copy_wattpilot(ram, apply)
        print()
        reconstruct_hp(ram, apply)
        if apply:
            ram.commit()
            print('\n[OK] RAM-DB aktualisiert.')
            print('Nächste Schritte:')
            print('  python3 -m collector.aggregate.statistics')
            print('  sqlite3 /dev/shm/fronius_data.db ".backup data.db"')
        else:
            print('\n[DRY-RUN] Keine Änderung. Mit --apply ausführen.')
    finally:
        ram.close()


if __name__ == '__main__':
    main()
