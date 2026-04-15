"""Operator-Overrides aus der Steuerbox in Automation-Aktionen ueberfuehren."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

LOG = logging.getLogger('engine.operator_overrides')

RAM_DB_PATH = '/dev/shm/automation_obs.db'

WP_HEIZ_STD_C = 37
WP_WW_STD_C = 57
WP_HEIZ_MAX_C = 42
WP_WW_MAX_C = 62
WP_ABSENK_K = 10
WP_WW_BARRIER_C = 55


class OperatorOverrideProcessor:
    """Liest offene operator_overrides und fuehrt sie ueber den Actuator aus."""

    def __init__(self, db_path: str = RAM_DB_PATH):
        self.db_path = db_path

    def process_pending(self, actuator, matrix: dict, limit: int = 20) -> dict[str, int]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            obs_flags = self._read_obs_flags(conn)

            active_rows = conn.execute(
                "SELECT id, action, params_json, created_at, respekt_s FROM operator_overrides "
                "WHERE status='active' ORDER BY id ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()

            rows = conn.execute(
                "SELECT id, action, params_json, created_at, respekt_s FROM operator_overrides "
                "WHERE status='open' ORDER BY id ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()

            done = 0
            failed = 0
            skipped = 0
            held = 0

            for row in active_rows:
                override_id = int(row[0])
                action = row[1]
                created_at = row[3]
                respekt_s = int(row[4] or 0)

                try:
                    params = json.loads(row[2])
                except Exception:
                    params = {}

                if self._remaining_respekt_s(created_at, respekt_s) <= 0:
                    self._set_status(conn, override_id, 'done')
                    self._audit(
                        conn,
                        action,
                        params,
                        {'ok': True, 'info': 'respekt window expired'},
                        override_id,
                        'override hold expired',
                    )
                    done += 1
                    continue

                action_plan = self._map_override_to_actions(action, params, matrix)
                if not action_plan:
                    self._set_status(conn, override_id, 'done')
                    self._audit(
                        conn,
                        action,
                        params,
                        {'ok': True, 'info': 'hold ended (no-op)'},
                        override_id,
                        'override hold ended',
                    )
                    done += 1
                    continue

                # Hold-Reapply nur bei Zustandsdrift, nicht blind jede Minute.
                if not self._active_hold_needs_reapply(action, params, obs_flags):
                    skipped += 1
                    continue

                self._mark_engine_origin_for_actions(action_plan)

                results = actuator.ausfuehren_plan(action_plan)
                ok = bool(results) and all(r.get('ok') for r in results)
                if ok:
                    held += 1
                else:
                    failed += 1
                    self._audit(
                        conn,
                        action,
                        params,
                        {'ok': False, 'results': results},
                        override_id,
                        'override hold re-apply failed',
                    )

            for row in rows:
                override_id = int(row[0])
                action = row[1]
                respekt_s = int(row[4] or 0)
                try:
                    params = json.loads(row[2])
                except Exception:
                    params = {}

                action_plan = self._map_override_to_actions(action, params, matrix)
                if action_plan is None:
                    self._set_status(conn, override_id, 'failed')
                    self._audit(conn, action, params, {'ok': False, 'error': 'unsupported action'}, override_id, 'unsupported action')
                    failed += 1
                    continue

                if not action_plan:
                    self._set_status(conn, override_id, 'done')
                    self._audit(conn, action, params, {'ok': True, 'info': 'neutral/no-op'}, override_id, 'override consumed (neutral)')
                    skipped += 1
                    continue

                self._mark_engine_origin_for_actions(action_plan)

                results = actuator.ausfuehren_plan(action_plan)
                ok = bool(results) and all(r.get('ok') for r in results)
                if ok:
                    if self._uses_respekt_hold(action, params) and respekt_s > 0:
                        self._set_status(conn, override_id, 'active')
                        self._audit(
                            conn,
                            action,
                            params,
                            {'ok': True, 'results': results, 'hold_active': True, 'respekt_s': respekt_s},
                            override_id,
                            'override executed, respekt hold active',
                        )
                        held += 1
                    else:
                        self._set_status(conn, override_id, 'done')
                        self._audit(conn, action, params, {'ok': True, 'results': results}, override_id, 'override executed by automation')
                        done += 1
                else:
                    self._set_status(conn, override_id, 'failed')
                    self._audit(conn, action, params, {'ok': False, 'results': results}, override_id, 'override execution failed')
                    failed += 1

            conn.commit()
            return {
                'done': done,
                'failed': failed,
                'skipped': skipped,
                'held': held,
                'total': len(rows) + len(active_rows),
            }
        finally:
            conn.close()

    @staticmethod
    def _read_obs_flags(conn: sqlite3.Connection) -> dict[str, bool]:
        """Liest aktuelle Gerätezustände aus obs_state (RAM-DB)."""
        try:
            row = conn.execute(
                "SELECT state_json FROM obs_state WHERE id=1"
            ).fetchone()
            if not row or not row[0]:
                return {}
            data = json.loads(row[0])
            return {
                'heizpatrone_aktiv': bool(data.get('heizpatrone_aktiv', False)),
                'klima_aktiv': bool(data.get('klima_aktiv', False)),
            }
        except Exception:
            return {}

    @staticmethod
    def _active_hold_needs_reapply(action: str, params: dict[str, Any],
                                   obs_flags: dict[str, bool]) -> bool:
        """True wenn ein aktiver Hold erneut ausgeführt werden muss."""
        if action == 'hp_toggle':
            state = params.get('state')
            ist_an = obs_flags.get('heizpatrone_aktiv')
            if state == 'on' and ist_an is True:
                return False
            if state == 'off' and ist_an is False:
                return False
        # Für andere Actions konservativ: Reapply erlaubt.
        return True

    @staticmethod
    def _mark_engine_origin_for_actions(action_plan: list[dict[str, Any]]) -> None:
        """Brücke für Extern-Erkennung: Klima-EIN aus Override als Engine markieren."""
        try:
            from automation.engine.regeln.geraete import registriere_klima_engine_ein
        except Exception:
            return

        for action in action_plan:
            if action.get('aktor') == 'fritzdect' and action.get('kommando') == 'klima_ein':
                registriere_klima_engine_ein()
                break

    @staticmethod
    def _remaining_respekt_s(created_at: str, respekt_s: int) -> int:
        try:
            ts = datetime.fromisoformat(created_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
            return max(0, int(respekt_s - elapsed))
        except Exception:
            return 0

    @staticmethod
    def _uses_respekt_hold(action: str, params: dict[str, Any]) -> bool:
        # Klima nutzt KEIN Hold — RegelKlimaanlage erkennt externes Schalten
        # selbstständig über Zustandsübergänge (analog HP-Extern-Erkennung).
        if action in {'hp_toggle', 'lueftung_toggle'}:
            return params.get('state') in {'on', 'off'}
        return False

    def _set_status(self, conn: sqlite3.Connection, override_id: int, status: str) -> None:
        conn.execute(
            'UPDATE operator_overrides SET status=? WHERE id=?',
            (status, override_id),
        )

    def _audit(
        self,
        conn: sqlite3.Connection,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
        override_id: int,
        note: str,
    ) -> None:
        conn.execute(
            'INSERT INTO steuerbox_audit (ts, client_ip, action, params_json, result_json, override_id, note) '
            "VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)",
            (
                'automation-engine',
                action,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                override_id,
                note,
            ),
        )

    def _map_override_to_actions(self, action: str, params: dict[str, Any], matrix: dict) -> list[dict[str, Any]] | None:
        if action == 'hp_toggle':
            state = params.get('state')
            if state == 'on':
                return [self._mk('fritzdect', 'hp_ein', None, 'Steuerbox Override: HP EIN')]
            if state == 'off':
                return [self._mk('fritzdect', 'hp_aus', None, 'Steuerbox Override: HP AUS')]
            if state == 'neutral':
                return []
            return None

        if action == 'klima_toggle':
            state = params.get('state')
            if state == 'on':
                return [self._mk('fritzdect', 'klima_ein', None, 'Steuerbox Override: Klima EIN')]
            if state == 'off':
                return [self._mk('fritzdect', 'klima_aus', None, 'Steuerbox Override: Klima AUS')]
            if state == 'neutral':
                return []
            return None

        if action == 'lueftung_toggle':
            state = params.get('state')
            if state == 'on':
                return [self._mk('fritzdect', 'lueftung_ein', None, 'Steuerbox Override: Lueftung EIN')]
            if state == 'off':
                return [self._mk('fritzdect', 'lueftung_aus', None, 'Steuerbox Override: Lueftung AUS')]
            if state == 'neutral':
                return []
            return None

        if action == 'wattpilot_mode':
            mode = params.get('mode')
            if mode == 'eco':
                return [self._mk('wattpilot', 'set_charge_mode_eco', None, 'Steuerbox Override: Wattpilot ECO')]
            if mode == 'default':
                return [self._mk('wattpilot', 'set_charge_mode_default', None, 'Steuerbox Override: Wattpilot Default')]
            if mode == 'neutral':
                return []
            return None

        if action == 'wattpilot_start_stop':
            cmd = params.get('command')
            if cmd == 'start':
                return [self._mk('wattpilot', 'resume_charging', None, 'Steuerbox Override: Wattpilot START')]
            if cmd == 'stop':
                return [self._mk('wattpilot', 'pause_charging', None, 'Steuerbox Override: Wattpilot STOP')]
            if cmd == 'neutral':
                return []
            return None

        if action == 'wattpilot_amp':
            amp = params.get('amp')
            if amp in (8, 24):
                return [self._mk('wattpilot', 'set_max_current', int(amp), f'Steuerbox Override: Wattpilot {amp}A')]
            if amp == 'neutral':
                return []
            return None

        if action == 'wp_mode':
            mode = params.get('mode')
            if mode == 'neutral':
                return []

            if mode == 'max':
                heiz = WP_HEIZ_MAX_C
                ww = WP_WW_MAX_C
            elif mode == 'std':
                heiz = WP_HEIZ_STD_C
                ww = WP_WW_STD_C
            elif mode == 'min':
                heiz = max(18, WP_HEIZ_STD_C - WP_ABSENK_K)
                ww = max(10, WP_WW_STD_C - WP_ABSENK_K)
            else:
                return None

            current_heiz, current_ww = self._get_current_wp_setpoints()

            # Wenn beide Sollwerte bereits im Absenkbetrieb sind, nicht weiter absenken.
            if mode == 'min' and current_heiz is not None and current_ww is not None:
                if current_heiz <= heiz and current_ww <= ww:
                    return []

            actions: list[dict[str, Any]] = []

            # WW-55C-Sperre: Beim Wechsel von >=55 auf <55 einen Zwischenschritt fahren.
            if (
                mode == 'min'
                and current_ww is not None
                and current_ww >= WP_WW_BARRIER_C
                and ww < WP_WW_BARRIER_C
            ):
                actions.append(
                    self._mk('waermepumpe', 'set_ww_soll', WP_WW_BARRIER_C - 1,
                             'Steuerbox Override: WP MIN (WW 55C-Sperre umgehen, Zwischenschritt 54C)')
                )

            actions.extend([
                self._mk('waermepumpe', 'set_ww_soll', ww, f'Steuerbox Override: WP {mode.upper()} (WW {ww}C)'),
                self._mk('waermepumpe', 'set_heiz_soll', heiz, f'Steuerbox Override: WP {mode.upper()} (Heiz {heiz}C)'),
            ])
            return actions

        if action == 'battery_mode':
            mode = params.get('mode')
            if mode == 'komfort':
                return [
                    self._mk('batterie', 'set_soc_mode', 'manual', 'Steuerbox Override: Batterie Komfort (SOC_MODE manual)'),
                    self._mk('batterie', 'set_soc_min', 25, 'Steuerbox Override: Batterie Komfort (SOC_MIN 25%)'),
                    self._mk('batterie', 'set_soc_max', 75, 'Steuerbox Override: Batterie Komfort (SOC_MAX 75%)'),
                ]
            if mode == 'auto':
                return [
                    self._mk('batterie', 'set_soc_mode', 'auto', 'Steuerbox Override: Batterie Auto (SOC_MODE auto)'),
                    self._mk('batterie', 'set_soc_min', 5, 'Steuerbox Override: Batterie Auto (SOC_MIN 5%)'),
                    self._mk('batterie', 'set_soc_max', 100, 'Steuerbox Override: Batterie Auto (SOC_MAX 100%)'),
                ]
            return None

        return None

    @staticmethod
    def _mk(aktor: str, kommando: str, wert: int | None, grund: str) -> dict[str, Any]:
        payload = {
            'tier': 2,
            'aktor': aktor,
            'kommando': kommando,
            'grund': grund,
        }
        if wert is not None:
            payload['wert'] = wert
        return payload

    @staticmethod
    def _get_current_wp_setpoints() -> tuple[int | None, int | None]:
        """Liest aktuelle WP-Sollwerte (heiz_soll, ww_soll) fuer sichere Mapping-Entscheidungen."""
        try:
            from wp_modbus import get_wp_status

            wp = get_wp_status() or {}
            heiz = wp.get('heiz_soll')
            ww = wp.get('ww_soll')
            heiz_i = int(heiz) if heiz is not None else None
            ww_i = int(ww) if ww is not None else None
            return heiz_i, ww_i
        except Exception:
            return None, None
