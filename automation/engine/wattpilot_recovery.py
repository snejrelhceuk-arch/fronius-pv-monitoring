"""
wattpilot_recovery.py — Vorsichtige Auto-Recovery fuer Wattpilot-Stoerfaelle.

Ziele:
  - Keine Dauer-Reset-Schleifen (Cooldown + Tageslimit)
  - Keine Eingriffe waehrend aktiver EV-Ladung
  - Standardmaessig deaktiviert (nur per config aktiv)

Ausgeloest durch Integrity-Signale aus diagnos (read-only):
  - last_poll_age_s
  - consecutive_errors
  - last_reconnect.success
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import time
from datetime import date
from typing import Optional, Tuple

import config as app_config

LOG = logging.getLogger('wattpilot.recovery')


class WattpilotRecoveryManager:
    """Führt bei anhaltenden Störungen optional eine Recovery-Aktion aus."""

    def __init__(self):
        self.enabled = bool(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_ENABLED', False))
        self.mode = str(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_MODE', 'disabled')).lower()
        self.allow_wallbox_reset = bool(
            getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_ALLOW_WALLBOX_RESET', False)
        )

        self.min_fail_age_s = int(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_MIN_FAIL_AGE_S', 900))
        self.error_threshold = int(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_ERROR_THRESHOLD', 8))
        self.cooldown_s = int(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_COOLDOWN_S', 21600))
        self.max_actions_per_day = int(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_MAX_ACTIONS_PER_DAY', 1))
        self.min_recovery_power_w = float(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_ACTIVE_POWER_W', 500.0))
        self.reset_timer_ms = int(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_RESET_TIMER_MS', 10000))

        default_state = os.path.join(app_config.BASE_DIR, 'config', 'wattpilot_recovery_state.json')
        self.state_file = str(getattr(app_config, 'WATTPILOT_AUTO_RECOVERY_STATE_FILE', default_state))

    def evaluate_and_recover(self, attachment: dict) -> Optional[str]:
        """Prüft Trigger und führt ggf. genau eine Recovery-Aktion aus.

        Returns:
            String mit Aktions-Info bei ausgefuehrter Recovery, sonst None.
        """
        if not self.enabled or self.mode in ('', 'disabled', 'off', 'none'):
            return None
        if not isinstance(attachment, dict) or not attachment:
            return None

        triggered, reason = self._should_trigger(attachment)
        if not triggered:
            return None

        state = self._load_state()
        blocked, block_reason = self._rate_limited(state)
        if blocked:
            LOG.info(f"Wattpilot-Recovery unterdrueckt: {block_reason}")
            return None

        charging, charging_reason = self._is_active_charging()
        if charging:
            LOG.info(f"Wattpilot-Recovery unterdrueckt: {charging_reason}")
            return None

        ok, action_detail = self._execute_action(reason)
        now = int(time.time())

        self._store_state(
            state=state,
            now_ts=now,
            success=ok,
            mode=self.mode,
            trigger_reason=reason,
            detail=action_detail,
        )

        if ok:
            msg = f"auto-recovery ausgefuehrt ({self.mode}): {action_detail}"
            LOG.warning(f"Wattpilot {msg}")
            return msg

        LOG.error(f"Wattpilot auto-recovery fehlgeschlagen ({self.mode}): {action_detail}")
        return None

    def _should_trigger(self, attachment: dict) -> Tuple[bool, str]:
        poll_age = attachment.get('last_poll_age_s')
        consecutive_errors = int(attachment.get('consecutive_errors') or 0)
        reconnect = attachment.get('last_reconnect') or {}

        if poll_age is not None and int(poll_age) >= self.min_fail_age_s:
            return True, f'poll_age={int(poll_age)}s'

        if consecutive_errors >= self.error_threshold:
            return True, f'consecutive_errors={consecutive_errors}'

        if reconnect and not reconnect.get('success', True):
            ts = reconnect.get('ts')
            if ts and (int(time.time()) - int(ts)) <= self.min_fail_age_s:
                return True, 'recent_reconnect_failed'

        return False, ''

    def _rate_limited(self, state: dict) -> Tuple[bool, str]:
        now = int(time.time())
        last_ts = int(state.get('last_action_ts') or 0)
        if last_ts and (now - last_ts) < self.cooldown_s:
            return True, f'cooldown aktiv ({now - last_ts}s < {self.cooldown_s}s)'

        today = date.today().isoformat()
        per_day = state.get('actions_per_day') or {}
        count_today = int(per_day.get(today) or 0)
        if count_today >= self.max_actions_per_day:
            return True, f'tageslimit erreicht ({count_today}/{self.max_actions_per_day})'

        return False, ''

    def _is_active_charging(self) -> Tuple[bool, str]:
        """Nutze vorhandene DB-Daten (kein zusaetzlicher WebSocket-Read)."""
        db_path = app_config.DB_PATH
        if not os.path.exists(db_path):
            return False, 'db nicht vorhanden'

        try:
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=3)
            row = conn.execute(
                """
                SELECT ts, COALESCE(power_w, 0), COALESCE(car_state, 0)
                FROM wattpilot_readings
                ORDER BY ts DESC
                LIMIT 1
                """
            ).fetchone()
            conn.close()
        except sqlite3.Error as exc:
            return False, f'car-state unbekannt (db-fehler: {exc})'

        if not row:
            return False, 'keine wattpilot_readings vorhanden'

        ts, power_w, car_state = int(row[0]), float(row[1]), int(row[2])
        age_s = int(time.time()) - ts
        if age_s > 300:
            return False, f'car-state veraltet ({age_s}s)'

        if car_state == 2:
            return True, 'aktive ladung (car_state=2)'
        if power_w >= self.min_recovery_power_w:
            return True, f'aktive ladung (power_w={power_w:.0f})'

        return False, 'keine aktive ladung'

    def _execute_action(self, trigger_reason: str) -> Tuple[bool, str]:
        if self.mode == 'collector_restart':
            return self._restart_collector()

        if self.mode == 'wallbox_reset':
            if not self.allow_wallbox_reset:
                return False, 'wallbox_reset nicht freigegeben (ALLOW_WALLBOX_RESET=False)'
            return self._reset_wallbox(trigger_reason)

        return False, f'unbekannter recovery-mode: {self.mode}'

    def _restart_collector(self) -> Tuple[bool, str]:
        commands = [
            ['systemctl', 'restart', 'pv-wattpilot.service'],
            ['sudo', '-n', 'systemctl', 'restart', 'pv-wattpilot.service'],
        ]
        last_err = ''
        for cmd in commands:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_err = str(exc)
                continue
            if proc.returncode == 0:
                return True, f"{' '.join(cmd)} ok"
            last_err = (proc.stderr or proc.stdout or '').strip() or f'rc={proc.returncode}'

        return False, f'collector restart fehlgeschlagen: {last_err}'

    def _reset_wallbox(self, trigger_reason: str) -> Tuple[bool, str]:
        try:
            from wattpilot_api import WattpilotClient
            client = WattpilotClient()
            result = client.set_value('rbt', self.reset_timer_ms)
        except Exception as exc:
            return False, f'rbt-write exception: {exc}'

        if result.get('ok'):
            return True, (
                f"rbt={self.reset_timer_ms}ms gesendet "
                f"(trigger={trigger_reason}; detail={result.get('detail', 'ok')})"
            )

        return False, f"rbt-write abgelehnt: {result.get('detail', 'unbekannt')}"

    def _load_state(self) -> dict:
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _store_state(
        self,
        state: dict,
        now_ts: int,
        success: bool,
        mode: str,
        trigger_reason: str,
        detail: str,
    ):
        per_day = dict(state.get('actions_per_day') or {})
        today = date.today().isoformat()
        per_day[today] = int(per_day.get(today) or 0) + 1

        # Cleanup: nur letzte 14 Tage behalten
        keep_days = sorted(per_day.keys())[-14:]
        per_day = {k: per_day[k] for k in keep_days}

        payload = {
            'last_action_ts': now_ts,
            'last_action_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now_ts)),
            'last_success': bool(success),
            'last_mode': mode,
            'last_trigger': trigger_reason,
            'last_detail': detail,
            'actions_per_day': per_day,
        }

        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
