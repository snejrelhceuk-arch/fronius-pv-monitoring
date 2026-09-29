"""
flow_greetings.py — Editierbare Textbausteine der Begrüßungszeile (/flow).

Diese Datei ist bewusst als **Bedien-/Redaktionsdatei** angelegt: hier stehen die
Text-Schnipsel, die in der dezenten Statuszeile neben dem Menü-Button der
Flow-Ansicht ausgegeben werden. Der Auswahl-Mechanismus (`build_greeting`) bleibt
stabil; **Texte** dürfen frei angepasst werden. Bitte ≤ 100 Schnipsel halten.

Was ausgegeben wird, hängt vom **Systemkontext** ab:
  - Tageszeit  → morgen / tag / nachmittag / abend / nacht
  - Prognose   → gut / mittel / schlecht (heute)
  - Lage       → akku_voll / akku_leer (Vorrang vor der Standard-Phrase)

Verfügbare Platzhalter (in geschweiften Klammern) — werden zur Laufzeit ersetzt;
ein Baustein wird nur gewählt, wenn ALLE seine Platzhalter gerade verfügbar sind
(sonst greift automatisch eine platzhalterfreie Variante derselben Zelle):
  {kwh}        heute erwartete Tagesernte in kWh
  {rest_kwh}   heute noch erwartete Rest-Ernte (ab jetzt bis Sonnenuntergang)
  {morgen_kwh} morgen erwartete Tagesernte in kWh
  {morgen_qual} morgiges Wetter als Wort (sonnig / wechselhaft / trüb)
  {soc}        aktueller Batterie-Ladestand in %

Jeder Eintrag ist ein Paar (lange_Phrase, kurze_Phrase): die lange erscheint auf
breiten Screens, die kurze auf schmalen. Der Client stellt „Guten Morgen …" und
den Ortsnamen selbst voran — hier stehen nur die Kontext-Phrasen (ohne Gruß).
"""
from __future__ import annotations

import re

# Standard-Bausteine: Tageszeit → Prognosequalität → [(lang, kurz), …].
# Pro Zelle sollte mindestens EINE platzhalterfreie Variante stehen (Fallback,
# falls eine Kennzahl gerade fehlt).
SNIPPETS: dict[str, dict[str, list[tuple[str, str]]]] = {
    'morgen': {
        'gut': [
            ('heute wird es sonnig — {kwh} kWh erwartet', 'sonnig · {kwh} kWh'),
            ('starker Sonnentag voraus — {kwh} kWh erwartet', 'sonnig'),
            ('viel Sonne heute — Großverbraucher einplanen', 'sonnig'),
        ],
        'mittel': [
            ('durchwachsener Tag — {kwh} kWh erwartet', 'wechselhaft · {kwh} kWh'),
            ('teils Sonne, teils Wolken heute', 'wechselhaft'),
        ],
        'schlecht': [
            ('wenig Sonne heute — nur {kwh} kWh, bewusst verbrauchen', 'sparsam · {kwh} kWh'),
            ('trüber Tag voraus — Strom bewusst nutzen', 'sparsam'),
        ],
    },
    'tag': {
        'gut': [
            ('volle Ernte — {kwh} kWh heute, Akku lädt', 'Ernte läuft · {kwh} kWh'),
            ('Sonne satt — jetzt ist Erzeugungsspitze', 'Erzeugungsspitze'),
        ],
        'mittel': [
            ('solide Ausbeute — {kwh} kWh erwartet heute', 'Ernte läuft · {kwh} kWh'),
            ('Sonne mit Wolkenlücken — Ernte läuft', 'Ernte läuft'),
        ],
        'schlecht': [
            ('mageres Licht — heute nur {kwh} kWh', 'wenig Ertrag · {kwh} kWh'),
            ('trüb — Netzbezug wahrscheinlich, sparsam bleiben', 'sparsam'),
        ],
    },
    'nachmittag': {
        'gut': [
            ('noch {rest_kwh} kWh Sonne heute — jetzt Verbraucher nutzen', 'noch {rest_kwh} kWh'),
            ('Sonne hält an — {rest_kwh} kWh Rest heute', 'noch {rest_kwh} kWh'),
            ('gute Restausbeute erwartet — Ernte läuft weiter', 'Ernte läuft'),
        ],
        'mittel': [
            ('noch etwa {rest_kwh} kWh Rest heute', 'noch {rest_kwh} kWh'),
            ('Sonne lässt langsam nach', 'Ernte klingt aus'),
        ],
        'schlecht': [
            ('Ernte klingt aus — wenig Rest heute', 'Ernte klingt aus'),
        ],
    },
    'abend': {
        'gut': [
            ('sonniger Tag — morgen {morgen_qual}, {morgen_kwh} kWh erwartet',
             'morgen {morgen_kwh} kWh'),
            ('guter Sonnentag gewesen — Akku bei {soc}%', 'Akku {soc}%'),
            ('Ernte für heute gelaufen — Feierabend', 'Feierabend'),
        ],
        'mittel': [
            ('durchwachsener Tag — morgen {morgen_qual}, {morgen_kwh} kWh',
             'morgen {morgen_kwh} kWh'),
            ('Tag vorbei — Akku bei {soc}%', 'Akku {soc}%'),
            ('Sonne ist weg — Ruhephase', 'Feierabend'),
        ],
        'schlecht': [
            ('trüber Tag — morgen {morgen_qual}, {morgen_kwh} kWh erwartet',
             'morgen {morgen_kwh} kWh'),
            ('magerer Tag gewesen — Akku bei {soc}%', 'Akku {soc}%'),
            ('Tag gelaufen — Ruhephase', 'Feierabend'),
        ],
    },
    'nacht': {
        '*': [
            ('Nachtruhe — Akku bei {soc}%', 'Akku {soc}%'),
            ('Ruhephase — morgen {morgen_qual}, {morgen_kwh} kWh', 'morgen {morgen_kwh} kWh'),
            ('gute Nacht — Anlage im Ruhemodus', 'Nachtruhe'),
        ],
    },
}

