"""
schaltlog.py — Zentrales Schaltlog für ALLE Schaltvorgänge

Registriert in einer einzigen Logdatei:
  • Engine-Aktionen (exakter Zeitstempel)
  • Extern erkannte Änderungen (≈ ungefährer Zeitpunkt)
  • SOC-Änderungen, HP-Schaltungen, Batterie-Modi

Datei: logs/schaltlog.txt (max. MAX_ZEILEN, älteste werden abgeschnitten)

Zugriff: pv-config.py → Menüpunkt "Schalt-Logbuch"
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

LOG = logging.getLogger('schaltlog')

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCHALTLOG_PATH = os.path.join(_PROJECT_ROOT, 'logs', 'schaltlog.txt')
MAX_ZEILEN = 2000

_lock = threading.Lock()


def _ensure_dir():
    """Log-Verzeichnis sicherstellen."""
    d = os.path.dirname(SCHALTLOG_PATH)
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _truncate_if_needed():
    """Logdatei auf MAX_ZEILEN kürzen (älteste entfernen)."""
    try:
        if not os.path.exists(SCHALTLOG_PATH):
            return
        with open(SCHALTLOG_PATH, 'r') as f:
            lines = f.readlines()
        if len(lines) > MAX_ZEILEN:
            with open(SCHALTLOG_PATH, 'w') as f:
                f.writelines(lines[-MAX_ZEILEN:])
    except Exception as e:
        LOG.warning(f'Schaltlog Truncate fehlgeschlagen: {e}')


def logge(quelle: str, aktor: str, kommando: str,
          wert: str = '', ergebnis: str = '', grund: str = '',
          zeitpunkt: Optional[datetime] = None,
          ungefaehr: bool = False):
    """Einen Schaltvorgang ins zentrale Log schreiben.

    Args:
        quelle:    'ENGINE' | 'EXTERN' | 'MANUELL'
        aktor:     'batterie' | 'fritzdect' | 'wattpilot'
        kommando:  z.B. 'set_soc_min', 'hp_ein', 'set_charge_rate'
        wert:      Wert als String (z.B. '5', 'manual', '0')
        ergebnis:  'OK' | 'FEHLER' | 'DRY-RUN' | '--' (für extern)
        grund:     Menschenlesbare Begründung
        zeitpunkt: Zeitstempel (default: jetzt)
        ungefaehr: True → Zeitstempel wird mit '~' markiert (für extern erkannte)
    """
    now = zeitpunkt or datetime.now()

    if ungefaehr:
        ts_str = f'~{now.strftime("%Y-%m-%d %H:%M")}'
    else:
        ts_str = f' {now.strftime("%Y-%m-%d %H:%M:%S")}'

    # Kompaktes Wert-Format
    wert_str = f'={wert}' if wert else ''
    cmd_str = f'{kommando}{wert_str}'

    # Zeile zusammenbauen (feste Spaltenbreiten für Lesbarkeit)
    # Format: TS  QUELLE  AKTOR  KOMMANDO=WERT  ERG  GRUND
    zeile = (f'{ts_str}  {quelle:<7s}  {aktor:<11s}  '
             f'{cmd_str:<28s}  {ergebnis:<7s}')
    if grund:
        # Grund kürzen wenn nötig
        zeile += f'  {grund[:80]}'
    zeile += '\n'

    with _lock:
        try:
            _ensure_dir()
            with open(SCHALTLOG_PATH, 'a') as f:
                f.write(zeile)
            _truncate_if_needed()
        except Exception as e:
            LOG.error(f'Schaltlog Schreibfehler: {e}')


def logge_engine(aktor: str, kommando: str, wert: str = '',
                 ergebnis: str = 'OK', grund: str = ''):
    """Kurzform für Engine-eigene Schaltvorgänge (exakter Zeitstempel)."""
    logge('ENGINE', aktor, kommando, wert=wert,
          ergebnis=ergebnis, grund=grund, ungefaehr=False)


def logge_extern(aktor: str, beschreibung: str, grund: str = ''):
    """Kurzform für extern erkannte Schaltvorgänge (≈ ungefähr).

    Args:
        aktor:         z.B. 'batterie', 'fritzdect'
        beschreibung:  z.B. 'SOC_MIN 5%→20%', 'HP extern EIN'
        grund:         Optionale Zusatzinfo
    """
    logge('EXTERN', aktor, beschreibung, wert='',
          ergebnis='--', grund=grund, ungefaehr=True)


def lese_log(max_zeilen: int = 500) -> str:
    """Log lesen (neueste zuerst) für Anzeige in pv-config.

    Returns:
        Formatierter Text mit Header und den letzten max_zeilen Einträgen.
    """
    trenn = '=' * 76
    linie = '-' * 76
    header = (
        'SCHALT-LOGBUCH - Alle Schaltvorgaenge\n'
        + trenn + '\n'
        '  ~ = ungefaehrer Zeitpunkt (extern erkannt)\n'
        '  QUELLE: ENGINE = eigener Schaltvorgang,\n'
        '          EXTERN = ausserhalb der Automation erkannt\n'
        + linie + '\n\n'
    )

    if not os.path.exists(SCHALTLOG_PATH):
        return header + '(Noch keine Eintraege)\n'

    try:
        with open(SCHALTLOG_PATH, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        return header + f'Fehler beim Lesen: {e}\n'

    # Neueste zuerst
    lines = lines[-max_zeilen:]
    lines.reverse()

    # Unicode-Zeichen ersetzen (whiptail kann kein UTF-8)
    body = ''.join(lines)
    for uc, ac in [('\u2192', '->'), ('\u2500', '-'), ('\u2550', '='),
                   ('\u00e4', 'ae'), ('\u00f6', 'oe'), ('\u00fc', 'ue'),
                   ('\u00c4', 'Ae'), ('\u00d6', 'Oe'), ('\u00dc', 'Ue'),
                   ('\u00df', 'ss'), ('\u2248', '~')]:
        body = body.replace(uc, ac)

    return header + body + '\n' + linie + '\n' + f'{len(lines)} Eintraege\n'
