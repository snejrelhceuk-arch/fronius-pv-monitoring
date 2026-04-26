"""
waermepumpe.py — WP-Sollwertregeln (P2, fast-Zyklus)

Regeln:
    - RegelWwAbsenkung      — Nachtabsenkung WW-Solltemperatur (Reg 5047)
    - RegelHeizAbsenkung    — Absenkung Heiz-Festwertsolltemperatur (Reg 5037)
    - RegelWwVerschiebung   — WW-Bereitung verschieben bei schlechter Energiebilanz
    - RegelHeizVerschiebung — Heiz-Soll absenken bei schlechter Energiebilanz
    - RegelWwBoost          — WW-Soll anheben bei PV-Überschuss (therm. Speicherung)
    - RegelWpPflichtlauf    — Täglicher WP-Pflichtlauf via Heiz-Boost
    - RegelHeizBedarf       — FBH-Heizbedarf: Heiz-Soll priorisiert nach Außentemp.

ABCD: C-Rolle (Automation Engine) → D (Hardware via Modbus RTU)
Siehe: doc/automation/WP_REGISTER.md
"""

from __future__ import annotations

import logging
from datetime import datetime

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')


# ── Verschiebungs-Status (modul-global) ──────────────────────
# Wird von RegelWw/HeizVerschiebung gesetzt und von
# RegelWw/HeizAbsenkung gelesen, um Konflikte zu vermeiden.
_verschoben = {
    'ww_aktiv': False,
    'ww_seit': None,
    'ww_letzte_ruecknahme': None,   # Cooldown: Zeitpunkt letzte Rücknahme
    'heiz_aktiv': False,
    'heiz_seit': None,
    'heiz_letzte_ruecknahme': None,  # Cooldown: Zeitpunkt letzte Rücknahme
}

# ── WP-Laufzeit-Tracker (modul-global) ───────────────────────
# Schützt Scroll-Kompressor vor Kurzzeittakten.
# Verschiebungsregeln dürfen Sollwerte nicht ändern, solange die
# WP weniger als 15 Minuten ununterbrochen läuft.
# GILT NUR für Automations-Regeln, NICHT für Steuerbox-Overrides.
_wp_laufzeit = {
    'aktiv_seit': None,   # datetime: wann WP zuletzt aktiv wurde
}

# ── Extern-Respekt-Tracker (modul-global) ────────────────────
# Erkennt extern-geänderte WP-Sollwerte (manuell, anderer Prozess)
# und schützt sie vor sofortigem Überschreiben.
# Mechanik: Jede Absenkungsregel registriert nach Schreibzugriff
# den Zielwert als "engine_wert". Weicht der nächste Messwert ab,
# gilt er als extern → Respekt-Timer startet.
_wp_extern = {
    'ww_letzter_engine_wert': None,   # Was die Engine zuletzt geschrieben hat
    'ww_extern_seit': None,           # datetime wenn extern-Änderung erkannt
    'heiz_letzter_engine_wert': None,
    'heiz_extern_seit': None,
}


def _prüfe_extern_respekt(register: str, aktuell: int, matrix: dict,
                           regelkreis: str) -> bool:
    """Prüfe ob ein extern geänderter Wert noch respektiert werden muss.

    Returns True → Regel soll NICHT eingreifen (extern-Toleranz läuft).
    """
    prefix = 'ww' if register == 'ww' else 'heiz'
    key_engine = f'{prefix}_letzter_engine_wert'
    key_seit = f'{prefix}_extern_seit'

    respekt_s = get_param(matrix, regelkreis, 'extern_respekt_s', 1800)
    if respekt_s <= 0:
        return False

    engine_wert = _wp_extern[key_engine]

    # Engine hat noch nie geschrieben → aktuellen Wert als "engine_wert" annehmen
    if engine_wert is None:
        return False

    # Aktueller Wert stimmt mit Engine-Wert überein → kein externer Eingriff
    if int(aktuell) == int(engine_wert):
        _wp_extern[key_seit] = None  # Timer zurücksetzen
        return False

    # Abweichung erkannt → extern-Timer starten oder prüfen
    now = datetime.now()
    if _wp_extern[key_seit] is None:
        _wp_extern[key_seit] = now
        LOG.info(f"WP extern_respekt ({prefix}): Externe Änderung erkannt "
                 f"(Engine={engine_wert}°C, Aktuell={aktuell}°C) — "
                 f"respektiere für {respekt_s}s")

    alter_s = (now - _wp_extern[key_seit]).total_seconds()
    if alter_s < respekt_s:
        LOG.debug(f"WP extern_respekt ({prefix}): Noch {respekt_s - alter_s:.0f}s Toleranz")
        return True

    # Toleranzzeit abgelaufen → Regel darf überschreiben
    LOG.info(f"WP extern_respekt ({prefix}): Toleranz abgelaufen nach {alter_s:.0f}s — "
             f"Engine überschreibt {aktuell}°C")
    _wp_extern[key_seit] = None
    return False


def _registriere_engine_wert(register: str, wert: int):
    """Registriere den Wert den die Engine gerade schreibt."""
    prefix = 'ww' if register == 'ww' else 'heiz'
    _wp_extern[f'{prefix}_letzter_engine_wert'] = int(wert)
    _wp_extern[f'{prefix}_extern_seit'] = None  # Timer zurücksetzen


def reset_wp_extern_tracking():
    """Extern-Respekt-State zurücksetzen.

    Muss nach Matrix-Reload (SIGHUP) aufgerufen werden, damit geänderte
    Parameter (z.B. standard_temp_c) sofort in die Aktorik übernommen werden
    und nicht durch den Extern-Respekt-Mechanismus blockiert bleiben.
    """
    LOG.info("WP extern_respekt: State nach Matrix-Reload zurückgesetzt")
    for key in list(_wp_extern.keys()):
        _wp_extern[key] = None


def _aktualisiere_wp_laufzeit(obs: ObsState) -> None:
    """WP-Laufzeit-Tracker aktualisieren anhand obs.wp_active.

    Wird von den Verschiebungsregeln in bewerte() aufgerufen.
    """
    if obs.wp_active:
        if _wp_laufzeit['aktiv_seit'] is None:
            _wp_laufzeit['aktiv_seit'] = datetime.now()
    else:
        _wp_laufzeit['aktiv_seit'] = None


