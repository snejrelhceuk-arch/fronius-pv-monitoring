"""
credential_store.py — Verschlüsselter Credential-Store (Machine-ID-gebunden)

Speichert Geheimnisse (z.B. SMTP-Passwort) AES-verschlüsselt in
/etc/pv-system/. Der Schlüssel wird aus /etc/machine-id abgeleitet,
so dass die verschlüsselte Datei auf keinem anderen Host entschlüsselt
werden kann.

Ablage:  /etc/pv-system/<name>.key   (root:root 0600)
Schlüssel: PBKDF2-HMAC-SHA256(machine-id, salt=festes Projekt-Salt)
           → Fernet-Key (AES-128-CBC + HMAC-SHA256)

Nutzung:
    from automation.engine.credential_store import speichere, lade

    speichere('smtp_pass', 'geheimesPasswort')    # schreibt /etc/pv-system/smtp_pass.key
    pw = lade('smtp_pass')                         # liest + entschlüsselt → str | None

Hinweis: speichere() braucht root-Rechte (für /etc/pv-system/).
         lade() braucht Leserechte auf die .key-Datei.
         Der Daemon läuft als root → beides OK.

Sicherheitsmodell:
  ✅ Geschützt gegen: Git-Leak, Backup-Diebstahl, SD-Card-Klon auf anderen Pi
  ⚠️  Nicht geschützt gegen: Root-Zugriff auf dem SELBEN Pi (unvermeidbar)

Siehe: doc/AUTOMATION_ARCHITEKTUR.md
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

LOG = logging.getLogger('credential_store')

# Festes Verzeichnis außerhalb des Repos
STORE_DIR = Path('/etc/pv-system')

# Projekt-Salt (darf öffentlich sein — verhindert Rainbow-Tables)
_PROJECT_SALT = b'pv-system-hekabe-2026'


def _machine_id() -> bytes:
    """Lese /etc/machine-id (128-bit hex, unique pro Installation)."""
    mid_path = Path('/etc/machine-id')
    if not mid_path.exists():
        raise RuntimeError(
            'Kein /etc/machine-id gefunden — '
            'credential_store funktioniert nur auf Linux-Systemen mit systemd.'
        )
    return mid_path.read_text().strip().encode('ascii')


def _derive_key() -> bytes:
    """Leite Fernet-Key aus machine-id + Projekt-Salt ab (PBKDF2)."""
    dk = hashlib.pbkdf2_hmac(
        'sha256',
        _machine_id(),
        _PROJECT_SALT,
        iterations=200_000,
    )
    # Fernet erwartet 32 Byte URL-safe Base64
    return base64.urlsafe_b64encode(dk[:32])


def _key_path(name: str) -> Path:
    """Pfad zur verschlüsselten Datei."""
    safe_name = name.replace('/', '_').replace('..', '_')
    return STORE_DIR / f'{safe_name}.key'


def speichere(name: str, klartext: str) -> Path:
    """Verschlüssele und speichere ein Geheimnis.

    Args:
        name: Logischer Name (z.B. 'smtp_pass')
        klartext: Das zu speichernde Geheimnis

    Returns:
        Pfad zur geschriebenen Datei

    Raises:
        PermissionError: Ohne root-Rechte
        RuntimeError: Kein /etc/machine-id
    """
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STORE_DIR, 0o700)

    fernet = Fernet(_derive_key())
    token = fernet.encrypt(klartext.encode('utf-8'))

    ziel = _key_path(name)
    ziel.write_bytes(token)
    os.chmod(ziel, 0o600)

    LOG.info(f'Credential gespeichert: {ziel} ({len(token)} Bytes)')
    return ziel


def lade(name: str) -> str | None:
    """Lade und entschlüssele ein Geheimnis.

    Args:
        name: Logischer Name (z.B. 'smtp_pass')

    Returns:
        Klartext-String oder None wenn nicht vorhanden / nicht entschlüsselbar
    """
    ziel = _key_path(name)
    try:
        if not ziel.exists():
            LOG.debug(f'Credential-Datei nicht gefunden: {ziel}')
            return None
    except PermissionError:
        LOG.warning(f'Keine Leserechte auf {ziel} — als root ausführen?')
        return None

    try:
        token = ziel.read_bytes()
        fernet = Fernet(_derive_key())
        return fernet.decrypt(token).decode('utf-8')
    except InvalidToken:
        LOG.error(
            f'Credential {ziel} konnte nicht entschlüsselt werden — '
            f'machine-id geändert oder Datei von anderem Host?'
        )
        return None
    except PermissionError:
        LOG.warning(f'Keine Leserechte auf {ziel} — als root ausführen?')
        return None
    except Exception as e:
        LOG.error(f'Credential {ziel} Lesefehler: {e}')
        return None


def existiert(name: str) -> bool:
    """Prüfe ob ein verschlüsseltes Credential vorhanden ist."""
    try:
        return _key_path(name).exists()
    except PermissionError:
        # /etc/pv-system ist root-only — wenn wir nicht lesen dürfen,
        # nehmen wir an, dass die Datei nicht existiert (sicherer Default)
        return False


def loesche(name: str) -> bool:
    """Lösche ein gespeichertes Credential."""
    ziel = _key_path(name)
    if ziel.exists():
        ziel.unlink()
        LOG.info(f'Credential gelöscht: {ziel}')
        return True
    return False
