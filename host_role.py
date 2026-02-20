"""
Host-Rolle erkennen — zentrale Prüfung für alle Python-Scripts.

Nutzung:
    from host_role import ROLE, is_primary, is_failover

    if is_failover():
        sys.exit(0)   # Nichts tun auf Failover-Host

Die Rolle wird aus der Datei .role im Repo-Root gelesen (gitignored).
Fehlt die Datei, gilt der Host als "primary" (sicherer Default).

Siehe doc/DUAL_HOST_ARCHITECTURE.md für Details.
"""
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROLE_FILE = os.path.join(_BASE_DIR, '.role')


def get_role() -> str:
    """Liest die Host-Rolle aus .role (primary|failover)."""
    if os.path.exists(_ROLE_FILE):
        with open(_ROLE_FILE) as f:
            role = f.readline().strip().lower()
            if role in ('primary', 'failover'):
                return role
    return 'primary'


ROLE = get_role()


def is_primary() -> bool:
    return ROLE == 'primary'


def is_failover() -> bool:
    return ROLE == 'failover'
