"""Geteilte Konstanten und Read-Helfer fuer das pac4200-Blueprint (Rolle B).

Aufgeteilt aus der frueheren Monolith-Datei ``routes/pac4200.py`` (2026-09-28).
NQ-DB-Verzeichnisse, Plausibilitaetsgrenzen und die read-only Legacy-/Primary-
DB-Oeffner, die von mehreren Submodulen genutzt werden.
"""
import os
import sqlite3
import time as _time
from datetime import datetime, timedelta

import config

# Legacy NQ DB-Verzeichnis
_NQ_LEGACY_DIR = os.path.join(config.BASE_DIR, 'nq', 'legacy', 'db')
# Neue PAC4200 NQ DB-Verzeichnis
_NQ_PRIMARY_DIR = os.path.join(config.BASE_DIR, 'nq', 'db')

# Plausibilitätsgrenzen (nq_samples: L-L-Spannungen ~400–420 V)
_F_MIN, _F_MAX = 49.0, 51.0
_U_MIN, _U_MAX = 350.0, 460.0


def _legacy_dbs_for_days(days: int) -> list[str]:
    """Listet Legacy-NQ-DB-Pfade (nq_YYYY-MM.db) auf, die die letzten `days` Tage abdecken."""
    needed: set[str] = set()
    d = datetime.now()
    for _ in range(days + 32):
        needed.add(os.path.join(_NQ_LEGACY_DIR, f"nq_{d.strftime('%Y-%m')}.db"))
        d -= timedelta(days=1)
        if len(needed) > 12:
            break
    return sorted(p for p in needed if os.path.exists(p))


def _open_legacy(path: str) -> sqlite3.Connection | None:
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:
        return None


def _ts_window(days: int) -> tuple[int, int]:
    end = int(_time.time())
    start = end - days * 86400
    return start, end


def _nq_primary_db(month: str) -> str:
    return os.path.join(_NQ_PRIMARY_DIR, f"nq_{month}.db")
