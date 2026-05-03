---
title: Automation-State (RAM-DB, Configs, Persist-Log)
domain: automation
role: C
tags: [state, obs-state, persist, ram-db, configs]
status: stable
last_review: 2026-05-03
---

# Automation-State

## Zweck
Wo lebt welcher Zustand? Welche Datei/Tabelle ist Quelle der Wahrheit? Klärung der Trennung zwischen RAM-DB (transient), Persist-DB (`data.db`) und Config-JSONs.

## Code-Anchor
- **ObsState (Schreibpfad):** `automation/engine/obs_state.py:write_obs_state`
- **RAM-DB-Pfad:** `/dev/shm/automation_obs.db` (Tabellen: `obs_state`, `tier1_flags`, `operator_overrides`)
- **Operator-Override-Verarbeitung:** `automation/engine/operator_overrides.py:OperatorOverrideProcessor.process_pending`
- **Persist-Log:** `data.db` Tabelle `automation_log` (geschrieben durch `aktoren/*` via `actuator.py`)
- **Configs:** `config/soc_param_matrix.json`, `config/battery_control.json`, `config/battery_scheduler_state.json`, `config/fritz_config.json`, `config/heizpatrone_fritz_reference.json`, `config/diagnos_alert_state.json`

## Inputs / Outputs
- **Schreibend in RAM-DB:** Collector (ObsState alle 10 s), Tier1Checker, Steuerbox (`operator_overrides`).
- **Schreibend in Persist-DB:** Aktoren (`automation_log`), Collector (`raw_data` etc., siehe Collector-Cards).
- **Lesend aus RAM-DB:** Engine, Web-API (read-only).

## Invarianten
- RAM-DB ist **transient**: Bei System-Reboot weg. Daemon muss "sauber" starten können.
- Persist-DB ist **dauerhaft**: einzige Quelle für historische Auswertungen.
- Configs sind **persistent + manuell editierbar** (per `pv-config.py` TUI). Quelle der Wahrheit für Schwellen.
- `battery_scheduler_state.json` ist **Legacy-Fallback**, nicht primär.

## No-Gos
- Keine Schreibvorgänge auf RAM-DB außerhalb der dafür vorgesehenen Module (Collector, Tier1, Steuerbox).
- Keine direkten Schreibzugriffe der Web-API auf `data.db` (Rolle B = read-only).
- Kein Überschreiben von Configs ohne Backup-Strategie.

## Häufige Aufgaben
- ObsState-Feld hinzufügen → `obs_state.py` Schema + Producer (Collector) + Consumer (Engine).
- Operator-Override neu definieren → Steuerbox `intent_handler.py` + `operator_overrides.py`.
- Matrix-Eintrag ändern → `config/soc_param_matrix.json` (Daemon-Restart bis K-04 erledigt).

## Bekannte Fallstricke
- **`battery_control_log` (Persist-DB):** Wird vom Code mehrheitlich noch gelesen (`pv-config.py`, `routes/system.py`), aber nicht mehr geschrieben. Reader-Cleanup ist offene Tech-Debt (`doc/TODO.md`).
- RAM-DB-Pfad muss vor Daemon-Start existieren (`/dev/shm/`). Bei Container/Restricted-Mounts prüfen.
- Config-Reload: Aktuell nur per Daemon-Restart (K-04 in TODO).
- `failover-sync` kann Config-JSONs überschreiben — Pfad-Mapping prüfen (`failover-sync-orange-status-note`).

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-steuerungsphilosophie.card.md`](./automation-steuerungsphilosophie.card.md) — Matrix als Quelle
- [`collector-db-schema.card.md`](./collector-db-schema.card.md) — Persist-DB Tabellen

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/automation/PV_CONFIG_HANDBUCH.md`