def _wp_laeuft_kuerzer_als(min_minuten: float) -> bool:
    """True wenn WP gerade läuft, aber kürzer als min_minuten.

    Schützt den Scroll-Kompressor vor Kurzzeittakten.
    Verschiebungsregeln dürfen nur umschalten, wenn die WP
    mindestens min_minuten ununterbrochen gelaufen ist (oder aus ist).
    """
    seit = _wp_laufzeit['aktiv_seit']
    if seit is None:
        return False  # WP läuft nicht → kein Schutz nötig
    lauf_min = (datetime.now() - seit).total_seconds() / 60.0
    return lauf_min < min_minuten


def _verschiebung_cooldown_aktiv(prefix: str, cooldown_s: float) -> bool:
    """True wenn seit letzter Rücknahme weniger als cooldown_s vergangen.

    Verhindert Oszillation: Nach jeder Rücknahme muss die Verschiebung
    mindestens cooldown_s warten, bevor sie erneut aktiviert werden darf.
    """
    key = f'{prefix}_letzte_ruecknahme'
    letzte = _verschoben.get(key)
    if letzte is None:
        return False
    alter_s = (datetime.now() - letzte).total_seconds()
    if alter_s < cooldown_s:
        LOG.debug(f"{prefix.upper()}-Verschiebung: Cooldown aktiv "
                  f"(noch {cooldown_s - alter_s:.0f}s bis Reaktivierung)")
        return True
    return False


# ── Absenkung: Einmal-pro-Tag-Tracker (date pro Transition) ──
_absenkung_done: dict[str, object] = {}   # key → date


def _registriere_absenkung_done(tag: str) -> None:
    """Markiert eine Absenkungs-Transition als erledigt (heutiges Datum).

    Wird nur nach bestätigtem Actuator-Erfolg aufgerufen.
    """
    _absenkung_done[tag] = datetime.now().date()


def _ist_im_zeitfenster(start_h: float, ende_h: float) -> bool:
    """True wenn aktuelle Uhrzeit im (ggf. über-Mitternacht) Fenster liegt."""
    now_h = datetime.now().hour + datetime.now().minute / 60.0
    if start_h > ende_h:
        return now_h >= start_h or now_h < ende_h
    return start_h <= now_h < ende_h


class RegelWwAbsenkung(Regel):
    """WW-Nachtabsenkung: Temperatur nachts senken, morgens wiederherstellen.

    Zeitfenster-Logik (start_h > ende_h → über Mitternacht):
      23:00–03:00  →  Nacht-Soll = standard - absenkung
      03:00–23:00  →  Tag-Soll   = standard

    Schutz: Jede Transition 1×/Tag; deaktivierbar via param_matrix.
    """

    name = 'ww_absenkung'
    regelkreis = 'ww_absenkung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _ist_nachtzeit(self, matrix: dict) -> bool:
        """Prüfe ob aktuelle Uhrzeit im Absenkungsfenster liegt."""
        # Default an Matrix angeglichen (2026-04-26): Matrix=22, Code war 23.
        start = get_param(matrix, self.regelkreis, 'start_h', 22)
        ende = get_param(matrix, self.regelkreis, 'ende_h', 3)
        return _ist_im_zeitfenster(start, ende)

    def _ziel_temp(self, matrix: dict) -> int:
        """Ziel-WW-Soll je nach Tageszeit."""
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 57)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 5)
        if self._ist_nachtzeit(matrix):
            return int(standard - absenkung)
        return int(standard)

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # WW-Verschiebung hat Vorrang → nicht eingreifen
        if _verschoben['ww_aktiv']:
            return 0

        # WW-Boost hat Vorrang → Absenkung darf nicht gegen Boost arbeiten
        if _boost['ww_aktiv']:
            return 0

        tag = 'ww_nacht' if self._ist_nachtzeit(matrix) else 'ww_tag'
        if _absenkung_done.get(tag) == datetime.now().date():
            return 0

        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_ww_soll_c
        if aktuell is None:
            return 0
        if int(aktuell) == ziel:
            # Nur engine_wert registrieren, NICHT absenkung_done.
            # done wird erst nach bestätigtem Actuator-Schreiberfolg gesetzt
            # (Engine-Callback via meta_absenkung_tag). Sonst bewirkt der
            # Mitternachts-Datumswechsel (aktuell==ziel vom Vortag) eine
            # falsche done-Registrierung für den neuen Tag.
            _registriere_engine_wert('ww', ziel)
            return 0

        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_ww_soll_c
        ist_nacht = self._ist_nachtzeit(matrix)

        phase = "Nachtabsenkung" if ist_nacht else "Tagwert-Wiederherstellung"
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 57)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 5)

        tag = 'ww_nacht' if ist_nacht else 'ww_tag'

        return [{
            'tier': 2,
            'aktor': 'waermepumpe',
            'kommando': 'set_ww_soll',
            'wert': ziel,
            'meta_absenkung_tag': tag,
            'grund': (f'WW {phase}: {aktuell}°C → {ziel}°C '
                      f'(Standard {standard}°C, Absenkung {absenkung}K)'),
        }]


