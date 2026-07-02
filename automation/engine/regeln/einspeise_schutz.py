"""
einspeise_schutz.py — Nulleinspeisungs-Schutz (P1, fast-Zyklus)

RegelEinspeiseSchutz — Erkennt anhaltende Netzeinspeisung und reagiert.

Hintergrund (Zwischenfall 2026-07-02):
  Vertrag mit dem Netzversorger = *Nulleinspeisung*. Die Absicherung ruht
  bisher auf zwei Säulen, die BEIDE versagen können:
    1. GEN24-Soft-Limit (Einspeisebegrenzung 0 W) curtailt die Wechselrichter.
    2. Batterie als Senke: solange SOC_MAX Luft lässt, absorbiert sie Überschuss.
  Am 2026-07-02 kappte die Morgenregel SOC_MAX auf 75 % (LFP-Schonung), die
  Batterie war ab 09:01 voll — und F3 (Ost-WR) gehorchte dem Soft-Limit NICHT.
  Ergebnis: 2,97 kWh Einspeisung statt < 1 kWh; KEINE Instanz reagierte.

Diese Regel schließt die Lücke: Sensorik + Logging + Warnung + Steuerung.

Reaktions-Leiter (bei ACT):
  Stufe 1 (Default, bewährt): SOC_MAX → 100 % + SOC_MODE → auto.
      Öffnet den Batterie-Puffer, damit der Überschuss absorbiert wird.
      Genau diese Aktion beendete den Zwischenfall am 2026-07-02 um 14:29.
      Setzt engine_flag `einspeise_guard_soc_open_bis`, damit die Morgenregel
      SOC_MAX nicht sofort wieder auf 75 % deckelt.
  Stufe 2 (opt-in `dumpload_aktiv`): Dump-Load (Heizpatrone/Klima EIN), wenn
      die Batterie faktisch voll ist (SOC ≥ `dumpload_soc_min_pct`) und der
      Überschuss weiter ins Netz fließt.
  Stufe 3 (opt-in `provokation_aktiv`): Provokation — schaltbare, EINgeschaltete
      Verbraucher kurz AUS und wieder EIN, um einen hängenden Regelkreis
      (SmartMeter/WR-Kommunikation) neu anzustoßen. Standardmäßig AUS, weil die
      AUS-Phase die Einspeisung kurzzeitig erhöht.

No-Gos (siehe AGENTS.md):
  - Keine Software-Ratenlimits (InWRte/OutWRte/StorCtl_Mod). Steuerung
    ausschließlich über SOC_MIN/SOC_MAX via Fronius HTTP-API.

Parametermatrix: regelkreise.einspeise_schutz
Card: doc/llm/cards/automation-einspeise-schutz.card.md
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections import deque
from datetime import date, datetime
from email.mime.text import MIMEText
from typing import Optional

import config as app_config
from automation.engine.obs_state import ObsState, RAM_DB_PATH
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
EINSPEISE_LOG_PATH = os.path.join(_PROJECT_ROOT, 'logs', 'einspeise_guard.log')

# engine_flag-Schlüssel: solange in der Zukunft, unterdrückt die Morgenregel
# ihre SOC_MAX=75%-Deckelung (verhindert Oszillation gegen die Guard-Öffnung).
GUARD_SOC_OPEN_FLAG = 'einspeise_guard_soc_open_bis'


class RegelEinspeiseSchutz(Regel):
    """Schutzregel gegen anhaltende Netzeinspeisung (Nulleinspeisungs-Vertrag).

    Sensorik:
      - Momentan-Export     = max(0, -grid_power_w)
      - Sustained-Integral  = Σ(Export_W) der letzten `sustained_fenster_min`
                              Ticks (≈ Min bei 60-s-Tick) / 60000 → kWh
      - Tages-Kumulativ      = Σ(data_1min.W_Einspeis) seit lokaler Mitternacht

    Auslöse-Logik (ODER-verknüpft):
      WARN  wenn  kumul ≥ baseline·warn_faktor   ODER  integral ≥ sustained_warn_kwh
      ACT   wenn  kumul ≥ baseline·akt_faktor    ODER  integral ≥ sustained_akt_kwh

      WARN = nur Logging + Warn-Mail (keine Hardware-Aktion).
      ACT  = Logging + Warn-Mail + Reaktions-Leiter.

    Score: ACT → int(score_gewicht·1.5); WARN/none → 0 (Mail als Seiteneffekt).

    Name enthält 'schutz' → Engine führt die Regel im Schutz-Pass IMMER aus,
    unabhängig von Optimierungs-Gewinnern.

    Parametermatrix: regelkreise.einspeise_schutz
    """

    name = 'einspeise_schutz'
    regelkreis = 'einspeise_schutz'
    aktor = 'batterie'
    engine_zyklus = 'fast'

    def __init__(self):
        super().__init__()
        # Export-Historie (positive Wattwerte = Einspeisung), 1 Sample/Tick.
        # maxlen erlaubt Fenster-Tuning bis 15 Min via Matrix.
        self._export_history: deque = deque(maxlen=15)
        # Tages-Kumulativ-Cache (DB-Read gedrosselt)
        self._kumul_cache: dict = {'ts': 0.0, 'kwh': None}
        # Warn-Mail-Drosselung: {dedup_key: letzter_versand_ts}
        self._letzte_warnung: dict[str, float] = {}
        # Log-Drosselung (nur alle 60 s ins File/LOG bei anhaltendem Event)
        self._letztes_event_log: float = 0.0
        # Übergabe bewerte()→erzeuge_aktionen()
        self._status: dict = {}

    # ── Sensorik ─────────────────────────────────────────────

    def _pflege_history(self, obs: ObsState) -> None:
        """Export-Historie fortschreiben — MUSS 1×/Tick laufen."""
        gw = obs.grid_power_w
        if gw is not None:
            self._export_history.append(max(0.0, -float(gw)))

    def _export_integral_kwh(self, fenster_min: int) -> tuple[float, float, int]:
        """Energie-Integral der Einspeisung über die letzten `fenster_min` Ticks.

        Returns: (energie_kwh, mittel_w, samples). Energie = Σ(W)·60s/3600/1000.
        """
        recent = list(self._export_history)[-fenster_min:]
        if not recent:
            return 0.0, 0.0, 0
        summe = sum(recent)
        return summe / 60000.0, summe / len(recent), len(recent)

    def _kumul_einspeis_kwh(self, matrix: dict) -> Optional[float]:
        """Heutige Netzeinspeisung [kWh] aus data_1min.W_Einspeis (gecached).

        Read-only; bei DB-Fehler None → die Sustained-Erkennung greift weiter.
        """
        ttl = int(get_param(matrix, self.regelkreis, 'kumul_cache_s', 120))
        now = time.time()
        if self._kumul_cache['kwh'] is not None and (now - self._kumul_cache['ts']) <= ttl:
            return self._kumul_cache['kwh']

        db_path = next((p for p in [app_config.DB_PATH, app_config.DB_PERSIST_PATH]
                        if p and os.path.exists(p)), None)
        if not db_path:
            return self._kumul_cache['kwh']
        try:
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=3.0)
            try:
                row = conn.execute(
                    "SELECT SUM(W_Einspeis)/1000.0 FROM data_1min "
                    "WHERE ts >= strftime('%s', date('now','localtime'), 'utc')"
                ).fetchone()
            finally:
                conn.close()
            kwh = float(row[0]) if row and row[0] is not None else 0.0
            self._kumul_cache = {'ts': now, 'kwh': kwh}
            return kwh
        except Exception as e:
            LOG.debug("einspeise_schutz: Kumulativ nicht lesbar: %s", e)
            return self._kumul_cache['kwh']

    # ── Persistenz / Logging ─────────────────────────────────

    def _schreibe_guard_flag(self, bis_ts: float) -> None:
        """Setzt engine_flag `einspeise_guard_soc_open_bis` (RAM-DB)."""
        try:
            conn = sqlite3.connect(RAM_DB_PATH, timeout=2.0)
            conn.execute('PRAGMA journal_mode=WAL')
            now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            conn.execute(
                "INSERT INTO engine_flags (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                (GUARD_SOC_OPEN_FLAG, str(bis_ts), now_iso),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.debug("einspeise_schutz: engine_flag-Write fehlgeschlagen: %s", e)

    def _log_event(self, level: str, text: str) -> None:
        """Robustes Event-Log: eigene Datei + LOG.warning (unabhängig von DB)."""
        LOG.warning("EINSPEISE-%s: %s", level.upper(), text)
        try:
            os.makedirs(os.path.dirname(EINSPEISE_LOG_PATH), exist_ok=True)
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(EINSPEISE_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{ts}  {level.upper():4}  {text}\n")
        except Exception as e:
            LOG.debug("einspeise_schutz: Event-Log-Write fehlgeschlagen: %s", e)

    def _sende_warnung(self, matrix: dict, level: str, betreff: str,
                       koerper: str) -> None:
        """Warn-Mail (best-effort). Drosselung: max. 1× pro `warn_cooldown_min`."""
        cooldown_s = int(get_param(matrix, self.regelkreis, 'warn_cooldown_min', 60)) * 60
        dedup_key = level
        now = time.time()
        if (now - self._letzte_warnung.get(dedup_key, 0)) < cooldown_s:
            return

        empfaenger = getattr(app_config, 'NOTIFICATION_EMAIL', '')
        if not empfaenger:
            self._letzte_warnung[dedup_key] = now  # kein Mail-Ziel → nicht spammen
            return

        try:
            from automation.engine.notify import mail
            from automation.engine import credential_store

            smtp_host = getattr(app_config, 'NOTIFICATION_SMTP_HOST', 'localhost')
            smtp_port = getattr(app_config, 'NOTIFICATION_SMTP_PORT', 465)
            smtp_user = getattr(app_config, 'NOTIFICATION_SMTP_USER', '')
            absender = getattr(app_config, 'NOTIFICATION_FROM', 'alerts@example.invalid')
            smtp_pass = credential_store.lade('smtp_pass')
            if smtp_user and not smtp_pass:
                LOG.error("einspeise_schutz: Warn-Mail ohne SMTP-Passwort nicht möglich")
                return

            msg = MIMEText(koerper, 'plain', 'utf-8')
            msg['Subject'] = betreff
            msg['From'] = absender
            msg['To'] = empfaenger
            msg['X-PV-Event'] = f'einspeise_{level}'
            mail.smtp_versand(smtp_host, smtp_port, smtp_user, smtp_pass,
                              absender, empfaenger, msg)
            LOG.info("einspeise_schutz: Warn-Mail (%s) gesendet → %s", level, empfaenger)
            self._letzte_warnung[dedup_key] = now
        except Exception as e:
            LOG.error("einspeise_schutz: Warn-Mail fehlgeschlagen: %s", e)

    # ── Bewertung ────────────────────────────────────────────

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Historie IMMER fortschreiben (auch wenn kein Alarm)
        self._pflege_history(obs)

        baseline = float(get_param(matrix, self.regelkreis, 'baseline_einspeis_kwh', 0.9))
        warn_faktor = float(get_param(matrix, self.regelkreis, 'warn_faktor', 1.5))
        akt_faktor = float(get_param(matrix, self.regelkreis, 'akt_faktor', 2.0))
        fenster_min = int(get_param(matrix, self.regelkreis, 'sustained_fenster_min', 5))
        veto_w = float(get_param(matrix, self.regelkreis, 'sustained_veto_w', 150))
        sust_warn = float(get_param(matrix, self.regelkreis, 'sustained_warn_kwh', 0.04))
        sust_akt = float(get_param(matrix, self.regelkreis, 'sustained_akt_kwh', 0.06))

        export_now = max(0.0, -float(obs.grid_power_w or 0))
        integral_kwh, mittel_w, samples = self._export_integral_kwh(fenster_min)
        kumul_kwh = self._kumul_einspeis_kwh(matrix)

        # Sustained nur werten, wenn aktuell Export fließt, das Fenster gefüllt
        # ist UND die Einspeisung über das Fenster ANHÄLT (nicht ein einzelner
        # Curtailment-Transient). "Anhalten" = ein Mindestanteil der Samples
        # liegt über dem Veto → filtert kurze -10-kW-Spitzen zuverlässig weg.
        recent = list(self._export_history)[-fenster_min:]
        hits = sum(1 for s in recent if s >= veto_w)
        min_hit_pct = float(get_param(matrix, self.regelkreis, 'sustained_min_hit_pct', 0.8))
        min_hits = max(1, int(-(-fenster_min * min_hit_pct // 1)))  # ceil
        sustained_ok = (export_now >= veto_w and samples >= fenster_min
                        and hits >= min_hits)
        sust_warn_hit = sustained_ok and integral_kwh >= sust_warn
        sust_akt_hit = sustained_ok and integral_kwh >= sust_akt

        kumul_warn_hit = kumul_kwh is not None and kumul_kwh >= baseline * warn_faktor
        kumul_akt_hit = kumul_kwh is not None and kumul_kwh >= baseline * akt_faktor

        # ACT-Alarm (Log + Mail): live anhaltender Export ODER Tages-Kumulativ.
        act_alert = sust_akt_hit or kumul_akt_hit
        warn = act_alert or sust_warn_hit or kumul_warn_hit

        # ACT-REAKTION (Hardware): NUR wenn aktuell tatsächlich anhaltend Export
        # fließt. Ein hohes Tages-Kumulativ allein (z. B. abends, Export längst
        # vorbei) darf SOC_MAX NICHT öffnen — sonst Konflikt mit Komfort-Reset/
        # Nacht-SOC-Management. Reaktion nur, wenn es etwas zu absorbieren gibt.
        act_reaktion = act_alert and sustained_ok

        self._status = {
            'export_now': export_now, 'integral_kwh': integral_kwh,
            'mittel_w': mittel_w, 'kumul_kwh': kumul_kwh, 'baseline': baseline,
        }

        if not warn:
            return 0

        level = 'act' if act_alert else 'warn'
        kumul_str = f"{kumul_kwh:.3f} kWh" if kumul_kwh is not None else "n/a"
        text = (f"Einspeisung {level.upper()}: aktuell {export_now:.0f} W, "
                f"Ø {mittel_w:.0f} W / {samples}·Tick ({integral_kwh:.3f} kWh), "
                f"heute {kumul_str} (Baseline {baseline:.2f} kWh, "
                f"WARN≥{baseline*warn_faktor:.2f}/ACT≥{baseline*akt_faktor:.2f}); "
                f"SOC {obs.batt_soc_pct}% SOC_MAX {obs.soc_max}% "
                f"F1={obs.pv_f1_w} F2={obs.pv_f2_w} F3={obs.pv_f3_w} W"
                f"{'' if act_reaktion else '  [nur Alarm — keine Reaktion]'}")

        # Logging gedrosselt (bei anhaltendem Event nicht jede Minute)
        now = time.time()
        if (now - self._letztes_event_log) > 55:
            self._log_event(level, text)
            self._letztes_event_log = now

        self._sende_warnung(matrix, level, f'[PV-Nulleinspeisung] {level.upper()}',
                            self._mail_body(obs, text))

        if not act_reaktion:
            return 0

        # ACT mit Live-Export: Guard-Flag setzen (Morgenregel nicht gegen die
        # Öffnung arbeiten lassen) und Reaktions-Score liefern.
        cooldown_min = int(get_param(matrix, self.regelkreis, 'soc_open_cooldown_min', 120))
        self._schreibe_guard_flag(now + cooldown_min * 60)
        return int(get_score_gewicht(matrix, self.regelkreis) * 1.5)

    def _mail_body(self, obs: ObsState, text: str) -> str:
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        return (
            f"Automatische Meldung des Nulleinspeisungs-Schutzes\n"
            f"Zeitpunkt: {now_str}\n\n"
            f"{text}\n\n"
            f"── Snapshot ──\n"
            f"Grid:        {obs.grid_power_w} W (negativ = Einspeisung)\n"
            f"SOC:         {obs.batt_soc_pct} %   SOC_MAX: {obs.soc_max} %   "
            f"Mode: {obs.soc_mode}\n"
            f"PV F1/F2/F3: {obs.pv_f1_w} / {obs.pv_f2_w} / {obs.pv_f3_w} W\n"
            f"Hauslast:    {obs.house_load_w} W\n"
            f"HP aktiv:    {obs.heizpatrone_aktiv}   Klima aktiv: {obs.klima_aktiv}\n\n"
            f"Reaktion: SOC_MAX→100% (Batterie-Puffer öffnen). "
            f"Details siehe logs/einspeise_guard.log und logs/schaltlog.txt.\n"
        )

    # ── Reaktion ─────────────────────────────────────────────

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        st = self._status or {}
        grund_basis = (f"Einspeise-Schutz: Ø {st.get('mittel_w', 0):.0f} W anhaltend, "
                       f"heute {st.get('kumul_kwh') if st.get('kumul_kwh') is None else round(st['kumul_kwh'], 3)} kWh")

        aktionen: list[dict] = []

        # ── Stufe 1 (bewährt): Batterie-Puffer öffnen ──
        soc_max = obs.soc_max
        if soc_max is not None and soc_max < 100:
            aktionen.append({
                'tier': 1, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': 100,
                'grund': f'{grund_basis} → SOC_MAX {soc_max}%→100% (Puffer öffnen)',
            })
            if obs.soc_mode != 'auto':
                aktionen.append({
                    'tier': 1, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'auto',
                    'grund': f'{grund_basis} → SOC_MODE auto (Vollladung erlauben)',
                })
            return aktionen

        # ── Stufe 2 (opt-in): Dump-Load, wenn Batterie faktisch voll ──
        if bool(get_param(matrix, self.regelkreis, 'dumpload_aktiv', False)):
            soc = obs.batt_soc_pct
            soc_min_pct = float(get_param(matrix, self.regelkreis, 'dumpload_soc_min_pct', 95))
            ww_max = float(get_param(matrix, self.regelkreis, 'dumpload_ww_temp_max_c', 75))
            if soc is not None and soc >= soc_min_pct:
                ww_ok = obs.ww_temp_c is None or obs.ww_temp_c < ww_max
                if not obs.heizpatrone_aktiv and ww_ok:
                    aktionen.append({
                        'tier': 1, 'aktor': 'fritzdect', 'kommando': 'hp_ein',
                        'grund': f'{grund_basis}, Batt voll ({soc:.0f}%) → Dump-Load HP EIN',
                    })
                    return aktionen
                if not obs.klima_aktiv:
                    aktionen.append({
                        'tier': 1, 'aktor': 'fritzdect', 'kommando': 'klima_ein',
                        'grund': f'{grund_basis}, Batt voll ({soc:.0f}%) → Dump-Load Klima EIN',
                    })
                    return aktionen

        # ── Stufe 3 (opt-in): Provokation (AUS→EIN eingeschalteter Verbraucher) ──
        if bool(get_param(matrix, self.regelkreis, 'provokation_aktiv', False)):
            aktionen.extend(self._provokation(obs, matrix, grund_basis))

        return aktionen

    def _provokation(self, obs: ObsState, matrix: dict, grund: str) -> list[dict]:
        """Diagnose-Provokation: eingeschaltete Verbraucher AUS→EIN.

        Ziel: einen hängenden Regelkreis (SmartMeter/WR-Limit) neu anstoßen.
        Zeitlich gesperrt über `provokation_min_abstand_min`. Der Actuator
        führt die Aktionen sequentiell aus; die Wiedereinschaltung erfolgt im
        Folge-Tick über die regulären Geräteregeln bzw. den nächsten Guard-Lauf.
        """
        abstand_s = int(get_param(matrix, self.regelkreis, 'provokation_min_abstand_min', 30)) * 60
        now = time.time()
        if (now - self._letzte_warnung.get('provokation', 0)) < abstand_s:
            return []
        self._letzte_warnung['provokation'] = now

        aktionen: list[dict] = []
        if obs.heizpatrone_aktiv:
            aktionen.append({'tier': 1, 'aktor': 'fritzdect', 'kommando': 'hp_aus',
                             'grund': f'{grund} → Provokation: HP AUS (Regelkreis anstoßen)'})
        if obs.klima_aktiv:
            aktionen.append({'tier': 1, 'aktor': 'fritzdect', 'kommando': 'klima_aus',
                             'grund': f'{grund} → Provokation: Klima AUS (Regelkreis anstoßen)'})
        if aktionen:
            self._log_event('act', f'Provokation ausgelöst: {len(aktionen)} Verbraucher AUS→EIN')
        return aktionen
