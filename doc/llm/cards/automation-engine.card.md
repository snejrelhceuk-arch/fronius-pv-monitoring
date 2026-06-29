---
title: Automation-Engine (Tick-Loop, Regel-Registry)
domain: automation
role: C
applyTo: "automation/engine/**"
tags: [engine, tick-loop, regeln, registry]
status: stable
last_review: 2026-06-29
---

# Automation-Engine

## Zweck
Zentrale Steuerschleife (Rolle C). Sammelt Beobachtungen, ruft Schutz-Checks, dann Regel-Engine, dann Operator-Overrides. Einziger Schreibpfad zur Hardware (Fronius/FritzDECT/Wattpilot).

## Code-Anchor
- **Hauptdatei:** `automation/engine/automation_daemon.py:AutomationDaemon`
- **Engine-Kern:** `automation/engine/engine.py:Engine.zyklus`
- **Plugin-Registry (Regeln + Aktoren):** `automation/engine/registry.py:lade_regeln`/`lade_aktoren`, deklarativ in `config/engine_registry.json`
- **Benachrichtigung (Sunset-Mail/Sofort-Alarme):** `automation/engine/event_notifier.py:EventNotifier`; Helfer-Paket `automation/engine/notify/` (`dedup.py`, `thresholds.py`, `mail.py`)
- **Zugehörige Configs:** `config/soc_param_matrix.json` (zentrale Parameter-Matrix)
- **State (RAM):** `/dev/shm/automation_obs.db` (ObsState, Tier1, Operator-Overrides)
- **State (Persist):** `data.db` Tabelle `automation_log` (Aktor-Resultate)
- **systemd-Unit:** `config/systemd/` (Daemon + ggf. Watchdog)

## Inputs / Outputs
- **Inputs:** ObsState (Sensorwerte alle 10 s), Tier-1-Flags, `soc_param_matrix.json`, Operator-Overrides aus Steuerbox.
- **Outputs:** Hardware-Calls über Aktoren (`aktor_batterie`, `aktor_fritzdect`, `aktor_wattpilot`), `automation_log`-Inserts, Engine-Werte für ExternalRespect-Tracker.

### Override-Hinweis (neu)
- `afternoon_charge_request` ist ein Policy-Hold ohne direkte Aktoraktion in `OperatorOverrideProcessor`: Status bleibt `active` und wird von `RegelNachmittagSocMax`/`RegelHeizpatrone` ausgewertet.

## Invarianten
- **Tick-Schichten:** OBS_COLLECT=10 s, FAST=60 s, STRATEGIC=900 s. Reihenfolge pro Zyklus: DataCollector → Tier1Checker → Engine.fast → Engine.strategic → OperatorOverrideProcessor.
- **Tier-1 hält Engine an:** Bei aktivem Tier-1-Alarm (z. B. `batt_temp>45 °C`, `SOC<5 %`) pausiert die Regel-Auswertung, Schutz-Aktoren bleiben frei.
- **Score 0..100:** Regeln werden bewertet; Schutz-Regeln (Name enthält `schutz` oder `aktor=fritzdect`) laufen parallel, Optimierungs-Regeln nur Gewinner pro Aktor-Cascade.
- **ExternalRespect:** Nach erfolgreichem Aktor-Schreibvorgang muss der Engine-Zielwert via `_registriere_erfolgreiche_soc_aktionen()` registriert werden, sonst falsch-positive Extern-Erkennung.

## No-Gos
- **Keine Software-Ratenlimits an die Batterie** (GEN24 DC-DC = 22 A HW-Limit). Entfernt 2026-03-07: `RegelSocSchutz`, `RegelTempSchutz`, `RegelAbendEntladerate`, `RegelLaderateDynamisch`, Modbus-`InWRte`/`OutWRte`-Manipulation.
- Keine direkten Hardware-Calls außerhalb der Aktor-Klassen.
- Keine Regeländerung ohne Score-/Aktor-Cascade-Berücksichtigung (sonst Doppelschaltungen).

