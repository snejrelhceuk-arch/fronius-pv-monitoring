#!/usr/bin/env python3
"""
tools/pv_config/service.py — Service-Steuerung fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-06-29): Daemon-Reload
(SIGHUP -> Matrix-Reload) und Ownership-Fix nach sudo.
"""
from __future__ import annotations

import os
import signal

from tools.pv_config.common import PROJECT_ROOT

_DAEMON_PID_FILE = os.path.join(PROJECT_ROOT, 'automation_daemon.pid')


def _notify_daemon_reload():
    """SIGHUP an Automation-Daemon senden → Matrix-Reload."""
    try:
        if not os.path.exists(_DAEMON_PID_FILE):
            return
        with open(_DAEMON_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGHUP)
    except (ValueError, ProcessLookupError, PermissionError):
        pass


def _fix_ownership(path: str):
    """Datei-Owner auf SUDO_USER zurücksetzen wenn unter sudo gelaufen.

    Verhindert root:root-Ownership bei Config-Dateien die mit
    sudo python3 pv-config.py geschrieben werden.
    """
    sudo_uid = os.environ.get('SUDO_UID')
    sudo_gid = os.environ.get('SUDO_GID')
    if sudo_uid and sudo_gid:
        try:
            os.chown(path, int(sudo_uid), int(sudo_gid))
        except OSError:
            pass
