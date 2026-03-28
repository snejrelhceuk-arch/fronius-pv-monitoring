#!/usr/bin/env python3
"""
test_skeleton.py — Dry-Run-Test des Automation-Skeletts

Testet den kompletten Datenfluss ohne Hardware-Zugriff:
  1. ObsState anlegen + RAM-DB schreiben
  2. Tier-1 Schwellenprüfung (Batterie-Temp, SOC, Netz)
  3. Engine-Zyklus (Score-Bewertung, Regel-Auswahl)
  4. Actuator Dispatch (Dry-Run, kein Modbus/HTTP)
  5. Persist-DB Logging (automation_log)
  6. Parametermatrix validierung
  7. Matrix-getriebene Regel-Tests (9 Regelkreise)

Aufruf:
  cd <project-root>
  python3 -m automation.engine.test_skeleton
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

# Projekt-Root
from automation.engine.obs_state import (
    ObsState, init_ram_db, write_obs_state, read_obs_state,
    write_heartbeat,
)
from automation.engine.observer import Tier1Checker
from automation.engine.actuator import Actuator
from automation.engine.engine import (
    Engine, RegelMorgenSocMin,
    RegelNachmittagSocMax, RegelKomfortReset, RegelZellausgleich,
    RegelForecastPlausi,
    RegelWattpilotBattSchutz,
)
from automation.engine.param_matrix import (
    lade_matrix, validiere_matrix, get_param, ist_aktiv,
    get_score_gewicht, DEFAULT_MATRIX_PATH,
)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(name)-14s %(levelname)-8s %(message)s',
    datefmt='%H:%M:%S',
)
LOG = logging.getLogger('test')


def _sep(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print('═' * 60)


def test_obs_state_ram_db(ram_db_path: str):
    """Test 1: ObsState → RAM-DB → Read-Back."""
    _sep("1. ObsState + RAM-DB")

    conn = init_ram_db(ram_db_path)

    obs = ObsState(
        ts='2025-06-01T14:30:00',
        pv_total_w=8500,
        pv_f1_w=4200, pv_f2_w=3300, pv_f3_w=1000,
        batt_soc_pct=72.5,
        batt_power_w=3500,
        batt_temp_c=28.3,
        batt_temp_max_c=29.1,
        batt_temp_min_c=27.5,
        storctl_mod=0,
        charge_rate_pct=100,
        discharge_rate_pct=100,
        cha_state=4,  # CHARGING
        grid_power_w=-2100,  # Einspeisung
        house_load_w=2900,
        is_day=True,
    )

    write_obs_state(conn, obs)
    write_heartbeat(conn, 'test.obs')

    read_back = read_obs_state(conn)
    assert read_back is not None, "Read-Back fehlgeschlagen"
    assert read_back.batt_soc_pct == 72.5, f"SOC falsch: {read_back.batt_soc_pct}"
    assert read_back.batt_temp_max_c == 29.1

    LOG.info("✓ ObsState geschrieben + gelesen")
    LOG.info(f"  SOC={read_back.batt_soc_pct}%, Temp_max={read_back.batt_temp_max_c}°C, "
             f"Grid={read_back.grid_power_w}W")

    conn.close()
    return True


def test_tier1_normal():
    """Test 2a: Tier-1 bei normalen Bedingungen → keine Alarme."""
    _sep("2a. Tier-1: Normalbetrieb")

    checker = Tier1Checker(schutz_cfg={
        'batt_temp_warn_c': 40,
        'batt_temp_alarm_c': 45,
        'batt_temp_reduce_c_rate': 0.3,
        'batt_kapazitaet_kwh': 20.48,
        'batt_soc_kritisch': 5,
        'netz_ueberlast_warn_w': 24000,
        'netz_ueberlast_alarm_w': 26000,
    })

    obs = ObsState(
        batt_temp_max_c=28.0,
        batt_soc_pct=65.0,
        grid_power_w=3000,
    )

    actions = checker.check(obs)
    assert len(actions) == 0, f"Unerwartete Aktionen: {actions}"
    assert not obs.alarm_batt_temp
    assert not obs.alarm_batt_kritisch
    assert not obs.alarm_ueberlast

    LOG.info("✓ Keine Alarme bei Normalbetrieb")
    return True


def test_tier1_temp_warn():
    """Test 2b: Tier-1 Batterie-Temp WARNUNG (≥40°C → Alarm-Flag, kein HW-Eingriff)."""
    _sep("2b. Tier-1: Batterie-Temp WARNUNG (40°C)")

    checker = Tier1Checker(schutz_cfg={
        'batt_temp_warn_c': 40,
        'batt_temp_alarm_c': 45,
    })

    obs = ObsState(batt_temp_max_c=41.2, batt_soc_pct=80.0)
    actions = checker.check(obs)

    assert obs.alarm_batt_temp, "Alarm-Flag nicht gesetzt"
    assert len(actions) == 0, f"Erwarte keine Aktionen (HW-Eingriffe entfernt), got {actions}"

    LOG.info("✓ Alarm-Flag gesetzt, keine HW-Aktion (BMS regelt selbständig)")
    return True


def test_tier1_temp_alarm():
    """Test 2c: Tier-1 Batterie-Temp ALARM (≥45°C → Alarm-Flag, kein HW-Eingriff)."""
    _sep("2c. Tier-1: Batterie-Temp ALARM (45°C)")

    checker = Tier1Checker(schutz_cfg={
        'batt_temp_warn_c': 40,
        'batt_temp_alarm_c': 45,
    })

    obs = ObsState(batt_temp_max_c=46.5, batt_soc_pct=90.0)
    actions = checker.check(obs)

    assert obs.alarm_batt_temp
    assert len(actions) == 0, f"Erwarte keine Aktionen (HW-Eingriffe entfernt), got {actions}"

    LOG.info("✓ ALARM-Flag gesetzt, keine HW-Aktion (BMS regelt selbständig)")
    return True


def test_tier1_temp_hysterese():
    """Test 2d: Alarm-Flags setzen/löschen bei Temperaturänderung."""
    _sep("2d. Tier-1: Temp-Alarm-Flags")

    checker = Tier1Checker(schutz_cfg={
        'batt_temp_warn_c': 40,
        'batt_temp_alarm_c': 45,
    })

    # Schritt 1: Alarm auslösen bei 42°C
    obs = ObsState(batt_temp_max_c=42.0)
    actions = checker.check(obs)
    assert obs.alarm_batt_temp
    assert len(actions) == 0, "Keine HW-Aktionen erwartet"
    LOG.info("  42°C → Alarm-Flag gesetzt")

    # Schritt 2: 37°C — Alarm gelöst
    obs2 = ObsState(batt_temp_max_c=37.0)
    actions2 = checker.check(obs2)
    assert not obs2.alarm_batt_temp
    assert len(actions2) == 0
    LOG.info("  37°C → Alarm-Flag gelöst")

    LOG.info("✓ Alarm-Flags korrekt: 42°C→Alarm, 37°C→Normal")
    return True


def test_tier1_soc_kritisch():
    """Test 2e: Tier-1 SOC kritisch (<5%) → Alarm-Flag (kein HW-Eingriff)."""
    _sep("2e. Tier-1: SOC kritisch")

    checker = Tier1Checker(schutz_cfg={'batt_soc_kritisch': 5})
    obs = ObsState(batt_soc_pct=3.2, batt_temp_max_c=25.0, grid_power_w=1000)
    actions = checker.check(obs)

    assert obs.alarm_batt_kritisch
    assert len(actions) == 0, f"Erwarte keine Aktionen (SOC_MIN steuert implizit), got {actions}"
    LOG.info("✓ SOC kritisch: Alarm-Flag gesetzt, keine HW-Aktion")
    return True


def test_actuator_dry_run(persist_db_path: str):
    """Test 3: Actuator Dry-Run + Persist-DB Logging."""
    _sep("3. Actuator (Dry-Run)")

    actuator = Actuator(dry_run=True, persist_db_path=persist_db_path)

    aktion = {
        'tier': 1,
        'aktor': 'batterie',
        'kommando': 'set_soc_min',
        'wert': 10,
        'grund': 'Test: SOC-Schutz',
    }

    ergebnis = actuator.ausfuehren(aktion)
    assert ergebnis['ok'], f"Dry-Run fehlgeschlagen: {ergebnis}"
    LOG.info(f"✓ Dry-Run OK: {ergebnis['kommando']} → {ergebnis['detail']}")

    # Prüfe Persist-DB
    conn = sqlite3.connect(persist_db_path)
    row = conn.execute(
        "SELECT ts, aktor, kommando, wert, ergebnis FROM automation_log "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "Kein Eintrag in automation_log"
    assert row[4] == 'DRY-RUN'
    LOG.info(f"✓ Persist-DB: {row[1]}.{row[2]}={row[3]} → {row[4]}")

    conn.close()
    actuator.close()
    return True


def test_engine_zyklus(ram_db_path: str, persist_db_path: str):
    """Test 4: Engine-Zyklus mit simuliertem ObsState + Parametermatrix."""
    _sep("4. Engine-Zyklus (Matrix-getrieben)")

    # ObsState mit 32°C Batterie-Temp in RAM-DB schreiben
    ram_conn = init_ram_db(ram_db_path)

    obs = ObsState(
        ts='2025-06-01T14:30:00',
        batt_soc_pct=60.0,
        batt_temp_max_c=32.0,  # → triggers Temp-Schutz (30°C → 80%)
        grid_power_w=2000,
    )
    write_obs_state(ram_conn, obs)
    ram_conn.close()

    # Engine mit echtem Matrix-Pfad
    actuator = Actuator(dry_run=True, persist_db_path=persist_db_path)
    engine = Engine(actuator=actuator, dry_run=True,
                    matrix_path=DEFAULT_MATRIX_PATH)

    # HACK: Engine RAM-DB Path überschreiben für Test
    import automation.engine.obs_state as obs_mod
    orig_path = obs_mod.RAM_DB_PATH
    obs_mod.RAM_DB_PATH = ram_db_path

    try:
        ergebnisse = engine.zyklus('fast')
    finally:
        obs_mod.RAM_DB_PATH = orig_path

    if ergebnisse:
        for e in ergebnisse:
            LOG.info(f"✓ Engine → {e.get('kommando')}: {'OK' if e.get('ok') else 'FEHLER'}")
    else:
        LOG.info("  (Keine Regeln aktiv bei aktuellen Werten)")

    engine.close()
    actuator.close()
    return True


# ═════════════════════════════════════════════════════════════
# Parametermatrix Tests
# ═════════════════════════════════════════════════════════════

def test_matrix_laden_validieren():
    """Test 5: Parametermatrix laden + validieren."""
    _sep("5. Parametermatrix laden + validieren")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    assert 'regelkreise' in matrix, "Kein 'regelkreise' Schlüssel"

    rk = matrix['regelkreise']
    erwartete = ['soc_schutz', 'temp_schutz', 'morgen_soc_min',
                 'nachmittag_soc_max', 'abend_entladerate', 'zellausgleich']
    for name in erwartete:
        assert name in rk, f"Regelkreis '{name}' fehlt"
    LOG.info(f"✓ {len(rk)} Regelkreise geladen: {list(rk.keys())}")

    # Validierung
    fehler = validiere_matrix(matrix)
    assert len(fehler) == 0, f"Validierungsfehler: {fehler}"
    LOG.info("✓ Alle Parameter im gültigen Bereich")

    # Hilfsfunktionen testen
    assert ist_aktiv(matrix, 'soc_schutz') is True
    assert get_score_gewicht(matrix, 'soc_schutz') == 90
    assert get_param(matrix, 'temp_schutz', 'stufe_30c_pct', 0) == 80
    LOG.info("✓ get_param / ist_aktiv / get_score_gewicht korrekt")

    return True


# ═════════════════════════════════════════════════════════════
# Regel-Level Tests (isoliert, ohne Engine)
# ═════════════════════════════════════════════════════════════

def test_regel_morgen_soc_min():
    """Test 6c: RegelMorgenSocMin — SOC_MIN morgens öffnen."""
    _sep("6c. RegelMorgenSocMin")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelMorgenSocMin()

    # Morgens 6:30 Uhr, Sunrise=6.0, PV@SR+1h=2000W (>1500), SOC_MIN noch bei 25
    fake_time = datetime(2025, 6, 15, 6, 30)  # 6.5h
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs = ObsState(
            forecast_kwh=35.0,
            pv_total_w=800,
            pv_at_sunrise_1h_w=2000,
            soc_min=25,
            soc_mode='auto',
            sunrise=6.0,
        )
        score = regel.bewerte(obs, matrix)
        assert score > 0, f"Erwarte Score > 0 morgens bei guter Prognose, got {score}"
        LOG.info(f"✓ 06:30, Prognose 35 kWh: Score {score}")

        aktionen = regel.erzeuge_aktionen(obs, matrix)
        assert len(aktionen) >= 2, f"Erwarte ≥2 Aktionen (set_soc_mode + set_soc_min + opt. set_soc_max), got {len(aktionen)}"
        assert aktionen[0]['kommando'] == 'set_soc_mode'
        assert aktionen[0]['wert'] == 'manual'
        assert aktionen[1]['kommando'] == 'set_soc_min'
        assert aktionen[1]['wert'] == 5
        LOG.info(f"✓ Aktionen: {[a['kommando'] for a in aktionen]}")

    # Nachmittags 15:00 → außerhalb Zeitfenster → Score 0
    fake_afternoon = datetime(2025, 6, 15, 15, 0)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_afternoon
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        score2 = regel.bewerte(obs, matrix)
        assert score2 == 0, f"Erwarte Score 0 nachmittags, got {score2}"
        LOG.info(f"✓ 15:00: Score {score2} (außerhalb Fenster)")

    # Morgens, aber PV@SR+1h unter Schwelle (500W < 1500W)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs_bad = ObsState(forecast_kwh=2.0, pv_total_w=100, pv_at_sunrise_1h_w=500,
                           soc_min=25, sunrise=6.0)
        score3 = regel.bewerte(obs_bad, matrix)
        assert score3 == 0, f"Erwarte Score 0 bei PV@SR+1h < Schwelle, got {score3}"
        LOG.info(f"✓ PV@SR+1h=500W: Score {score3} (unter Schwelle)")

    return True


def test_regel_komfort_reset_morgen_sperre():
    """Regressions-Test: Bei guter Prognose ab Sunrise-1h kein Komfort-Reset."""
    _sep("6c2. RegelKomfortReset Morgen-Sperre")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelKomfortReset()

    # 05:30, Sunrise=6.0 -> > Sunrise-1h, gute Prognose
    # Erwartung: Komfort-Reset greift NICHT ein, SOC_MIN=5% bleibt unangetastet.
    fake_time_block = datetime(2025, 6, 15, 5, 30)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time_block
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs = ObsState(
            forecast_quality='gut',
            sunrise=6.0,
            sunset=20.5,
            soc_min=5,
            soc_max=75,
            soc_mode='manual',
            batt_soc_pct=24,
        )
        score = regel.bewerte(obs, matrix)
        assert score == 0, f"Erwarte Score 0 bei guter Prognose ab Sunrise-1h, got {score}"
        aktionen = regel.erzeuge_aktionen(obs, matrix)
        assert aktionen == [], f"Erwarte keine Aktionen, got {aktionen}"
        LOG.info("✓ 05:30, forecast=gut: Komfort-Reset gesperrt")

    # 04:30, Sunrise=6.0 -> vor Sunrise-1h
    # Erwartung: Sperre greift noch nicht, Komfort-Reset darf bewerten.
    fake_time_allow = datetime(2025, 6, 15, 4, 30)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time_allow
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs2 = ObsState(
            forecast_quality='gut',
            sunrise=6.0,
            sunset=20.5,
            soc_min=5,
            soc_max=75,
            soc_mode='manual',
            batt_soc_pct=24,
        )
        score2 = regel.bewerte(obs2, matrix)
        assert score2 > 0, f"Erwarte Score >0 vor Sunrise-1h, got {score2}"
        LOG.info(f"✓ 04:30, forecast=gut: Komfort-Reset aktiv (Score {score2})")

    return True


def test_regel_nachmittag_soc_max():
    """Test 6d: RegelNachmittagSocMax — SOC_MAX nachmittags erhöhen."""
    _sep("6d. RegelNachmittagSocMax")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelNachmittagSocMax()

    # 16:30, Sunset 17.5 → nur 1h bis Sunset → max_stunden_vor_sunset = 1.5 → Deadline!
    fake_time = datetime(2025, 6, 15, 16, 30)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs = ObsState(soc_max=75, soc_mode='auto', sunset=17.5)
        score = regel.bewerte(obs, matrix)
        assert score == 55, f"Erwarte Score 55 (Deadline), got {score}"
        LOG.info(f"✓ 16:30, Sunset 17:30: Score {score} (Deadline)")

        aktionen = regel.erzeuge_aktionen(obs, matrix)
        assert len(aktionen) == 2
        assert aktionen[0]['kommando'] == 'set_soc_mode'
        assert aktionen[1]['kommando'] == 'set_soc_max'
        assert aktionen[1]['wert'] == 100
        LOG.info(f"✓ Aktionen: {[a['kommando'] for a in aktionen]}")

    # SOC_MAX schon bei 100% → Score 0
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs_voll = ObsState(soc_max=100, sunset=17.5)
        score2 = regel.bewerte(obs_voll, matrix)
        assert score2 == 0, f"Erwarte Score 0 wenn SOC_MAX schon 100%, got {score2}"
        LOG.info(f"✓ SOC_MAX=100%: Score {score2} (schon offen)")

    return True


def test_regel_zellausgleich():
    """Test 6f: RegelZellausgleich — Vollzyklus bei guter Prognose."""
    _sep("6f. RegelZellausgleich")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelZellausgleich()

    # Tag 10, Prognose 55 kWh (>50) → Score 30
    from datetime import date as real_date
    with patch('automation.engine.regeln.optimierung.date') as mock_date:
        mock_date.today.return_value = real_date(2025, 6, 10)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        obs = ObsState(forecast_kwh=55.0)
        score = regel.bewerte(obs, matrix)
        assert score == 30, f"Erwarte Score 30 bei guter Prognose, got {score}"
        LOG.info(f"✓ Tag 10, 55 kWh: Score {score}")

        aktionen = regel.erzeuge_aktionen(obs, matrix)
        assert len(aktionen) == 2, f"Erwarte 2 Aktionen, got {len(aktionen)}"
        assert aktionen[0]['kommando'] == 'set_soc_min'
        assert aktionen[0]['wert'] == 5
        assert aktionen[1]['kommando'] == 'set_soc_max'
        assert aktionen[1]['wert'] == 100
        LOG.info(f"✓ Aktionen: {[a['kommando'] for a in aktionen]}")

    # Tag 10, Prognose 20 kWh (< 50) → Score 0
    with patch('automation.engine.regeln.optimierung.date') as mock_date:
        mock_date.today.return_value = real_date(2025, 6, 10)

        obs_schlecht = ObsState(forecast_kwh=20.0)
        score2 = regel.bewerte(obs_schlecht, matrix)
        assert score2 == 0, f"Erwarte Score 0 bei schlechter Prognose, got {score2}"
        LOG.info(f"✓ Tag 10, 20 kWh: Score {score2} (zu wenig Sonne)")

    # Tag 30 → außerhalb spaetester_tag=28 → Score 0
    with patch('automation.engine.regeln.optimierung.date') as mock_date:
        mock_date.today.return_value = real_date(2025, 6, 30)

        obs_ok = ObsState(forecast_kwh=60.0)
        score3 = regel.bewerte(obs_ok, matrix)
        assert score3 == 0, f"Erwarte Score 0 nach Tag 28, got {score3}"
        LOG.info(f"✓ Tag 30: Score {score3} (nach Deadline)")

    return True


def test_regel_nachmittag_forecast_rest():
    """Test 6d2: Nachmittag-Regel nutzt forecast_rest_kwh und cloud_rest_avg_pct."""
    _sep("6d2. Nachmittag mit forecast_rest + cloud_rest")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelNachmittagSocMax()

    # 17:30, Sunset 18.5 → 1h bis Sunset → Deadline-Zone → Score=55
    # Mit forecast_rest nur 2 kWh + Wolken-Check
    fake_time = datetime(2025, 6, 15, 17, 30)
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs = ObsState(soc_max=75, soc_mode='auto', sunset=18.5,
                       forecast_rest_kwh=2.0, cloud_rest_avg_pct=50.0)
        score = regel.bewerte(obs, matrix)
        # 1h bis Sunset < max_stunden_vor_sunset (1.5) → Deadline = max Score
        assert score == 55, f"Erwarte Score 55 (Deadline), got {score}"
        LOG.info(f"✓ 17:30, Sunset 18:30, Rest 2 kWh: Score {score} (Deadline)")

    # 17:30, Sunset 18.5, cloud_rest_avg 90% → gleicher Deadline-Score
    with patch('automation.engine.regeln.soc_steuerung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs2 = ObsState(soc_max=75, soc_mode='auto', sunset=18.5,
                        forecast_rest_kwh=10.0, cloud_rest_avg_pct=90.0)
        score2 = regel.bewerte(obs2, matrix)
        assert score2 == 55, f"Erwarte Score 55 (Deadline), got {score2}"
        LOG.info(f"✓ 17:30, cloud_rest 90%: Score {score2} (Deadline)")

    return True


def test_regel_forecast_plausi():
    """Test 6g: RegelForecastPlausi — Prognose an Realität anpassen."""
    _sep("6g. RegelForecastPlausi")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelForecastPlausi()

    # 12:00, Sunrise 6.0 → 6h Betrieb > min_betriebsstunden(2)
    fake_time = datetime(2025, 6, 15, 12, 0)

    # Fall 1: IST/SOLL 60% < Schwelle 70% → Score 40 (50*0.8 ohne schwere Wolken)
    with patch('automation.engine.regeln.optimierung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs = ObsState(pv_vs_forecast_pct=60.0, forecast_rest_kwh=8.0,
                       sunrise=6.0, cloud_rest_avg_pct=50.0)
        score = regel.bewerte(obs, matrix)
        assert score == int(50 * 0.8), f"Erwarte {int(50*0.8)}, got {score}"
        LOG.info(f"✓ IST/SOLL 60%, Wolken 50%: Score {score}")

    # Fall 2: IST/SOLL 60% + cloud_rest 85% (>80 schwer) → voller Score 50
    with patch('automation.engine.regeln.optimierung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs2 = ObsState(pv_vs_forecast_pct=60.0, forecast_rest_kwh=8.0,
                        sunrise=6.0, cloud_rest_avg_pct=85.0)
        score2 = regel.bewerte(obs2, matrix)
        assert score2 == 50, f"Erwarte Score 50 (schwere Wolken), got {score2}"
        LOG.info(f"✓ IST/SOLL 60%, Wolken 85%: Score {score2}")

    # Fall 3: IST/SOLL 80% > Schwelle 70% → Score 0 (Prognose plausibel)
    with patch('automation.engine.regeln.optimierung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs3 = ObsState(pv_vs_forecast_pct=80.0, forecast_rest_kwh=8.0,
                        sunrise=6.0)
        score3 = regel.bewerte(obs3, matrix)
        assert score3 == 0, f"Erwarte Score 0 (plausibel), got {score3}"
        LOG.info(f"✓ IST/SOLL 80%: Score {score3} (Prognose OK)")

    # Fall 4: Zu früh (7:30, Sunrise 6.0 → 1.5h < min_betriebsstunden 2) → Score 0
    early_time = datetime(2025, 6, 15, 7, 30)
    with patch('automation.engine.regeln.optimierung.datetime') as mock_dt:
        mock_dt.now.return_value = early_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs4 = ObsState(pv_vs_forecast_pct=40.0, forecast_rest_kwh=8.0,
                        sunrise=6.0)
        score4 = regel.bewerte(obs4, matrix)
        assert score4 == 0, f"Erwarte Score 0 (zu früh), got {score4}"
        LOG.info(f"✓ 07:30: Score {score4} (< min_betriebsstunden)")

    # Fall 5: Aktionen — Rest 2 kWh, Wolken schwer → doppelte Reduktion → SOC_MAX 100%
    with patch('automation.engine.regeln.optimierung.datetime') as mock_dt:
        mock_dt.now.return_value = fake_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        obs5 = ObsState(pv_vs_forecast_pct=50.0, forecast_rest_kwh=5.0,
                        sunrise=6.0, cloud_rest_avg_pct=85.0,
                        soc_max=80, soc_mode='auto')
        aktionen = regel.erzeuge_aktionen(obs5, matrix)
        # Rest 5 * 0.7 * 0.6 = 2.1 kWh < 5 → SOC_MAX auf 100%
        assert len(aktionen) == 2, f"Erwarte 2 Aktionen, got {len(aktionen)}"
        assert aktionen[0]['kommando'] == 'set_soc_mode'
        assert aktionen[1]['kommando'] == 'set_soc_max'
        assert aktionen[1]['wert'] == 100
        LOG.info(f"✓ Rest 5kWh + schwere Wolken: {[a['kommando'] for a in aktionen]}")

    return True


def test_regel_wattpilot_battschutz():
    """Test 6i: RegelWattpilotBattSchutz — Batterieschutz bei EV-Ladung."""
    _sep("6i. RegelWattpilotBattSchutz")

    matrix = lade_matrix(DEFAULT_MATRIX_PATH)
    regel = RegelWattpilotBattSchutz()

    # Fall 1: EV lädt, SOC 45% (< 50%), Batterie entlädt → kein Eingriff (Stufe 2 entfernt)
    obs_mitte = ObsState(
        ev_charging=True, ev_power_w=11000.0, ev_eco_mode=False,
        batt_soc_pct=45.0, batt_power_w=-8000.0,
        soc_min=10, discharge_rate_pct=100,
    )
    score = regel.bewerte(obs_mitte, matrix)
    assert score == 0, f"Erwarte Score 0 (SOC 45% > soc_min+puffer), got {score}"
    LOG.info(f"✓ SOC 45%: Score {score} (kein Eingriff, Stufe 2 entfernt)")

    # Fall 2: EV lädt, SOC 14% nahe SOC_MIN 10% (Puffer 5%) → SOC_MIN anheben
    obs_stufe3 = ObsState(
        ev_charging=True, ev_power_w=22000.0, ev_eco_mode=False,
        batt_soc_pct=14.0, batt_power_w=-10000.0,
        soc_min=10, soc_mode='auto',
    )
    score3 = regel.bewerte(obs_stufe3, matrix)
    assert score3 == int(60 * 1.3), f"Erwarte Score {int(60*1.3)}, got {score3}"
    aktionen3 = regel.erzeuge_aktionen(obs_stufe3, matrix)
    assert len(aktionen3) == 2
    assert aktionen3[0]['kommando'] == 'set_soc_mode'
    assert aktionen3[1]['kommando'] == 'set_soc_min'
    assert aktionen3[1]['wert'] == 25
    assert 'hinweis' in aktionen3[1]
    assert 'Netz' in aktionen3[1]['hinweis']
    LOG.info(f"✓ SOC 14%: Score {score3}, SOC_MIN → {aktionen3[1]['wert']}%")
    LOG.info(f"  Hinweis: {aktionen3[1]['hinweis']}")

    # Fall 3: EV lädt, SOC 70% (> 50%) → Score 0 (kein Eingriff)
    obs_stufe1 = ObsState(
        ev_charging=True, ev_power_w=15000.0,
        batt_soc_pct=70.0, batt_power_w=-3000.0,
    )
    score1 = regel.bewerte(obs_stufe1, matrix)
    assert score1 == 0, f"Erwarte Score 0 (SOC hoch), got {score1}"
    LOG.info(f"✓ SOC 70%: Score {score1} (kein Eingriff)")

    # Fall 4: EV lädt, Batterie lädt auch (PV reicht) → Score 0
    obs_laden = ObsState(
        ev_charging=True, ev_power_w=11000.0,
        batt_soc_pct=40.0, batt_power_w=2000.0,
    )
    score4 = regel.bewerte(obs_laden, matrix)
    assert score4 == 0, f"Erwarte Score 0 (Batterie lädt), got {score4}"
    LOG.info(f"✓ PV reicht: Score {score4} (Batterie lädt trotz EV)")

    # Fall 5: Kein EV-Laden → Score 0
    obs_kein_ev = ObsState(
        ev_charging=False, ev_power_w=0.0,
        batt_soc_pct=30.0, batt_power_w=-5000.0,
    )
    score5 = regel.bewerte(obs_kein_ev, matrix)
    assert score5 == 0, f"Erwarte Score 0 (kein EV), got {score5}"
    LOG.info(f"✓ Kein EV-Laden: Score {score5}")

    return True


def test_engine_zyklusfilter(ram_db_path: str, persist_db_path: str):
    """Test 7: Engine filtert Regeln nach Zyklus-Typ."""
    _sep("7. Engine Zyklus-Filter (fast vs strategic)")

    ram_conn = init_ram_db(ram_db_path)
    obs = ObsState(
        ts='2025-06-15T06:30:00',
        batt_soc_pct=60.0,
        batt_temp_max_c=24.0,  # Kein Temp-Schutz
        forecast_kwh=40.0,
        pv_total_w=1000,
        soc_min=25,
        soc_mode='auto',
        sunrise=6.0,
        sunset=17.5,
    )
    write_obs_state(ram_conn, obs)
    ram_conn.close()

    actuator = Actuator(dry_run=True, persist_db_path=persist_db_path)
    engine = Engine(actuator=actuator, dry_run=True, matrix_path=DEFAULT_MATRIX_PATH)

    import automation.engine.obs_state as obs_mod
    orig_path = obs_mod.RAM_DB_PATH
    obs_mod.RAM_DB_PATH = ram_db_path

    try:
        # Fast-Zyklus: sollte nur fast-Regeln auswerten (soc_schutz, temp_schutz, abend_entladerate)
        # Bei SOC 60% + Temp 24°C sollte nur abend_entladerate aktiv sein (je nach Uhrzeit)
        res_fast = engine.zyklus('fast')
        LOG.info(f"  Fast-Zyklus: {len(res_fast)} Aktion(en)")

        # Strategic-Zyklus: sollte alle Regeln auswerten
        res_strat = engine.zyklus('strategic')
        LOG.info(f"  Strategic-Zyklus: {len(res_strat)} Aktion(en)")
    finally:
        obs_mod.RAM_DB_PATH = orig_path

    engine.close()
    actuator.close()
    LOG.info("✓ Zyklus-Filter Test durchlaufen")
    return True


def test_engine_multi_aktion(ram_db_path: str, persist_db_path: str):
    """Test 8: Engine dispatcht Multi-Aktions-Pläne an Actuator."""
    _sep("8. Multi-Aktions-Plan")

    actuator = Actuator(dry_run=True, persist_db_path=persist_db_path)
    matrix = lade_matrix(DEFAULT_MATRIX_PATH)

    # Manuell Zellausgleich-Aktionen erzeugen (2 Aktionen: set_soc_min + set_soc_max)
    regel = RegelZellausgleich()
    obs = ObsState(forecast_kwh=55.0)
    aktionen = regel.erzeuge_aktionen(obs, matrix)

    assert len(aktionen) == 2, f"Erwarte 2 Aktionen, got {len(aktionen)}"

    ergebnisse = actuator.ausfuehren_plan(aktionen)
    assert len(ergebnisse) == 2, f"Erwarte 2 Ergebnisse, got {len(ergebnisse)}"
    for e in ergebnisse:
        assert e['ok'], f"Aktion fehlgeschlagen: {e}"
        LOG.info(f"✓ {e['kommando']}: {e['detail']}")

    # Prüfe Persist-DB: 2 Einträge
    conn = sqlite3.connect(persist_db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM automation_log WHERE kommando IN ('set_soc_min', 'set_soc_max')"
    ).fetchone()[0]
    assert count >= 2, f"Erwarte ≥2 Log-Einträge, got {count}"
    LOG.info(f"✓ {count} Aktionen in Persist-DB geloggt")

    conn.close()
    actuator.close()
    return True


def main():
    print("\n" + "█" * 60)
    print("  PV-Automation Skeleton — Dry-Run-Test")
    print("█" * 60)

    # Temporäre DBs für Tests (keine echten DBs berühren)
    with tempfile.TemporaryDirectory(prefix='pvaut_test_') as tmpdir:
        ram_db = os.path.join(tmpdir, 'test_obs.db')
        persist_db = os.path.join(tmpdir, 'test_persist.db')
        LOG.info(f"Temp-Verzeichnis: {tmpdir}")

        tests = [
            # Basis-Tests (aus Phase 1)
            ('ObsState + RAM-DB', lambda: test_obs_state_ram_db(ram_db)),
            ('Tier-1 Normalbetrieb', test_tier1_normal),
            ('Tier-1 Temp WARNUNG', test_tier1_temp_warn),
            ('Tier-1 Temp ALARM', test_tier1_temp_alarm),
            ('Tier-1 Temp Hysterese', test_tier1_temp_hysterese),
            ('Tier-1 SOC kritisch', test_tier1_soc_kritisch),
            ('Actuator Dry-Run', lambda: test_actuator_dry_run(persist_db)),
            ('Engine-Zyklus', lambda: test_engine_zyklus(ram_db, persist_db)),
            # Parametermatrix Tests (Phase 2)
            ('Matrix laden+validieren', test_matrix_laden_validieren),
            # Regel-Level Tests (Phase 2)
            # Entfernt (2026-03-07): SOC-Schutz, Temp-Schutz, Abend-Entladerate, Laderate dynamisch
            ('Regel: Morgen SOC_MIN', test_regel_morgen_soc_min),
            ('Regel: Komfort-Reset Morgen-Sperre', test_regel_komfort_reset_morgen_sperre),
            ('Regel: Nachmittag SOC_MAX', test_regel_nachmittag_soc_max),
            ('Regel: Zellausgleich', test_regel_zellausgleich),
            ('Regel: Nachmittag+Forecast', test_regel_nachmittag_forecast_rest),
            ('Regel: Forecast-Plausi', test_regel_forecast_plausi),
            ('Regel: WattPilot BattSchutz', test_regel_wattpilot_battschutz),
            # Integration Tests (Phase 2)
            ('Engine Zyklus-Filter', lambda: test_engine_zyklusfilter(ram_db, persist_db)),
            ('Multi-Aktions-Plan', lambda: test_engine_multi_aktion(ram_db, persist_db)),
        ]

        passed = 0
        failed = 0
        for name, test_fn in tests:
            try:
                ok = test_fn()
                if ok:
                    passed += 1
                else:
                    failed += 1
                    LOG.error(f"✗ {name}: Test nicht bestanden")
            except Exception as e:
                failed += 1
                LOG.error(f"✗ {name}: {e}", exc_info=True)

        _sep("ERGEBNIS")
        total = passed + failed
        LOG.info(f"  {passed}/{total} Tests bestanden")
        if failed:
            LOG.error(f"  {failed} Test(s) fehlgeschlagen!")
            return 1
        LOG.info("  Alle Tests OK!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
