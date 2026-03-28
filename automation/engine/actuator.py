"""
actuator.py — Aktor-Dispatcher (Schicht S4)

Empfängt Action-Pläne von der Engine, dispatcht an das richtige
Aktor-Plugin, führt Read-Back-Verifikation durch und loggt in
die Persist-DB (data.db → automation_log).

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §6, §10
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from automation.engine.aktoren.aktor_batterie import AktorBatterie, AktorBase
from automation.engine.aktoren.aktor_wattpilot import AktorWattpilot
from automation.engine.aktoren.aktor_fritzdect import AktorFritzDECT
from automation.engine.aktoren.aktor_waermepumpe import AktorWaermepumpe
from automation.engine.schaltlog import logge_engine

LOG = logging.getLogger('actuator')

# Persist-DB für Logging (data.db)
PERSIST_DB_PATH = os.path.join(_PROJECT_ROOT, 'data.db')


# ═════════════════════════════════════════════════════════════
# Persist-DB Schema (automation_log)
# ═════════════════════════════════════════════════════════════

_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS automation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    tier        INTEGER NOT NULL DEFAULT 0,
    aktor       TEXT NOT NULL,
    kommando    TEXT NOT NULL,
    wert        TEXT,
    grund       TEXT,
    ergebnis    TEXT NOT NULL,    -- 'OK' | 'FEHLER' | 'DRY-RUN'
    verify_ok   INTEGER,         -- 1=OK, 0=FAIL, NULL=nicht verifiziert
    verify_json TEXT,            -- Verifikations-Details
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_autolog_ts ON automation_log(ts);
CREATE INDEX IF NOT EXISTS idx_autolog_aktor ON automation_log(aktor, ts);
"""


