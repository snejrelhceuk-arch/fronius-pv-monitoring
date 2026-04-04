#!/usr/bin/env python3
"""
diagnos/health.py — Phase-1 Read-only Health-Checks

Schicht D: strikt unabhängig von A/B/C.
Ausgabe: JSON auf stdout, Warnungen auf stderr.

Nutzung:
    python3 -m diagnos.health              # alle Checks
    python3 -m diagnos.health --pretty     # menschenlesbar
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from glob import glob
from datetime import datetime, timezone
from typing import List, Optional

from diagnos.config import (
    BACKUP_CRIT_HOURS,
    BACKUP_WARN_HOURS,
    CPU_TEMP_CRIT_C, CPU_TEMP_WARN_C,
    CRIT, DB_PATH, DISK_CRIT_PCT, DISK_WARN_PCT, FAIL,
    FRESHNESS_TABLES,
    FRESHNESS_CRIT_S, FRESHNESS_WARN_S,
    LOCAL_GFS_DAILY_GLOB,
    MIRROR_CRIT_S,
    MIRROR_SYNC_MARKER,
    MIRROR_WARN_S,
    OK, RAM_WARN_PCT, SERVICES, WARN,
    ROLE_FILE,
)

# ═══════════════════════════════════════════════════════════
# Hilfs-Funktionen
# ═══════════════════════════════════════════════════════════

def _run(cmd: List[str], timeout: int = 5) -> Optional[str]:
    """Subprocess-Aufruf mit Timeout, gibt stdout oder None zurück."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _classify(value: float, warn: float, crit: float) -> str:
    """Schwellwert-Klassifikation (aufsteigend: ok < warn < crit)."""
    if value >= crit:
        return CRIT
    if value >= warn:
        return WARN
    return OK


# ═══════════════════════════════════════════════════════════
# Host-Checks
# ═══════════════════════════════════════════════════════════

def check_cpu_temp() -> dict:
    """CPU-Temperatur über thermal_zone0."""
    try:
        raw = open('/sys/class/thermal/thermal_zone0/temp').read().strip()
        temp_c = int(raw) / 1000.0
        return {
            'check': 'cpu_temp',
            'value_c': round(temp_c, 1),
            'severity': _classify(temp_c, CPU_TEMP_WARN_C, CPU_TEMP_CRIT_C),
        }
    except (OSError, ValueError) as exc:
        return {'check': 'cpu_temp', 'severity': FAIL, 'error': str(exc)}


def check_throttle() -> dict:
    """Raspberry Pi Throttle-Flags via vcgencmd."""
    raw = _run(['vcgencmd', 'get_throttled'])
    if raw is None:
        return {'check': 'throttle', 'severity': FAIL, 'error': 'vcgencmd nicht verfügbar'}

    # Format: throttled=0x50000
    m = re.search(r'0x([0-9a-fA-F]+)', raw)
    if not m:
        return {'check': 'throttle', 'severity': FAIL, 'error': f'Unerwartete Ausgabe: {raw}'}

    flags = int(m.group(1), 16)
    # Bit 0: Under-voltage detected
    # Bit 1: Arm frequency capped
    # Bit 2: Currently throttled
    # Bit 3: Soft temperature limit active
    active_now = flags & 0xF
    occurred   = (flags >> 16) & 0xF

    severity = OK
    if active_now:
        severity = CRIT
    elif occurred:
        severity = WARN

    return {
        'check': 'throttle',
        'hex': f'0x{flags:X}',
        'active_now': active_now,
        'occurred_since_boot': occurred,
        'severity': severity,
    }


def check_ram() -> dict:
    """RAM-Nutzung über /proc/meminfo."""
    try:
        info = {}
        with open('/proc/meminfo') as f:
            for line in f:
                parts = line.split()
                if parts[0] in ('MemTotal:', 'MemAvailable:'):
                    info[parts[0].rstrip(':')] = int(parts[1])  # kB
        total_kb = info['MemTotal']
        avail_kb = info['MemAvailable']
        used_pct = round((1 - avail_kb / total_kb) * 100, 1)
        return {
            'check': 'ram',
            'total_mb': round(total_kb / 1024),
            'available_mb': round(avail_kb / 1024),
            'used_pct': used_pct,
            'severity': _classify(used_pct, RAM_WARN_PCT, 95.0),
        }
    except (OSError, KeyError, ZeroDivisionError) as exc:
        return {'check': 'ram', 'severity': FAIL, 'error': str(exc)}


