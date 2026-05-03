---
title: Regel Heizpatrone (Phasen, Hysterese, ExternalRespect)
domain: automation
role: C
applyTo: "automation/engine/regeln/geraete.py"
tags: [heizpatrone, fritzdect, ww-speicher, prognose]
status: stable
last_review: 2026-05-03
---

# Regel Heizpatrone

## Zweck
Schaltet die Heizpatrone (im WW-Speicher, FritzDECT-Steckdose) abhängig von PV-Prognose, SOC, WW-Temperatur und Tageszeit. 6 Phasen (0, 1, 1b, 2, 3, 4) decken Tagesverlauf ab.

## Code-Anchor
- **Regel:** `automation/engine/regeln/geraete.py:RegelHeizpatrone.bewerte` (~L280)
- **Override-Annullation:** `automation/engine/regeln/geraete.py:RegelHeizpatrone._cancel_conflicting_overrides`
- **Aktor:** `automation/engine/aktoren/aktor_fritzdect.py:AktorFritzDECT.ausfuehren` (Kommando `hp_ein`/`hp_aus`)
- **Matrix:** `config/soc_param_matrix.json` Regelkreis `heizpatrone`
- **AIN-Mapping:** `config/fritz_config.json`
- **Referenz:** `config/heizpatrone_fritz_reference.json`

## Inputs / Outputs
- **Inputs:** ObsState (`P_PV`, `P_Netz`, `SOC_Batt`, `WW_Temp`), Forecast (Tages-kWh), Matrix-Parameter (`extern_respekt_s`, Phasenschwellen), Operator-Overrides.
- **Outputs:** FritzDECT-Schaltbefehl `hp_ein`/`hp_aus`, Engine-Zielwert für ExternalRespect-Tracker.

## Invarianten
- Prognose-Klassifikation: `<40 kWh = schlecht`, `40–100 = mittel`, `≥100 = gut` → bestimmt Freigabegrad pro Phase.
- Notaus-Schwellen (immer aktiv): `WW_Temp ≥ 78 °C`, `SOC ≤ 7 %`, Netzbezug erkennbar (`grid_avg`), `PV<1500 W` in PV-only-Phasen.
- Externe Schaltung erkannt → `_cancel_conflicting_overrides()` annulliert offene Operator-Overrides + setzt 30-min-Respekt-Hold (`extern_respekt_s`).
- Schreibbestätigung: Aktor muss Engine-Wert registrieren, sonst falsch-positive Extern-Erkennung.

## No-Gos
- Keine HP-Einschaltung bei Tier-1-Alarm.
- Keine HP-Einschaltung bei Operator-Override `hp_aus` ohne Respekt-Ablauf.
- Keine Hartcodierung von Schwellen — alles in Matrix.

## Häufige Aufgaben
- Phasenschwelle ändern → Matrix `heizpatrone.<phase>.<param>` (z. B. `phase2.soc_min_freigabe`).
- ExternalRespect-Dauer ändern → Matrix `heizpatrone.extern_respekt_s` (Default 1800).
- Neue Phase einbauen → `RegelHeizpatrone.bewerte` + Score-Logik + Matrix-Schema dokumentieren.
- HP-Startup-Check (Daemon-Restart schaltet HP AUS) → `automation/engine/automation_daemon.py:_hp_startup_check`.

## Bekannte Fallstricke
- ExternalRespect: Wenn der Aktor erfolgreich schreibt, aber die Engine den Zielwert nicht registriert, erkennt der nächste Tick eine "fremde" Änderung → Endlos-Hold (`hp-extern-respekt-hold-note`).
- FritzDECT-Session: 15 min Cache, bei Fritz!Box-Reboot kurzzeitig 401 → Aktor retry.
- AIN-Mapping aus `fritz_config.json` muss zur HW passen — Vertauschungen sind häufige Quelle stiller Fehlschaltung (`fritzdect-ain-mapping-note`).
- Heizpatronen-Nachtlast (Phase 0 Drain): noch im Aufbau (`heizpatrone-nachtlast-phase0-note`, `heizpatrone-potenzial-schwellen-note`).

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-steuerungsphilosophie.card.md`](./automation-steuerungsphilosophie.card.md) — ExternalRespect-Konzept
- [`collector-fritzdect-collector.card.md`](./collector-fritzdect-collector.card.md) — AIN-Mapping & Polling

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/automation/HP_TOGGLE_OVERRIDE_FLOW.md`
