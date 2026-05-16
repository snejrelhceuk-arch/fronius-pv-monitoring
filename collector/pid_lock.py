"""
collector.pid_lock — Single-Instance-Schutz fuer den Modbus-Collector.

Extrahiert aus modbus_v3.py (Refactor 2026-05-16). Verhindert Doppelstart
und entfernt stale PID-Files. atexit-Cleanup haengt am Prozess-Tod.
"""

import atexit
import logging
import os
import sys

import config

PID_FILE = config.PID_FILE


def _is_collector_process(pid):
    """Prueft ob der Prozess mit dieser PID tatsaechlich ein Collector ist."""
    try:
        with open(f'/proc/{pid}/cmdline', 'r') as f:
            cmdline = f.read()
        return 'collector.py' in cmdline or 'modbus_v3' in cmdline or 'collector/' in cmdline
    except (FileNotFoundError, PermissionError):
        return False


def create_pid_file():
    """Erstellt PID-File und prueft auf laufende Instanz."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())

            try:
                os.kill(old_pid, 0)
                if _is_collector_process(old_pid):
                    print(f"[ERROR] collector.py laeuft bereits (PID {old_pid})")
                    print(f"   Beenden Sie den Prozess mit: kill {old_pid}")
                    print(f"   Oder erzwingen Sie Start mit: rm {PID_FILE}")
                    sys.exit(1)
                else:
                    print(f"[WARN] PID {old_pid} lebt, ist aber kein Collector — entferne stale PID-File")
                    os.remove(PID_FILE)
            except OSError:
                print(f"[WARN] Entferne verwaistes PID-File (PID {old_pid} existiert nicht)")
                os.remove(PID_FILE)
        except (ValueError, FileNotFoundError):
            os.remove(PID_FILE)

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    atexit.register(remove_pid_file)
    print(f"[OK] PID-File erstellt: {PID_FILE} (PID {os.getpid()})")


def remove_pid_file():
    """Entfernt PID-File beim sauberen Beenden."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(PID_FILE)
                print("[OK] PID-File entfernt")
        except Exception as e:
            logging.debug(f"PID-File Cleanup: {e}")
