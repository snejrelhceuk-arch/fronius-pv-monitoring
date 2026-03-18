"""
Diagnos-Konfiguration — Schicht D
Eigene Konstanten, keine Imports aus A/B/C.
"""

# ── Datenbank (read-only) ──────────────────────────────────
DB_PATH = '/dev/shm/fronius_data.db'

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

# ── Ausgabe ────────────────────────────────────────────────
# Severity-Stufen
OK   = 'ok'
WARN = 'warn'
CRIT = 'crit'
FAIL = 'fail'   # Check selbst fehlgeschlagen
