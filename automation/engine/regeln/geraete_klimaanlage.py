"""
geraete_klimaanlage.py — RegelKlimaanlage (Rolle C, fast-Zyklus).

Temperaturgefuehrter Thermoschutz der Heizhaus-Klimaanlage via Fritz!DECT mit
Schaltfrequenz-Cooldown und Extern-Erkennung. Erbt die Override-Cancellation
von RegelHeizpatrone. Re-Export ueber geraete.py.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Optional

from automation.engine.obs_state import ObsState
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
    get_effective_forecast_quality, get_forecast_tier, FC_TIER_GUT,
)
from automation.engine.schaltlog import logge_extern
from automation.engine.regeln.geraete_heizpatrone import RegelHeizpatrone

LOG = logging.getLogger('engine')
RAM_DB_PATH = '/dev/shm/automation_obs.db'

# Override-Bridge: Steuerbox-Klima-Aktionen als engine-initiiert markieren,
# damit die Extern-Erkennung keinen falschen OFF->ON Extern-Event loggt.
_klima_engine_ein_ts: float = 0.0


def registriere_klima_engine_ein() -> None:
    """Markiere eine engine-initiierte Klima-Einschaltung.

    Wird sowohl von RegelKlimaanlage als auch vom Override-Processor genutzt.
    """
    global _klima_engine_ein_ts
    _klima_engine_ein_ts = time.time()


def klima_engine_ein_kuerzlich(timeout_s: float = 180.0) -> bool:
    """True wenn kürzlich ein engine-initiiertes Klima-EIN markiert wurde."""
    global _klima_engine_ein_ts
    if _klima_engine_ein_ts <= 0:
        return False
    if (time.time() - _klima_engine_ein_ts) < timeout_s:
        return True
    _klima_engine_ein_ts = 0.0  # Remanenz sauber abbauen
    return False


class RegelKlimaanlage(RegelHeizpatrone):
    # Eigenstaendige Thermoschutzregel fuer das Heizhaus via Fritz!DECT.
    #
    # Extern-Erkennung:
    #   Identisches Muster wie HP: Zustandsübergangs-Erkennung (OFF↔ON ohne
    #   Engine-Beteiligung). Während extern_respekt_s wird der erkannte Zustand
    #   (ON oder OFF) aktiv gehalten.
    #   Zusätzlich wird ein aktiver Steuerbox-Override-Hold (status=active)
    #   für klima_toggle ON/OFF symmetrisch respektiert.

    name = 'klimaanlage'
    regelkreis = 'klimaanlage'
    aktor = 'fritzdect'
    engine_zyklus = 'fast'

    def __init__(self):
        super().__init__()
        # Klima-spezifische Extern-Erkennung (getrennt von HP-State)
        self._klima_letzter_zustand: Optional[bool] = None
        self._klima_extern_ein_ts: float = 0
        self._klima_extern_aus_ts: float = 0
        self._engine_klima_ein_ts: float = 0
        self._engine_klima_aus_ts: float = 0
        # Schaltfrequenz-Schutz (Kompressor-Kurzzyklen)
        self._klima_schalt_aus_zeiten: list[float] = []  # AUS-Zeitstempel (Sliding Window)
        self._klima_schalt_cooldown_bis: float = 0.0     # epoch: EIN-Sperre bis
        # Lastflanken-Detektion (Hysterese auf klima_power_w)
        self._klima_kompressor_aktiv: Optional[bool] = None  # True=HIGH, False=LOW, None=unbekannt
        self._klima_letztes_aus_event_ts: float = 0.0        # Dedup-Guard (min. 60 s zwischen Events)

    # ── Schaltfrequenz-Schutz ────────────────────────────────

    # Hysterese-Schwellen für Kompressor-Lasterkennung (Klima ~1 kW Inverter-Sprung,
    # Standby ~30 W). Werte robust auch bei minimalem Lüfter-Betrieb.
    _KOMP_ON_THR_W: float = 600.0
    _KOMP_OFF_THR_W: float = 200.0
    _AUS_EVENT_DEDUP_S: float = 60.0  # min. Abstand zwischen gezählten AUS-Events

    def _erkenne_kompressor_aus(self, obs: ObsState, matrix: dict) -> None:
        """Erkennt Kompressor-AUS via Lastflanke an klima_power_w.

        Hintergrund: Das Klimagerät taktet intern (eigener Thermostat) — die
        Fritz!DECT-Steckdose bleibt EIN, nur die Last springt ~1 kW ↔ ~30 W.
        Eine Erkennung über SD-Schaltflanken (klima_aktiv) verpasst diese
        Kompressor-Kurzzyklen vollständig.

        Trigger: HIGH→LOW-Übergang mit Hysterese (≥600 W → ≤200 W). Erfasst
        sowohl interne Kompressor-Pausen (SD bleibt EIN, Last fällt auf ~30 W)
        als auch echte SD-Schaltvorgänge (Last fällt auf 0 W).

        Dedup: minimum `_AUS_EVENT_DEDUP_S` zwischen gezählten Events, damit
        kurze Last-Wackler nicht mehrfach zählen.
        """
        pw = obs.klima_power_w
        if pw is None:
            return
        new_state = self._klima_kompressor_aktiv
        if pw >= self._KOMP_ON_THR_W:
            new_state = True
        elif pw <= self._KOMP_OFF_THR_W:
            new_state = False
        # else: in Hysterese-Band → State unverändert (carry-over)

        if self._klima_kompressor_aktiv is True and new_state is False:
            now = time.time()
            if (now - self._klima_letztes_aus_event_ts) >= self._AUS_EVENT_DEDUP_S:
                self._klima_letztes_aus_event_ts = now
                LOG.info(
                    'Klima Kompressor-AUS erkannt (Last %.0f W → Lastflanke HIGH→LOW)', pw
                )
                self._verarbeite_schaltfrequenz_aus(now, matrix)
        self._klima_kompressor_aktiv = new_state

    def _verarbeite_schaltfrequenz_aus(self, now: float, matrix: dict) -> None:
        """Jedes AUS-Ereignis zählen. Bei 2× AUS im Fenster → Cooldown.

        Wird ausschließlich von `_erkenne_kompressor_aus` aufgerufen (Lastflanke).
        Sliding-Window: Einträge außerhalb `schaltintervall_s` werden verworfen.
        
        **WICHTIG:** Wenn Cooldown bereits aktiv ist, wird die neue AUS-Flanke
        NICHT gezählt und der bestehende Cooldown wird NICHT zurückgesetzt!
        Das verhindert, dass schnelle Kompressor-Takten den Timer verlängern.
        
        Nach Cooldown-Aktivierung wird die History geleert. Waehrend Cooldown
        werden AUS-Flanken ignoriert; nach Ablauf startet das Fenster mit der
        naechsten AUS-Flanke neu.
        
        Cooldown-Zeitpunkt wird in RAM-DB (engine_flags) persistiert, damit
        die Web-API (B-Rolle) ihn lesen kann ohne C-Modul-Import.
        """
        schaltintervall_s = float(get_param(
            matrix, self.regelkreis, 'schaltintervall_s', 1800
        ))
        cooldown_s = float(get_param(
            matrix, self.regelkreis, 'cooldown_s', 3600
        ))

        # Wenn Cooldown bereits aktiv: ignoriere neue AUS-Flanke komplett
        # (Flanke wird nicht gezählt, Timer wird nicht verlängert)
        if self._klima_schalt_cooldown_bis > now:
            remaining = (self._klima_schalt_cooldown_bis - now) / 60
            LOG.info(
                'Klima AUS-Flanke während Cooldown aktiv (noch %.0f Min) → IGNORIERT',
                remaining,
            )
            return
        
        # Nach Cooldown-Ablauf: neues Fenster starten und aktuelle Flanke zaehlen.
        if self._klima_schalt_cooldown_bis > 0:
            LOG.info(
                'Klima: Cooldown abgelaufen, AUS-Zähler zurückgesetzt für neue Fenster'
            )
            self._klima_schalt_cooldown_bis = 0.0
            self._klima_schalt_aus_zeiten = []
            self._schreibe_cooldown_in_db(0.0)
        
        # Normaler Betrieb: AUS-Flanke zählen
        self._klima_schalt_aus_zeiten.append(now)
        # Einträge außerhalb des Fensters entfernen
        self._klima_schalt_aus_zeiten = [
            t for t in self._klima_schalt_aus_zeiten
            if now - t <= schaltintervall_s
        ]

        if len(self._klima_schalt_aus_zeiten) >= 2:
            self._klima_schalt_cooldown_bis = now + cooldown_s
            self._schreibe_cooldown_in_db(self._klima_schalt_cooldown_bis)
            LOG.warning(
                'Klima Schaltfrequenz-Cooldown: %d×AUS in %.0f Min → '
                'EIN-Sperre %.0f Min (bis %s)',
                len(self._klima_schalt_aus_zeiten),
                schaltintervall_s / 60,
                cooldown_s / 60,
                datetime.fromtimestamp(self._klima_schalt_cooldown_bis).strftime('%H:%M'),
            )
            self._klima_schalt_aus_zeiten = []

    @staticmethod
    def _schreibe_cooldown_in_db(cooldown_bis: float) -> None:
        """Schreibt klima_cooldown_bis in RAM-DB engine_flags (für B-Lesezugriff)."""
        try:
            conn = sqlite3.connect(RAM_DB_PATH, timeout=2.0)
            conn.execute('PRAGMA journal_mode=WAL')
            now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            conn.execute(
                "INSERT INTO engine_flags (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                ('klima_cooldown_bis', str(cooldown_bis), now_iso),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.debug('engine_flags write failed: %s', e)

    def _schaltfrequenz_cooldown_verbleibend(self) -> int:
        """Verbleibende EIN-Sperrdauer in Sekunden. 0 = kein aktiver Cooldown.

        Nutzt Instance-State (schnell). DB-Wert wird beim Daemon-Start durch
        `_lade_cooldown_aus_db()` in den Instance-State übertragen.
        """
        if self._klima_schalt_cooldown_bis <= 0:
            return 0
        rem = int(self._klima_schalt_cooldown_bis - time.time())
        if rem <= 0:
            self._klima_schalt_cooldown_bis = 0.0
            self._klima_schalt_aus_zeiten = []
            self._schreibe_cooldown_in_db(0.0)
        return max(0, rem)

    def lade_cooldown_aus_db(self) -> None:
        """Stellt Cooldown-State nach Daemon-Neustart aus RAM-DB wieder her.

        Muss vom Daemon beim Start aufgerufen werden (analog HP min_pause-Schutz).
        """
        try:
            conn = sqlite3.connect(RAM_DB_PATH, timeout=2.0)
            row = conn.execute(
                "SELECT value FROM engine_flags WHERE key='klima_cooldown_bis'"
            ).fetchone()
            conn.close()
            if row:
                val = float(row[0])
                if val > time.time():
                    self._klima_schalt_cooldown_bis = val
                    LOG.info(
                        'Klima Cooldown aus DB wiederhergestellt: noch %.0f Min',
                        (val - time.time()) / 60,
                    )
        except Exception as e:
            LOG.debug('lade_cooldown_aus_db: %s', e)

    # ── Extern-Erkennung ─────────────────────────────────────

    def _aktualisiere_klima_extern(self, obs: ObsState, matrix: dict) -> bool:
        """Zustandsübergangs-basierte Extern-Erkennung. Muss JEDEN Zyklus laufen.

        Erkennt ob Klima OFF↔ON ging ohne dass die Engine es veranlasst hat.
        Returns: True wenn ein externer Hold (ON/OFF) aktuell aktiv ist.
        """
        extern_respekt = float(get_param(
            matrix, self.regelkreis, 'extern_respekt_s', 1800
        ))

        # Lastflanken-basierter Schaltfrequenz-Schutz: erfasst auch Kompressor-
        # interne Kurzzyklen (SD bleibt EIN, nur Last springt).
        self._erkenne_kompressor_aus(obs, matrix)

        # ── OFF→ON Transition ──
        if (obs.klima_aktiv
                and self._klima_letzter_zustand is not None
                and not self._klima_letzter_zustand):
            # War das die Engine? (klima_ein innerhalb 180s erzeugt)
            if ((time.time() - self._engine_klima_ein_ts) < 180
                    or klima_engine_ein_kuerzlich(180.0)):
                self._engine_klima_ein_ts = 0  # verbraucht
                LOG.debug('Klima EIN: Engine-initiiert (erkannt)')
            else:
                self._klima_extern_ein_ts = time.time()
                self._klima_extern_aus_ts = 0
                LOG.info('Klima extern eingeschaltet erkannt → Respekt %ds aktiv',
                         int(extern_respekt))
                logge_extern('fritzdect', 'Klima extern EIN',
                             'Manuell eingeschaltet (nicht durch Engine)')
                # Symmetrie zu Extern-AUS (2026-04-26):
                # cancelt alle konfligierenden klima_toggle(state=off)-Overrides.
                self._cancel_conflicting_overrides('on', geraet='klima')

        # ── ON→OFF Transition ──
        if (not obs.klima_aktiv
                and self._klima_letzter_zustand is not None
                and self._klima_letzter_zustand):
            # Schaltfrequenz-Tracking erfolgt jetzt lastflanken-basiert in
            # _erkenne_kompressor_aus() — die SD-OFF wird dort als HIGH→LOW
            # auf klima_power_w erfasst (power=0 nach SD-AUS).
            if (time.time() - self._engine_klima_aus_ts) < 180:
                self._engine_klima_aus_ts = 0
                LOG.debug('Klima AUS: Engine-initiiert (erkannt)')
            else:
                self._klima_extern_aus_ts = time.time()
                self._klima_extern_ein_ts = 0
                LOG.info('Klima extern ausgeschaltet erkannt → Respekt %ds aktiv',
                         int(extern_respekt))
                logge_extern('fritzdect', 'Klima extern AUS',
                             'Manuell ausgeschaltet (nicht durch Engine)')
                # Race-Condition-Fix: Cancelt alle konfliktierenden klima_toggle(state=on) Overrides
                self._cancel_conflicting_overrides('off', geraet='klima')

        self._klima_letzter_zustand = obs.klima_aktiv
        now = time.time()
        return (
            (self._klima_extern_ein_ts > 0 and (now - self._klima_extern_ein_ts) < extern_respekt)
            or
            (self._klima_extern_aus_ts > 0 and (now - self._klima_extern_aus_ts) < extern_respekt)
        )

    def _aktiver_klima_extern_hold(self, matrix: dict) -> tuple[str | None, int]:
        extern_respekt = float(get_param(
            matrix, self.regelkreis, 'extern_respekt_s', 1800
        ))
        now = time.time()

        if self._klima_extern_ein_ts > 0:
            verbleibend = int(extern_respekt - (now - self._klima_extern_ein_ts))
            if verbleibend > 0:
                return 'on', verbleibend
            self._klima_extern_ein_ts = 0

        if self._klima_extern_aus_ts > 0:
            verbleibend = int(extern_respekt - (now - self._klima_extern_aus_ts))
            if verbleibend > 0:
                return 'off', verbleibend
            self._klima_extern_aus_ts = 0

        return None, 0

    @staticmethod
    def _aktiver_steuerbox_klima_hold() -> tuple[str | None, int]:
        try:
            conn = sqlite3.connect(RAM_DB_PATH, timeout=2.0)
            row = conn.execute(
                "SELECT params_json, created_at, respekt_s FROM operator_overrides "
                "WHERE action='klima_toggle' AND status='active' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
        except Exception:
            return None, 0

        if not row:
            return None, 0

        try:
            params = json.loads(row[0] or '{}')
            state = str(params.get('state') or '').strip().lower()
            if state not in {'on', 'off'}:
                return None, 0
            created_at = datetime.fromisoformat(row[1])
            remaining = int(created_at.timestamp() + int(row[2] or 0) - time.time())
            if remaining <= 0:
                return None, 0
            return state, remaining
        except Exception:
            return None, 0

    # ── Hilfsfunktionen ──────────────────────────────────────

    def _now_h(self) -> float:
        now = datetime.now()
        return now.hour + now.minute / 60.0

    def _ist_vor_sunrise(self, obs: ObsState) -> bool:
        sunrise_h = obs.sunrise if obs.sunrise is not None else 6.0
        return self._now_h() < sunrise_h

    def _get_temp_ist_c(self, obs: ObsState, matrix: dict) -> float:
        if obs.klima_temp_c is not None:
            return float(obs.klima_temp_c)
        return float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))

    def _forecast_ist_gut(self, obs: ObsState, matrix: dict) -> bool:
        return get_forecast_tier(obs, matrix) >= FC_TIER_GUT

    def _start_temp_nach_sunrise(self, obs: ObsState, matrix: dict) -> float:
        """Start-Schwelle nach Sunrise abhängig von der Prognosequalität."""
        if self._forecast_ist_gut(obs, matrix):
            return float(get_param(
                matrix, self.regelkreis, 'initial_temp_c_gut_nach_sunrise', 15
            ))
        return float(get_param(matrix, self.regelkreis, 'initial_temp_c_maessig', 20))

    def _sunset_soc_stop(self, obs: ObsState, matrix: dict) -> bool:
        soc_stop = float(get_param(matrix, self.regelkreis, 'sunset_soc_stop_pct', 90))
        sunset = obs.sunset if obs.sunset is not None else 20.0
        now_h = self._now_h()
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 100
        return now_h > sunset and soc < soc_stop

    def _soll_klima_laufen(self, obs: ObsState, matrix: dict) -> bool:
        """Reine Temperatur-/Zeitlogik — ohne Extern-Berücksichtigung.

        Extern-Handling erfolgt in bewerte() und erzeuge_aktionen(),
        NICHT hier, um Zirkelschlüsse zu vermeiden.
        """
        if not self._startzeit_erreicht(obs, matrix):
            return False
        if self._sunset_soc_stop(obs, matrix):
            return False

        temp_ist = self._get_temp_ist_c(obs, matrix)
        hyst_k = float(get_param(matrix, self.regelkreis, 'temp_hysterese_k', 1.0))

        # Laufend EIN: Temperatur-Hysterese statt Tages-Latch
        if bool(obs.klima_aktiv):
            if self._ist_vor_sunrise(obs):
                temp_start = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                temp_stop = temp_start - hyst_k
                return self._forecast_ist_gut(obs, matrix) and temp_ist >= temp_stop

            temp_start = self._start_temp_nach_sunrise(obs, matrix)
            temp_stop = temp_start - hyst_k
            return temp_ist >= temp_stop

        if self._ist_vor_sunrise(obs):
            temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
            return self._forecast_ist_gut(obs, matrix) and temp_ist >= temp_pre

        temp_tag = self._start_temp_nach_sunrise(obs, matrix)
        return temp_ist >= temp_tag

    def _startzeit_erreicht(self, obs: ObsState, matrix: dict) -> bool:
        sunrise_h = obs.sunrise if obs.sunrise is not None else 6.0
        now_h = self._now_h()
        return now_h >= (sunrise_h - 1.0)

    # ── Haupt-Regellogik ─────────────────────────────────────

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        basis_score = get_score_gewicht(matrix, self.regelkreis)

        # Extern-Erkennung MUSS IMMER laufen (State-Tracking jeder Zyklus)
        ist_extern = self._aktualisiere_klima_extern(obs, matrix)

        # Harte Sicherheit: Sunset+SOC-Stop — IMMER aktiv, auch bei extern.
        if self._sunset_soc_stop(obs, matrix):
            if obs.klima_aktiv:
                return int(basis_score * 2)
            return 0

        # Hardware-Schutz vor User-Overrides: Cooldown erzwingt AUS und blockiert EIN.
        cd_rem = self._schaltfrequenz_cooldown_verbleibend()
        if cd_rem > 0:
            if obs.klima_aktiv:
                return int(basis_score * 2)
            LOG.debug('Klima EIN blockiert: Schaltfrequenz-Cooldown noch %d Min', cd_rem // 60)
            return 0

        # Steuerbox-Hold (ON/OFF) hat Vorrang vor normaler Regelautomatik.
        sb_state, sb_rem = self._aktiver_steuerbox_klima_hold()
        if sb_state == 'on':
            if not obs.klima_aktiv:
                return int(basis_score * 2)
            LOG.debug('Klima Steuerbox-Hold ON aktiv (%ds verbleibend)', sb_rem)
            return 0
        if sb_state == 'off':
            if obs.klima_aktiv:
                return int(basis_score * 2)
            LOG.debug('Klima Steuerbox-Hold OFF aktiv (%ds verbleibend)', sb_rem)
            return 0

        # Extern-Hold (ON/OFF) symmetrisch respektieren.
        if ist_extern:
            ext_state, ext_rem = self._aktiver_klima_extern_hold(matrix)
            if ext_state == 'on':
                if not obs.klima_aktiv:
                    return int(basis_score * 2)
                LOG.debug('Klima extern-Hold ON aktiv (%ds verbleibend)', ext_rem)
                return 0
            if ext_state == 'off':
                if obs.klima_aktiv:
                    return int(basis_score * 2)
                LOG.debug('Klima extern-Hold OFF aktiv (%ds verbleibend)', ext_rem)
                return 0

        soll_laufen = self._soll_klima_laufen(obs, matrix)
        ist_an = bool(obs.klima_aktiv)

        if soll_laufen != ist_an:
            return basis_score
        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        if not ist_aktiv(matrix, self.regelkreis):
            return []

        soc_stop = float(get_param(matrix, self.regelkreis, 'sunset_soc_stop_pct', 90))

        # Harte Sicherheit: Sunset+SOC — IMMER, auch bei extern.
        if self._sunset_soc_stop(obs, matrix):
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: nach Sonnenuntergang und SOC < {soc_stop:.0f}%',
                }]
            return []

        # Hardware-Schutz vor User-Overrides: Cooldown erzwingt AUS und blockiert EIN.
        cd_rem = self._schaltfrequenz_cooldown_verbleibend()
        if cd_rem > 0:
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                LOG.warning(
                    'Klima AUS erzwungen: Schaltfrequenz-Cooldown aktiv noch %d Min',
                    cd_rem // 60,
                )
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: Schaltfrequenz-Cooldown aktiv (noch {cd_rem // 60} Min)',
                }]
            LOG.info(
                'Klima EIN blockiert: Schaltfrequenz-Cooldown aktiv noch %d Min',
                cd_rem // 60,
            )
            return []

        # Steuerbox-Hold (ON/OFF) erzwingen.
        sb_state, sb_rem = self._aktiver_steuerbox_klima_hold()
        if sb_state == 'on':
            if not obs.klima_aktiv:
                self._engine_klima_ein_ts = time.time()
                registriere_klima_engine_ein()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_ein',
                    'grund': f'Klima EIN: Steuerbox-Respekt-Hold aktiv ({sb_rem}s verbleibend)',
                }]
            return []
        if sb_state == 'off':
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: Steuerbox-Respekt-Hold aktiv ({sb_rem}s verbleibend)',
                }]
            return []

        # Extern-Hold (ON/OFF) erzwingen.
        ext_state, ext_rem = self._aktiver_klima_extern_hold(matrix)
        if ext_state == 'on':
            if not obs.klima_aktiv:
                self._engine_klima_ein_ts = time.time()
                registriere_klima_engine_ein()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_ein',
                    'grund': f'Klima EIN: Extern-Respekt-Hold aktiv ({ext_rem}s verbleibend)',
                }]
            return []
        if ext_state == 'off':
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: Extern-Respekt-Hold aktiv ({ext_rem}s verbleibend)',
                }]
            return []

        soll_laufen = self._soll_klima_laufen(obs, matrix)
        ist_an = bool(obs.klima_aktiv)

        if soll_laufen and not ist_an:
            # Schaltfrequenz-Cooldown: EIN-Sperre
            cd_rem = self._schaltfrequenz_cooldown_verbleibend()
            if cd_rem > 0:
                LOG.info(
                    'Klima EIN blockiert: Schaltfrequenz-Cooldown aktiv noch %d Min',
                    cd_rem // 60,
                )
                return []
            # Engine-Einschaltung markieren (für Extern-Erkennung im nächsten Zyklus)
            self._engine_klima_ein_ts = time.time()
            registriere_klima_engine_ein()
            if self._ist_vor_sunrise(obs):
                temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                grund = (f'Klima EIN: Vor Sunrise, Forecast gut und Temp >= {temp_pre:.1f}°C')
            else:
                temp_tag = self._start_temp_nach_sunrise(obs, matrix)
                fq = (get_effective_forecast_quality(obs, matrix) or 'unbekannt').lower()
                grund = (f'Klima EIN: Nach Sunrise, Temp >= {temp_tag:.1f}°C '
                         f'(Forecast={fq})')
            return [{
                'tier': 2,
                'aktor': 'fritzdect',
                'kommando': 'klima_ein',
                'grund': grund,
            }]

        if (not soll_laufen) and ist_an:
            self._engine_klima_aus_ts = time.time()
            temp_ist = self._get_temp_ist_c(obs, matrix)
            hyst_k = float(get_param(matrix, self.regelkreis, 'temp_hysterese_k', 1.0))
            if not self._startzeit_erreicht(obs, matrix):
                grund = 'Klima AUS: Startfenster noch nicht offen (ab sunrise-1h)'
            elif self._sunset_soc_stop(obs, matrix):
                grund = f'Klima AUS: nach Sonnenuntergang und SOC < {soc_stop:.0f}%'
            else:
                if self._ist_vor_sunrise(obs):
                    temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                    temp_stop = temp_pre - hyst_k
                    grund = (f'Klima AUS: Vor Sunrise Temp {temp_ist:.1f}°C < '
                             f'{temp_stop:.1f}°C (Schwelle {temp_pre:.1f}°C, Hyst {hyst_k:.1f}K) '
                             f'oder Forecast nicht gut')
                else:
                    temp_tag = self._start_temp_nach_sunrise(obs, matrix)
                    temp_stop = temp_tag - hyst_k
                    grund = (f'Klima AUS: Nach Sunrise Temp {temp_ist:.1f}°C < '
                             f'{temp_stop:.1f}°C (Start {temp_tag:.1f}°C, Hyst {hyst_k:.1f}K)')
            return [{
                'tier': 2,
                'aktor': 'fritzdect',
                'kommando': 'klima_aus',
                'grund': grund,
            }]

        return []
