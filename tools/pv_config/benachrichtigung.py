#!/usr/bin/env python3
"""
tools/pv_config/benachrichtigung.py — E-Mail-Benachrichtigungs-Menue fuer pv-config

Extrahiert aus pv-config.py (Architektur-Refactor 2026-09-28): Event-Auswahl,
Test-Mail-Versand (SMTP, Passwort verschluesselt via credential_store),
Empfaenger-/SMTP-Passwort-Pflege und config.py-Zeilen-Update.
"""
from __future__ import annotations

import os

import config
from tools.pv_config.common import (
    WT_H, WT_W, WT_LIST_H,
    PROJECT_ROOT,
    _wt, wt_menu, wt_msgbox,
)


# ═══════════════════════════════════════════════════════════════
# Benachrichtigungen (E-Mail)
# ═══════════════════════════════════════════════════════════════

def menu_benachrichtigung():
    """E-Mail-Benachrichtigungen konfigurieren.

    Zeigt aktive Events, erlaubt Ein/Ausschalten und Test-Mail.
    SMTP-Passwort wird verschlüsselt in /etc/pv-system/smtp_pass.key gespeichert.
    """
    from automation.engine import credential_store

    while True:
        # Aktuelle Config
        email = getattr(config, 'NOTIFICATION_EMAIL', '(nicht konfiguriert)')
        smtp_host = getattr(config, 'NOTIFICATION_SMTP_HOST', 'smtp.example.invalid')
        smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', '')
        events = getattr(config, 'NOTIFICATION_EVENTS', [])
        thresholds = getattr(config, 'EVENT_THRESHOLDS', {})

        # Passwort-Status
        pw_status = '✓ gesetzt' if credential_store.existiert('smtp_pass') else '✗ FEHLT'

        # Status-Text
        lines = [f'Empfänger:  {email}',
                 f'SMTP:       {smtp_host}:{getattr(config, "NOTIFICATION_SMTP_PORT", 465)}',
                 f'Benutzer:   {smtp_user}',
                 f'Passwort:   {pw_status} (verschlüsselt in /etc/pv-system/)',
                 '',
                 'Aktive Events:']
        if events:
            for ev in events:
                t = thresholds.get(ev, {})
                text = t.get('text', ev)
                feld = t.get('obs_feld', '?')
                op = t.get('op', '?')
                sw = t.get('schwelle', '?')
                lines.append(f'  ✓ {ev}: {text} ({feld} {op} {sw})')
        else:
            lines.append('  (keine)')
        lines.append('')
        lines.append('Verfügbare Events:')
        for key, t in thresholds.items():
            marker = '✓' if key in events else '○'
            lines.append(f'  {marker} {key}: {t.get("text", key)}')

        body = '\n'.join(lines)

        choice = wt_menu(body, [
            ('1', 'Events ein/ausschalten'),
            ('2', 'Test-Mail senden'),
            ('3', 'Empfänger ändern'),
            ('4', 'SMTP-Passwort setzen'),
            ('z', 'Zurück'),
        ])

        if choice is None or choice == 'z':
            break

        elif choice == '1':
            _menu_benachrichtigung_events(thresholds, events)

        elif choice == '2':
            _menu_benachrichtigung_test(email, smtp_host)

        elif choice == '3':
            _menu_benachrichtigung_email()

        elif choice == '4':
            _menu_benachrichtigung_password()


def _menu_benachrichtigung_events(thresholds: dict, aktive: list):
    """Events ein/ausschalten (Checklist)."""
    args = ['--checklist', 'Events ein/ausschalten:',
            str(WT_H), str(WT_W), str(WT_LIST_H)]
    for key, t in thresholds.items():
        text = t.get('text', key)
        status = 'ON' if key in aktive else 'OFF'
        args.extend([key, text, status])
    rc, selected = _wt(args)
    if rc != 0:
        return
    # Ergebnis: "key1" "key2" ... → parsen
    neue_events = [s.strip('"') for s in selected.split() if s.strip('"')]
    # config.py aktualisieren
    _update_config_line('NOTIFICATION_EVENTS', repr(neue_events))
    # Live-Objekt aktualisieren
    config.NOTIFICATION_EVENTS = neue_events
    wt_msgbox(f'Events aktualisiert:\n\n{", ".join(neue_events) or "(keine)"}')


