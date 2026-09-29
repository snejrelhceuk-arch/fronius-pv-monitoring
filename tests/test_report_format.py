#!/usr/bin/env python3
"""Regressionstest fuer notify/report_format — Autarkie/Eigenverbrauch + Layout.

Prueft die Kennzahl-Berechnung (inkl. Rand-/Nullfaelle) und dass jede Sektion
(Tag/Monat/Jahr/Gesamt) eine Autarkie-Zeile traegt.

Nutzung:
  python3 tests/test_report_format.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from automation.engine.notify import report_format as rf  # noqa: E402


def _sec(e, v, n, i, bl=0.0, be=0.0):
    return {'erzeugung': e, 'verbrauch': v, 'netzbezug': n,
            'einspeisung': i, 'batt_ladung': bl, 'batt_entladung': be}


def test_quote_grund_und_randfaelle():
    # Autarkie = (Verbrauch - Netzbezug) / Verbrauch
    assert rf._quote(30.0 - 6.0, 30.0) == 80.0
    # Nenner 0 -> None (undefiniert)
    assert rf._quote(5.0, 0.0) is None
    # Klemmung 0..100 (Netzbezug > Verbrauch -> negativ -> 0)
    assert rf._quote(-5.0, 10.0) == 0.0
    assert rf._quote(15.0, 10.0) == 100.0
    assert rf._fmt_pct(None) == '—'
    assert rf._fmt_pct(82.4) == '82 %'


def test_bilanz_zeilen_hat_autarkie():
    zeilen = rf._bilanz_zeilen(_sec(45.2, 30.1, 5.3, 20.4, 12.0, 11.5))
    text = '\n'.join(zeilen)
    assert 'Autarkie' in text
    assert 'Eigenverbrauch' in text
    # Nebeneinander mit Schrägstrich
    assert '/' in zeilen[0]
    # (30.1 - 5.3) / 30.1 ~= 82 %
    assert '82 %' in text


def test_tagesbericht_alle_kategorien_mit_autarkie():
    d = {
        'tag': {**_sec(45.2, 30.1, 5.3, 20.4, 12.0, 11.5),
                'datum': '28.09.2026', 'fallback': False,
                'wp_kwh': 8.1, 'hp_kwh': 2.0, 'wattpilot_kwh': 6.5,
                'haushalt_kwh': 13.5, 'stresszeit_pct': 12.3,
                'stress_low': 25, 'stress_high': 75},
        'monat': {**_sec(980.0, 720.0, 180.0, 410.0, 300.0, 290.0),
                  'label': 'September 2026', 'bis': '28.09.'},
        'jahr': {**_sec(8200.0, 6100.0, 1450.0, 3600.0, 2600.0, 2500.0),
                 'label': '2026', 'bis': '28.09.'},
        'gesamt': {**_sec(21000.0, 15000.0, 4000.0, 9000.0, 6600.0, 6400.0),
                   'label': 'seit Inbetriebnahme', 'bis': '28.09.2026'},
    }
    text = rf.tagesbericht(d)
    # Autarkie muss in jeder der vier Kategorien vorkommen.
    assert text.count('Autarkie') == 4


def main() -> int:
    fehler = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'OK  {name}')
            except AssertionError as e:
                fehler += 1
                print(f'FAIL {name}: {e}')
    if fehler:
        print(f'\n{fehler} Test(s) fehlgeschlagen.')
        return 1
    print('\nAlle report_format-Tests gruen.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
