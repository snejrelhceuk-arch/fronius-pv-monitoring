#!/usr/bin/env python3
"""
tools/pv_config/netzkriterien.py — NQ-Menues fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-09-28): Netzkriterien-
Grenzwerte (PAC4200/NQ → config/nq_config.json) und iMSys-Ablesung
(Netzbetreiber-Zaehler, kumulative OBIS-Staende → nq_ims_reading). Reine
NQ-Referenzpflege; kein Aktor-/Produktions-Write.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, date
from typing import Optional

import config
from tools.pv_config.common import (
    PROJECT_ROOT,
    wt_menu, wt_inputbox, wt_yesno, wt_msgbox,
)
from tools.pv_config.service import _fix_ownership


# ═══════════════════════════════════════════════════════════════
# Menü n: Netzkriterien-Grenzwerte (NQ/PAC4200)
# ═══════════════════════════════════════════════════════════════

def _nq_config_path() -> str:
    return os.path.join(PROJECT_ROOT, 'config', 'nq_config.json')


def _save_nq_config(path: str, cfg: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def menu_netzkriterien():
    """Netzkriterien-Grenzwerte (NQ/PAC4200) bearbeiten -> config/nq_config.json."""
    path = _nq_config_path()
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        wt_msgbox(f'nq_config.json nicht lesbar:\n{str(e)[:200]}')
        return
    gw = cfg.setdefault('grenzwerte', {})
    lv = gw.setdefault('warning_levels', {})
    lvl = gw.setdefault('warning_levels_load', {})

    # (tag, label, container, key)
    fields = [
        ('i_max',  'Strom-Grenze i_max [A]',                 gw,  'i_max_a'),
        ('p_max',  'Leistungs-Grenze p_max [W]',             gw,  'p_max_w'),
        ('u_lo',   'Spannung L-L min [V]',                   gw,  'u_ll_min_v'),
        ('u_hi',   'Spannung L-L max [V]',                   gw,  'u_ll_max_v'),
        ('f_lo',   'Frequenz min [Hz]',                      gw,  'freq_min_hz'),
        ('f_hi',   'Frequenz max [Hz]',                      gw,  'freq_max_hz'),
        ('thd',    'THD-U max [%]',                          gw,  'thd_u_max_pct'),
        ('nw',     'Warnstufe U/f/THD  warn [%]',            lv,  'warn_pct'),
        ('nh',     'Warnstufe U/f/THD  hoch [%]',            lv,  'high_pct'),
        ('nc',     'Warnstufe U/f/THD  kritisch [%]',        lv,  'crit_pct'),
        ('lw',     'Warnstufe Strom/Leistung  warn [%]',     lvl, 'warn_pct'),
        ('lh',     'Warnstufe Strom/Leistung  hoch [%]',     lvl, 'high_pct'),
        ('lc',     'Warnstufe Strom/Leistung  kritisch [%]', lvl, 'crit_pct'),
    ]
    while True:
        items = [(tag, f'{label}  [{cont.get(key, "—")}]') for tag, label, cont, key in fields]
        choice = wt_menu(
            'Netzkriterien-Grenzwerte (PAC4200/NQ)\n\n'
            'Strom + Leistung = Anschlussgroessen (Warnstufen 80/100/120%).\n'
            'Spannung/Frequenz/THD = Norm (Warnstufen 50/70/90%).\n'
            'Wirkt sofort im Netzkriterien-Monitoring (kein Neustart noetig).',
            items,
        )
        if not choice:
            return
        _tag, label, cont, key = next(f for f in fields if f[0] == choice)
        val = wt_inputbox(f'{label}:', str(cont.get(key, '')))
        if val is None:
            continue
        try:
            num = float(val.strip().replace(',', '.'))
        except ValueError:
            wt_msgbox('Ungueltige Zahl.')
            continue
        cont[key] = num
        try:
            _save_nq_config(path, cfg)
        except Exception as e:
            wt_msgbox(f'Speichern fehlgeschlagen:\n{str(e)[:200]}')


# ═══════════════════════════════════════════════════════════════
# Menü i: iMSys-Ablesung (Netzbetreiber-Zähler) erfassen
# ═══════════════════════════════════════════════════════════════

def _nq_primary_dir() -> str:
    return os.path.join(config.BASE_DIR, 'nq', 'db')


def _ims_last_reading() -> Optional[tuple]:
    """Letzte iMSys-Ablesung (ts, day, imp_kwh, exp_kwh) über alle NQ-Monats-DBs."""
    import glob as _glob
    import sqlite3 as _sql
    latest = None
    for db_path in sorted(_glob.glob(os.path.join(_nq_primary_dir(), 'nq_*.db'))):
        try:
            conn = _sql.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5.0)
            row = conn.execute(
                'SELECT ts, day, imp_kwh, exp_kwh FROM nq_ims_reading ORDER BY ts DESC LIMIT 1'
            ).fetchone()
            conn.close()
        except Exception:
            continue
        if row and (latest is None or row[0] > latest[0]):
            latest = row
    return latest


def menu_imsys_ablesung():
    """iMSys-Ablesung (OBIS 1.8.0/2.8.0, kumulative Zählerstände) erfassen → nq_ims_reading.

    Referenzdaten für den Energievergleich (eichrechtlicher Netzbetreiber-Zähler).
    Kein Aktor-/Produktions-Write; schreibt ausschließlich die NQ-Monats-DB.
    """
    from nq.nq_common import open_db, PRIMARY_SCHEMA

    last = _ims_last_reading()
    if last:
        last_dt = datetime.fromtimestamp(last[0]).strftime('%Y-%m-%d %H:%M')
        head = (f'Letzte iMSys-Ablesung: {last[1]} ({last_dt})\n'
                f'  Import 1.8.0 = {last[2]} kWh · Export 2.8.0 = {last[3]} kWh\n\n')
    else:
        head = 'Noch keine iMSys-Ablesung vorhanden.\n\n'

    day = wt_inputbox(head + 'Ablese-Datum (YYYY-MM-DD):', date.today().isoformat())
    if day is None:
        return
    day = day.strip()
    try:
        dt = datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        wt_msgbox('Ungültiges Datum (Format YYYY-MM-DD).')
        return

    hm = wt_inputbox('Ablese-Uhrzeit (HH:MM):', datetime.now().strftime('%H:%M'))
    if hm is None:
        return
    try:
        t = datetime.strptime(hm.strip(), '%H:%M')
    except ValueError:
        wt_msgbox('Ungültige Uhrzeit (Format HH:MM).')
        return
    reading_dt = dt.replace(hour=t.hour, minute=t.minute)
    ts = int(reading_dt.timestamp())

    imp_s = wt_inputbox('Import 1.8.0 [kWh] (Bezug, kumulativer Zählerstand):', '')
    if imp_s is None:
        return
    exp_s = wt_inputbox('Export 2.8.0 [kWh] (Lieferung, kumulativer Zählerstand):', '')
    if exp_s is None:
        return
    try:
        imp_kwh = float(imp_s.strip().replace(',', '.'))
        exp_kwh = float(exp_s.strip().replace(',', '.'))
    except ValueError:
        wt_msgbox('Ungültige Zahl bei Import/Export.')
        return
    if imp_kwh < 0 or exp_kwh < 0:
        wt_msgbox('Zählerstände dürfen nicht negativ sein.')
        return

    source = wt_menu('Quelle der Ablesung:', [
        ('manual', 'Display abgelesen (manuell)'),
        ('portal', 'Netzbetreiber-Portal'),
        ('foto',   'Foto / Beleg'),
    ])
    if not source:
        return
    note = wt_inputbox('Notiz (optional):', '')
    if note is None:
        note = ''

    # Plausibilität: Zählerstände sind kumulativ → monoton nicht-fallend + Zuwachs-Sanity.
    if last:
        last_ts, last_day, last_imp, last_exp = last
        if ts <= last_ts:
            wt_msgbox(f'Ablesezeit muss nach der letzten Ablesung liegen ({last_day}).')
            return
        if last_imp is not None and imp_kwh < last_imp:
            wt_msgbox(f'Import {imp_kwh:.3f} < letzter Stand {last_imp:.3f} kWh — Zähler kann nicht fallen.')
            return
        if last_exp is not None and exp_kwh < last_exp:
            wt_msgbox(f'Export {exp_kwh:.3f} < letzter Stand {last_exp:.3f} kWh — Zähler kann nicht fallen.')
            return
        span_d = max(1.0, (ts - last_ts) / 86400.0)
        d_imp = imp_kwh - (last_imp or 0.0)
        d_exp = exp_kwh - (last_exp or 0.0)
        MAX_KWH_DAY = 300.0  # großzügige Sanity-Obergrenze (37.6 kWp), kein Hard-Limit
        if d_imp / span_d > MAX_KWH_DAY or d_exp / span_d > MAX_KWH_DAY:
            if not wt_yesno(
                f'Ungewöhnlich großer Zuwachs seit {last_day}:\n'
                f'  Import +{d_imp:.1f} kWh, Export +{d_exp:.1f} kWh in {span_d:.1f} Tagen\n'
                f'  (> {MAX_KWH_DAY:.0f} kWh/Tag)\n\nTrotzdem speichern?'):
                return

    delta_info = ''
    if last and last[2] is not None and last[3] is not None:
        delta_info = (f'\nΔ seit {last[1]}: Import +{imp_kwh - last[2]:.1f} · '
                      f'Export +{exp_kwh - last[3]:.1f} kWh')
    if not wt_yesno(
        f'iMSys-Ablesung speichern?\n\n'
        f'  Datum:  {day} {hm.strip()}\n'
        f'  Import: {imp_kwh:.3f} kWh (1.8.0)\n'
        f'  Export: {exp_kwh:.3f} kWh (2.8.0)\n'
        f'  Quelle: {source}{delta_info}'):
        return

    month = reading_dt.strftime('%Y-%m')
    db_path = os.path.join(_nq_primary_dir(), f'nq_{month}.db')
    try:
        conn = open_db(db_path, PRIMARY_SCHEMA)
        conn.execute(
            'INSERT OR REPLACE INTO nq_ims_reading (ts, day, imp_kwh, exp_kwh, source, note) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (ts, day, imp_kwh, exp_kwh, source, note or None),
        )
        conn.commit()
        try:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except Exception:
            pass
        conn.close()
    except Exception as e:
        wt_msgbox(f'Speichern fehlgeschlagen:\n{str(e)[:200]}')
        return

    _fix_ownership(db_path)  # falls unter sudo geschrieben: Owner zurücksetzen
    wt_msgbox(
        f'iMSys-Ablesung gespeichert.\n\n'
        f'  {day}: Import {imp_kwh:.3f} / Export {exp_kwh:.3f} kWh\n'
        f'  DB: nq/db/nq_{month}.db\n\n'
        f'Sichtbar unter Netzqualität → Energievergleich (Umschalter „iMSys").'
    )