def _menu_benachrichtigung_test(email: str, smtp_host: str):
    """Test-Mail senden — über konfigurierten SMTP-Server mit verschlüsseltem Passwort."""
    if not email:
        wt_msgbox('Kein Empfänger konfiguriert.\n\nBitte zuerst Empfänger setzen.')
        return

    from automation.engine import credential_store
    smtp_pass = credential_store.lade('smtp_pass')
    smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', '')

    if smtp_user and not smtp_pass:
        wt_msgbox('SMTP-Passwort nicht gesetzt.\n\n'
                   'Bitte zuerst über Menüpunkt 4 setzen.')
        return

    try:
        import smtplib
        from email.mime.text import MIMEText
        import socket

        hostname = socket.gethostname()
        sender = getattr(config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
        port = getattr(config, 'NOTIFICATION_SMTP_PORT', 465)

        msg = MIMEText(
            f'Test-Mail von {hostname}\n\n'
            f'E-Mail-Versand funktioniert.\n'
            f'Konfiguriert für: {email}\n'
            f'SMTP: {smtp_host}:{port} (User: {smtp_user})\n',
            'plain', 'utf-8'
        )
        msg['Subject'] = '[PV-Automation] Test-Mail'
        msg['From'] = sender
        msg['To'] = email

        if port == 465:
            smtp = smtplib.SMTP_SSL(smtp_host, port, timeout=15)
        else:
            smtp = smtplib.SMTP(smtp_host, port, timeout=15)
            if port == 587:
                smtp.starttls()

        if smtp_user and smtp_pass:
            smtp.login(smtp_user, smtp_pass)

        smtp.sendmail(sender, [email], msg.as_string())
        smtp.quit()
        wt_msgbox(f'Test-Mail gesendet an:\n{email}\n\nSMTP: {smtp_host}:{port}')
    except Exception as e:
        wt_msgbox(f'Fehler beim Senden:\n\n{str(e)[:300]}')


def _menu_benachrichtigung_email():
    """Empfänger-Adresse ändern."""
    aktuell = getattr(config, 'NOTIFICATION_EMAIL', '')
    rc, neue = _wt(['--inputbox', 'E-Mail-Adresse für Benachrichtigungen:',
                     '10', str(WT_W), aktuell])
    if rc != 0 or not neue.strip():
        return
    neue = neue.strip()
    _update_config_line('NOTIFICATION_EMAIL', repr(neue))
    config.NOTIFICATION_EMAIL = neue
    wt_msgbox(f'Empfänger gesetzt:\n{neue}')


def _menu_benachrichtigung_password():
    """SMTP-Passwort verschlüsselt speichern (Machine-ID-gebunden).

    Das Passwort wird NICHT in config.py abgelegt, sondern
    AES-verschlüsselt in /etc/pv-system/smtp_pass.key.
    Entschlüsselung nur auf diesem Pi möglich.
    """
    from automation.engine import credential_store

    aktuell_status = 'gesetzt' if credential_store.existiert('smtp_pass') else 'nicht gesetzt'
    smtp_user = getattr(config, 'NOTIFICATION_SMTP_USER', 'alerts@example.invalid')

    rc, passwort = _wt([
        '--passwordbox',
        f'SMTP-Passwort für {smtp_user}\n'
        f'(aktuell: {aktuell_status})\n\n'
        f'Das Passwort wird AES-verschlüsselt in\n'
        f'/etc/pv-system/smtp_pass.key gespeichert.\n'
        f'Entschlüsselung nur auf diesem Pi möglich.',
        '16', str(WT_W),
    ])
    if rc != 0 or not passwort.strip():
        return

    passwort = passwort.strip()

    try:
        pfad = credential_store.speichere('smtp_pass', passwort)
        wt_msgbox(
            f'SMTP-Passwort verschlüsselt gespeichert:\n'
            f'{pfad}\n\n'
            f'Verschlüsselung: AES-128 (Fernet)\n'
            f'Schlüssel: Machine-ID-gebunden (PBKDF2)\n\n'
            f'Tipp: Test-Mail senden um Zustellung zu prüfen.'
        )
    except PermissionError:
        wt_msgbox(
            'Fehler: Keine Schreibrechte auf /etc/pv-system/.\n\n'
            'pv-config muss als root laufen:\n'
            '  sudo python3 pv-config.py'
        )
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern:\n\n{str(e)[:300]}')


def _update_config_line(key: str, new_value: str):
    """Einzelne Zeile in config.py aktualisieren (Key = Value)."""
    config_path = os.path.join(PROJECT_ROOT, 'config.py')
    try:
        with open(config_path, 'r') as f:
            lines = f.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key} ') or line.startswith(f'{key}='):
                lines[i] = f'{key} = {new_value}\n'
                found = True
                break
        if not found:
            lines.append(f'{key} = {new_value}\n')
        with open(config_path, 'w') as f:
            f.writelines(lines)
    except Exception as e:
        wt_msgbox(f'Fehler beim Speichern von config.py:\n\n{str(e)[:200]}')
