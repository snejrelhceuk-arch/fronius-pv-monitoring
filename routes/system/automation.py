"""Automation-State- und Phasen-Helfer fuer das system-Blueprint.

Liest read-only aus ``automation_log`` (Persist-DB), der RAM-DB
(``/dev/shm/automation_obs.db``) und Config-Dateien. Wird von
``battery.py`` (``_build_flow_status_result``) genutzt; registriert
selbst keine Routen.
"""
import logging
import sqlite3
import time
from pathlib import Path

import config

# Repo-Root: routes/system/automation.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _fetch_automation_state(now, result):
    """Engine-State aus automation_log: SOC-Switches, Aktionen, Phasen."""
    try:
        import json as _json

        with sqlite3.connect(config.DB_PATH) as _adb:
            _24h_ago = int(now) - 86400

            soc_rows = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                  AND kommando IN ('set_soc_min', 'set_soc_max', 'set_soc_mode')
                  AND ts >= datetime(?, 'unixepoch')
                ORDER BY ts DESC
                LIMIT 20
            """, (_24h_ago,)).fetchall()

            result['soc_switches'] = [{
                'ts': r[0], 'kommando': r[1], 'wert': r[2],
                'grund': (r[3] or '')[:120], 'ergebnis': r[4],
            } for r in soc_rows]

            all_rows = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                  AND ts >= datetime(?, 'unixepoch')
                ORDER BY ts DESC
                LIMIT 50
            """, (_24h_ago,)).fetchall()

            result['engine_aktionen'] = [{
                'ts': r[0], 'kommando': r[1], 'wert': r[2],
                'grund': (r[3] or '')[:120], 'ergebnis': r[4],
            } for r in all_rows]

            last_action = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if last_action:
                result['last_engine_action'] = {
                    'ts': last_action[0], 'kommando': last_action[1],
                    'wert': last_action[2],
                    'grund': (last_action[3] or '')[:120],
                    'ergebnis': last_action[4],
                }

        # Engine-Vorausschau
        try:
            from automation.engine.automation_daemon import engine_vorausschau
            result['vorausschau'] = engine_vorausschau()
        except Exception as ev:
            logging.debug(f"Vorausschau nicht verfügbar: {ev}")
            result['vorausschau'] = []

        # Scheduler-State (Phasen-Flags, Legacy-Kompatibilität)
        state_file = _REPO_ROOT / 'config' / 'battery_scheduler_state.json'
        if state_file.exists():
            with open(state_file, 'r') as f:
                sched_state = _json.load(f)
            result['scheduler'] = {
                'morning_done': sched_state.get('morning_done', False),
                'afternoon_done': sched_state.get('afternoon_done', False),
                'balancing_active': sched_state.get('balancing_active', False),
                'evening_rate_active': sched_state.get('evening_rate_active', False),
                'evening_rate_percent': sched_state.get('evening_rate_percent'),
                'manual_override': sched_state.get('manual_override', False),
                'last_date': sched_state.get('last_date'),
            }

            # Zellausgleich aktiv? → True wenn letzter Ausgleich NICHT im laufenden Quartal
            try:
                from datetime import date as _date_type
                _last_bal = sched_state.get('last_balancing') or ''
                _heute = _date_type.today()
                _zausgl_aktiv = True  # Default: noch nicht erledigt
                if _last_bal:
                    _lb = _date_type.fromisoformat(_last_bal)
                    if ((_lb.year == _heute.year)
                            and ((_lb.month - 1) // 3 == (_heute.month - 1) // 3)):
                        _zausgl_aktiv = False
                result['zellausgleich_aktiv'] = _zausgl_aktiv
            except Exception:
                result['zellausgleich_aktiv'] = False

        # Automation-Phasen für Tagesübersicht
        _build_automation_phasen(now, result)

    except Exception as e:
        logging.warning(f"Automation-State nicht lesbar: {e}")


def _build_automation_phasen(now, result):
    """Tages-Phasenübersicht aus automation_log + Defaults."""
    try:
        _persist_db = str(_REPO_ROOT / 'data.db')
        _auto_rows = []
        try:
            with sqlite3.connect(_persist_db) as _alog_db:
                _auto_rows = _alog_db.execute("""
                    SELECT kommando, wert, grund, ts, ergebnis
                    FROM automation_log
                    WHERE aktor = 'batterie'
                      AND ts >= ?
                      AND ergebnis = 'OK'
                    ORDER BY ts ASC
                """, (time.strftime('%Y-%m-%d', time.localtime(now)),)).fetchall()
        except Exception:
            pass

        _phase_log = {}

        for _r in _auto_rows:
            _cmd, _wert = _r[0], _r[1]
            _grund = (_r[2] or '')[:80]
            _ts_str = _r[3][:16].replace('T', ' ') if _r[3] and len(_r[3]) > 15 else None
            _zeit = _ts_str[11:16] if _ts_str and len(_ts_str) >= 16 else None

            if _cmd == 'set_soc_min' and 'Morgen' in _grund:
                _phase_log['morgen'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': f'SOC_MIN → {_wert}%' if _wert else 'SOC_MIN geöffnet',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd == 'set_soc_max' and 'Nachmittag' in _grund:
                _aktion_label = 'Ladewunsch' if 'Ladewunsch' in _grund else 'SOC_MAX'
                _phase_log['nachmittag'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': f'{_aktion_label} → {_wert}%' if _wert else f'{_aktion_label} (erhöht)',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd in ('auto',) and 'TAG-Phase' in _grund:
                _phase_log['komfort'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': 'Limits aufgehoben',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd in ('set_soc_min', 'set_soc_max') and 'Komfort-Reset' in _grund:
                _phase_log['komfort'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': 'Komfort-Reset',
                    'grund': _grund, 'manuell': False,
                }

        # ── Kontextreiche Defaults für fehlende Phasen ──
        # ObsState lesen für aktuelle Werte + Prognose
        _obs_soc_min = result.get('soc_min')
        _obs_soc_max = result.get('soc_max')

        # SOC-Grenz-Zeitpunkte aus letzten Switches rekonstruieren (24h-Fenster)
        _soc_switches = result.get('soc_switches', [])
        _last_soc_min_ts = None
        _last_soc_max_ts = None
        for _sw in _soc_switches:
            if _sw.get('kommando') == 'set_soc_min' and _sw.get('ergebnis') == 'OK' and not _last_soc_min_ts:
                _last_soc_min_ts = _sw.get('ts', '')[:16].replace('T', ' ')
            if _sw.get('kommando') == 'set_soc_max' and _sw.get('ergebnis') == 'OK' and not _last_soc_max_ts:
                _last_soc_max_ts = _sw.get('ts', '')[:16].replace('T', ' ')
        # Fallback: all-time letzter Switch wenn nicht im 24h-Fenster
        if not _last_soc_min_ts or not _last_soc_max_ts:
            try:
                with sqlite3.connect(_persist_db) as _alog_fb:
                    if not _last_soc_min_ts:
                        _fb_min = _alog_fb.execute(
                            "SELECT ts FROM automation_log WHERE aktor='batterie'"
                            " AND kommando='set_soc_min' AND ergebnis='OK'"
                            " ORDER BY ts DESC LIMIT 1").fetchone()
                        if _fb_min:
                            _last_soc_min_ts = _fb_min[0][:16].replace('T', ' ')
                    if not _last_soc_max_ts:
                        _fb_max = _alog_fb.execute(
                            "SELECT ts FROM automation_log WHERE aktor='batterie'"
                            " AND kommando='set_soc_max' AND ergebnis='OK'"
                            " ORDER BY ts DESC LIMIT 1").fetchone()
                        if _fb_max:
                            _last_soc_max_ts = _fb_max[0][:16].replace('T', ' ')
            except Exception:
                pass

        # Nachmittag-Prognose: wann wird SOC_MAX auf 100% gesetzt?
        _nachmittag_prognose = ''
        _sunrise_h = None
        _sunset_h = None
        _clearsky_peak = None
        try:
            import json as _json_nmp
            _obs_db_np = '/dev/shm/automation_obs.db'
            with sqlite3.connect(_obs_db_np) as _odb_np:
                _orow_np = _odb_np.execute('SELECT state_json FROM obs_state LIMIT 1').fetchone()
                if _orow_np:
                    _obs_np = _json_nmp.loads(_orow_np[0])
                    _clearsky_peak = _obs_np.get('clearsky_peak_h')
                    _sunrise_h = _obs_np.get('sunrise')
                    _sunset_h = _obs_np.get('sunset')
                    _forecast_kwh = _obs_np.get('forecast_kwh', 0) or 0
                    if _clearsky_peak and _obs_soc_max and _obs_soc_max < 100:
                        _nachmittag_prognose = f'voraussichtlich ~{int(_clearsky_peak)}:00'
        except Exception:
            pass

        def _h_to_hhmm(h):
            """Dezimalstunde → 'HH:MM' String."""
            if h is None:
                return None
            hh = int(h)
            mm = int((h - hh) * 60)
            return f'{hh:02d}:{mm:02d}'

        if 'morgen' not in _phase_log:
            _morgen_zeit_est = _h_to_hhmm(_sunrise_h - 0.5) if _sunrise_h else None
            if _obs_soc_min is not None and _obs_soc_min <= 5:
                _morgen_grund = f'SOC_MIN = {_obs_soc_min}%'
                if _last_soc_min_ts:
                    _morgen_grund += f' seit {_last_soc_min_ts[5:]}'
                else:
                    _morgen_grund += ' (kein Log verfügbar)'
                _morgen_grund += ' — Batterie entleeren vor PV-Übernahme'
                _phase_log['morgen'] = {
                    'status': 'done', 'zeit': _last_soc_min_ts[11:16] if _last_soc_min_ts else None,
                    'aktion': f'SOC_MIN = {_obs_soc_min}%',
                    'grund': _morgen_grund, 'manuell': False,
                }
            elif _obs_soc_min is not None and _obs_soc_min >= 25:
                _phase_log['morgen'] = {
                    'status': 'skipped', 'zeit': None,
                    'aktion': f'SOC_MIN bleibt {_obs_soc_min}%',
                    'grund': 'Batterie reicht über die Nacht, kein Öffnen nötig',
                    'manuell': False,
                }
            else:
                _phase_log['morgen'] = {
                    'status': 'pending', 'zeit': f'~{_morgen_zeit_est}' if _morgen_zeit_est else None,
                    'aktion': 'SOC_MIN → 5%',
                    'grund': 'Wartet auf PV-Übernahme-Prognose', 'manuell': False,
                }

        if 'nachmittag' not in _phase_log:
            _nm_zeit_est = _h_to_hhmm(_clearsky_peak) if _clearsky_peak else None
            if _obs_soc_max is not None and _obs_soc_max >= 100:
                _nm_grund = 'SOC_MAX = 100%'
                if _last_soc_max_ts:
                    _nm_grund += f' seit {_last_soc_max_ts[5:]}'
                _phase_log['nachmittag'] = {
                    'status': 'done', 'zeit': _last_soc_max_ts[11:16] if _last_soc_max_ts else None,
                    'aktion': 'SOC_MAX = 100%',
                    'grund': _nm_grund, 'manuell': False,
                }
            else:
                _nm_aktion = f'SOC_MAX {_obs_soc_max}% → 100%'
                _nm_grund = f'SOC_MAX aktuell {_obs_soc_max}%'
                if _last_soc_max_ts:
                    _nm_grund += f' (zuletzt {_last_soc_max_ts[5:16]})'
                if _nachmittag_prognose:
                    _nm_grund += f', Öffnung {_nachmittag_prognose}'
                else:
                    _nm_grund += ', wartet auf Clear-Sky-Peak'
                _phase_log['nachmittag'] = {
                    'status': 'pending', 'zeit': f'~{_nm_zeit_est}' if _nm_zeit_est else None,
                    'aktion': _nm_aktion,
                    'grund': _nm_grund, 'manuell': False,
                }

        # Komfort-Grenzen aus battery_control.json
        try:
            import json as _json_cfg
            _cfg_path = _REPO_ROOT / 'config' / 'battery_control.json'
            with open(_cfg_path, 'r') as _cf:
                _bcfg = _json_cfg.load(_cf)
            _k_min = _bcfg.get('soc_grenzen', {}).get('komfort_min', 25)
            _k_max = _bcfg.get('soc_grenzen', {}).get('komfort_max', 75)
        except Exception:
            _k_min, _k_max = 25, 75

        # Komfort-Phase: Abend + Reset zusammengelegt
        _sunset_zeit = _h_to_hhmm(_sunset_h) if _sunset_h else None
        if 'abend' in _phase_log:
            # Already logged as 'abend' → adopt as 'komfort'
            _phase_log['komfort'] = _phase_log.pop('abend')
        elif 'reset' in _phase_log:
            # Already logged as 'reset' → adopt as 'komfort'
            _phase_log['komfort'] = _phase_log.pop('reset')
        else:
            _phase_log['komfort'] = {
                'status': 'pending',
                'zeit': f'~{_sunset_zeit}' if _sunset_zeit else None,
                'aktion': f'Grenzen → {_k_min}–{_k_max}%',
                'grund': 'Komfort-Modus nach Sonnenuntergang'
                         + (f' (~{_sunset_zeit})' if _sunset_zeit else ''),
                'manuell': False,
            }
        # Remove leftover keys if both existed
        _phase_log.pop('abend', None)
        _phase_log.pop('reset', None)

        result['automation_phasen'] = _phase_log
    except Exception as _pe:
        logging.debug(f"Automation-Phasen: {_pe}")
