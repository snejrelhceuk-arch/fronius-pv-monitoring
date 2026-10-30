#!/usr/bin/env python3
"""set_smtp_password.py — SMTP-Passwort host-lokal im Credential-Store setzen.

Das Passwort wird AES-/Fernet-verschlüsselt (an die /etc/machine-id des Hosts
gebunden) unter /etc/pv-system/smtp_pass.key abgelegt. Es wird NICHT im Repo
gespeichert und NICHT per Code-Sync übertragen — darum einmal pro Host setzen.

Aufruf (root nötig für /etc/pv-system/):
    sudo .venv/bin/python scripts/set_smtp_password.py

Lesen/Nutzen: automation (event_notifier), diagnos (health),
failover_health_check.sh — alle via automation.engine.credential_store.
"""
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from automation.engine import credential_store  # noqa: E402


def main() -> int:
    if credential_store.existiert('smtp_pass'):
        print("Hinweis: Es ist bereits ein smtp_pass gesetzt — wird überschrieben.")
    pw1 = getpass.getpass('SMTP-Passwort: ')
    if not pw1:
        print("Abbruch: leeres Passwort.", file=sys.stderr)
        return 1
    pw2 = getpass.getpass('Wiederholen:   ')
    if pw1 != pw2:
        print("Abbruch: Passwörter stimmen nicht überein.", file=sys.stderr)
        return 1
    try:
        ziel = credential_store.speichere('smtp_pass', pw1)
    except PermissionError:
        print("Fehlende Rechte für /etc/pv-system/ — bitte mit sudo ausführen.",
              file=sys.stderr)
        return 1
    print(f"✓ Gespeichert (verschlüsselt): {ziel}")
    print("  Test: pv-config → Benachrichtigungen → Test-Mail, "
          "oder Automation/Diagnos-Mail abwarten.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
