"""
Host-Rolle erkennen — zentrale Prüfung für alle Python-Scripts.

Nutzung:
    from host_role import ROLE, is_primary, is_failover, require_primary

    if is_failover():
        sys.exit(0)   # Nichts tun auf Failover-Host

Die Rolle wird aus der Datei .role im Repo-Root gelesen (gitignored).
Fehlt die Datei, gilt der Host als "primary" (sicherer Default).

Siehe doc/DUAL_HOST_ARCHITECTURE.md für Details.
"""
import os
import sys

VALID_ROLES = ('primary', 'failover', 'tech', 'kueche')
UNKNOWN_ROLE = 'unknown'

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROLE_FILE = os.path.join(_BASE_DIR, '.role')


def get_role() -> str:
    """Liest die Host-Rolle aus .role (primary|failover|tech|kueche)."""
    if os.path.exists(_ROLE_FILE):
        with open(_ROLE_FILE) as f:
            role = f.readline().strip().lower()
            if role in VALID_ROLES:
                return role
            return UNKNOWN_ROLE
    return 'primary'


ROLE = get_role()


def is_primary() -> bool:
    return ROLE == 'primary'


def is_failover() -> bool:
    return ROLE == 'failover'


def is_tech() -> bool:
    return ROLE == 'tech'


def is_kueche() -> bool:
    return ROLE == 'kueche'


def require_role(*roles: str) -> None:
    allowed = {r.lower() for r in roles}
    if ROLE not in allowed:
        print(f"role={ROLE} -> required one of: {', '.join(sorted(allowed))}", file=sys.stderr)
        raise SystemExit(1)


def require_primary() -> None:
    require_role('primary')