def check_disk() -> dict:
    """Root-Partition Belegung."""
    try:
        st = os.statvfs('/')
        total = st.f_blocks * st.f_frsize
        free  = st.f_bavail * st.f_frsize
        used_pct = round((1 - free / total) * 100, 1)
        return {
            'check': 'disk_root',
            'total_gb': round(total / 1e9, 1),
            'free_gb': round(free / 1e9, 1),
            'used_pct': used_pct,
            'severity': _classify(used_pct, DISK_WARN_PCT, DISK_CRIT_PCT),
        }
    except (OSError, ZeroDivisionError) as exc:
        return {'check': 'disk_root', 'severity': FAIL, 'error': str(exc)}


def check_load() -> dict:
    """System Load Average."""
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        # Warn wenn Load > Anzahl Cores, Crit wenn > 2x
        severity = _classify(load1, cpu_count * 1.0, cpu_count * 2.0)
        return {
            'check': 'load',
            'load_1m': round(load1, 2),
            'load_5m': round(load5, 2),
            'load_15m': round(load15, 2),
            'cpus': cpu_count,
            'severity': severity,
        }
    except OSError as exc:
        return {'check': 'load', 'severity': FAIL, 'error': str(exc)}


def check_uptime() -> dict:
    """System-Uptime."""
    try:
        raw = open('/proc/uptime').read().strip()
        uptime_s = float(raw.split()[0])
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        return {
            'check': 'uptime',
            'seconds': round(uptime_s),
            'human': f'{days}d {hours}h',
            'severity': OK,
        }
    except (OSError, ValueError) as exc:
        return {'check': 'uptime', 'severity': FAIL, 'error': str(exc)}


# ═══════════════════════════════════════════════════════════
# Service-Checks
# ═══════════════════════════════════════════════════════════

def check_service(unit: str) -> dict:
    """systemd Unit aktiv?"""
    raw = _run(['systemctl', 'is-active', unit])
    active = raw == 'active'
    return {
        'check': f'service:{unit}',
        'state': raw or 'unknown',
        'severity': OK if active else CRIT,
    }


def check_all_services() -> List[dict]:
    return [check_service(u) for u in SERVICES]


# ═══════════════════════════════════════════════════════════
# Daten-Freshness
# ═══════════════════════════════════════════════════════════