def init_persist_log(db_path: str = PERSIST_DB_PATH) -> sqlite3.Connection:
    """Öffne Persist-DB und erstelle automation_log Tabelle."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_LOG_SCHEMA)
    conn.commit()
    LOG.info(f"Persist-DB automation_log initialisiert: {db_path}")
    return conn


# ═════════════════════════════════════════════════════════════
# Actuator
# ═════════════════════════════════════════════════════════════

# Deduplizierungs-Sperre: Identische Befehle innerhalb dieser Zeit überspringen
DEDUP_INTERVALL_S = 45  # Sekunden
DEDUP_FEHLER_INTERVALL_S = 300  # 5 Minuten Cooldown nach FEHLER


class Actuator:
    """Dispatcher: Empfängt Aktionen, führt aus, verifiziert, loggt.

    Aktuell registrierte Aktoren:
      'batterie' → AktorBatterie
    """

    def __init__(self, dry_run: bool = False, persist_db_path: str = PERSIST_DB_PATH):
        self.dry_run = dry_run
        self._persist_conn = None
        self._persist_db_path = persist_db_path

        # Aktor-Registry
        self._aktoren: dict[str, AktorBase] = {}
        self._register_default_aktoren()

        # Deduplizierung: {(aktor, kommando, wert_str): timestamp}
        self._letzte_aktion: dict[tuple, float] = {}
        # FEHLER-Cooldown: {(aktor, kommando, wert_str): timestamp}
        self._letzte_fehler: dict[tuple, float] = {}

    def _register_default_aktoren(self):
        """Standard-Aktoren registrieren."""
        self._aktoren['batterie'] = AktorBatterie(dry_run=self.dry_run)
        self._aktoren['wattpilot'] = AktorWattpilot(dry_run=self.dry_run)
        self._aktoren['fritzdect'] = AktorFritzDECT(dry_run=self.dry_run)
        self._aktoren['waermepumpe'] = AktorWaermepumpe(dry_run=self.dry_run)
        LOG.info(f"Aktoren registriert: {list(self._aktoren.keys())}")

    def registriere_aktor(self, name: str, aktor: AktorBase):
        """Zusätzlichen Aktor registrieren (Plugin-System)."""
        aktor.dry_run = self.dry_run
        self._aktoren[name] = aktor
        LOG.info(f"Aktor '{name}' registriert")

    def _get_persist_conn(self) -> sqlite3.Connection:
        """Lazy-Init der Persist-DB Verbindung."""
        if self._persist_conn is None:
            self._persist_conn = init_persist_log(self._persist_db_path)
        return self._persist_conn

    # ── Aktion ausführen ─────────────────────────────────────

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine Einzelaktion aus.

        Args:
            aktion: dict mit 'tier', 'aktor', 'kommando', optional 'wert', 'grund'

        Returns:
            dict mit 'ok', 'kommando', 'detail', optional 'verify'
        """
        aktor_name = aktion.get('aktor', '')
        kommando = aktion.get('kommando', '?')
        wert_str = str(aktion.get('wert', ''))
        dedup_key = (aktor_name, kommando, wert_str)

        aktor = self._aktoren.get(aktor_name)

        if not aktor:
            LOG.error(f"Kein Aktor für '{aktor_name}' registriert")
            ergebnis = {'ok': False, 'kommando': kommando,
                        'detail': f'Kein Aktor: {aktor_name}'}
            self._log_aktion(aktion, ergebnis)
            return ergebnis

        # ── Deduplizierung: identischen Befehl nicht wiederholen ──
        now = time.time()
        letzte_ts = self._letzte_aktion.get(dedup_key, 0)
        if (now - letzte_ts) < DEDUP_INTERVALL_S:
            LOG.debug(f"Dedup: {aktor_name}.{kommando}={wert_str} übersprungen "
                      f"(vor {now - letzte_ts:.0f}s bereits gesendet)")
            return {'ok': True, 'kommando': kommando,
                    'detail': 'Dedupliziert (identischer Befehl kürzlich gesendet)'}

        # ── FEHLER-Cooldown: nach Fehler nicht sofort erneut versuchen ──
        letzte_fehler_ts = self._letzte_fehler.get(dedup_key, 0)
        if (now - letzte_fehler_ts) < DEDUP_FEHLER_INTERVALL_S:
            LOG.debug(f"FEHLER-Cooldown: {aktor_name}.{kommando}={wert_str} übersprungen "
                      f"(Fehler vor {now - letzte_fehler_ts:.0f}s, Sperre {DEDUP_FEHLER_INTERVALL_S}s)")
            return {'ok': False, 'kommando': kommando,
                    'detail': f'FEHLER-Cooldown ({DEDUP_FEHLER_INTERVALL_S}s): letzter Versuch fehlgeschlagen'}
        # Ausführen
        ergebnis = aktor.ausfuehren(aktion)

        # Bei Erfolg: Timestamp für Deduplizierung merken
        if ergebnis.get('ok'):
            self._letzte_aktion[dedup_key] = now
        else:
            self._letzte_fehler[dedup_key] = now

        # Read-Back Verifikation (nur bei echtem Betrieb und Erfolg)
        if ergebnis.get('ok') and not self.dry_run:
            time.sleep(0.3)  # Kurze Pause für Hardware-Propagation
            verify = aktor.verifiziere(aktion)
            ergebnis['verify'] = verify
            if not verify.get('ok'):
                LOG.warning(f"VERIFIKATION FEHLGESCHLAGEN: {aktion.get('kommando')} "
                            f"— soll={verify.get('soll')}, ist={verify.get('ist')}")

        # In Persist-DB loggen
        self._log_aktion(aktion, ergebnis)

        return ergebnis

    def ausfuehren_plan(self, aktionen: list[dict]) -> list[dict]:
        """Führe einen Action-Plan (Liste von Aktionen) aus.

        Tier-1 Aktionen werden sofort ausgeführt.
        Aktionen stoppen bei FEHLER (fail-fast).
        """
        ergebnisse = []
        for aktion in aktionen:
            ergebnis = self.ausfuehren(aktion)
            ergebnisse.append(ergebnis)
            if not ergebnis.get('ok') and not self.dry_run:
                LOG.error(f"Aktion fehlgeschlagen — Plan abgebrochen: "
                          f"{aktion.get('kommando')}")
                break
        return ergebnisse

    # ── Logging ──────────────────────────────────────────────

    def _log_aktion(self, aktion: dict, ergebnis: dict):
        """Logge Aktion + Ergebnis in Persist-DB."""
        for _attempt in range(2):
            try:
                conn = self._get_persist_conn()
                now = datetime.now().isoformat()

                if self.dry_run:
                    status = 'DRY-RUN'
                elif ergebnis.get('ok'):
                    status = 'OK'
                else:
                    status = 'FEHLER'

                verify = ergebnis.get('verify')
                verify_ok = None
                verify_json = None
                if verify:
                    verify_ok = 1 if verify.get('ok') else 0
                    verify_json = json.dumps(verify, ensure_ascii=False)

                conn.execute(
                    "INSERT INTO automation_log "
                    "(ts, tier, aktor, kommando, wert, grund, ergebnis, verify_ok, verify_json, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        aktion.get('tier', 0),
                        aktion.get('aktor', '?'),
                        aktion.get('kommando', '?'),
                        json.dumps(aktion.get('wert')) if aktion.get('wert') is not None else None,
                        aktion.get('grund', ''),
                        status,
                        verify_ok,
                        verify_json,
                        ergebnis.get('detail', ''),
                    )
                )
                conn.commit()
                break  # Erfolg — Schleife verlassen
            except Exception as e:
                LOG.error(f"Persist-DB Logging fehlgeschlagen: {e}")
                # Bei "malformed" oder I/O-Fehlern: Verbindung verwerfen und neu aufbauen
                if _attempt == 0 and ('malformed' in str(e) or 'disk I/O' in str(e)):
                    LOG.warning("Persist-DB Verbindung wird erneuert (malformed/IO)")
                    try:
                        if self._persist_conn:
                            self._persist_conn.close()
                    except Exception:
                        pass
                    self._persist_conn = None
                    # Retry in nächster Iteration
                else:
                    break  # Kein Retry bei anderen Fehlern

        # ── Zentrales Schaltlog ──
        try:
            wert_str = ''
            if aktion.get('wert') is not None:
                wert_str = str(aktion['wert'])
            logge_engine(
                aktor=aktion.get('aktor', '?'),
                kommando=aktion.get('kommando', '?'),
                wert=wert_str,
                ergebnis=status,
                grund=aktion.get('grund', ''),
            )
        except Exception as e:
            LOG.warning(f"Schaltlog Eintrag fehlgeschlagen: {e}")

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        """Alle Aktoren und DB-Verbindungen schließen."""
        for name, aktor in self._aktoren.items():
            if hasattr(aktor, 'close'):
                aktor.close()
        if self._persist_conn:
            self._persist_conn.close()
            self._persist_conn = None
        LOG.info("Actuator geschlossen")
