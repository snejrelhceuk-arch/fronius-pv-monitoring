"""gap_accept.py — Bestätigte/akzeptierte Datenlücken (Diagnos, Rolle D).

Vom Betreiber akzeptierte Lücken (rekonstruiert, geprüft oder bewusst
hingenommen) treiben **keine** Diagnos-Warnung mehr. Die Zählerstände bleiben
davon unberührt: Sie werden per Backfill/Rekonstruktion verifiziert; die
Akzeptanz betrifft ausschließlich den Warn-Status der Lücke.

State-Datei: ``config/diagnos_gap_accept.json`` (operator-kuratiert, gitignored).
Schema::

    {
      "accepted": [
        {"table": "raw_data",
         "from": "2026-08-04 00:00:00",   # UTC (YYYY-MM-DD[ HH:MM:SS])
         "to":   "2026-08-04 23:59:59",
         "note": "Collector-Ausfall, aus SolarWeb rekonstruiert",
         "accepted_at": "2026-09-02"}
      ]
    }

``table`` darf ``"*"`` sein (gilt für alle Tabellen). Eine Lücke gilt als
akzeptiert, wenn sie vollständig in einem passenden Fenster liegt.

CLI::

    python3 -m diagnos.gap_accept --list
    python3 -m diagnos.gap_accept --table raw_data --day 2026-08-04 --note "..."
    python3 -m diagnos.gap_accept --table raw_data \
        --from "2026-08-04 01:00:00" --to "2026-08-04 20:43:00" --note "..."
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'diagnos_gap_accept.json',
)


def _parse_utc(s: str) -> float:
    """Parse UTC-Zeit 'YYYY-MM-DD' oder 'YYYY-MM-DD HH:MM:SS' → epoch."""
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    raise ValueError(f"Zeit nicht parsebar: {s!r} (erwartet YYYY-MM-DD[ HH:MM:SS])")


def load_acceptances(path: Optional[str] = None) -> list:
    """Lese die akzeptierten Fenster (ts-normalisiert). Fehlt die Datei → []."""
    p = path or _PATH
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    out = []
    for e in data.get('accepted', []) if isinstance(data, dict) else []:
        try:
            t0 = _parse_utc(str(e['from']))
            t1 = _parse_utc(str(e['to']))
        except (KeyError, ValueError, TypeError):
            continue
        out.append({'table': e.get('table', '*'), 'from_ts': t0, 'to_ts': t1,
                    'note': e.get('note', '')})
    return out


def is_accepted(table: str, start_ts: float, end_ts: float, acceptances: list) -> Optional[dict]:
    """True (das Fenster-Dict), wenn die Lücke vollständig in einem Fenster liegt."""
    for a in acceptances:
        if a['table'] not in (table, '*'):
            continue
        if a['from_ts'] <= start_ts and end_ts <= a['to_ts']:
            return a
    return None


# ── CLI ─────────────────────────────────────────────────────
def _load_raw(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {'accepted': []}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {'accepted': []}


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Diagnos: Datenlücken akzeptieren')
    parser.add_argument('--list', action='store_true', help='Akzeptanzen anzeigen')
    parser.add_argument('--table', help='Tabelle (raw_data, data_1min, … oder *)')
    parser.add_argument('--day', help='Ganzer UTC-Tag YYYY-MM-DD')
    parser.add_argument('--from', dest='von', help='Start UTC YYYY-MM-DD HH:MM:SS')
    parser.add_argument('--to', dest='bis', help='Ende UTC YYYY-MM-DD HH:MM:SS')
    parser.add_argument('--note', default='', help='Begründung')
    args = parser.parse_args(argv)

    data = _load_raw(_PATH)
    data.setdefault('accepted', [])

    if args.list or not (args.table and (args.day or (args.von and args.bis))):
        if not data['accepted']:
            print('Keine akzeptierten Lücken.')
        for e in data['accepted']:
            print(f"  {e.get('table', '*'):12s} {e.get('from')} → {e.get('to')}"
                  f"  {e.get('note', '')}")
        if not args.list:
            print('\nHinzufügen: --table T (--day D | --from F --to T) [--note ...]')
        return 0

    if args.day:
        von, bis = f'{args.day} 00:00:00', f'{args.day} 23:59:59'
    else:
        von, bis = args.von, args.bis
    # Validierung
    _parse_utc(von)
    _parse_utc(bis)

    data['accepted'].append({
        'table': args.table, 'from': von, 'to': bis, 'note': args.note,
        'accepted_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    })
    tmp = _PATH + '.tmp'
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _PATH)
    print(f'Akzeptiert: {args.table} {von} → {bis}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