## Häufige Aufgaben
- Neue Regel hinzufügen → Regel-Modul unter `automation/engine/regeln/` anlegen (Subklasse `Regel`, `bewerte()` + ggf. `erzeuge_aktionen()`), dann Eintrag in `config/engine_registry.json` → `regeln[]` (`name`, `klasse`, `aktiv`) **an der gewünschten Reihenfolge-Position**. Die Engine lädt die Regeln daraus (`registry.py:lade_regeln`); `DEFAULT_REGELN_SPEC` in `registry.py` ist der Code-Fallback und muss synchron gehalten werden.
- Regel/Aktor abschalten ohne Code → `"aktiv": false` im Registry-Eintrag.
- Auswertungsreihenfolge ändern → Reihenfolge in `config/engine_registry.json` → `regeln[]` ändern (= Reihenfolge bei Score-Gleichstand).
- Tick-Intervall ändern → `automation/engine/automation_daemon.py:AutomationDaemon.run` (Konstanten OBS_COLLECT/FAST/STRATEGIC).
- Score-Logik einer Regel debuggen → `automation/engine/engine.py:Engine.zyklus` (Logging) + Regel-Klasse `bewerte()`.
- Operator-Override verarbeiten → `automation/engine/operator_overrides.py:OperatorOverrideProcessor.process_pending`.
- Aktiven Tages-Intent lesen → `automation/engine/operator_intents.py:read_active_afternoon_charge_intent`.

## Bekannte Fallstricke
- 17 Regeln registriert (Stand 2026-06). Reihenfolge in `config/engine_registry.json` = Auswertungsreihenfolge bei Score-Gleichstand. Fehlt/defekt die Registry-JSON, fällt `registry.py` sicher auf `DEFAULT_REGELN_SPEC`/`DEFAULT_AKTOREN_SPEC` zurück (Produktion läuft unverändert) — eine kaputte JSON darf nie Schutz-Regeln still verschlucken.
- `engine_vorausschau()` (Web-API, ohne Daemon) nutzt **dieselbe** `lade_regeln()`-Registry wie die Live-Engine (Single-Source, kein Drift mehr).
- **FBH-Nachtschaltung** (`RegelFussbodenheizungNacht`, `geraete.py`): rein zeitbasierte, flankengetriggerte Schaltung der Fußbodenheizungs-Steckdose (Fritz!DECT) — genau 1× `fbh_ein` zu `fenster_start_h` und 1× `fbh_aus` im Nachlauf nach `fenster_ende_h`, je Kalendertag. Once-pro-Tag-Sperre über `_absenkung_done['fbh_ein'/'fbh_aus']` (erst nach Aktor-Erfolg via `meta_absenkung_tag`). Läuft im Schutz-Pass (Whitelist in `_ist_schutz`), kein Nachstellen → oszillationssicher und konfliktarm zur HomeAssistant-Heizung. Matrix: `regelkreise.fussbodenheizung`. Gedacht als Sommer-Regelmäßigkeit (HA-Automation dann aus); im Winter `aktiv:false` setzen, da HA die FBH verwaltet.
- ExternalRespect-Hold (HP/WP, 30 min) wird per `extern_respekt_s` in der Matrix gesteuert — siehe `automation-regel-heizpatrone.card.md` und `automation-regel-wattpilot.card.md`.
- `automation_log` ist die einzige aktive Persistenz-Tabelle für Aktor-Resultate. **`battery_control_log` wird nicht mehr geschrieben**; der frühere Lese-Fallback in `pv-config.py`/`routes/system/` wurde 2026-05-29 entfernt.
- Tier-1-Bypass: Schutz-Aktoren laufen weiter, auch wenn Engine pausiert. Wer einen neuen Schutz-Pfad einbaut, muss Tier-1-kompatibel sein.

## Verwandte Cards
- [`automation-battery-algorithm.card.md`](./automation-battery-algorithm.card.md) — SOC-Modus-Schreibpfad
- [`automation-steuerungsphilosophie.card.md`](./automation-steuerungsphilosophie.card.md) — Prioritäten + ExternalRespect
- [`automation-schutzregeln.card.md`](./automation-schutzregeln.card.md) — Tier-1, SLS, No-Op-Schutz
- [`automation-state.card.md`](./automation-state.card.md) — ObsState, RAM-DB, Persist-DB

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/automation/PV_CONFIG_HANDBUCH.md`
