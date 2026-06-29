#!/usr/bin/env python3
"""
tools/pv_config/matrix_editor.py — Parameter-Matrix-Editor fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-06-29): Regelkreise an/aus,
Parameter-Matrix anzeigen/bearbeiten, atomar speichern (+ Daemon-Reload).
"""
from __future__ import annotations

import json
import os
from datetime import date

from automation.engine.param_matrix import (
    lade_matrix, validiere_matrix, alle_regelkreise, DEFAULT_MATRIX_PATH,
)
from tools.pv_config.common import (
    PRIO_LABELS, WT_W,
    wt_menu, wt_checklist, wt_inputbox, wt_yesno, wt_msgbox,
)
from tools.pv_config.service import _notify_daemon_reload, _fix_ownership


def menu_regelkreise():
    """Regelkreise per Checklist aktivieren/deaktivieren."""
    matrix = lade_matrix()
    items = []

    for rk_name, rk in alle_regelkreise(matrix):
        prio = rk.get('prioritaet', 0)
        aktiv = rk.get('aktiv', False)
        gewicht = rk.get('score_gewicht', 0)
        label = PRIO_LABELS.get(prio, f'P{prio}')
        # Beschreibung dynamisch an Fensterbreite anpassen
        desc_max = max(20, WT_W - 40)
        desc = f'[{label}] Score={gewicht}  {rk.get("beschreibung", "")[:desc_max]}'
        items.append((rk_name, desc, aktiv))

    result = wt_checklist(
        'Regelkreise aktivieren/deaktivieren.\n'
        'Leertaste = Umschalten, Enter = Bestätigen, Esc = Abbrechen.\n\n'
        'SICHERHEIT-Regeln (P1) sollten immer aktiv bleiben!',
        items,
    )

    if result is None:
        return  # Abbruch

    # Änderungen ermitteln
    aenderungen = []
    for rk_name, rk in alle_regelkreise(matrix):
        war_aktiv = rk.get('aktiv', False)
        soll_aktiv = rk_name in result
        if war_aktiv != soll_aktiv:
            aenderungen.append((rk_name, soll_aktiv))

    if not aenderungen:
        wt_msgbox('Keine Änderungen.')
        return

    # Sicherheitscheck: P1-Regeln deaktivieren?
    p1_deaktiviert = [
        name for name, aktiv in aenderungen
        if not aktiv and matrix['regelkreise'][name].get('prioritaet') == 1
    ]
    if p1_deaktiviert:
        if not wt_yesno(
            f'⚠ WARNUNG: Sicherheitsregeln werden deaktiviert:\n\n'
            f'{", ".join(p1_deaktiviert)}\n\n'
            f'Dies kann zu Batterieschäden führen!\n'
            f'Wirklich fortfahren?'
        ):
            return

    # Zusammenfassung
    summary = 'Folgende Änderungen:\n\n'
    for name, aktiv in aenderungen:
        prio = matrix['regelkreise'][name].get('prioritaet', 0)
        if name == 'heizpatrone':
            detail = ' (HP-Steuerung, nicht die Last!)' if not aktiv else ' (HP-Automatik)'
        elif prio == 1:
            detail = ' ⚠ SICHERHEIT'
        else:
            detail = ''
        summary += f'  {"✓ Steuerung AN" if aktiv else "✗ Steuerung AUS"}: {name}{detail}\n'
    summary += '\nÄnderungen speichern?'

    if not wt_yesno(summary):
        return

    # Speichern
    for name, aktiv in aenderungen:
        matrix['regelkreise'][name]['aktiv'] = aktiv

    _speichere_matrix(matrix)
    wt_msgbox(f'{len(aenderungen)} Regelkreis(e) geändert.\n'
              f'Wirksam ab nächstem Engine-Zyklus (≤1 Min).')


def menu_parameter():
    """Parameter-Matrix: Regelkreis wählen → Parameter bearbeiten."""
    while True:
        matrix = lade_matrix()
        items = []
        for rk_name, rk in alle_regelkreise(matrix):
            prio = rk.get('prioritaet', 0)
            aktiv = '●' if rk.get('aktiv') else '○'
            n_params = len([k for k in rk.get('parameter', {}) if not k.startswith('_')])
            desc_max = max(20, WT_W - 30)
            beschr = rk.get('beschreibung', '')[:desc_max]
            desc = f'{aktiv} P{prio} S={rk.get("score_gewicht", 0):>3} {n_params}P  {beschr}'
            items.append((rk_name, desc))

        choice = wt_menu(
            'Regelkreis wählen zum Anzeigen/Bearbeiten der Parameter.\n'
            '● = aktiv, ○ = inaktiv',
            items,
        )

        if not choice:
            return

        _menu_regelkreis_detail(choice)


