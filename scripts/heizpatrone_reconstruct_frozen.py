#!/usr/bin/env python3
"""
Rekonstruiert eingefrorene Heizpatrone-Tageswerte aus den Zählerständen, die in
den note-Feldern von heizpatrone_daily überlebt haben.

Hintergrund (Fritz-Zähler-Freeze):
    Die Fritz!DECT-Steckdose 'heizpatrone' aktualisiert den Energiezähler
    (energy_total_wh) zeitweise nur ~einmal pro Tag. Die Tagesaggregation bildet
    "MAX − MIN" pro lokalem Tag und erhält dann 0 Wh, obwohl die Heizpatrone lief.
    Die Fritz-Rohdaten werden durch Retention gelöscht, die Tageszählerstände
    bleiben aber als note erhalten:
        "Fritz counter delta (N Messungen, START→END Wh)"

Methode (auto-detect):
    Ein Tag gilt als eingefroren, wenn START == END im note. Sein echter
    Verbrauch ist dann die Differenz zum START-Zählerstand des Folgetags:
        verbrauch(D) = counter_start(D+1) − counter_end(D)
    Das ist robust gegen isolierte Freeze-Tage neben einem NORMALEN Tag: dort
    ist counter_start(D+1) == counter_end(D) (kein unverbuchter Sprung), die
    Differenz wird 0 und der Tag bleibt unangetastet — der normale Folgetag hat
    seinen Verbrauch bereits im Intraday-Delta. Bei echten Freeze-Reihen
    (Mai/Juni) wandert der Zähler nur zwischen den Tagen → Differenz > 0.

    Bereits korrekt aggregierte Tage (Intraday-Delta > 0) und zuvor
    rekonstruierte Einträge (note enthält START→END mit START != END) bleiben
    unangetastet.

    Korrigierte Zeilen erhalten source='counter_interday_recon' und sind dadurch
    vor künftigen Auto-Aggregationsläufen geschützt.

Zieldatenbank: standardmäßig die LIVE-RAM-DB (/dev/shm/fronius_data.db), da diese
für Web-App und Collector autoritativ ist. Mit --disk auf die Disk-Kopie.

Usage:
    python3 scripts/heizpatrone_reconstruct_frozen.py            # Dry-Run (RAM)
    python3 scripts/heizpatrone_reconstruct_frozen.py --apply    # schreibt (RAM)
    python3 scripts/heizpatrone_reconstruct_frozen.py --apply --disk
"""

import os
import re
import sys
import sqlite3
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISK_DB   = os.path.join(REPO_ROOT, 'data.db')
RAM_DB    = '/dev/shm/fronius_data.db'


def _counters(note):
    """Gibt (start, end) Zählerstände aus dem note-Feld zurück, sonst (None, None)."""
    m = re.search(r'(\d+)\D+(\d+)\s*Wh', note or '')
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def reconstruct(db_path, apply):
    conn = sqlite3.connect(db_path, timeout=15)
    c = conn.cursor()
    c.execute('SELECT ts, energy_wh, source, note FROM heizpatrone_daily ORDER BY ts')
    rows = c.fetchall()

    parsed = []
    for ts, ewh, source, note in rows:
        cs, ce = _counters(note)
        parsed.append({'ts': ts, 'energy': ewh, 'source': source,
                       'cstart': cs, 'cend': ce,
                       'day': datetime.date.fromtimestamp(ts)})

    updates = []
    for i, cur in enumerate(parsed):
        frozen = (cur['cstart'] is not None and cur['cstart'] == cur['cend'])
        if not frozen:
            continue
        # Nächsten Tag mit bekanntem START-Zählerstand suchen
        nxt = None
        for j in range(i + 1, len(parsed)):
            if parsed[j]['cstart'] is not None:
                nxt = parsed[j]
                break
        if not nxt:
            continue
        # Nur direkt aufeinanderfolgende Tage rekonstruieren (Lücke wäre verfälschend)
        if (nxt['day'] - cur['day']).days != 1:
            continue
        # Differenz zum START des Folgetags: 0 bei isoliertem Freeze neben
        # Normaltag (kein unverbuchter Sprung), > 0 bei echter Freeze-Reihe.
        new_wh = nxt['cstart'] - cur['cend']
        if new_wh <= 0:
            continue
        updates.append((cur, new_wh, nxt))

    print(f'{"Tag":12} {"alt Wh":>9} {"neu Wh":>9}   Zähler')
    print('-' * 50)
    tot_old = tot_new = 0.0
    for cur, new_wh, nxt in updates:
        old = cur['energy'] or 0
        tot_old += old
        tot_new += new_wh
        print(f'{str(cur["day"]):12} {old:9.0f} {new_wh:9.0f}   {cur["cend"]}->{nxt["cstart"]}')
    print('-' * 50)
    print(f'{"Summe":12} {tot_old:9.0f} {tot_new:9.0f}   (+{tot_new-tot_old:.0f} Wh, {len(updates)} Tage)')

    if not apply:
        print('\n[DRY-RUN] Keine Änderung. Mit --apply ausführen.')
        conn.close()
        return

    for cur, new_wh, nxt in updates:
        note = (f'Interday-Rekonstruktion (Fritz-Zähler-Freeze): '
                f'{cur["cend"]}->{nxt["cstart"]} Wh = {new_wh} Wh; alt={cur["energy"] or 0:.0f}')
        c.execute(
            "UPDATE heizpatrone_daily SET energy_wh=?, source='counter_interday_recon', "
            "note=?, created_at=strftime('%s','now') WHERE ts=?",
            (float(new_wh), note, cur['ts'])
        )
    conn.commit()
    conn.close()
    print(f'\n[OK] {len(updates)} Tage in {db_path} aktualisiert.')


if __name__ == '__main__':
    apply = '--apply' in sys.argv
    db = DISK_DB if '--disk' in sys.argv else RAM_DB
    if not os.path.exists(db):
        print(f'FEHLER: DB {db} nicht gefunden.')
        sys.exit(1)
    print(f'Ziel-DB: {db}')
    reconstruct(db, apply)