def _db_readonly():
    """SQLite read-only Verbindung. Gibt Connection oder None zurück."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        uri = f'file:{DB_PATH}?mode=ro'
        return sqlite3.connect(uri, uri=True, timeout=3)
    except sqlite3.Error:
        return None


def check_freshness(
    table: str = 'raw_data',
    ts_col: str = 'ts',
    warn_s: float = FRESHNESS_WARN_S,
    crit_s: float = FRESHNESS_CRIT_S,
) -> dict:
    """Alter des letzten Eintrags in einer Tabelle (ts = Unix-Epoch REAL)."""
    conn = _db_readonly()
    if conn is None:
        return {'check': f'freshness:{table}', 'severity': FAIL, 'error': 'DB nicht erreichbar'}

    try:
        row = conn.execute(
            f'SELECT MAX("{ts_col}") FROM "{table}"'   # noqa: S608 — table/col aus eigenem Code
        ).fetchone()

        if row is None or row[0] is None:
            return {'check': f'freshness:{table}', 'severity': CRIT, 'error': 'Keine Daten'}

        epoch = float(row[0])
        age_s = time.time() - epoch
        severity = OK
        if age_s > crit_s:
            severity = CRIT
        elif age_s > warn_s:
            severity = WARN

        return {
            'check': f'freshness:{table}',
            'last_epoch': epoch,
            'last_utc': datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'age_s': round(age_s),
            'severity': severity,
        }
    except (sqlite3.Error, ValueError) as exc:
        return {'check': f'freshness:{table}', 'severity': FAIL, 'error': str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _read_role() -> str:
    """Liest die lokale Host-Rolle aus .role (Fallback: primary)."""
    try:
        if not os.path.exists(ROLE_FILE):
            return 'primary'
        with open(ROLE_FILE, 'r', encoding='utf-8') as f:
            role = f.readline().strip().lower()
        return role if role in ('primary', 'failover') else 'primary'
    except OSError:
        return 'primary'


def check_mirror_sync_age() -> dict:
    """Prüft Alter des Mirror-Sync-Markers (nur für Failover relevant)."""
    role = _read_role()
    if role != 'failover':
        return {
            'check': 'mirror_sync_age',
            'role': role,
            'severity': OK,
            'skipped': True,
            'detail': 'nur auf failover relevant',
        }

    if not os.path.exists(MIRROR_SYNC_MARKER):
        return {
            'check': 'mirror_sync_age',
            'role': role,
            'severity': CRIT,
            'error': 'Sync-Marker fehlt',
        }

    try:
        age_s = time.time() - os.path.getmtime(MIRROR_SYNC_MARKER)
        return {
            'check': 'mirror_sync_age',
            'role': role,
            'age_s': round(age_s),
            'severity': _classify(age_s, MIRROR_WARN_S, MIRROR_CRIT_S),
        }
    except OSError as exc:
        return {'check': 'mirror_sync_age', 'role': role, 'severity': FAIL, 'error': str(exc)}


def check_local_gfs_backup_age() -> dict:
    """Prüft Alter des jüngsten lokalen GFS-Daily-Backups."""
    try:
        files = [p for p in glob(LOCAL_GFS_DAILY_GLOB) if os.path.isfile(p)]
        if not files:
            return {
                'check': 'backup_local_gfs_daily',
                'severity': WARN,
                'error': 'Kein lokales Daily-GFS-Backup gefunden',
            }

        newest = max(files, key=os.path.getmtime)
        age_h = (time.time() - os.path.getmtime(newest)) / 3600.0
        return {
            'check': 'backup_local_gfs_daily',
            'latest_file': os.path.basename(newest),
            'age_h': round(age_h, 1),
            'severity': _classify(age_h, BACKUP_WARN_HOURS, BACKUP_CRIT_HOURS),
        }
    except OSError as exc:
        return {'check': 'backup_local_gfs_daily', 'severity': FAIL, 'error': str(exc)}


# ═══════════════════════════════════════════════════════════
# Hauptlauf
# ═══════════════════════════════════════════════════════════

def run_all() -> dict:
    """Alle Phase-1-Checks ausführen, Ergebnis als dict."""
    checks = []

    # Host
    checks.append(check_cpu_temp())
    checks.append(check_throttle())
    checks.append(check_ram())
    checks.append(check_disk())
    checks.append(check_load())
    checks.append(check_uptime())

    # Services
    checks.extend(check_all_services())

    # Freshness
    for table, ts_col, warn_s, crit_s in FRESHNESS_TABLES:
        checks.append(check_freshness(table, ts_col, warn_s, crit_s))

    # Backup / Failover-Mirror
    checks.append(check_mirror_sync_age())
    checks.append(check_local_gfs_backup_age())

    # Gesamtbewertung
    severity_order = {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}
    worst = max(checks, key=lambda c: severity_order.get(c.get('severity', OK), 0))

    return {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'host': os.uname().nodename,
        'overall': worst['severity'],
        'checks': checks,
    }


def main():
    pretty = '--pretty' in sys.argv
    result = run_all()

    # JSON auf stdout
    indent = 2 if pretty else None
    print(json.dumps(result, indent=indent, ensure_ascii=False))

    # Warnungen auf stderr
    for c in result['checks']:
        sev = c.get('severity', OK)
        if sev in (WARN, CRIT, FAIL):
            print(f"[{sev.upper()}] {c['check']}: {c}", file=sys.stderr)

    # Exit-Code: 0=ok, 1=warn, 2=crit/fail
    if result['overall'] in (CRIT, FAIL):
        sys.exit(2)
    elif result['overall'] == WARN:
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