def _menu_regelkreis_detail(rk_name: str):
    """Detail-Ansicht eines Regelkreises mit Parameter-Bearbeitung."""
    while True:
        matrix = lade_matrix()
        rk = matrix.get('regelkreise', {}).get(rk_name, {})
        if not rk:
            wt_msgbox(f'Regelkreis "{rk_name}" nicht gefunden.')
            return

        params = rk.get('parameter', {})
        items = []
        anzeige_zu_key = {}  # Mapping: Anzeigename → JSON-Key
        for p_name, p in params.items():
            if p_name.startswith('_'):
                continue
            wert = p.get('wert', '?')
            einheit = p.get('einheit', '')
            beschr = p.get('beschreibung', '')
            # Einheitssuffixe aus dem Namen entfernen (_pct, _kwh, _w)
            anzeige = p_name
            for suffix in ('_pct', '_kwh', '_w'):
                if anzeige.endswith(suffix):
                    anzeige = anzeige[:-len(suffix)]
                    break
            anzeige_zu_key[anzeige] = p_name
            # Beschreibung dynamisch an Fensterbreite anpassen
            desc_max = max(20, WT_W - len(anzeige) - 15)
            desc = f'{wert}{einheit}  {beschr[:desc_max]}'
            items.append((anzeige, desc))

        # Header
        prio = rk.get('prioritaet', 0)
        aktiv = 'AKTIV' if rk.get('aktiv') else 'INAKTIV'
        header = (
            f'{rk_name.upper()} — {PRIO_LABELS.get(prio, f"P{prio}")} — {aktiv}\n'
            f'{rk.get("beschreibung", "")}\n'
            f'Score: {rk.get("score_gewicht", 0)}  Zyklus: {rk.get("engine_zyklus", "?")}\n\n'
            f'Parameter wählen zum Bearbeiten:'
        )

        choice = wt_menu(header, items)
        if not choice:
            return

        # Anzeigename zurück auf echten JSON-Key mappen
        real_key = anzeige_zu_key.get(choice, choice)
        _edit_parameter(rk_name, real_key)


def _edit_parameter(rk_name: str, p_name: str):
    """Einzelnen Parameter bearbeiten."""
    matrix = lade_matrix()
    rk = matrix['regelkreise'][rk_name]
    p = rk['parameter'][p_name]

    wert = p.get('wert', 0)
    einheit = p.get('einheit', '')
    bereich = p.get('bereich', [])
    beschreibung = p.get('beschreibung', '')
    obs_feld = p.get('obs_feld', '')
    aktor = p.get('aktor_kommando', '')

    info = (
        f'Parameter: {p_name}\n'
        f'Beschreibung: {beschreibung}\n\n'
        f'Aktueller Wert: {wert}{einheit}\n'
    )
    if bereich and len(bereich) == 2:
        info += f'Gültiger Bereich: {bereich[0]} .. {bereich[1]}{einheit}\n'
    if obs_feld:
        info += f'ObsState-Feld: {obs_feld}\n'
    if aktor:
        info += f'Aktor-Kommando: {aktor}\n'
    info += '\nNeuen Wert eingeben:'

    neuer_wert_str = wt_inputbox(info, str(wert))
    if neuer_wert_str is None:
        return

    # Typ beibehalten (int oder float)
    try:
        if isinstance(wert, int) and '.' not in neuer_wert_str:
            neuer_wert = int(neuer_wert_str)
        else:
            neuer_wert = float(neuer_wert_str)
    except ValueError:
        wt_msgbox(f'Ungültiger Wert: "{neuer_wert_str}"\n\nBitte eine Zahl eingeben.')
        return

    # Bereichsprüfung
    if bereich and len(bereich) == 2:
        lo, hi = bereich
        if not (lo <= neuer_wert <= hi):
            wt_msgbox(
                f'Wert {neuer_wert}{einheit} liegt außerhalb des '
                f'gültigen Bereichs [{lo}..{hi}]{einheit}.\n\n'
                f'Änderung abgelehnt.'
            )
            return

    if neuer_wert == wert:
        wt_msgbox('Wert unverändert.')
        return

    # Bestätigung
    if not wt_yesno(
        f'Parameter: {rk_name} → {p_name}\n\n'
        f'Alt: {wert}{einheit}\n'
        f'Neu: {neuer_wert}{einheit}\n\n'
        f'Speichern?'
    ):
        return

    # Speichern
    matrix = lade_matrix()  # Frisch laden (Concurrent-Safety)
    matrix['regelkreise'][rk_name]['parameter'][p_name]['wert'] = neuer_wert
    _speichere_matrix(matrix)
    wt_msgbox(f'✓ {p_name} = {neuer_wert}{einheit} gespeichert.\n'
              f'Wirksam ab nächstem Engine-Zyklus.')


def _speichere_matrix(matrix: dict):
    """Matrix atomar speichern (write-to-temp + rename)."""
    # Zeitstempel aktualisieren
    matrix['_updated'] = date.today().isoformat()

    # Validieren vor Speichern
    fehler = validiere_matrix(matrix)
    if fehler:
        wt_msgbox(
            '⚠ VALIDIERUNGSFEHLER — Speichern abgebrochen!\n\n'
            + '\n'.join(f'• {f}' for f in fehler[:5])
        )
        return

    tmp_path = DEFAULT_MATRIX_PATH + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(matrix, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp_path, DEFAULT_MATRIX_PATH)
        _fix_ownership(DEFAULT_MATRIX_PATH)
        _notify_daemon_reload()
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern:\n\n{str(e)[:200]}')
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
