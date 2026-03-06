"""
schaltlog.py — Zentrales Schaltlog für ALLE Schaltvorgänge

Registriert in einer einzigen Logdatei:
  * Engine-Aktionen (exakter Zeitstempel)
  * Extern erkannte Änderungen (~ ungefährer Zeitpunkt)
  * SOC-Änderungen, HP-Schaltungen, Batterie-Modi

Wiederholungs-Zusammenfassung:
  Identische aufeinanderfolgende Einträge werden NICHT einzeln geschrieben,
  sondern zu Zeitbereichen zusammengefasst:
    " 2026-03-06, 01:07 bis 01:55  ENGINE  batterie  stop_discharge  OK  (49x)"
  Signatur für Gleichheit: quelle + aktor + kommando + wert + ergebnis

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


# ── Wiederholungs-Zusammenfassung ────────────────────────────

class _PendingEntry:
    """Gepufferter Eintrag für Zusammenfassung identischer Wiederholungen."""
    __slots__ = ('key', 'quelle', 'aktor', 'kommando', 'wert',
                 'ergebnis', 'grund', 'ungefaehr',
                 'start_ts', 'end_ts', 'count')

    def __init__(self):
        self.key: Optional[tuple] = None
        self.quelle = ''
        self.aktor = ''
        self.kommando = ''
        self.wert = ''
        self.ergebnis = ''
        self.grund = ''
        self.ungefaehr = False
        self.start_ts: Optional[datetime] = None
        self.end_ts: Optional[datetime] = None
        self.count = 0

_pending = _PendingEntry()


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


def _format_zeile(p: _PendingEntry) -> str:
    """Formatiere einen (ggf. zusammengefassten) Eintrag als Log-Zeile."""
    s = p.start_ts
    e = p.end_ts

    wert_str = f'={p.wert}' if p.wert else ''
    cmd_str = f'{p.kommando}{wert_str}'

    # Zeitstempel: Einzeln oder Bereich
    if p.count <= 1 or e is None or s is None:
        # Einzelner Eintrag
        if p.ungefaehr:
            ts_str = f'~{s.strftime("%Y-%m-%d, %H:%M")}'
        else:
            ts_str = f' {s.strftime("%Y-%m-%d, %H:%M:%S")}'
    else:
        # Zeitbereich (zusammengefasst)
        prefix = '~' if p.ungefaehr else ' '
        if s.date() == e.date():
            # Gleicher Tag: "2026-03-06, 01:07 bis 01:55"
            ts_str = (f'{prefix}{s.strftime("%Y-%m-%d, %H:%M")} '
                      f'bis {e.strftime("%H:%M")}')
        else:
            # Tagesübergreifend: "2026-03-05, 23:50 bis 03-06, 00:15"
            ts_str = (f'{prefix}{s.strftime("%Y-%m-%d, %H:%M")} '
                      f'bis {e.strftime("%m-%d, %H:%M")}')

    # Zeile zusammenbauen
    zeile = (f'{ts_str}  {p.quelle:<7s}  {p.aktor:<11s}  '
             f'{cmd_str:<28s}  {p.ergebnis:<7s}')
    if p.grund:
        zeile += f'  {p.grund[:72]}'
    if p.count > 1:
        zeile += f'  ({p.count}x)'
    zeile += '\n'
    return zeile


def _write_pending():
    """Schreibe den gepufferten Eintrag in die Datei (falls vorhanden)."""
    if _pending.key is None:
        return
    try:
        _ensure_dir()
        zeile = _format_zeile(_pending)

        if _pending.count <= 1:
            # Erster Eintrag: einfach anhängen
            with open(SCHALTLOG_PATH, 'a') as f:
                f.write(zeile)
        else:
            # Wiederholung: letzte Zeile ersetzen
            if os.path.exists(SCHALTLOG_PATH):
                with open(SCHALTLOG_PATH, 'r') as f:
                    lines = f.readlines()
                if lines:
                    lines[-1] = zeile
                with open(SCHALTLOG_PATH, 'w') as f:
                    f.writelines(lines)
            else:
                with open(SCHALTLOG_PATH, 'a') as f:
                    f.write(zeile)

        _truncate_if_needed()
    except Exception as e:
        LOG.error(f'Schaltlog Schreibfehler: {e}')


def logge(quelle: str, aktor: str, kommando: str,
          wert: str = '', ergebnis: str = '', grund: str = '',
          zeitpunkt: Optional[datetime] = None,
          ungefaehr: bool = False):
    """Einen Schaltvorgang ins zentrale Log schreiben.

    Identische aufeinanderfolgende Einträge werden zu Zeitbereichen
    zusammengefasst. Signatur: (quelle, aktor, kommando, wert, ergebnis).

    Args:
        quelle:    'ENGINE' | 'EXTERN' | 'MANUELL'
        aktor:     'batterie' | 'fritzdect' | 'wattpilot'
        kommando:  z.B. 'set_soc_min', 'hp_ein', 'set_charge_rate'
        wert:      Wert als String (z.B. '5', 'manual', '0')
        ergebnis:  'OK' | 'FEHLER' | 'DRY-RUN' | '--' (für extern)
        grund:     Menschenlesbare Begründung
        zeitpunkt: Zeitstempel (default: jetzt)
        ungefaehr: True → Zeitstempel wird mit '~' markiert
    """
    now = zeitpunkt or datetime.now()
    key = (quelle, aktor, kommando, wert, ergebnis)

    with _lock:
        if key == _pending.key:
            # Gleicher Eintrag wie vorher → Zeitbereich erweitern
            _pending.end_ts = now
            _pending.count += 1
            # Grund aktualisieren (neuester)
            if grund:
                _pending.grund = grund
            _write_pending()
        else:
            # Neuer Eintrag → alten abschließen, neuen starten
            # Alten wurde bereits beim letzten Aufruf geschrieben.
            # Jetzt neuen Eintrag puffern und sofort schreiben.
            _pending.key = key
            _pending.quelle = quelle
            _pending.aktor = aktor
            _pending.kommando = kommando
            _pending.wert = wert
            _pending.ergebnis = ergebnis
            _pending.grund = grund
            _pending.ungefaehr = ungefaehr
            _pending.start_ts = now
            _pending.end_ts = now
            _pending.count = 1
            _write_pending()


def logge_engine(aktor: str, kommando: str, wert: str = '',
                 ergebnis: str = 'OK', grund: str = ''):
    """Kurzform für Engine-eigene Schaltvorgänge (exakter Zeitstempel)."""
    logge('ENGINE', aktor, kommando, wert=wert,
          ergebnis=ergebnis, grund=grund, ungefaehr=False)


def logge_extern(aktor: str, beschreibung: str, grund: str = ''):
    """Kurzform für extern erkannte Schaltvorgänge (~ ungefähr).

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
