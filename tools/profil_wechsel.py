#!/usr/bin/env python3
"""
profil_wechsel.py — Umschaltung zwischen Inbetriebnahme-Profilen

Profile:
  A  Vollbetrieb (Eigenverbrauch Max)
     → SOC-Komfort 25–75%, max 12 kW, alle Raten frei
  B  Konservativ (Einfahren Tag 1)
     → SOC-Komfort 30–70%, max 6 kW (= 1 Tower), Raten frei
  C  Altsystem (vor Umbau)
     → SOC-Komfort 25–75%, 10,24 kWh, 10 kW, Raten aktiv

Verwendung:
  python3 tools/profil_wechsel.py          # Zeigt aktuelles Profil
  python3 tools/profil_wechsel.py A        # Wechsel auf Vollbetrieb
  python3 tools/profil_wechsel.py B        # Wechsel auf Konservativ
"""

import json
import os
import sys
import shutil
from datetime import datetime

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATT_CFG = os.path.join(_PROJECT, 'config', 'battery_control.json')
SOC_MATRIX = os.path.join(_PROJECT, 'config', 'soc_param_matrix.json')

# ══════════════════════════════════════════════════════════════
#  Profil-Definitionen
# ══════════════════════════════════════════════════════════════

PROFILE = {
    'A': {
        'name': 'Vollbetrieb (Eigenverbrauch Max)',
        'beschreibung': 'Volle Kapazität, alle Raten frei, SOC 25–75%',
        'battery_control': {
            'batterie.kapazitaet_kwh': 20.48,
            'batterie.max_lade_w': 12000,
            'batterie.max_entlade_w': 12000,
            'soc_grenzen.komfort_min': 25,
            'soc_grenzen.komfort_max': 75,
        },
        'soc_param_matrix': {
            'regelkreise.abend_entladerate.aktiv': False,
            'regelkreise.laderate_dynamisch.aktiv': False,
        },
    },
    'B': {
        'name': 'Konservativ (Einfahren)',
        'beschreibung': 'Engeres SOC-Fenster 30–70%, max 6 kW (1-Tower-Rate)',
        'battery_control': {
            'batterie.kapazitaet_kwh': 20.48,
            'batterie.max_lade_w': 6000,
            'batterie.max_entlade_w': 6000,
            'soc_grenzen.komfort_min': 30,
            'soc_grenzen.komfort_max': 70,
        },
        'soc_param_matrix': {
            'regelkreise.abend_entladerate.aktiv': False,
            'regelkreise.laderate_dynamisch.aktiv': False,
        },
    },
    'C': {
        'name': 'Altsystem (vor Umbau)',
        'beschreibung': 'Originalkonfiguration: 10,24 kWh, 10 kW, Raten aktiv',
        'battery_control': {
            'batterie.kapazitaet_kwh': 10.24,
            'batterie.max_lade_w': 10240,
            'batterie.max_entlade_w': 10240,
            'soc_grenzen.komfort_min': 25,
            'soc_grenzen.komfort_max': 75,
        },
        'soc_param_matrix': {
            'regelkreise.abend_entladerate.aktiv': True,
            'regelkreise.laderate_dynamisch.aktiv': True,
        },
    },
}


# ══════════════════════════════════════════════════════════════
#  Hilfsfunktionen
# ══════════════════════════════════════════════════════════════

def _load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def _set_nested(d, dotpath, value):
    """Setzt z.B. 'batterie.kapazitaet_kwh' → d['batterie']['kapazitaet_kwh']."""
    keys = dotpath.split('.')
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def _get_nested(d, dotpath):
    keys = dotpath.split('.')
    for k in keys:
        d = d.get(k)
        if d is None:
            return None
    return d


def _backup(path):
    """Erstellt ein Backup vor Änderungen."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    return bak


# ══════════════════════════════════════════════════════════════
#  Status anzeigen
# ══════════════════════════════════════════════════════════════

def detect_current_profile():
    """Erkennt welches Profil aktuell aktiv ist."""
    batt = _load_json(BATT_CFG)
    matrix = _load_json(SOC_MATRIX)

    for key, profil in PROFILE.items():
        match = True
        for dotpath, expected in profil['battery_control'].items():
            actual = _get_nested(batt, dotpath)
            if actual != expected:
                match = False
                break
        if match:
            for dotpath, expected in profil['soc_param_matrix'].items():
                actual = _get_nested(matrix, dotpath)
                if actual != expected:
                    match = False
                    break
        if match:
            return key
    return '?'


def show_status():
    """Zeigt aktuellen Status."""
    batt = _load_json(BATT_CFG)
    matrix = _load_json(SOC_MATRIX)

    current = detect_current_profile()
    profil_name = PROFILE.get(current, {}).get('name', 'Unbekannt / Mischkonfiguration')

    print("╔══════════════════════════════════════════════════════╗")
    print(f"║  Aktuelles Profil:  {current} — {profil_name}")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Kapazität:    {_get_nested(batt, 'batterie.kapazitaet_kwh')} kWh")
    print(f"║  Max Laden:    {_get_nested(batt, 'batterie.max_lade_w')} W")
    print(f"║  Max Entladen: {_get_nested(batt, 'batterie.max_entlade_w')} W")
    print(f"║  SOC Komfort:  {_get_nested(batt, 'soc_grenzen.komfort_min')}–{_get_nested(batt, 'soc_grenzen.komfort_max')}%")
    print(f"║  Abend-Rate:   {'aktiv' if _get_nested(matrix, 'abend_entladerate.aktiv') else 'AUS'}")
    print(f"║  Dyn. Laderate:{'aktiv' if _get_nested(matrix, 'laderate_dynamisch.aktiv') else 'AUS'}")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print("Verfügbare Profile:")
    for key, p in PROFILE.items():
        marker = " ◄── AKTIV" if key == current else ""
        print(f"  {key}  {p['name']}{marker}")
        print(f"     {p['beschreibung']}")
    print()
    print("Umschalten:  python3 tools/profil_wechsel.py A|B|C")


# ══════════════════════════════════════════════════════════════
#  Profil anwenden
# ══════════════════════════════════════════════════════════════

def apply_profile(key):
    """Wendet ein Profil an."""
    profil = PROFILE.get(key.upper())
    if not profil:
        print(f"Unbekanntes Profil: {key}")
        print(f"Verfügbar: {', '.join(PROFILE.keys())}")
        sys.exit(1)

    current = detect_current_profile()
    if current == key.upper():
        print(f"Profil {key.upper()} ist bereits aktiv — keine Änderung.")
        return

    # Backups
    bak1 = _backup(BATT_CFG)
    bak2 = _backup(SOC_MATRIX)
    print(f"Backups: {os.path.basename(bak1)}, {os.path.basename(bak2)}")

    # battery_control.json
    batt = _load_json(BATT_CFG)
    for dotpath, value in profil['battery_control'].items():
        _set_nested(batt, dotpath, value)
    batt['_updated'] = datetime.now().strftime('%Y-%m-%d')
    _save_json(BATT_CFG, batt)

    # soc_param_matrix.json
    matrix = _load_json(SOC_MATRIX)
    for dotpath, value in profil['soc_param_matrix'].items():
        _set_nested(matrix, dotpath, value)
    _save_json(SOC_MATRIX, matrix)

    print(f"\n✓ Profil {key.upper()} angewendet: {profil['name']}")
    print(f"  {profil['beschreibung']}")
    print()
    print("WICHTIG: Automation-Daemon neu starten damit Änderungen wirken:")
    print("  sudo systemctl restart pv-automation")


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) < 2:
        show_status()
    else:
        apply_profile(sys.argv[1])
