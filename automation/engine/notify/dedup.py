"""
automation/engine/notify/dedup.py — persistenter Dedup-State des EventNotifier.

Sofortalarme und Live-Events werden 1× pro Kalendertag pro Key versandt.
Der Versandzustand liegt in einer kleinen JSON-Datei, damit ein Daemon-Restart
(deploy/reboot/crash) keine Doppelmails verursacht. Heilung erfolgt automatisch
bei Tageswechsel (Cleanup im EventNotifier).

Verbatim aus event_notifier.py extrahiert (Architektur-Refactor 2026-06-29).
"""

from __future__ import annotations

import json
import logging
import os

LOG = logging.getLogger('event_notifier')

DEDUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'config',
    'event_notifier_dedup.json',
)


def load(path: str = DEDUP_PATH) -> dict[str, str]:
    """Lade Dedup-Map (event_key → ISO-Datum). Defekte Dateien sind kein Fehler."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning(f"Dedup-State nicht lesbar ({path}): {exc} → fresh start")
        return {}


def save(state: dict[str, str], path: str = DEDUP_PATH) -> None:
    """Speichere Dedup-Map atomar. Tagesalte Einträge werden mitgenommen,
    Aufräumen erfolgt im EventNotifier (entfernt Einträge < heute)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        LOG.error(f"Dedup-State nicht schreibbar ({path}): {exc}")
