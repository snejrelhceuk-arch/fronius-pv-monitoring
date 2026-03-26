"""
optimierung.py — Optimierungsregeln (P2-P3, mixed Zyklen)

RegelZellausgleich      — Monatlicher BYD-Zellbalancing (strategic)
RegelForecastPlausi     — Prognose an Realität anpassen (strategic)

Entfernt (2026-03-07) — GEN24 HW-Limit macht SW-Ratenlimits wirkungslos:
  RegelAbendEntladerate   — Entladerate nach Tageszeit (via set_discharge_rate)
  RegelLaderateDynamisch  — Laderate je nach WP/PV/SOC (via set_charge_rate)

Siehe: doc/BATTERIE_STRATEGIEN.md, doc/PARAMETER_MATRIZEN.md
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, date
from typing import Optional

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.regeln.soc_extern import soc_extern_tracker
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# ENTFERNT (2026-03-07): ABEND-ENTLADERATE
# RegelAbendEntladerate nutzte set_discharge_rate/stop_discharge/auto.
# GEN24 DC-DC-Wandler begrenzt Batteriestrom auf ~22 A; Modbus-Raten-
# limits waren wirkungslos. SOC_MIN steuert Entlade-Erlaubnis implizit.
# ═════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════
# ZELLAUSGLEICH (P3 — Wartung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelZellausgleich(Regel):
    """Monatlicher Vollzyklus für BYD-Zellbalancing.

    Parametermatrix: regelkreise.zellausgleich
    """

    name = 'zellausgleich'
    regelkreis = 'zellausgleich'
    engine_zyklus = 'strategic'

    _DETECT_AFTER_H = 15.0
    _LOW_MARGIN_PCT = 3.0
    _HIGH_MARGIN_PCT = 2.0
    _MIN_HIGH_SAMPLES = 30
    _MIN_DAY_SAMPLES = 120

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Zyklus-Erkennung vor Trigger-Logik: reale Vollzyklen markieren,
        # damit im laufenden Monat keine unnötigen Neu-Trigger entstehen.
        self._erkenne_und_markiere_zyklus(matrix)

        if obs.forecast_kwh is None:
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        letzter = self._letzter_ausgleich()
        if letzter:
            try:
                last_date = datetime.strptime(letzter, '%Y-%m-%d').date()
                heute = date.today()
                if last_date.year == heute.year and last_date.month == heute.month:
                    return 0
            except (ValueError, TypeError):
                pass

        min_pv = get_param(matrix, self.regelkreis, 'min_prognose_kwh', 50.0)
        frueh = get_param(matrix, self.regelkreis, 'fruehester_tag', 1)
        spaet = get_param(matrix, self.regelkreis, 'spaetester_tag', 28)
        tag = date.today().day

        if tag < frueh or tag > spaet:
            return 0

        if obs.forecast_kwh >= min_pv:
            return get_score_gewicht(matrix, self.regelkreis)

        notfall = get_param(matrix, self.regelkreis, 'notfall_min_prognose_kwh', 25.0)
        if tag > spaet - 5 and obs.forecast_kwh >= notfall:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.8)

        return 0

    @staticmethod
    def _letzter_ausgleich() -> Optional[str]:
        """Lese letzten Zellausgleich aus State/Config."""
        state_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            with open(state_path) as f:
                state = json.load(f)
            val = state.get('last_balancing')
            if val:
                return val
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            return cfg.get('zellausgleich', {}).get('letzter_ausgleich')
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _erkenne_und_markiere_zyklus(self, matrix: dict) -> None:
        """Erkenne abgeschlossenen Tages-Vollzyklus und setze Marker.

        Konservativ: Nur wenn Tages-SOC klar von unten bis oben gefahren wurde
        und genügend Messpunkte vorliegen.
        """
        heute = date.today().isoformat()
        if self._letzter_ausgleich() == heute:
            return

        now_h = datetime.now().hour + datetime.now().minute / 60.0
        if now_h < self._DETECT_AFTER_H:
            return

        stats = self._lade_tages_soc_stats(matrix)
        if not stats:
            return

        min_soc, max_soc, high_samples, total_samples = stats
        if min_soc is None or max_soc is None:
            return

        if total_samples < self._MIN_DAY_SAMPLES:
            return

        soc_min_target = float(get_param(matrix, self.regelkreis, 'soc_min_waehrend_pct', 5))
        soc_max_target = float(get_param(matrix, self.regelkreis, 'soc_max_waehrend_pct', 100))

        low_ok = min_soc <= (soc_min_target + self._LOW_MARGIN_PCT)
        high_threshold = max(95.0, soc_max_target - self._HIGH_MARGIN_PCT)
        high_ok = max_soc >= high_threshold
        span_ok = (max_soc - min_soc) >= (high_threshold - (soc_min_target + self._LOW_MARGIN_PCT))
        samples_ok = high_samples >= self._MIN_HIGH_SAMPLES

        if not (low_ok and high_ok and span_ok and samples_ok):
            return

        if self._setze_letzten_ausgleich(heute):
            LOG.info(
                'Zellausgleich-Zyklus automatisch erkannt: '
                f'SOC min/max={min_soc:.1f}/{max_soc:.1f}%, '
                f'high_samples={high_samples}, samples={total_samples} '
                f'→ letzter_ausgleich={heute}'
            )

    @staticmethod
    def _lade_tages_soc_stats(matrix: dict) -> Optional[tuple[Optional[float], Optional[float], int, int]]:
        """Hole Tages-SOC-Statistik aus Collector-DB (RAM, fallback persist)."""
        try:
            import config as app_config
            db_paths = [app_config.DB_PATH, app_config.DB_PERSIST_PATH]
        except Exception:
            db_paths = [
                '/dev/shm/fronius_data.db',
                os.path.join(_PROJECT_ROOT, 'data.db'),
            ]

        heute = date.today()
        start_ts = datetime(heute.year, heute.month, heute.day).timestamp()
        end_ts = start_ts + 86400

        soc_max_target = float(get_param(matrix, 'zellausgleich', 'soc_max_waehrend_pct', 100))
        high_threshold = max(95.0, soc_max_target - RegelZellausgleich._HIGH_MARGIN_PCT)

        query = """
            SELECT
                MIN(SOC_Batt) AS min_soc,
                MAX(SOC_Batt) AS max_soc,
                SUM(CASE WHEN SOC_Batt >= ? THEN 1 ELSE 0 END) AS high_samples,
                COUNT(SOC_Batt) AS total_samples
            FROM raw_data
            WHERE ts >= ?
              AND ts < ?
              AND SOC_Batt IS NOT NULL
        """

        for path in db_paths:
            if not path or not os.path.exists(path):
                continue
            try:
                conn = sqlite3.connect(path, timeout=2.0)
                try:
                    row = conn.execute(query, (high_threshold, start_ts, end_ts)).fetchone()
                finally:
                    conn.close()

                if not row:
                    continue

                min_soc, max_soc, high_samples, total_samples = row
                return (
                    float(min_soc) if min_soc is not None else None,
                    float(max_soc) if max_soc is not None else None,
                    int(high_samples or 0),
                    int(total_samples or 0),
                )
            except sqlite3.Error:
                continue

        return None

    def _setze_letzten_ausgleich(self, iso_date: str) -> bool:
        """Persistiere Datum in beiden Marker-Dateien (best effort, atomisch)."""
        updated = False

        state_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            with open(state_path) as f:
                state = json.load(f)
            if state.get('last_balancing') != iso_date:
                state['last_balancing'] = iso_date
                self._write_json_atomic(state_path, state)
                updated = True
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            LOG.warning(f'Zellausgleich-Marker state nicht gesetzt ({state_path}): {e}')

        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            zellausgleich = cfg.setdefault('zellausgleich', {})
            if zellausgleich.get('letzter_ausgleich') != iso_date:
                zellausgleich['letzter_ausgleich'] = iso_date
                self._write_json_atomic(cfg_path, cfg)
                updated = True
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            LOG.warning(f'Zellausgleich-Marker cfg nicht gesetzt ({cfg_path}): {e}')

        return updated

    @staticmethod
    def _write_json_atomic(path: str, data: dict) -> None:
        tmp_path = f'{path}.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp_path, path)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        soc_min = get_param(matrix, self.regelkreis, 'soc_min_waehrend_pct', 5)
        soc_max = get_param(matrix, self.regelkreis, 'soc_max_waehrend_pct', 100)
        aktionen = [
            {
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': soc_min,
                'grund': f'Zellausgleich: SOC_MIN → {soc_min}%',
            },
            {
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': soc_max,
                'grund': f'Zellausgleich: SOC_MAX → {soc_max}% (Vollladung)',
            },
        ]
        # Hinweis: registriere_aktion() erfolgt NACH Actuator-Erfolg in engine.py (K2)
        return aktionen


# ═════════════════════════════════════════════════════════════
# FORECAST-PLAUSIBILISIERUNG (P2 — Steuerung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelForecastPlausi(Regel):
    """PV-Prognose an Realität anpassen.

    Vergleicht bisherige Erzeugung mit dem erwarteten Anteil.
    Bei > 30% Abweichung → SOC-Strategie anpassen.

    Parametermatrix: regelkreise.forecast_plausibilisierung
    """

    name = 'forecast_plausi'
    regelkreis = 'forecast_plausibilisierung'
    engine_zyklus = 'strategic'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        if obs.pv_vs_forecast_pct is None or obs.forecast_rest_kwh is None:
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        min_h = get_param(matrix, self.regelkreis, 'min_betriebsstunden', 2.0)
        sunrise = obs.sunrise or 7.0
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        if now_h - sunrise < min_h:
            return 0

        schwelle = get_param(matrix, self.regelkreis, 'abweichung_schwelle_pct', 70)
        if obs.pv_vs_forecast_pct < schwelle:
            score = get_score_gewicht(matrix, self.regelkreis)

            cloud_schwer = get_param(matrix, self.regelkreis, 'cloud_rest_schwer_pct', 80)
            if obs.cloud_rest_avg_pct is not None and obs.cloud_rest_avg_pct > cloud_schwer:
                return score
            return int(score * 0.8)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """Bei unplausibler Prognose: SOC_MAX vorsorglich erhöhen."""
        faktor = get_param(matrix, self.regelkreis, 'korrektur_faktor', 0.7)
        cloud_schwer = get_param(matrix, self.regelkreis, 'cloud_rest_schwer_pct', 80)
        cloud_faktor = get_param(matrix, self.regelkreis, 'cloud_reduktion_faktor', 0.6)

        eff_faktor = faktor
        if obs.cloud_rest_avg_pct is not None and obs.cloud_rest_avg_pct > cloud_schwer:
            eff_faktor = faktor * cloud_faktor

        rest_korrigiert = round((obs.forecast_rest_kwh or 0) * eff_faktor, 1)
        ist_pct = obs.pv_vs_forecast_pct or 0

        aktionen = []
        if rest_korrigiert < 5.0 and obs.soc_max is not None and obs.soc_max < 100:
            if obs.soc_mode != 'manual':
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'manual',
                    'grund': f'Forecast-Korrektur: SOC_MODE → manual',
                })
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': 100,
                'grund': (f'Forecast-Korrektur: IST/SOLL {ist_pct:.0f}%, '
                          f'Rest {rest_korrigiert} kWh (Faktor {eff_faktor:.2f}) → SOC_MAX 100%'),
            })
        else:
            LOG.info(f"Forecast-Plausi: IST/SOLL {ist_pct:.0f}%, Rest {rest_korrigiert} kWh — keine Aktion")

        # Hinweis: registriere_aktion() erfolgt NACH Actuator-Erfolg in engine.py (K2)

        return aktionen


# ═════════════════════════════════════════════════════════════
# ENTFERNT (2026-03-07): LADERATE DYNAMISCH
# RegelLaderateDynamisch nutzte set_charge_rate. GEN24 DC-DC-Wandler
# begrenzt Batteriestrom auf ~22 A; InWRte-Schreiben wirkungslos.
# ═════════════════════════════════════════════════════════════
