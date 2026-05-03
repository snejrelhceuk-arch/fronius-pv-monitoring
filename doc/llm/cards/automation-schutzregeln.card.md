---
title: Schutzregeln (Tier-1, SLS, No-Op-Schutz)
domain: automation
role: C
applyTo: "automation/engine/collectors/tier1_checker.py"
tags: [schutz, tier1, sls, no-op, watchdog]
status: stable
last_review: 2026-05-03
---

# Schutzregeln

## Zweck
Hartstop-Schutzschicht oberhalb der normalen Regel-Engine. Tier-1-Alarme bypassen die Regel-Auswertung, SLS-Schutz reagiert auf Hauptsicherung. No-Op-Sentinel verhindert FEHLER-Cooldowns bei wiederholtem Schreiben gleicher Werte.

## Code-Anchor
- **Tier-1:** `automation/engine/collectors/tier1_checker.py:Tier1Checker`
- **SLS:** `automation/engine/regeln/schutz.py:RegelSlsSchutz`
- **Wattpilot-Batt-Schutz:** `automation/engine/regeln/geraete.py:RegelWattpilotBattSchutz`
- **HP-Startup-Check:** `automation/engine/automation_daemon.py:_hp_startup_check`
- **No-Op-Sentinel:** `fronius_api.py:_NoOpResult`
- **Aktor-Retry:** `automation/engine/aktoren/aktor_batterie.py:_retry`

## Inputs / Outputs
- **Inputs:** ObsState (`batt_temp`, `SOC_Batt`, `I_Netz_Phase*`), Sicherungs-Stromwerte.
- **Outputs:** Tier-1-Flags (RAM-DB), direkte Aktor-Calls (Wattpilot `reduce_current`, HP `aus`).

## Invarianten
- **Tier-1 pausiert Engine.** Nur die Schutzregeln und ihre Aktoren laufen weiter.
- **SLS-Schwelle 35 A** (Hauptsicherung): bei Überschreitung sofort Wattpilot reduzieren.
- **HP-Startup-Check:** Bei jedem Daemon-Neustart wird HP/Klima per FritzDECT AUS geschaltet — verhindert Hängenbleiben in unbekanntem Zustand.
- **No-Op-Sentinel:** `BatteryConfig.write` liefert `_NoOpResult` (truthy, `.noop=True`) wenn Soll==Ist. `aktor_batterie._retry` muss truthy-checken, sonst FEHLER-Cooldown obwohl alles ok (Bug-Fix 2026-04-27).

## No-Gos
- Schutzregeln nicht durch Operator-Overrides aushebelbar machen.
- Tier-1-Bypass nicht für Komfort-/Optimierungs-Regeln nutzen.
- `rbt`-Reset (Wattpilot-Reboot) nicht ohne Freigabe — siehe `automation-regel-wattpilot.card.md`.

## Häufige Aufgaben
- Neue Tier-1-Bedingung → `tier1_checker.py:Tier1Checker` (z. B. zusätzlicher Temperatursensor).
- SLS-Schwelle anpassen → `schutz.py:RegelSlsSchutz` (aktuell hartcodiert; ggf. in Matrix migrieren — Tech-Debt).
- No-Op-Verhalten testen → gleichen Wert zweimal schreiben, im `automation_log` darf kein FEHLER auftauchen.

## Bekannte Fallstricke
- SLS-Schutz nutzt direkte Aktor-Calls (kein Score-Pfad), Reihenfolge im Engine-Zyklus muss diesen Pfad zuerst durchlaufen.
- Tier-1-RAM-DB (`/dev/shm/automation_obs.db`) wird bei System-Reboot gelöscht — Tier-1 startet "sauber".
- No-Op-Sentinel: `aktor_batterie._retry` prüft truthy (`if result is True or (result is not None and result)`) — explizite `.noop`-Auswertung fehlt; bei Erweiterungen darauf achten.
- Fronius-Write-No-Op-Bug: Vor dem Fix lieferte `write()` `None` bei Soll==Ist → ständige FEHLER-Cooldowns (`fronius-write-noop-bug-note`).

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-battery-algorithm.card.md`](./automation-battery-algorithm.card.md) — `_NoOpResult`
- [`automation-regel-wattpilot.card.md`](./automation-regel-wattpilot.card.md)
- [`diagnos-health.card.md`](./diagnos-health.card.md)

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/diagnos/` (Phase 1+2 Doku)
