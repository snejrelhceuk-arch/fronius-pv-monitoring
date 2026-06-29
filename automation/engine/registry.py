"""
registry.py — Plugin-Registry für Engine-Regeln und Aktoren (Schicht C)

Single-Source für die Registrierung von Regeln (geordnet) und Aktoren.
Liest `config/engine_registry.json`; die Reihenfolge der Regeln dort ist
die Auswertungsreihenfolge bei Score-Gleichstand. Jeder Eintrag kann per
`"aktiv": false` ohne Code-Änderung deaktiviert werden.

Sicherheit: Fehlt die Registry-Datei oder ist sie strukturell defekt,
fällt der Loader auf die im Code hinterlegten Default-Specs zurück
(`DEFAULT_REGELN_SPEC` / `DEFAULT_AKTOREN_SPEC`). Die Produktion läuft
dann unverändert weiter — eine fehlerhafte JSON darf nie dazu führen,
dass Schutz-Regeln stillschweigend verschwinden.

Rolle C, aber KEIN Hardware-Zugriff hier — nur Klassen-Instanziierung.

Siehe: doc/automation/AUTOMATION_ARCHITEKTUR.md §5, automation-engine.card.md
"""

from __future__ import annotations

import importlib
import json
import logging
import os

from automation.engine.regeln.basis import Regel
from automation.engine.aktoren.aktor_batterie import AktorBase

LOG = logging.getLogger('engine.registry')

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DEFAULT_REGISTRY_PATH = os.path.join(_PROJECT_ROOT, 'config', 'engine_registry.json')


# ── Code-Defaults (Fallback) ─────────────────────────────────
# Reihenfolge = Auswertungsreihenfolge bei Score-Gleichstand.
# Format: (name, dotted_class_path, aktiv)

DEFAULT_REGELN_SPEC: list[tuple[str, str, bool]] = [
    ('sls_schutz',           'automation.engine.regeln.schutz.RegelSlsSchutz', True),
    ('komfort_reset',        'automation.engine.regeln.soc_steuerung.RegelKomfortReset', True),
    ('morgen_soc_min',       'automation.engine.regeln.soc_steuerung.RegelMorgenSocMin', True),
    ('nachmittag_soc_max',   'automation.engine.regeln.soc_steuerung.RegelNachmittagSocMax', True),
    ('zellausgleich',        'automation.engine.regeln.optimierung.RegelZellausgleich', True),
    ('forecast_plausi',      'automation.engine.regeln.optimierung.RegelForecastPlausi', True),
    ('wattpilot_battschutz', 'automation.engine.regeln.geraete.RegelWattpilotBattSchutz', True),
    ('klimaanlage',          'automation.engine.regeln.geraete.RegelKlimaanlage', True),
    ('heizpatrone',          'automation.engine.regeln.geraete.RegelHeizpatrone', True),
    ('fbh_nacht',            'automation.engine.regeln.geraete.RegelFussbodenheizungNacht', True),
    ('ww_verschiebung',      'automation.engine.regeln.waermepumpe.RegelWwVerschiebung', True),
    ('heiz_verschiebung',    'automation.engine.regeln.waermepumpe.RegelHeizVerschiebung', True),
    ('ww_boost',             'automation.engine.regeln.waermepumpe.RegelWwBoost', True),
    ('wp_pflichtlauf',       'automation.engine.regeln.waermepumpe.RegelWpPflichtlauf', True),
    ('heiz_bedarf',          'automation.engine.regeln.waermepumpe.RegelHeizBedarf', True),
    ('ww_absenkung',         'automation.engine.regeln.waermepumpe.RegelWwAbsenkung', True),
    ('heiz_absenkung',       'automation.engine.regeln.waermepumpe.RegelHeizAbsenkung', True),
]

DEFAULT_AKTOREN_SPEC: list[tuple[str, str, bool]] = [
    ('batterie',    'automation.engine.aktoren.aktor_batterie.AktorBatterie', True),
    ('wattpilot',   'automation.engine.aktoren.aktor_wattpilot.AktorWattpilot', True),
    ('fritzdect',   'automation.engine.aktoren.aktor_fritzdect.AktorFritzDECT', True),
    ('waermepumpe', 'automation.engine.aktoren.aktor_waermepumpe.AktorWaermepumpe', True),
]


