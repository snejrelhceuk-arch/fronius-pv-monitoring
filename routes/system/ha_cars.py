"""Read-only Resolver: welches E-Auto gehoert zur aktuellen Wattpilot-Session?

Rolle B (read-only ggü. Produktionsdaten/Hardware). Liest Telemetrie aus Home
Assistant (REST, Long-Lived-Token) und schreibt nichts in `data.db`/Aktoren.
Ohne Konfiguration (``HA_READ_ENABLED``/Token) bleibt der Resolver inaktiv und
liefert ``None`` — die Wattpilot-Anzeige zeigt dann keinen Auto-Namen.

Der Wattpilot selbst kennt das Auto nicht (RFID ``trx`` i.d.R. leer); die
Identitaet stammt aus den Fahrzeug-Integrationen in HA (Renault/Stellantis) und
ist nur waehrend des aktiven Ladens auslesbar (`charge_in_progress`).

Session-Latch: Der einmal erkannte Name wird — analog zur Session-Energie, die
der Wattpilot bis zum naechsten Anstecken haelt — persistiert, bis eine **neue**
Session beginnt (erkannt am Ruecksprung der Session-Energie `session_wh`). So
bleibt der Name in der Flow-Bubble stehen, bis ein anderes Auto angesteckt wird.
Persistenz als kleine JSON-Datei (multi-worker-sicher via atomic replace),
Muster wie ``config/battery_bms_checkpoints.json``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import config

LOG = logging.getLogger('routes.ha_cars')

# (entity_id, aktive_states (lowercase, set), Anzeigename) — Prio-Reihenfolge.
# Quelle: HA-Fahrzeug-Integrationen auf dem HA-Host (X400). Die Renault-ZOE-
# Integration meldet den Roh-State `charge_in_progress` (nicht den lokalisierten
# Anzeigetext); der Stellantis-Binary-Sensor `on`.
_DEFAULT_CAR_ENTITIES: list[tuple[str, frozenset[str], str]] = [
    ('sensor.zoe1_ladezustand', frozenset({'charge_in_progress'}), 'Zoe-jk'),
    ('sensor.zoe2_ladezustand', frozenset({'charge_in_progress'}), 'Zoe-X'),
    ('binary_sensor.chris_citroen_batterie_ladt', frozenset({'on'}), 'Citroën'),
]

# Session gilt als neu, wenn die Session-Energie um mehr als EPS zurueckspringt.
_SESSION_RESET_EPS_WH = 100.0

_LATCH_PATH = Path(__file__).resolve().parents[2] / 'config' / 'wattpilot_session_car.json'

# Kurz-Cache nur fuer die HA-REST-Abfrage (nicht fuer den Latch).
_HA_CACHE: dict[str, Any] = {'ts': 0.0, 'value': None}


def _parse_car_entities(raw: str) -> list[tuple[str, frozenset[str], str]]:
    """'entity|state[/state2]|Name, ...' -> [(entity, {states}, name), ...].

    Mehrere aktive Zustaende je Entity mit '/' trennen. Leere/ungueltige
    Eintraege werden ignoriert. Ist nichts konfiguriert, nutzt ``_car_entities()``
    die eingebauten Defaults.
    """
    out: list[tuple[str, frozenset[str], str]] = []
    for part in (raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        fields = [f.strip() for f in part.split('|')]
        if len(fields) != 3 or not all(fields):
            continue
        entity, states, name = fields
        state_set = frozenset(s.strip().lower() for s in states.split('/') if s.strip())
        if not state_set:
            continue
        out.append((entity, state_set, name))
    return out


def _car_entities() -> list[tuple[str, frozenset[str], str]]:
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


def _resolve_live_ha() -> str | None:
    """Fragt HA ab, welches Auto gerade laedt (ungecacht)."""
    if not getattr(config, 'HA_READ_ENABLED', False):
        return None
    if not getattr(config, 'HA_READ_TOKEN', ''):
        return None
    try:
        import requests
    except Exception:
        return None

    session = requests.Session()
    for entity_id, active_states, name in _car_entities():
        value = _fetch_state(session, entity_id)
        if value is None or value in {'unavailable', 'unknown', ''}:
            continue
        if value in active_states:
            return name
    return None


def _resolve_live(force_refresh: bool = False) -> str | None:
    now = time.time()
    ttl = getattr(config, 'HA_READ_CACHE_TTL_S', 20)
    if not force_refresh and (now - float(_HA_CACHE['ts'])) <= ttl:
        return _HA_CACHE['value']
    value = _resolve_live_ha()
    _HA_CACHE['ts'] = now
    _HA_CACHE['value'] = value
    return value


def _read_latch() -> dict:
    try:
        with open(_LATCH_PATH, encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_latch(data: dict) -> None:
    try:
        _LATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_LATCH_PATH.parent), suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, _LATCH_PATH)
    except Exception as exc:  # pragma: no cover
        LOG.debug('Wattpilot-Session-Latch nicht schreibbar: %s', exc)


def resolve_charging_car(wattpilot: dict | None = None) -> str | None:
    """Liefert den Anzeigenamen des Autos der aktuellen Wattpilot-Session.

    Haelt den zuletzt erkannten Namen ueber Ladepausen/-ende hinweg, bis eine
    neue Session beginnt (``session_wh`` springt zurueck → anderes Auto). Ohne
    HA-Konfiguration inaktiv (``None``).
    """
    if not getattr(config, 'HA_READ_ENABLED', False):
        return None
    if not getattr(config, 'HA_READ_TOKEN', ''):
        return None

    wp = wattpilot or {}
    cur_swh = float(wp.get('energy_session_wh') or 0.0)
    charging = bool(wp.get('charging'))

    latch = _read_latch()
    car = latch.get('car')
    last_swh = latch.get('session_wh')

    new_session = (
        last_swh is not None
        and cur_swh + _SESSION_RESET_EPS_WH < float(last_swh)
    )
    if new_session:
        car = None  # anderes Auto angesteckt → alten Namen verwerfen

    if charging:
        live = _resolve_live(force_refresh=new_session)
        if live:
            car = live

    if car != latch.get('car') or last_swh != cur_swh:
        _write_latch({'car': car, 'session_wh': cur_swh})

    return car
