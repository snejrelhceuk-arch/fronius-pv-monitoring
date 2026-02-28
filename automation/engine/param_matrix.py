"""
param_matrix.py — Parametermatrix-Loader, -Validator und -Display

Lädt config/soc_param_matrix.json, validiert Wertebereiche,
zeigt die Matrix tabellarisch an und stellt Zugriffsfunktionen
für Engine-Regeln bereit.

CLI-Aufruf:
  python3 -m automation.engine.param_matrix              # Anzeigen
  python3 -m automation.engine.param_matrix --validate   # Validieren
  python3 -m automation.engine.param_matrix --json       # JSON-Dump

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §3, §5
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

LOG = logging.getLogger('param_matrix')

DEFAULT_MATRIX_PATH = os.path.join(_PROJECT_ROOT, 'config', 'soc_param_matrix.json')

# Prioritäts-Label und Farben (ANSI)
PRIO_LABELS = {1: 'SICHERHEIT', 2: 'STEUERUNG', 3: 'WARTUNG'}
PRIO_COLORS = {1: '\033[91m', 2: '\033[93m', 3: '\033[94m'}  # rot, gelb, blau
RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'
GREEN = '\033[92m'
RED = '\033[91m'


# ═════════════════════════════════════════════════════════════
# Laden & Validieren
# ═════════════════════════════════════════════════════════════

def lade_matrix(pfad: str = DEFAULT_MATRIX_PATH) -> dict:
    """Lade Parametermatrix aus JSON-Datei."""
    if not os.path.exists(pfad):
        raise FileNotFoundError(f"Parametermatrix nicht gefunden: {pfad}")
    with open(pfad, 'r') as f:
        return json.load(f)


def validiere_matrix(matrix: dict) -> list[str]:
    """Prüfe alle Werte gegen ihre Bereiche. Gibt Liste von Fehlern zurück."""
    fehler = []
    regelkreise = matrix.get('regelkreise', {})

    for rk_name, rk in regelkreise.items():
        if rk_name.startswith('_'):
            continue
        params = rk.get('parameter', {})
        for p_name, p in params.items():
            if p_name.startswith('_'):
                continue
            wert = p.get('wert')
            bereich = p.get('bereich')
            if wert is None:
                fehler.append(f"{rk_name}.{p_name}: Kein Wert definiert")
                continue
            if bereich and len(bereich) == 2:
                lo, hi = bereich
                if not (lo <= wert <= hi):
                    fehler.append(
                        f"{rk_name}.{p_name}: {wert} außerhalb [{lo}..{hi}]"
                    )

    return fehler


def get_regelkreis(matrix: dict, name: str) -> dict:
    """Hole einen Regelkreis nach Name."""
    return matrix.get('regelkreise', {}).get(name, {})


def get_param(matrix: dict, regelkreis: str, param: str, default=None):
    """Hole einen einzelnen Parameter-Wert."""
    rk = get_regelkreis(matrix, regelkreis)
    p = rk.get('parameter', {}).get(param, {})
    return p.get('wert', default)


def ist_aktiv(matrix: dict, regelkreis: str) -> bool:
    """Prüfe ob ein Regelkreis aktiv ist."""
    rk = get_regelkreis(matrix, regelkreis)
    return rk.get('aktiv', False)


def get_score_gewicht(matrix: dict, regelkreis: str) -> int:
    """Hole das Score-Gewicht für Engine-Ranking."""
    rk = get_regelkreis(matrix, regelkreis)
    return rk.get('score_gewicht', 0)


def alle_regelkreise(matrix: dict) -> list[tuple[str, dict]]:
    """Alle Regelkreise sortiert nach Priorität."""
    rks = matrix.get('regelkreise', {})
    items = [(k, v) for k, v in rks.items() if not k.startswith('_')]
    return sorted(items, key=lambda x: x[1].get('prioritaet', 99))


# ═════════════════════════════════════════════════════════════
# CLI-Anzeige
# ═════════════════════════════════════════════════════════════

def _fmt_wert(p: dict) -> str:
    """Wert formatieren mit Einheit."""
    wert = p.get('wert', '?')
    einheit = p.get('einheit', '')
    return f"{wert}{einheit}"


def _fmt_bereich(p: dict) -> str:
    """Bereich formatieren."""
    bereich = p.get('bereich')
    if not bereich or len(bereich) != 2:
        return '—'
    einheit = p.get('einheit', '')
    return f"[{bereich[0]}..{bereich[1]}]{einheit}"


def _in_range(p: dict) -> bool:
    """Prüfe ob Wert im Bereich."""
    wert = p.get('wert')
    bereich = p.get('bereich')
    if wert is None or not bereich or len(bereich) != 2:
        return True
    return bereich[0] <= wert <= bereich[1]


def zeige_matrix(matrix: dict, farbig: bool = True):
    """Zeige die gesamte Parametermatrix tabellarisch an."""

    hw = matrix.get('hardware', {})

    print()
    print(f"{BOLD if farbig else ''}{'═' * 78}")
    print(f"  SOC-PARAMETERMATRIX — BYD HVS {hw.get('kapazitaet_kwh', '?')} kWh ({hw.get('chemie', '?')})")
    print(f"{'═' * 78}{RESET if farbig else ''}")

    for rk_name, rk in alle_regelkreise(matrix):
        prio = rk.get('prioritaet', 0)
        aktiv = rk.get('aktiv', False)
        gewicht = rk.get('score_gewicht', 0)
        zyklus = rk.get('engine_zyklus', '?')
        color = PRIO_COLORS.get(prio, '') if farbig else ''
        prio_label = PRIO_LABELS.get(prio, f'P{prio}')

        status = f"{GREEN}●{RESET}" if (aktiv and farbig) else (
            f"{RED}○{RESET}" if farbig else ('●' if aktiv else '○'))

        print(f"\n{color}{BOLD if farbig else ''}┌─── {rk_name.upper()} "
              f"({prio_label}) "
              f"{'─' * max(0, 50 - len(rk_name) - len(prio_label))}"
              f"{RESET if farbig else ''}")
        print(f"│ {status} {rk.get('beschreibung', '')}")
        print(f"│ Score-Gewicht: {gewicht}   Zyklus: {zyklus}")
        print(f"│")

        # Parameter-Tabelle
        params = rk.get('parameter', {})
        if params:
            # Header
            print(f"│ {'Parameter':<30} {'Wert':>10}  {'Bereich':<20} {'ObsState-Feld':<20}")
            print(f"│ {'─' * 30} {'─' * 10}  {'─' * 20} {'─' * 20}")

            for p_name, p in params.items():
                if p_name.startswith('_'):
                    continue
                wert_str = _fmt_wert(p)
                bereich_str = _fmt_bereich(p)
                obs = p.get('obs_feld', '')
                ok = _in_range(p)

                # Wert-Farbe
                if farbig:
                    wert_color = GREEN if ok else RED
                    wert_display = f"{wert_color}{wert_str:>10}{RESET}"
                else:
                    wert_display = f"{wert_str:>10}"

                aktor = p.get('aktor_kommando', '')
                if aktor:
                    obs_display = f"{obs:<20}" if obs else f"{'→ ' + aktor:<20}"
                else:
                    obs_display = f"{obs:<20}"

                print(f"│ {p_name:<30} {wert_display}  {bereich_str:<20} {obs_display}")

                # Beschreibung (dimmed)
                desc = p.get('beschreibung', '')
                if desc:
                    dim = DIM if farbig else ''
                    rst = RESET if farbig else ''
                    print(f"│   {dim}{desc}{rst}")

        print(f"└{'─' * 77}")

    # Meta
    meta = matrix.get('meta', {})
    if meta:
        print(f"\n{DIM if farbig else ''}Komfort: {meta.get('komfort_bereich', '')}")
        print(f"Stress:  {meta.get('stress_bereich', '')}{RESET if farbig else ''}")
    print()


def zeige_zusammenfassung(matrix: dict, farbig: bool = True):
    """Kompakte Übersicht: Regelkreise mit Status."""
    print(f"\n{BOLD if farbig else ''}SOC-Automation — Regelkreise{RESET if farbig else ''}")
    print(f"{'─' * 60}")

    for rk_name, rk in alle_regelkreise(matrix):
        prio = rk.get('prioritaet', 0)
        aktiv = rk.get('aktiv', False)
        gewicht = rk.get('score_gewicht', 0)
        n_params = len([k for k in rk.get('parameter', {}) if not k.startswith('_')])
        color = PRIO_COLORS.get(prio, '') if farbig else ''

        status = f"{GREEN}AKT{RESET}" if (aktiv and farbig) else (
            f"{RED}AUS{RESET}" if farbig else ('AKT' if aktiv else 'AUS'))

        prio_label = PRIO_LABELS.get(prio, f'P{prio}')
        print(f"  {color}P{prio}{RESET if farbig else ''} "
              f"{status} "
              f"{rk_name:<25} "
              f"Score={gewicht:>3}  "
              f"{n_params} Param  "
              f"{DIM if farbig else ''}{prio_label}{RESET if farbig else ''}")

    fehler = validiere_matrix(matrix)
    if fehler:
        print(f"\n{RED if farbig else ''}⚠ {len(fehler)} Validierungsfehler!{RESET if farbig else ''}")
        for f in fehler:
            print(f"  • {f}")
    else:
        print(f"\n{GREEN if farbig else ''}✓ Alle Werte im gültigen Bereich{RESET if farbig else ''}")


# ═════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='SOC-Parametermatrix — Anzeige und Validierung',
    )
    parser.add_argument('--config', default=DEFAULT_MATRIX_PATH,
                        help='Pfad zur Parametermatrix-JSON')
    parser.add_argument('--validate', action='store_true',
                        help='Nur validieren, nicht anzeigen')
    parser.add_argument('--json', action='store_true',
                        help='Rohe JSON-Ausgabe')
    parser.add_argument('--no-color', action='store_true',
                        help='Keine ANSI-Farben')
    parser.add_argument('--summary', action='store_true',
                        help='Nur Zusammenfassung')
    args = parser.parse_args()

    matrix = lade_matrix(args.config)

    if args.json:
        print(json.dumps(matrix, indent=2, ensure_ascii=False))
        return

    if args.validate:
        fehler = validiere_matrix(matrix)
        if fehler:
            for f in fehler:
                print(f"✗ {f}")
            sys.exit(1)
        else:
            print("✓ Alle Werte im gültigen Bereich")
            sys.exit(0)

    farbig = not args.no_color and sys.stdout.isatty()

    if args.summary:
        zeige_zusammenfassung(matrix, farbig)
    else:
        zeige_matrix(matrix, farbig)
        zeige_zusammenfassung(matrix, farbig)


if __name__ == '__main__':
    main()