# ── Hilfsfunktionen ──────────────────────────────────────────

def _resolve(dotted: str) -> type:
    """Dotted-Path 'paket.modul.Klasse' → Klassen-Objekt."""
    module_path, _, cls_name = dotted.rpartition('.')
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


def _load_specs_from_json(path: str, key: str) -> list[tuple[str, str, bool]] | None:
    """Liest [{name, klasse, aktiv}] aus JSON. None bei Fehlen/Defekt → Fallback."""
    if not os.path.exists(path):
        LOG.info(f"Engine-Registry nicht vorhanden ({path}) — Code-Defaults aktiv")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        eintraege = data.get(key)
        if not isinstance(eintraege, list) or not eintraege:
            LOG.warning(f"Engine-Registry '{key}' leer/ungültig — Code-Defaults aktiv")
            return None
        specs: list[tuple[str, str, bool]] = []
        for e in eintraege:
            name = e.get('name')
            klasse = e.get('klasse')
            if not name or not klasse:
                LOG.warning(f"Registry-Eintrag unvollständig in '{key}': {e} — Code-Defaults aktiv")
                return None
            specs.append((name, klasse, bool(e.get('aktiv', True))))
        return specs
    except Exception as ex:
        LOG.error(f"Engine-Registry nicht lesbar ({path}): {ex} — Code-Defaults aktiv")
        return None


def _instanziiere_regeln(specs: list[tuple[str, str, bool]]) -> list[Regel]:
    regeln: list[Regel] = []
    for name, dotted, aktiv in specs:
        if not aktiv:
            LOG.info(f"Regel '{name}' per Registry deaktiviert — übersprungen")
            continue
        cls = _resolve(dotted)
        if not (isinstance(cls, type) and issubclass(cls, Regel)):
            raise TypeError(f"'{dotted}' ist keine Regel-Subklasse")
        regeln.append(cls())
    return regeln


def _instanziiere_aktoren(specs: list[tuple[str, str, bool]],
                          dry_run: bool) -> dict[str, AktorBase]:
    aktoren: dict[str, AktorBase] = {}
    for name, dotted, aktiv in specs:
        if not aktiv:
            LOG.info(f"Aktor '{name}' per Registry deaktiviert — übersprungen")
            continue
        cls = _resolve(dotted)
        if not (isinstance(cls, type) and issubclass(cls, AktorBase)):
            raise TypeError(f"'{dotted}' ist kein Aktor (AktorBase)")
        aktoren[name] = cls(dry_run=dry_run)
    return aktoren


# ── Öffentliche API ──────────────────────────────────────────

def lade_regeln(registry_path: str = DEFAULT_REGISTRY_PATH) -> list[Regel]:
    """Regeln in Auswertungsreihenfolge laden (Registry → Fallback Defaults)."""
    specs = _load_specs_from_json(registry_path, 'regeln')
    if specs is not None:
        try:
            return _instanziiere_regeln(specs)
        except Exception as ex:
            LOG.error(f"Regel-Registry fehlerhaft ({ex}) — Fallback auf Code-Defaults")
    return _instanziiere_regeln(DEFAULT_REGELN_SPEC)


def lade_aktoren(dry_run: bool = False,
                 registry_path: str = DEFAULT_REGISTRY_PATH) -> dict[str, AktorBase]:
    """Aktoren laden (Registry → Fallback Defaults). Key = Dispatch-Name."""
    specs = _load_specs_from_json(registry_path, 'aktoren')
    if specs is not None:
        try:
            return _instanziiere_aktoren(specs, dry_run)
        except Exception as ex:
            LOG.error(f"Aktor-Registry fehlerhaft ({ex}) — Fallback auf Code-Defaults")
    return _instanziiere_aktoren(DEFAULT_AKTOREN_SPEC, dry_run)