class RegelHeizAbsenkung(Regel):
    """Heiz-Nachtabsenkung: Festwertsoll nachts senken, morgens wiederherstellen.

    Zeitfenster-Logik (start_h > ende_h → über Mitternacht):
      18:00–03:00  → Nacht-Soll = standard - absenkung
      03:00–18:00  → Tag-Soll   = standard

    Hinweis:
      - Die Wärmepumpe nutzt intern den Rücklaufbezug; für die Automation
        ist das ohne Bedeutung, gesteuert wird ausschließlich Register 5037.
      - Zielwert wird auf Modbus-Bereich 18..60°C begrenzt.
    """

    name = 'heiz_absenkung'
    regelkreis = 'heiz_absenkung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _ist_absenkzeit(self, matrix: dict) -> bool:
        start = get_param(matrix, self.regelkreis, 'start_h', 18)
        ende = get_param(matrix, self.regelkreis, 'ende_h', 3)
        return _ist_im_zeitfenster(start, ende)

    def _ziel_temp(self, matrix: dict) -> int:
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 37)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 2)
        if self._ist_absenkzeit(matrix):
            return max(18, int(standard - absenkung))
        return int(standard)

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # FBH-Heizbedarf hat Vorrang vor Tagwert-Wiederherstellung.
        if _heizbedarf['aktiv']:
            return 0

        # Heiz-Verschiebung hat Vorrang → nicht eingreifen
        if _verschoben['heiz_aktiv']:
            return 0

        # Pflichtlauf-Boost aktiv → nicht gegenarbeiten
        if _pflichtlauf['boost_aktiv']:
            return 0

        tag = 'heiz_nacht' if self._ist_absenkzeit(matrix) else 'heiz_tag'
        if _absenkung_done.get(tag) == datetime.now().date():
            return 0

        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_heiz_soll_c
        if aktuell is None:
            return 0
        if int(aktuell) == ziel:
            # Nur engine_wert registrieren, NICHT absenkung_done.
            # done wird erst nach bestätigtem Actuator-Schreiberfolg gesetzt
            # (Engine-Callback via meta_absenkung_tag). Sonst bewirkt der
            # Mitternachts-Datumswechsel (aktuell==ziel vom Vortag) eine
            # falsche done-Registrierung für den neuen Tag.
            _registriere_engine_wert('heiz', ziel)
            return 0

        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_heiz_soll_c
        ist_absenkung = self._ist_absenkzeit(matrix)

        phase = "Absenkung" if ist_absenkung else "Tagwert-Wiederherstellung"
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 37)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 2)

        tag = 'heiz_nacht' if ist_absenkung else 'heiz_tag'

        return [{
            'tier': 2,
            'aktor': 'waermepumpe',
            'kommando': 'set_heiz_soll',
            'wert': ziel,
            'meta_absenkung_tag': tag,
            'grund': (f'Heiz-Soll {phase}: {aktuell}°C → {ziel}°C '
                      f'(Standard {standard}°C, Absenkung {absenkung}K)'),
        }]


# ═════════════════════════════════════════════════════════════
# Energiebilanz-basierte Verschiebung (P2, fast-Zyklus)
# ═════════════════════════════════════════════════════════════