# Vorrang-Bausteine: greifen situationsbezogen VOR der Standard-Phrase, wenn die
# Lage (akku_voll / akku_leer) zur Tageszeit passt. Fehlt ein passender Eintrag,
# fällt die Auswahl automatisch auf die Standard-Zelle zurück.
VORRANG: dict[tuple[str, str], list[tuple[str, str]]] = {
    ('tag', 'akku_voll'): [
        ('Akku voll — Sonne läuft in die Abregelung. Auto oder Waschmaschine?',
         'Akku voll · Verbraucher?'),
        ('Akku voll — freie PV-Leistung jetzt sinnvoll nutzen', 'Akku voll'),
    ],
    ('nachmittag', 'akku_voll'): [
        ('Akku voll, noch {rest_kwh} kWh Sonne — hast du ein Auto zu laden?',
         'Akku voll · {rest_kwh} kWh'),
        ('Akku voll — noch {rest_kwh} kWh Überschuss, jetzt nutzen',
         'Akku voll · {rest_kwh} kWh'),
        ('Akku voll — restliche Sonne besser direkt verbrauchen', 'Akku voll'),
    ],
    ('morgen', 'akku_voll'): [
        ('Akku schon voll — heute {kwh} kWh, Überschuss einplanen', 'Akku voll · {kwh} kWh'),
    ],
    ('nachmittag', 'akku_leer'): [
        ('Akku niedrig ({soc}%) — Rest-Sonne füllt nach', 'Akku {soc}%'),
    ],
    ('abend', 'akku_leer'): [
        ('Akku niedrig ({soc}%) — heute Nacht sparsam bleiben', 'Akku {soc}% · sparsam'),
        ('Akku fast leer ({soc}%) — Netzbezug über Nacht', 'Akku {soc}%'),
    ],
    ('nacht', 'akku_leer'): [
        ('Akku niedrig ({soc}%) — Grundlast läuft über Netz', 'Akku {soc}%'),
    ],
    ('morgen', 'akku_leer'): [
        ('Akku leer über Nacht ({soc}%) — Sonne füllt bald nach', 'Akku {soc}%'),
    ],
}

_PLACEHOLDER = re.compile(r'{(\w+)}')


def period_of(now_h: float, sunset_h: float | None = None) -> str:
    """Tageszeit-Bucket aus Uhrzeit + (optional) Sonnenuntergang."""
    if now_h < 5 or now_h >= 22:
        return 'nacht'
    sset = sunset_h if sunset_h else 18.5
    if now_h < 10:
        return 'morgen'
    if now_h >= sset:
        return 'abend'          # Sonne unter → Tag gelaufen
    if now_h >= 14:
        return 'nachmittag'     # Ernte klingt aus
    return 'tag'                # Mittag, Hauptertrag


def _needs(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _pick(varianten: list[tuple[str, str]], ctx: dict) -> tuple[str, str] | None:
    """Wähle eine nutzbare Variante (Platzhalter verfügbar), stabil rotierend."""
    avail = {k for k, v in ctx.items() if v not in (None, '')}
    nutzbar = [p for p in varianten
               if _needs(p[0]) <= avail and _needs(p[1]) <= avail]
    if not nutzbar:
        nutzbar = [p for p in varianten if not _needs(p[0]) and not _needs(p[1])]
    if not nutzbar:
        return None
    idx = int(ctx.get('_bucket', 0)) % len(nutzbar)
    return nutzbar[idx]


def build_greeting(ctx: dict) -> dict | None:
    """Baue die Kontext-Phrase (lang + kurz) aus dem Systemkontext.

    ctx-Felder: ``period``, ``today_quality`` (gut/mittel/schlecht), ``lage``
    (akku_voll/akku_leer/None), ``_bucket`` (Rotationsindex) sowie die
    Platzhalter-Werte (``kwh``, ``rest_kwh``, ``morgen_kwh``, ``morgen_qual``,
    ``soc``) als bereits formatierte Strings.

    Returns ``{'full': str, 'short': str}`` oder ``None`` (kein passender Baustein
    → Client nutzt seine schlichte Fallback-Phrase).
    """
    period = ctx.get('period') or 'tag'
    quality = ctx.get('today_quality') or 'mittel'

    paar = None
    lage = ctx.get('lage')
    if lage:
        paar = _pick(VORRANG.get((period, lage), []), ctx)
    if paar is None:
        zelle = SNIPPETS.get(period) or SNIPPETS['tag']
        varianten = zelle.get(quality) or zelle.get('*') or []
        paar = _pick(varianten, ctx)
    if paar is None:
        return None

    try:
        return {'full': paar[0].format(**ctx), 'short': paar[1].format(**ctx)}
    except (KeyError, IndexError):
        return None
