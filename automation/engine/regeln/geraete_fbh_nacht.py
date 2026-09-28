"""
geraete_fbh_nacht.py — RegelFussbodenheizungNacht (Rolle C, fast-Zyklus).

Minimale naechtliche Flankenschaltung der Fussbodenheizungs-Steckdose
(Fritz!DECT) fuer die HA-Sommerpause. Re-Export ueber geraete.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import ist_aktiv, get_param, get_score_gewicht


class RegelFussbodenheizungNacht(Regel):
    """Minimale nächtliche Schaltung der Fußbodenheizungs-Steckdose (Fritz!DECT).

    Zweck: Im Sommer ist die HomeAssistant-Heizungssteuerung (HA-Heizung.yaml)
    deaktiviert, damit das Haus kühl bleibt. Dadurch entfällt auch die nächtliche
    Bad-Fußboden-Erwärmung. Diese Regel schaltet die FBH-Steckdose minimal einmal
    pro Nacht EIN (zu `fenster_start_h`) und AUS (zu `fenster_ende_h`), damit
    wenigstens eine Regelmäßigkeit erhalten bleibt. Die FBH-Temperatur regelt eine
    eigene Thermostatik — zu warm ist unkritisch (es zirkuliert dann nur kaltes
    Wasser).

    Oszillationssicherheit & HA-Koexistenz:
      - Reine Flankenschaltung: genau EIN `fbh_ein` zu Fensterbeginn und EIN
        `fbh_aus` im Nachlauf-Fenster nach Fensterende, je 1×/Kalendertag.
      - KEIN Nachstellen des Zustands während des Fensters. Falls HA (oder ein
        Mensch) zwischendurch umschaltet, wird NICHT gegengesteuert → kein
        Ping-Pong mit der HA-Automation.
      - Die Once-pro-Tag-Sperre (`_absenkung_done['fbh_ein'/'fbh_aus']`) wird erst
        nach bestätigtem Aktor-Erfolg gesetzt (Engine-Callback via
        `meta_absenkung_tag`), sodass ein fehlgeschlagener Schaltversuch im
        nächsten Tick erneut probiert wird.
      - Das AUS-Nachlauffenster (`aus_nachlauf_h`) begrenzt die AUS-Flanke auf die
        Nachtstunden nach Fensterende und verhindert spurious-OFF nach einem
        Daemon-Neustart tagsüber.

    No-Go: Die Erwärmung selbst ist nicht messbar (die SD meldet keine Leistung).
    Diese Regel garantiert nur den Schaltvorgang, nicht den thermischen Effekt.

    Parametermatrix: regelkreise.fussbodenheizung
    """

    name = 'fbh_nacht'
    regelkreis = 'fussbodenheizung'
    aktor = 'fritzdect'
    engine_zyklus = 'fast'

    def _pending_flanke(self, matrix: dict) -> Optional[str]:
        """Liefert 'ein' / 'aus' wenn eine Flankenschaltung fällig ist, sonst None."""
        if not ist_aktiv(matrix, self.regelkreis):
            return None

        # Lazy-Import: gemeinsamer Once-pro-Tag-Tracker + Zeitfenster-Helfer.
        from automation.engine.regeln import waermepumpe as _wp_mod

        start_h = float(get_param(matrix, self.regelkreis, 'fenster_start_h', 3))
        ende_h = float(get_param(matrix, self.regelkreis, 'fenster_ende_h', 5))
        aus_nachlauf_h = float(get_param(matrix, self.regelkreis, 'aus_nachlauf_h', 1))

        heute = datetime.now().date()
        done = _wp_mod._absenkung_done

        # EIN-Flanke: im Hauptfenster [start, ende), 1×/Tag.
        if _wp_mod._ist_im_zeitfenster(start_h, ende_h):
            if done.get('fbh_ein') != heute:
                return 'ein'
            return None

        # AUS-Flanke: im Nachlauffenster [ende, ende+aus_nachlauf), 1×/Tag.
        aus_ende_h = (ende_h + aus_nachlauf_h) % 24
        if _wp_mod._ist_im_zeitfenster(ende_h, aus_ende_h):
            if done.get('fbh_aus') != heute:
                return 'aus'
        return None

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if self._pending_flanke(matrix) is None:
            return 0
        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        flanke = self._pending_flanke(matrix)
        if flanke is None:
            return []

        start_h = float(get_param(matrix, self.regelkreis, 'fenster_start_h', 3))
        ende_h = float(get_param(matrix, self.regelkreis, 'fenster_ende_h', 5))

        if flanke == 'ein':
            return [{
                'tier': 2,
                'aktor': 'fritzdect',
                'kommando': 'fbh_ein',
                'meta_absenkung_tag': 'fbh_ein',
                'grund': (f'FBH Nacht-EIN (Regelmäßigkeit, HA-Sommerpause): '
                          f'Fenster {start_h:.0f}:00–{ende_h:.0f}:00'),
            }]
        return [{
            'tier': 2,
            'aktor': 'fritzdect',
            'kommando': 'fbh_aus',
            'meta_absenkung_tag': 'fbh_aus',
            'grund': f'FBH Nacht-AUS (Fensterende {ende_h:.0f}:00)',
        }]
