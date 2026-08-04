#!/usr/bin/env python3
"""scripts/pv_weekly_maintenance_report.py — Woechentlicher Update-Melder (per Mail).

Defensiv, non-interaktiv: sammelt verfuegbare apt- und (falls vorhanden) pip-Updates
und schickt eine Info-Mail mit Handlungsanweisung ueber denselben SMTP-Pfad wie das
Produktivsystem (``config.NOTIFICATION_*`` + verschluesselter ``credential_store``).

Bewusst KEIN Auto-Upgrade: app-kritische Pakete + pip-Pins werden nur GEMELDET,
angewendet wird via bestaetigtem ``scripts/pv_maintenance_upgrade.sh`` (Rueckfrage).
Jeder Fehler fuehrt zu sauberem Exit 0 (Timer soll nie „failed" melden).

Aufruf: ``.venv/bin/python scripts/pv_weekly_maintenance_report.py [--force]``
``--force`` schickt die Mail auch ohne anstehende Updates (Test/Heartbeat).
"""
from __future__ import annotations

import os
import socket
import smtplib
import ssl
import subprocess
import sys
from datetime import date
from email.message import EmailMessage

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Robust gegen kaputte System-Locale (LC_ALL=de_DE -> latin-1): stdout/err utf-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 120) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or '').strip()
    except Exception:
        return ''


def _apt_upgradable() -> list[str]:
    raw = _run(['apt-get', '-s', 'dist-upgrade'])  # simulate, kein Root noetig
    pkgs = []
    for line in raw.splitlines():
        if line.startswith('Inst '):
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(parts[1])
    return sorted(set(pkgs))


def _pip_outdated() -> list[str]:
    pip = os.path.join(REPO_ROOT, '.venv', 'bin', 'pip')
    if not os.path.exists(pip):
        return []
    raw = _run([pip, 'list', '--outdated', '--format=columns'])
    lines = raw.splitlines()
    # Kopf (2 Zeilen) ueberspringen; nur "Paket alt -> neu"
    out = []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) >= 3:
            out.append(f'{parts[0]} {parts[1]} -> {parts[2]}')
    return out


def _host_label() -> str:
    role = ''
    try:
        with open(os.path.join(REPO_ROOT, '.role')) as f:
            role = f.read().strip()
    except OSError:
        pass
    host = socket.gethostname()
    return f'{host} ({role})' if role else host


def _send_mail(subject: str, body: str, timeout: float = 12.0) -> bool:
    """Versendet ueber den Produktiv-SMTP-Pfad. Vollstaendig defensiv."""
    try:
        import config
    except Exception:
        return False
    recipient = getattr(config, 'NOTIFICATION_EMAIL', '') or ''
    smtp_host = getattr(config, 'NOTIFICATION_SMTP_HOST', '') or ''
    smtp_port = getattr(config, 'NOTIFICATION_SMTP_PORT', 465)
    smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', '') or ''
    smtp_from = getattr(config, 'NOTIFICATION_FROM', smtp_user) or smtp_user
    if not recipient or not smtp_host or smtp_host.endswith('.invalid'):
        return False
    smtp_pass = None
    try:
        from automation.engine import credential_store
        smtp_pass = credential_store.lade('smtp_pass')
    except Exception:
        smtp_pass = None
    if smtp_user and not smtp_pass:
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = smtp_from
    msg['To'] = recipient
    msg['X-PV-Event'] = 'maintenance_report'
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ctx) as srv:
            if smtp_user and smtp_pass:
                srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return True
    except Exception:
        return False


def main() -> int:
    force = '--force' in sys.argv[1:]
    apt_pkgs = _apt_upgradable()
    pip_pkgs = _pip_outdated()

    if not apt_pkgs and not pip_pkgs and not force:
        print('Keine anstehenden Updates — keine Mail.')
        return 0

    host = _host_label()
    lines = [
        f'PV-System Wartungs-Report -- {host}',
        f'Datum: {date.today().isoformat()}',
        '',
        f'APT-Updates verfuegbar: {len(apt_pkgs)}',
    ]
    if apt_pkgs:
        lines += ['  ' + p for p in apt_pkgs[:60]]
        if len(apt_pkgs) > 60:
            lines.append(f'  ... (+{len(apt_pkgs) - 60} weitere)')
    lines += ['', f'PIP-Updates im venv verfuegbar: {len(pip_pkgs)}']
    if pip_pkgs:
        lines += ['  ' + p for p in pip_pkgs]
    lines += [
        '',
        '-' * 56,
        'ANWENDEN (bewusst manuell/bestaetigt, kein Auto-Upgrade):',
        '',
        f'  cd {REPO_ROOT}',
        '  sudo bash scripts/pv_maintenance_upgrade.sh',
        '',
        'Das Skript sichert zuerst die tmpfs-DB, zieht dann per bestaetigtem',
        '`apt full-upgrade` auch die app-kritischen Pakete (python/sqlite/kernel)',
        'mit, zeigt pip-Updates nur als Report (pins bleiben manuell) und weist',
        'auf einen noetigen Reboot hin (Reboot NICHT automatisch).',
        '',
        'Security-Updates laufen bereits unbeaufsichtigt (unattended-upgrades).',
    ]
    body = '\n'.join(lines)
    print(body)

    if _send_mail(f'[PV-Wartung] {host}: {len(apt_pkgs)} apt-, {len(pip_pkgs)} pip-Updates', body):
        print('\nMail versendet.')
    else:
        print('\nMail NICHT versendet (SMTP nicht konfiguriert/erreichbar) -- Report nur im Log.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
