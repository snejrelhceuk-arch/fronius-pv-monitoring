"""
engine.py — Entscheidungs-Engine (Schicht S3)

Liest ObsState aus RAM-DB und SOC-Parametermatrix aus
config/soc_param_matrix.json.  Bewertet Regeln per Score-System
und erzeugt einen ActionPlan für den Actuator.

Zyklen:
  Fast-Cycle  (1 min)  — Sicherheit + Entladeraten
  Strat-Cycle (15 min) — SOC_MIN / SOC_MAX Steuerung, Zellausgleich

Tier-1 Alarm-Aktionen werden NICHT hier behandelt — die laufen
direkt im Observer → Actuator Bypass.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §5
"""

from __future__ import annotations

import logging
import os
import sqlite3

import automation.engine.obs_state as obs_mod
from automation.engine.obs_state import read_obs_state
from automation.engine.actuator import Actuator
from automation.engine.param_matrix import (
    lade_matrix, get_score_gewicht, DEFAULT_MATRIX_PATH,
)
from automation.engine.regeln.soc_extern import soc_extern_tracker
from automation.engine.regeln.waermepumpe import reset_wp_extern_tracking

from automation.engine.regeln import (          # noqa: E402
    Regel,
    # Entfernt (2026-03-07): RegelSocSchutz, RegelTempSchutz,
    # RegelAbendEntladerate, RegelLaderateDynamisch
    RegelSlsSchutz,
    RegelKomfortReset,
    RegelMorgenSocMin,
    RegelNachmittagSocMax,
    RegelZellausgleich,
    RegelForecastPlausi,
    RegelWattpilotBattSchutz,
    RegelHeizpatrone,
    RegelKlimaanlage,
    RegelWwAbsenkung,
    RegelHeizAbsenkung,
    RegelWwVerschiebung,
    RegelHeizVerschiebung,
    RegelWwBoost,
    RegelWpPflichtlauf,
    RegelHeizBedarf,
)

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# Engine
# ═════════════════════════════════════════════════════════════

def _registriere_erfolgreiche_soc_aktionen(aktionen: list[dict],
                                            ergebnisse: list[dict]) -> None:
    """SOC-Aktionen beim SocExternTracker registrieren — NUR nach Actuator-Erfolg.

    Korrektur K2: Vorher wurden Aktionen in erzeuge_aktionen() registriert
    (vor Ausführung). Jetzt nur nach bestätigtem ok=True.
    """
    for aktion, ergebnis in zip(aktionen, ergebnisse):
        if not ergebnis.get('ok'):
            continue
        kommando = aktion.get('kommando', '')
        if kommando in ('set_soc_min', 'set_soc_max'):
            soc_extern_tracker.registriere_aktion(kommando, aktion.get('wert'))


def _registriere_erfolgreiche_wp_aktionen(aktionen: list[dict],
                                          ergebnisse: list[dict]) -> None:
    """WP-Sollwerte beim Extern-Respekt-Tracker registrieren — NUR nach Actuator-Erfolg.

    Korrektur K2 (adaptiert von SOC): Vorher wurden Engine-Werte in
    erzeuge_aktionen() registriert (vor Ausführung). Race-Condition bei
    Actuator-Fehler → falsche Extern-Erkennung im nächsten Zyklus.
    """
    from automation.engine.regeln.waermepumpe import (
        _registriere_engine_wert,
        _registriere_absenkung_done,
    )
    for aktion, ergebnis in zip(aktionen, ergebnisse):
        if not ergebnis.get('ok'):
            continue
        kommando = aktion.get('kommando', '')
        if kommando == 'set_ww_soll':
            _registriere_engine_wert('ww', aktion.get('wert'))
        elif kommando == 'set_heiz_soll':
            _registriere_engine_wert('heiz', aktion.get('wert'))

        # Absenkung-Transitionen erst nach bestätigtem Schreib-Erfolg sperren
        tag = aktion.get('meta_absenkung_tag')
        if tag:
            _registriere_absenkung_done(str(tag))


