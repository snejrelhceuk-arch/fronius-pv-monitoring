"""
Diagnos-Konfiguration — Schicht D
Eigene Konstanten, keine Imports aus A/B/C.
"""

import os

# ── Datenbank (read-only) ──────────────────────────────────
DB_PATH = '/dev/shm/fronius_data.db'

# ── Rollen-/Statusmarker (read-only) ───────────────────────
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ROLE_FILE = os.path.join(BASE_DIR, '.role')
MIRROR_SYNC_MARKER = os.path.join(BASE_DIR, '.state', 'last_mirror_sync.ok')

# ── Backup-Pfade (read-only) ────────────────────────────────
LOCAL_GFS_DAILY_GLOB = os.path.join(BASE_DIR, 'backup', 'db', 'daily', '*.gz')

# ── Services (systemd unit names) ──────────────────────────
SERVICES = [
    'pv-collector.service',
    'pv-web.service',
    'pv-automation.service',
    'pv-wattpilot.service',
]

# ── Schwellwerte ───────────────────────────────────────────
# Host
CPU_TEMP_WARN_C     = 75.0
CPU_TEMP_CRIT_C     = 80.0
RAM_WARN_PCT        = 85.0
DISK_WARN_PCT       = 80.0
DISK_CRIT_PCT       = 90.0

# Freshness (Sekunden seit letztem Eintrag)
FRESHNESS_WARN_S    = 120    # 2 min
FRESHNESS_CRIT_S    = 600    # 10 min

# Weitere tabellenbasierte Freshness-Checks
# Format: (table, ts_col, warn_s, crit_s)
FRESHNESS_TABLES = [
    ('raw_data', 'ts', 120, 600),           # 2/10 min
    ('data_1min', 'ts', 180, 900),          # 3/15 min
    ('data_15min', 'ts', 1800, 5400),       # 30/90 min
    ('daily_data', 'ts', 129600, 216000),   # 36/60 h
]

# Mirror-Sync (nur auf Failover relevant)
MIRROR_WARN_S = 900          # 15 min
MIRROR_CRIT_S = 1800         # 30 min

# Lokales GFS-Backup-Alter (daily/*.gz)
BACKUP_WARN_HOURS = 30.0
BACKUP_CRIT_HOURS = 48.0

# ── Ausgabe ────────────────────────────────────────────────
# Severity-Stufen
OK   = 'ok'
WARN = 'warn'
CRIT = 'crit'
FAIL = 'fail'   # Check selbst fehlgeschlagen