class RegelWwVerschiebung(Regel):
    """WW-Bereitung verschieben bei ungünstiger Energiebilanz.

    Bedingungspfade:

      AKTIVIERUNG (alle müssen zutreffen):
        1. Batterie-SOC < soc_schwelle_pct        → Batt. fast leer
        2. PV-Leistung  < pv_min_w                → geringer Ertrag
        3. Forecast-Rest > forecast_rest_min_kwh   → später gute Prognose
           (Ausnahme: <2h vor Sunset → Schwelle halbiert)
        4. WW-Ist       > ww_min_c                 → noch warm genug

      RÜCKNAHME (einer reicht):
        a. PV-Leistung  > pv_restore_w             → PV wieder da
        b. Batterie-SOC > soc_restore_pct           → Batterie erholt
        c. WW-Ist       < ww_notfall_c              → zu kalt (Notfall)
        d. Dauer        > max_verschiebung_h        → Timeout

    Aktion: WW-Soll um verschiebung_k absenken (z.B. 7K → 50°C),
            WP stellt WW-Bereitung ein. Bei Rücknahme: Standard
            aus ww_absenkung wiederherstellen.

    Koordination: Setzt _verschoben['ww_aktiv'] — RegelWwAbsenkung
                  prüft dieses Flag und gibt nach (Score 0).
    """

    name = 'ww_verschiebung'
    regelkreis = 'ww_verschiebung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _soll_verschieben(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob WW-Verschiebung angebracht ist (PROAKTIV — vor WP-Start)."""
        soc = obs.batt_soc_pct
        pv = obs.pv_total_w
        forecast = obs.forecast_rest_kwh
        ww_ist = obs.ww_temp_c

        if any(v is None for v in (soc, pv, forecast, ww_ist)):
            return False

        soc_schwelle = get_param(matrix, self.regelkreis, 'soc_schwelle_pct', 10)
        pv_min = get_param(matrix, self.regelkreis, 'pv_min_w', 2000)
        forecast_min = get_param(matrix, self.regelkreis, 'forecast_rest_min_kwh', 10)
        ww_min = get_param(matrix, self.regelkreis, 'ww_min_c', 50)

        # Sunset-Sperre: <2h vor Sonnenuntergang → keine neue Verschiebung
        # Begründung: So kurz vor Nacht muss die WP noch heizen können
        if obs.sunset is not None:
            now_h = datetime.now().hour + datetime.now().minute / 60.0
            rest_h = obs.sunset - now_h
            if 0 < rest_h < 2.0:
                LOG.debug(f"WW-Verschiebung: Sunset-Sperre aktiv "
                          f"(rest_h={rest_h:.1f} — keine Verschiebung <2h vor Sunset)")
                return False

        return (soc < soc_schwelle
                and pv < pv_min
                and forecast > forecast_min
                and ww_ist > ww_min)

    def _soll_zuruecknehmen(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob Verschiebung aufzuheben ist."""
        pv_restore = get_param(matrix, self.regelkreis, 'pv_restore_w', 3000)
        soc_restore = get_param(matrix, self.regelkreis, 'soc_restore_pct', 30)
        ww_notfall = get_param(matrix, self.regelkreis, 'ww_notfall_c', 42)
        max_h = get_param(matrix, self.regelkreis, 'max_verschiebung_h', 1)

        # Timeout
        if _verschoben['ww_seit']:
            dauer_h = (datetime.now() - _verschoben['ww_seit']).total_seconds() / 3600
            if dauer_h >= max_h:
                LOG.info(f"WW-Verschiebung: Timeout nach {dauer_h:.1f}h")
                return True

        # PV wieder ausreichend
        if obs.pv_total_w is not None and obs.pv_total_w > pv_restore:
            return True

        # SOC erholt
        if obs.batt_soc_pct is not None and obs.batt_soc_pct > soc_restore:
            return True

        # WW zu kalt — Notfall-Rücknahme
        if obs.ww_temp_c is not None and obs.ww_temp_c < ww_notfall:
            LOG.info(f"WW-Verschiebung: Notfall-Rücknahme WW={obs.ww_temp_c}°C < {ww_notfall}°C")
            return True

        return False

    def _standard_temp(self, matrix: dict) -> int:
        """Standard-WW-Soll aus ww_absenkung übernehmen."""
        return int(get_param(matrix, 'ww_absenkung', 'standard_temp_c', 57))

    def _verschiebung_temp(self, matrix: dict) -> int:
        """Ziel-WW-Soll bei Verschiebung: Standard minus verschiebung_k."""
        standard = self._standard_temp(matrix)
        k = get_param(matrix, self.regelkreis, 'verschiebung_k', 7)
        return int(standard - k)

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            _verschoben['ww_aktiv'] = False
            return 0

        # WP-Laufzeit-Tracker aktualisieren
        _aktualisiere_wp_laufzeit(obs)

        verschiebung_temp = self._verschiebung_temp(matrix)
        aktuell = obs.wp_ww_soll_c

        # Laufzeitschutz-Parameter (konfigurierbar)
        min_lauf_min = get_param(matrix, self.regelkreis, 'wp_min_lauf_min', 15)
        cooldown_s = get_param(matrix, self.regelkreis, 'cooldown_nach_ruecknahme_s', 3600)

        if _verschoben['ww_aktiv']:
            # Verschiebung läuft — prüfe Rücknahme
            if self._soll_zuruecknehmen(obs, matrix):
                # Kompressorschutz: Nicht umschalten während WP < 15min läuft
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"WW-Verschiebung: Rücknahme blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _verschoben['ww_aktiv'] = False
                _verschoben['ww_seit'] = None
                _verschoben['ww_letzte_ruecknahme'] = datetime.now()
                LOG.info("WW-Verschiebung: Rücknahme → Standard wiederherstellen")
                standard = self._standard_temp(matrix)
                if aktuell is not None and int(aktuell) != standard:
                    return get_score_gewicht(matrix, self.regelkreis)
                return 0
            # Noch aktiv — Register-Konsistenz sicherstellen
            if aktuell is not None and int(aktuell) != int(verschiebung_temp):
                return get_score_gewicht(matrix, self.regelkreis)
            return 0
        else:
            # Nicht verschoben — prüfe Aktivierung
            if self._soll_verschieben(obs, matrix):
                # Cooldown: Mindestens 1h seit letzter Rücknahme
                if _verschiebung_cooldown_aktiv('ww', cooldown_s):
                    return 0
                # Kompressorschutz: Nicht umschalten während WP < 15min läuft
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"WW-Verschiebung: Aktivierung blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _verschoben['ww_aktiv'] = True
                _verschoben['ww_seit'] = datetime.now()
                LOG.info(f"WW-Verschiebung: Aktiviert "
                         f"(SOC={obs.batt_soc_pct}%, PV={obs.pv_total_w}W, "
                         f"Forecast-Rest={obs.forecast_rest_kwh}kWh, "
                         f"WW={obs.ww_temp_c}°C)")
                return get_score_gewicht(matrix, self.regelkreis)
            return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktuell = obs.wp_ww_soll_c

        if _verschoben['ww_aktiv']:
            ziel = self._verschiebung_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_ww_soll',
                'wert': ziel,
                'grund': (f'WW-Verschiebung: {aktuell}°C → {ziel}°C '
                          f'(SOC={obs.batt_soc_pct}%, PV={obs.pv_total_w}W, '
                          f'Forecast-Rest={obs.forecast_rest_kwh}kWh)'),
            }]
        else:
            # Rücknahme → Standard wiederherstellen
            standard = self._standard_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_ww_soll',
                'wert': standard,
                'grund': (f'WW-Verschiebung aufgehoben: {aktuell}°C → {standard}°C '
                          f'(PV={obs.pv_total_w}W, SOC={obs.batt_soc_pct}%)'),
            }]


class RegelHeizVerschiebung(Regel):
    """Heiz-Soll absenken bei ungünstiger Energiebilanz.

    Bedingungspfade:

      AKTIVIERUNG (alle müssen zutreffen):
        1. Batterie-SOC < soc_schwelle_pct        → Batt. fast leer
        2. PV-Leistung  < pv_min_w                → geringer Ertrag
        3. Forecast-Rest > forecast_rest_min_kwh   → später gute Prognose
           (Ausnahme: <2h vor Sunset → Schwelle halbiert)

      RÜCKNAHME (einer reicht):
        a. PV-Leistung  > pv_restore_w             → PV wieder da
        b. Batterie-SOC > soc_restore_pct           → Batterie erholt
        c. Dauer        > max_verschiebung_h        → Timeout

    Aktion: Heiz-Soll um verschiebung_k absenken (z.B. 7K → 30°C),
            WP reduziert Heizleistung. Bei Rücknahme: Standard aus
            heiz_absenkung wiederherstellen.

    Koordination: Setzt _verschoben['heiz_aktiv'] — RegelHeizAbsenkung
                  prüft dieses Flag und gibt nach (Score 0).
    """

    name = 'heiz_verschiebung'
    regelkreis = 'heiz_verschiebung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _soll_verschieben(self, obs: ObsState, matrix: dict) -> bool:
        soc = obs.batt_soc_pct
        pv = obs.pv_total_w
        forecast = obs.forecast_rest_kwh

        if any(v is None for v in (soc, pv, forecast)):
            return False

        soc_schwelle = get_param(matrix, self.regelkreis, 'soc_schwelle_pct', 10)
        pv_min = get_param(matrix, self.regelkreis, 'pv_min_w', 2000)
        forecast_min = get_param(matrix, self.regelkreis, 'forecast_rest_min_kwh', 10)

        # Sunset-Sperre: <2h vor Sonnenuntergang → keine neue Verschiebung
        if obs.sunset is not None:
            now_h = datetime.now().hour + datetime.now().minute / 60.0
            rest_h = obs.sunset - now_h
            if 0 < rest_h < 2.0:
                return False

        return (soc < soc_schwelle
                and pv < pv_min
                and forecast > forecast_min)

    def _soll_zuruecknehmen(self, obs: ObsState, matrix: dict) -> bool:
        pv_restore = get_param(matrix, self.regelkreis, 'pv_restore_w', 3000)
        soc_restore = get_param(matrix, self.regelkreis, 'soc_restore_pct', 30)
        max_h = get_param(matrix, self.regelkreis, 'max_verschiebung_h', 1)

        if _verschoben['heiz_seit']:
            dauer_h = (datetime.now() - _verschoben['heiz_seit']).total_seconds() / 3600
            if dauer_h >= max_h:
                LOG.info(f"Heiz-Verschiebung: Timeout nach {dauer_h:.1f}h")
                return True

        if obs.pv_total_w is not None and obs.pv_total_w > pv_restore:
            return True

        if obs.batt_soc_pct is not None and obs.batt_soc_pct > soc_restore:
            return True

        return False

    def _standard_temp(self, matrix: dict) -> int:
        return int(get_param(matrix, 'heiz_absenkung', 'standard_temp_c', 37))

    def _verschiebung_temp(self, matrix: dict) -> int:
        """Ziel-Heiz-Soll bei Verschiebung: Standard minus verschiebung_k."""
        standard = self._standard_temp(matrix)
        k = get_param(matrix, self.regelkreis, 'verschiebung_k', 7)
        return max(18, int(standard - k))

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            _verschoben['heiz_aktiv'] = False
            return 0

        # WP-Laufzeit-Tracker aktualisieren (idempotent, WW hat ggf. schon)
        _aktualisiere_wp_laufzeit(obs)

        verschiebung_temp = self._verschiebung_temp(matrix)
        aktuell = obs.wp_heiz_soll_c

        # Laufzeitschutz-Parameter (konfigurierbar)
        min_lauf_min = get_param(matrix, self.regelkreis, 'wp_min_lauf_min', 15)
        cooldown_s = get_param(matrix, self.regelkreis, 'cooldown_nach_ruecknahme_s', 3600)

        if _verschoben['heiz_aktiv']:
            if self._soll_zuruecknehmen(obs, matrix):
                # Kompressorschutz: Nicht umschalten während WP < 15min läuft
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"Heiz-Verschiebung: Rücknahme blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _verschoben['heiz_aktiv'] = False
                _verschoben['heiz_seit'] = None
                _verschoben['heiz_letzte_ruecknahme'] = datetime.now()
                LOG.info("Heiz-Verschiebung: Rücknahme → Standard wiederherstellen")
                standard = self._standard_temp(matrix)
                if aktuell is not None and int(aktuell) != standard:
                    return get_score_gewicht(matrix, self.regelkreis)
                return 0
            if aktuell is not None and int(aktuell) != int(verschiebung_temp):
                return get_score_gewicht(matrix, self.regelkreis)
            return 0
        else:
            if self._soll_verschieben(obs, matrix):
                # Cooldown: Mindestens 1h seit letzter Rücknahme
                if _verschiebung_cooldown_aktiv('heiz', cooldown_s):
                    return 0
                # Kompressorschutz: Nicht umschalten während WP < 15min läuft
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"Heiz-Verschiebung: Aktivierung blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _verschoben['heiz_aktiv'] = True
                _verschoben['heiz_seit'] = datetime.now()
                LOG.info(f"Heiz-Verschiebung: Aktiviert "
                         f"(SOC={obs.batt_soc_pct}%, PV={obs.pv_total_w}W, "
                         f"Forecast-Rest={obs.forecast_rest_kwh}kWh)")
                return get_score_gewicht(matrix, self.regelkreis)
            return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktuell = obs.wp_heiz_soll_c

        if _verschoben['heiz_aktiv']:
            ziel = self._verschiebung_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': ziel,
                'grund': (f'Heiz-Verschiebung: {aktuell}°C → {ziel}°C '
                          f'(SOC={obs.batt_soc_pct}%, PV={obs.pv_total_w}W, '
                          f'Forecast-Rest={obs.forecast_rest_kwh}kWh)'),
            }]
        else:
            standard = self._standard_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': standard,
                'grund': (f'Heiz-Verschiebung aufgehoben: {aktuell}°C → {standard}°C '
                          f'(PV={obs.pv_total_w}W, SOC={obs.batt_soc_pct}%)'),
            }]


# ═════════════════════════════════════════════════════════════
# PV-Überschuss → Thermische Speicherung (P2, fast-Zyklus)
# ═════════════════════════════════════════════════════════════

# Boost-Status (modul-global)
_boost = {
    'ww_aktiv': False,
    'ww_seit': None,
    'ww_letzte_ruecknahme': None,
}


class RegelWwBoost(Regel):
    """WW-Soll anheben bei PV-Überschuss + voller Batterie.

    Idee: Wenn Batterie fast voll und PV-Überschuss vorhanden, die
    überschüssige Energie als Wärme im WW-Speicher puffern statt
    einzuspeisen (Eigenverbrauchsoptimierung).

    Bedingungspfade:

      AKTIVIERUNG (alle müssen zutreffen):
        1. Batterie-SOC > soc_min_pct               → Batterie fast voll
        2. Batterie lädt NICHT (batt_power ≤ 200W)  → Ladeschutz
        3. WW-Ist       < ww_max_c                   → noch Platz für Wärme
        4. is_day = True                              → nur tagsüber

      RÜCKNAHME (einer reicht):
        a. Batterie lädt (batt_power > 200W)          → Ladeschutz
        b. WW-Ist       > ww_max_c                    → WW warm genug
        c. Batterie-SOC < soc_abbruch_pct             → Batterie braucht Strom
        d. Dauer        > max_boost_h                  → Timeout

    Aktion: WW-Soll von Standard (z.B. 57°C) auf boost_temp_c
            erhöhen (z.B. 62°C). Rücknahme → Standard.

    Koordination: Setzt _boost['ww_aktiv'] — RegelWwAbsenkung
                  prüft dieses Flag NICHT (Boost hat ohnehin höheren Soll).
                  Verschiebung-Flag _verschoben['ww_aktiv'] hat Vorrang
                  (bei SOC-Krise wird nicht geboostet).
    """

    name = 'ww_boost'
    regelkreis = 'ww_boost'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _soll_boosten(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob WW-Boost angebracht ist."""
        soc = obs.batt_soc_pct
        batt_p = obs.batt_power_w  # positiv = Laden, negativ = Entladen
        ww_ist = obs.ww_temp_c

        if any(v is None for v in (soc, ww_ist)):
            return False
        if not obs.is_day:
            return False

        soc_min = get_param(matrix, self.regelkreis, 'soc_min_pct', 90)
        ww_max = get_param(matrix, self.regelkreis, 'ww_max_c', 60)

        # Ladeschutz: Kein Boost solange Batterie aktiv lädt
        # (Verschiebung ist erlaubt, Boost nicht — Batterie hat Vorrang)
        if batt_p is not None and batt_p > 200:
            return False

        return (soc >= soc_min
                and ww_ist < ww_max)

    def _soll_zuruecknehmen(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob Boost aufzuheben ist."""
        max_h = get_param(matrix, self.regelkreis, 'max_boost_h', 2)
        ww_max = get_param(matrix, self.regelkreis, 'ww_max_c', 60)
        soc_abbruch = get_param(matrix, self.regelkreis, 'soc_abbruch_pct', 80)

        # Timeout
        if _boost['ww_seit']:
            dauer_h = (datetime.now() - _boost['ww_seit']).total_seconds() / 3600
            if dauer_h >= max_h:
                LOG.info(f"WW-Boost: Timeout nach {dauer_h:.1f}h")
                return True

        # Batterie lädt → sofort aufhören (Ladeschutz)
        if obs.batt_power_w is not None and obs.batt_power_w > 200:
            LOG.info(f"WW-Boost: Abbruch — Batterie lädt ({obs.batt_power_w}W)")
            return True

        # WW warm genug
        if obs.ww_temp_c is not None and obs.ww_temp_c >= ww_max:
            LOG.info(f"WW-Boost: WW-Ist {obs.ww_temp_c}°C ≥ {ww_max}°C — Ziel erreicht")
            return True

        # SOC fällt → Batterie braucht den Strom
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < soc_abbruch:
            return True

        return False

    def _boost_temp(self, matrix: dict) -> int:
        """Boost-Zieltemperatur."""
        return int(get_param(matrix, self.regelkreis, 'boost_temp_c', 60))

    def _standard_temp(self, matrix: dict) -> int:
        """Standard-WW-Soll aus ww_absenkung."""
        return int(get_param(matrix, 'ww_absenkung', 'standard_temp_c', 57))

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            _boost['ww_aktiv'] = False
            return 0

        # Verschiebung hat absoluten Vorrang (SOC-Krise)
        if _verschoben['ww_aktiv']:
            _boost['ww_aktiv'] = False
            return 0

        _aktualisiere_wp_laufzeit(obs)
        aktuell = obs.wp_ww_soll_c
        min_lauf_min = get_param(matrix, self.regelkreis, 'wp_min_lauf_min', 15)
        cooldown_s = get_param(matrix, self.regelkreis, 'cooldown_nach_ruecknahme_s', 3600)

        if _boost['ww_aktiv']:
            if self._soll_zuruecknehmen(obs, matrix):
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"WW-Boost: Rücknahme blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _boost['ww_aktiv'] = False
                _boost['ww_seit'] = None
                _boost['ww_letzte_ruecknahme'] = datetime.now()
                LOG.info("WW-Boost: Rücknahme → Standard wiederherstellen")
                standard = self._standard_temp(matrix)
                if aktuell is not None and int(aktuell) != standard:
                    return get_score_gewicht(matrix, self.regelkreis)
                return 0
            # Noch aktiv — Register-Konsistenz sicherstellen
            boost_temp = self._boost_temp(matrix)
            if aktuell is not None and int(aktuell) != boost_temp:
                return get_score_gewicht(matrix, self.regelkreis)
            return 0
        else:
            if self._soll_boosten(obs, matrix):
                # Cooldown: 1h seit letzter Rücknahme
                letzte = _boost.get('ww_letzte_ruecknahme')
                if letzte and (datetime.now() - letzte).total_seconds() < cooldown_s:
                    return 0
                if _wp_laeuft_kuerzer_als(min_lauf_min):
                    LOG.info(f"WW-Boost: Aktivierung blockiert — "
                             f"WP-Kompressorschutz ({min_lauf_min} min Mindestlauf)")
                    return 0
                _boost['ww_aktiv'] = True
                _boost['ww_seit'] = datetime.now()
                LOG.info(f"WW-Boost: Aktiviert "
                         f"(SOC={obs.batt_soc_pct}%, Batt={obs.batt_power_w}W, "
                         f"WW={obs.ww_temp_c}°C)")
                return get_score_gewicht(matrix, self.regelkreis)
            return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktuell = obs.wp_ww_soll_c

        if _boost['ww_aktiv']:
            ziel = self._boost_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_ww_soll',
                'wert': ziel,
                'grund': (f'WW-Boost: {aktuell}°C → {ziel}°C '
                          f'(SOC={obs.batt_soc_pct}%, Batt={obs.batt_power_w}W, '
                          f'WW={obs.ww_temp_c}°C — Batterie voll, thermisch puffern)'),
            }]
        else:
            standard = self._standard_temp(matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_ww_soll',
                'wert': standard,
                'grund': (f'WW-Boost aufgehoben: {aktuell}°C → {standard}°C '
                          f'(SOC={obs.batt_soc_pct}%)'),
            }]


# ═════════════════════════════════════════════════════════════
# WP täglicher Pflichtlauf (P2, fast-Zyklus)
# ═════════════════════════════════════════════════════════════

# Pflichtlauf-Status (modul-global)
_pflichtlauf = {
    'letzter_tag': None,         # date — für Tageswechsel-Reset
    'pruefung_erledigt': False,  # Einmalige Prüfung pro Tag
    'boost_aktiv': False,
    'boost_seit': None,
    'wp_lief_waehrend_boost': False,
}


class RegelWpPflichtlauf(Regel):
    """WP-Pflichtlauf: Heiz-Soll kurzzeitig boosten wenn WP lange nicht lief.

    Zweck: Sicherstellen dass die WP regelmäßig den Kompressor startet
    (Schmierung, Ventilbewegung). Im Sommer bei Heizpatrone am gleichen
    Sensor könnte die WP sonst tagelang stillstehen.

    Logik:
      - Einmalige Prüfung pro Tag in den späten Morgenstunden
        (pruef_start_h bis pruef_ende_h, Default 9-10 Uhr)
      - Prüft WP-Energieverbrauch der letzten 30h (wp_last30h_kwh)
      - Wenn ≥ wp_min_30h_kwh (0.5 kWh): WP lief → nichts tun
      - Wenn < Schwelle: Heiz-Boost auf boost_temp_c (45°C)
      - Boost läuft max max_boost_min (30min)
      - Selbstlaufend saisonal: Im Winter läuft die WP sowieso →
        30h-Prüfung findet immer Verbrauch → Boost wird nie nötig.
        Nur im Sommer bei HP-Dominanz kann der Boost triggern.

    Koordination: _pflichtlauf['boost_aktiv'] wird von
                  RegelHeizAbsenkung gelesen → gibt nach während Boost.
    """

    name = 'wp_pflichtlauf'
    regelkreis = 'wp_pflichtlauf'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _tageswechsel_prüfen(self):
        """Reset bei Tageswechsel."""
        heute = datetime.now().date()
        if _pflichtlauf['letzter_tag'] != heute:
            _pflichtlauf['pruefung_erledigt'] = False
            _pflichtlauf['boost_aktiv'] = False
            _pflichtlauf['boost_seit'] = None
            _pflichtlauf['wp_lief_waehrend_boost'] = False
            _pflichtlauf['letzter_tag'] = heute

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        self._tageswechsel_prüfen()

        # Bereits geprüft heute (egal ob Boost lief oder nicht) → fertig
        if _pflichtlauf['pruefung_erledigt'] and not _pflichtlauf['boost_aktiv']:
            return 0

        # ── Laufender Boost verwalten ──
        if _pflichtlauf['boost_aktiv']:
            # WP-Lauf während Boost erkennen
            if obs.wp_active:
                _pflichtlauf['wp_lief_waehrend_boost'] = True

            max_min = get_param(matrix, self.regelkreis, 'max_boost_min', 30)
            min_lauf = get_param(matrix, self.regelkreis, 'min_lauf_min', 5)
            seit = _pflichtlauf['boost_seit']
            if seit:
                dauer_min = (datetime.now() - seit).total_seconds() / 60

                # WP hat gelaufen UND Mindestlaufzeit → Erfolg
                if _pflichtlauf['wp_lief_waehrend_boost'] and dauer_min >= min_lauf:
                    _pflichtlauf['boost_aktiv'] = False
                    _pflichtlauf['boost_seit'] = None
                    LOG.info(f"WP-Pflichtlauf: Erfolg nach {dauer_min:.0f}min "
                             f"— WP-Kompressor hat gelaufen")
                    # Standard wiederherstellen
                    standard = int(get_param(matrix, 'heiz_absenkung',
                                             'standard_temp_c', 37))
                    aktuell = obs.wp_heiz_soll_c
                    if aktuell is not None and int(aktuell) != standard:
                        return get_score_gewicht(matrix, self.regelkreis)
                    return 0

                # Timeout → Boost beenden
                if dauer_min >= max_min:
                    _pflichtlauf['boost_aktiv'] = False
                    _pflichtlauf['boost_seit'] = None
                    if not _pflichtlauf['wp_lief_waehrend_boost']:
                        LOG.warning(f"WP-Pflichtlauf: FEHLGESCHLAGEN — WP hat "
                                    f"nach {dauer_min:.0f}min Boost NICHT "
                                    f"gestartet! Bitte prüfen.")
                    else:
                        LOG.info(f"WP-Pflichtlauf: Boost beendet nach "
                                 f"{dauer_min:.0f}min")
                    # Standard wiederherstellen
                    standard = int(get_param(matrix, 'heiz_absenkung',
                                             'standard_temp_c', 37))
                    aktuell = obs.wp_heiz_soll_c
                    if aktuell is not None and int(aktuell) != standard:
                        return get_score_gewicht(matrix, self.regelkreis)
                    return 0

            # Boost noch aktiv → Konsistenz sicherstellen
            boost_temp = int(get_param(matrix, self.regelkreis, 'boost_temp_c', 45))
            aktuell = obs.wp_heiz_soll_c
            if aktuell is not None and int(aktuell) != boost_temp:
                return get_score_gewicht(matrix, self.regelkreis)
            return 0

        # ── Einmalige Morgen-Prüfung ──
        pruef_start = get_param(matrix, self.regelkreis, 'pruef_start_h', 9)
        pruef_ende = get_param(matrix, self.regelkreis, 'pruef_ende_h', 10)
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        if now_h < pruef_start or now_h >= pruef_ende:
            return 0

        # Prüfungsfenster erreicht — 30h-Verbrauch auswerten
        _pflichtlauf['pruefung_erledigt'] = True

        wp_min = get_param(matrix, self.regelkreis, 'wp_min_30h_kwh', 0.5)
        wp_30h = obs.wp_last30h_kwh

        if wp_30h is not None and wp_30h >= wp_min:
            LOG.info(f"WP-Pflichtlauf: WP lief in letzten 30h "
                     f"({wp_30h:.1f} kWh ≥ {wp_min} kWh) — kein Boost nötig")
            return 0

        # WP hat in 30h nicht genug verbraucht → Boost starten
        _pflichtlauf['boost_aktiv'] = True
        _pflichtlauf['boost_seit'] = datetime.now()
        _pflichtlauf['wp_lief_waehrend_boost'] = False
        LOG.info(f"WP-Pflichtlauf: Boost gestartet "
                 f"(wp_last30h={wp_30h or 0:.1f} kWh < {wp_min} kWh)")
        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktuell = obs.wp_heiz_soll_c

        if _pflichtlauf['boost_aktiv']:
            ziel = int(get_param(matrix, self.regelkreis, 'boost_temp_c', 45))
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': ziel,
                'grund': (f'WP-Pflichtlauf: Heiz-Boost {aktuell}°C → {ziel}°C '
                          f'(WP letzte 30h: {obs.wp_last30h_kwh or 0:.1f} kWh)'),
            }]
        else:
            standard = int(get_param(matrix, 'heiz_absenkung', 'standard_temp_c', 37))
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': standard,
                'grund': (f'WP-Pflichtlauf beendet: {aktuell}°C → {standard}°C'),
            }]


# ═════════════════════════════════════════════════════════════
# FBH-Heizbedarf: Heiz-Soll priorisiert nach Außentemperatur
# ═════════════════════════════════════════════════════════════

# Heizbedarf-Status (modul-global)
_heizbedarf = {
    'aktiv': False,
    'seit': None,
}


class RegelHeizBedarf(Regel):
    """FBH-Heizbedarf: Heiz-Soll nach Außentemperatur priorisieren.

    Zweck: Wenn die Fußbodenheizung (Fritz!DECT) Wärme anfordert
    (fbh_aktiv=True), wird der Heiz-Soll je nach Außentemperatur
    angehoben oder zumindest auf Standard gehalten — so dass
    Absenkung/Verschiebung den Heizkreis nicht unterkühlen.

    Prioritätsstufen (Außentemperatur):
      ≤ temp_kalt_c (5°C):  Heiz-Soll = standard + boost_k  (volle Prio)
      ≤ temp_mild_c (15°C): Heiz-Soll = standard            (mittlere Prio)
      > temp_mild_c:        Keine Aktion                     (gering)

    Koordination: Heizbedarf setzt _heizbedarf['aktiv'] und blockiert
                  damit die Heiz-Absenkung zyklusuebergreifend. Fuer
                  aktive Heiz-Verschiebung bleibt _verschoben['heiz_aktiv']
                  der bewusst hoeher priorisierte Ausnahmefall.
    """

    name = 'heiz_bedarf'
    regelkreis = 'heiz_bedarf'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Benötigte Daten vorhanden?
        if obs.wp_aussen_temp_c is None:
            return 0

        aussen = obs.wp_aussen_temp_c
        temp_mild = get_param(matrix, self.regelkreis, 'temp_mild_c', 15)

        # FBH inaktiv oder warm genug → Rücknahme
        if not obs.fbh_aktiv or aussen > temp_mild:
            if _heizbedarf['aktiv']:
                _heizbedarf['aktiv'] = False
                _heizbedarf['seit'] = None
                LOG.info(f"HeizBedarf: Beendet "
                         f"(FBH={'an' if obs.fbh_aktiv else 'aus'}, "
                         f"Außen={aussen:.1f}°C)")
                # Heiz-Soll auf Standard zurückstellen (falls überhöht)
                standard = int(get_param(matrix, 'heiz_absenkung',
                                         'standard_temp_c', 37))
                aktuell = obs.wp_heiz_soll_c
                if aktuell is not None and int(aktuell) > standard:
                    return get_score_gewicht(matrix, self.regelkreis)
            return 0

        # Timeout prüfen
        max_h = get_param(matrix, self.regelkreis, 'max_bedarf_h', 3)
        if _heizbedarf['aktiv'] and _heizbedarf['seit']:
            dauer_h = (datetime.now() - _heizbedarf['seit']).total_seconds() / 3600
            if dauer_h >= max_h:
                _heizbedarf['aktiv'] = False
                _heizbedarf['seit'] = None
                LOG.info(f"HeizBedarf: Timeout nach {dauer_h:.1f}h")
                return 0

        # FBH aktiv + kalt/mild → aktivieren oder halten
        if not _heizbedarf['aktiv']:
            _heizbedarf['aktiv'] = True
            _heizbedarf['seit'] = datetime.now()
            LOG.info(f"HeizBedarf: Aktiviert "
                     f"(FBH=an, Außen={aussen:.1f}°C)")

        # Zielwert bestimmen
        ziel = self._ziel_temp(obs, matrix)
        aktuell = obs.wp_heiz_soll_c
        if aktuell is not None and int(aktuell) == ziel:
            return 0  # Register stimmt schon
        return get_score_gewicht(matrix, self.regelkreis)

    def _ziel_temp(self, obs: ObsState, matrix: dict) -> int:
        """Heiz-Soll je nach Außentemperatur berechnen."""
        aussen = obs.wp_aussen_temp_c or 10.0
        standard = int(get_param(matrix, 'heiz_absenkung',
                                 'standard_temp_c', 37))
        temp_kalt = get_param(matrix, self.regelkreis, 'temp_kalt_c', 5)
        boost_k = int(get_param(matrix, self.regelkreis, 'boost_k', 3))

        if aussen <= temp_kalt:
            return min(standard + boost_k, 47)  # Modbus-Max beachten
        else:
            return standard  # Mittlere Prio: Standard halten

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktuell = obs.wp_heiz_soll_c

        if _heizbedarf['aktiv']:
            ziel = self._ziel_temp(obs, matrix)
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': ziel,
                'grund': (f'HeizBedarf: {aktuell}°C → {ziel}°C '
                          f'(FBH=an, Außen={obs.wp_aussen_temp_c:.1f}°C)'),
            }]
        else:
            # Rücknahme auf Standard
            standard = int(get_param(matrix, 'heiz_absenkung',
                                     'standard_temp_c', 37))
            return [{
                'tier': 2,
                'aktor': 'waermepumpe',
                'kommando': 'set_heiz_soll',
                'wert': standard,
                'grund': (f'HeizBedarf beendet: {aktuell}°C → {standard}°C'),
            }]