class Engine:
    """Score-basierte Entscheidungs-Engine.

    Lifecycle:
      1. Lade Parametermatrix (config/soc_param_matrix.json)
      2. Lese ObsState aus RAM-DB
      3. Bewerte alle registrierten Regeln gegen Matrix + ObsState
      4. Regeln mit höchstem Score gewinnen → ActionPlan
      5. ActionPlan an Actuator dispatchen

    Zyklen:
      fast (1 min)      — wattpilot_battschutz, heizpatrone, komfort_reset
      strategic (15 min) — morgen_soc_min, nachmittag_soc_max, zellausgleich,
                           forecast_plausi
    """

    def __init__(self, actuator: Actuator, dry_run: bool = False,
                 matrix_path: str = DEFAULT_MATRIX_PATH):
        self.actuator = actuator
        self.dry_run = dry_run
        self._matrix_path = matrix_path
        self._matrix: dict = {}
        self._regeln: list[Regel] = []
        self._ram_db_conn = None
        self._lade_matrix()
        self._register_default_regeln()

    def _lade_matrix(self):
        """Lade Parametermatrix von Disk."""
        try:
            self._matrix = lade_matrix(self._matrix_path)
            LOG.info(f"Parametermatrix geladen: {self._matrix_path}")
        except Exception as e:
            LOG.error(f"Parametermatrix nicht ladbar: {e}")
            self._matrix = {'regelkreise': {}}

    def reload_matrix(self):
        """Parametermatrix neu laden (z.B. nach Config-Änderung).

        Setzt zusätzlich den WP-Extern-Respekt-State zurück, damit
        geänderte Sollwert-Parameter (standard_temp_c etc.) beim nächsten
        fast-Zyklus sofort aktiv gesetzt werden.
        """
        self._lade_matrix()
        reset_wp_extern_tracking()
        LOG.info("Parametermatrix neu geladen")

    def _register_default_regeln(self):
        """Alle SOC-Regeln registrieren."""
        self._regeln = [
            # Entfernt (2026-03-07): RegelSocSchutz(), RegelTempSchutz(),
            # RegelAbendEntladerate(), RegelLaderateDynamisch()
            RegelSlsSchutz(),
            RegelKomfortReset(),
            RegelMorgenSocMin(),
            RegelNachmittagSocMax(),
            RegelZellausgleich(),
            RegelForecastPlausi(),
            RegelWattpilotBattSchutz(),
            RegelKlimaanlage(),
            RegelHeizpatrone(),
            RegelWwVerschiebung(),
            RegelHeizVerschiebung(),
            RegelWwBoost(),
            RegelWpPflichtlauf(),
            RegelHeizBedarf(),
            RegelWwAbsenkung(),
            RegelHeizAbsenkung(),
        ]
        LOG.info(f"Regeln registriert: {[r.name for r in self._regeln]}")

    def registriere_regel(self, regel: Regel):
        """Zusätzliche Regel registrieren."""
        self._regeln.append(regel)
        LOG.info(f"Regel '{regel.name}' registriert")

    def _get_ram_db(self) -> sqlite3.Connection:
        """Lazy-Init RAM-DB Verbindung (readonly)."""
        if self._ram_db_conn is None:
            db_path = obs_mod.RAM_DB_PATH
            if not os.path.exists(db_path):
                raise RuntimeError(f"RAM-DB nicht gefunden: {db_path}")
            self._ram_db_conn = sqlite3.connect(
                f'file:{db_path}?mode=ro', uri=True, timeout=3.0
            )
        return self._ram_db_conn

    # ── Haupt-Zyklus ─────────────────────────────────────────

    def zyklus(self, zyklus_typ: str = 'fast') -> list[dict]:
        """Ein Engine-Zyklus: Bewerte → Entscheide → Handle.

        Args:
            zyklus_typ: 'fast' (1 min) oder 'strategic' (15 min)

        Returns:
            Liste der ausgeführten Aktionen (Ergebnisse)
        """
        # 1. ObsState lesen
        try:
            conn = self._get_ram_db()
            obs = read_obs_state(conn)
        except Exception as e:
            LOG.error(f"ObsState nicht lesbar: {e}")
            self._ram_db_conn = None
            return []

        if obs is None:
            LOG.warning("Kein ObsState vorhanden — überspringe Zyklus")
            return []

        # 2. Alarm-Flags prüfen (Tier-1 hat Vorrang → Engine pausiert)
        if obs.alarm_batt_temp or obs.alarm_batt_kritisch:
            LOG.info(f"Tier-1 Alarm aktiv — Engine-Zyklus '{zyklus_typ}' übersprungen "
                     f"(batt_temp={obs.alarm_batt_temp}, batt_krit={obs.alarm_batt_kritisch})")
            return []

        # 3. Regeln bewerten (nur passende Zyklen)
        scores: list[tuple[int, Regel]] = []
        for regel in self._regeln:
            if zyklus_typ == 'fast' and regel.engine_zyklus == 'strategic':
                continue
            try:
                score = regel.bewerte(obs, self._matrix)
                if score > 0:
                    scores.append((score, regel))
                    LOG.debug(f"  Regel '{regel.name}': Score {score}")
            except Exception as e:
                LOG.error(f"  Regel '{regel.name}' Fehler: {e}")

        if not scores:
            LOG.debug(f"Zyklus '{zyklus_typ}': Keine Regel aktiv")
            return []

        # 4. Schutz-Regeln und Optimierungs-Regeln trennen
        #    Schutz-Regeln werden ALLE ausgeführt (parallel-safe: versch. Aktoren),
        #    Optimierung: nur der Gewinner pro Aktor-Cascade.
        #    Schutz = Name enthält 'schutz' ODER Regel nutzt fremden Aktor
        #    mit erhöhtem Score (= Notaus, z.B. heizpatrone→fritzdect).
        def _ist_schutz(score, regel):
            if 'schutz' in regel.name:
                return True
            # Zeitgesteuerte WP-Sollwertregeln sollen unabhängig von
            # Optimierungs-Gewinnern zuverlässig laufen.
            if regel.name in ('ww_absenkung', 'heiz_absenkung',
                              'ww_verschiebung', 'heiz_verschiebung',
                              'ww_boost', 'wp_pflichtlauf',
                              'heiz_bedarf'):
                return True
            # HP-Notaus: fritzdect-Aktor mit erhöhtem Score (>score_gewicht)
            if regel.aktor == 'fritzdect' and score > get_score_gewicht(self._matrix, regel.regelkreis):
                return True
            return False

        schutz_scores = [(s, r) for s, r in scores if _ist_schutz(s, r)]
        optim_scores  = [(s, r) for s, r in scores if not _ist_schutz(s, r)]

        ergebnisse = []

        # 4a. Alle aktiven Schutz-Regeln ausführen (absteigend nach Score)
        #     Deduplizierung: pro Kommando (z.B. set_ww_soll) gewinnt die
        #     höchst-scorende Regel — nachfolgende werden übersprungen.
        schutz_scores.sort(key=lambda x: x[0], reverse=True)
        schutz_kommandos_erledigt: set[str] = set()
        for score, regel in schutz_scores:
            LOG.info(f"Zyklus '{zyklus_typ}': Schutz-Regel '{regel.name}' (Score {score})")
            try:
                aktionen = regel.erzeuge_aktionen(obs, self._matrix)
                if aktionen:
                    # Deduplizierung: bereits geschriebene Kommandos filtern
                    aktionen_neu = [a for a in aktionen
                                    if a.get('kommando') not in schutz_kommandos_erledigt]
                    if not aktionen_neu:
                        LOG.info(f"  '{regel.name}' übersprungen — "
                                 f"Kommando(s) bereits durch höher-scorende Regel bedient")
                        continue
                    teil_ergebnisse = self.actuator.ausfuehren_plan(aktionen_neu)
                    _registriere_erfolgreiche_soc_aktionen(aktionen_neu, teil_ergebnisse)
                    _registriere_erfolgreiche_wp_aktionen(aktionen_neu, teil_ergebnisse)
                    for a, e in zip(aktionen_neu, teil_ergebnisse):
                        LOG.info(f"  → {e.get('kommando')} = {'OK' if e.get('ok') else 'FEHLER'}")
                        if e.get('ok'):
                            schutz_kommandos_erledigt.add(a.get('kommando'))
                    ergebnisse.extend(teil_ergebnisse)
            except Exception as e:
                LOG.error(f"Aktionen erzeugen fehlgeschlagen '{regel.name}': {e}")

        # 4b. Optimierungs-Regeln: Gewinner first, Cascade bei leerer Aktion
        #     Wenn der Score-Gewinner keine Aktionen erzeugt (z.B.
        #     forecast_plausi entscheidet "keine Aktion nötig"), wird der
        #     nächstbeste Kandidat versucht.  So blockiert eine Score-hohe
        #     aber passiv bleibende Regel nie eine niedrigere aktive Regel.
        if optim_scores:
            optim_scores.sort(key=lambda x: x[0], reverse=True)

            for winner_score, winner in optim_scores:
                LOG.info(f"Zyklus '{zyklus_typ}': Gewinner '{winner.name}' (Score {winner_score})")

                try:
                    aktionen = winner.erzeuge_aktionen(obs, self._matrix)
                except Exception as e:
                    LOG.error(f"Aktionen erzeugen fehlgeschlagen '{winner.name}': {e}")
                    continue

                if aktionen:
                    # 6. An Actuator dispatchen
                    teil_ergebnisse = self.actuator.ausfuehren_plan(aktionen)
                    _registriere_erfolgreiche_soc_aktionen(aktionen, teil_ergebnisse)
                    _registriere_erfolgreiche_wp_aktionen(aktionen, teil_ergebnisse)
                    for e in teil_ergebnisse:
                        LOG.info(f"  → {e.get('kommando')} = {'OK' if e.get('ok') else 'FEHLER'}")
                    ergebnisse.extend(teil_ergebnisse)
                    break  # Erster Gewinner mit Aktionen → fertig
                else:
                    LOG.info(f"  '{winner.name}' hat keine Aktionen → Cascade zum Nächsten")

        return ergebnisse

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        if self._ram_db_conn:
            self._ram_db_conn.close()
            self._ram_db_conn = None
