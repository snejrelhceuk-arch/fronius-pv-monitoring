"""Read-only Resolver: welches E-Auto laedt gerade am Wattpilot?

Rolle B (read-only). Liest ausschliesslich Telemetrie aus Home Assistant
(REST, Long-Lived-Token) und schreibt nichts zurueck. Ohne Konfiguration
(``HA_READ_ENABLED``/Token) bleibt der Resolver inaktiv und liefert ``None`` —
die Wattpilot-Anzeige zeigt dann nur ``Lädt`` ohne Auto-Namen.

Der Wattpilot selbst kennt das Auto nicht (RFID ``trx`` i.d.R. leer); die
Identitaet stammt aus den Fahrzeug-Integrationen in HA (Renault/Stellantis).

Identifizierungslogik (nach HA-``automations.yaml``): das erste Fahrzeug, dessen
Lade-Entity den erwarteten Zustand meldet, gewinnt (Prioritaet = Reihenfolge).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import config

LOG = logging.getLogger('routes.ha_cars')

_CACHE: dict[str, Any] = {'ts': 0.0, 'value': None}

# (entity_id, erwarteter_state (lowercase), Anzeigename) — Prio-Reihenfolge.
# Quelle: HA-Fahrzeug-Integrationen auf dem HA-Host (X400).
_DEFAULT_CAR_ENTITIES: list[tuple[str, str, str]] = [
    ('sensor.zoe1_ladezustand', 'wird geladen', 'Zoe-jk'),
    ('sensor.zoe2_ladezustand', 'wird geladen', 'Zoe-X'),
    ('binary_sensor.chris_citroen_batterie_ladt', 'on', 'Citroën'),
]


def _parse_car_entities(raw: str) -> list[tuple[str, str, str]]:
    """'entity|state|Name, entity|state|Name' -> [(entity, state_lower, name), ...].

    Leere/ungueltige Eintraege werden ignoriert. Ist nichts konfiguriert,
    nutzt ``_car_entities()`` die eingebauten Defaults.
    """
    out: list[tuple[str, str, str]] = []
    for part in (raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        fields = [f.strip() for f in part.split('|')]
        if len(fields) != 3 or not all(fields):
            continue
        entity, state, name = fields
        out.append((entity, state.lower(), name))
    return out


def _car_entities() -> list[tuple[str, str, str]]:
    configured = _parse_car_entities(getattr(config, 'HA_READ_CAR_ENTITIES', ''))
    return configured or _DEFAULT_CAR_ENTITIES


def _fetch_state(session, entity_id: str) -> str | None:
    url = f'{config.HA_READ_BASE_URL}/api/states/{entity_id}'
    headers = {'Authorization': f'Bearer {config.HA_READ_TOKEN}'}
    try:
        resp = session.get(url, headers=headers, timeout=config.HA_READ_HTTP_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        return str(resp.json().get('state', '')).strip().lower()
    except Exception as exc:  # pragma: no cover - Netzwerk
        LOG.debug('HA-State %s nicht lesbar: %s', entity_id, exc)
        return None


def _resolve_uncached() -> str | None:
    if not getattr(config, 'HA_READ_ENABLED', False):
        return None
    if not getattr(config, 'HA_READ_TOKEN', ''):
        return None

    try:
        import requests
    except Exception:
        return None

    session = requests.Session()
    for entity_id, expected, name in _car_entities():
        value = _fetch_state(session, entity_id)
        if value is None or value in {'unavailable', 'unknown', ''}:
            continue
        if value == expected:
            return name
    return None


def resolve_charging_car(wattpilot: dict | None = None) -> str | None:
    """Liefert den Anzeigenamen des gerade ladenden Autos (oder None).

    Nur wenn der Wattpilot tatsaechlich laedt wird HA abgefragt. Ergebnis wird
    kurz gecacht (``HA_READ_CACHE_TTL_S``), um HA nicht pro Request zu treffen.
    """
    if wattpilot is not None and not wattpilot.get('charging'):
        return None

    now = time.time()
    ttl = getattr(config, 'HA_READ_CACHE_TTL_S', 20)
    if (now - float(_CACHE['ts'])) <= ttl:
        return _CACHE['value']

    value = _resolve_uncached()
    _CACHE['ts'] = now
    _CACHE['value'] = value
    return value
