---
title: Regel Heizpatrone (Phasen, Hysterese, ExternalRespect)
domain: automation
role: C
applyTo: "automation/engine/regeln/geraete.py"
tags: [heizpatrone, fritzdect, ww-speicher, prognose]
status: stable
last_review: 2026-05-29
---

# Regel Heizpatrone

## Zweck
Schaltet die Heizpatrone (im WW-Speicher, FritzDECT-Steckdose) abhängig von PV-Prognose, SOC, WW-Temperatur und Tageszeit. 6 Phasen (0, 1, 1b, 2, 3, 4) decken Tagesverlauf ab.

Zusätzlich pausiert die Regel bei aktivem `afternoon_charge_request` den HP-Betrieb bis das Ziel-SOC erreicht ist (oder Hold endet), damit die Batterie priorisiert aufgeladen werden kann.

## Code-Anchor
- **Regel:** `automation/engine/regeln/geraete.py:RegelHeizpatrone.bewerte` (~L280)
- **Override-Annullation:** `automation/engine/regeln/geraete.py:RegelHeizpatrone._cancel_conflicting_overrides`
- **WP-Koordinations-Cap:** `automation/engine/regeln/geraete.py:RegelHeizpatrone._dynamic_temp_max_c`
- **Aktor:** `automation/engine/aktoren/aktor_fritzdect.py:AktorFritzDECT.ausfuehren` (Kommando `hp_ein`/`hp_aus`)
- **Matrix:** `config/soc_param_matrix.json` Regelkreis `heizpatrone`
- **AIN-Mapping:** `config/fritz_config.json`
- **Referenz:** `config/heizpatrone_fritz_reference.json`

## Inputs / Outputs
- **Inputs:** ObsState (`P_PV`, `P_Netz`, `SOC_Batt`, `WW_Temp`), Forecast (Tages-kWh), Matrix-Parameter (`extern_respekt_s`, Phasenschwellen), Operator-Overrides.
- **Outputs:** FritzDECT-Schaltbefehl `hp_ein`/`hp_aus`, Engine-Zielwert für ExternalRespect-Tracker.

## Invarianten
- **Grundprinzip:** Die Heizpatrone ist ein Verbraucher für PV-Überschuss. Sie darf grundsätzlich **keinen Netzbezug verursachen**. Toleriert sind ausschließlich kurze Schaltverluste durch Lastwechsel/Erzeugungsschwankungen (Wattpilot-Start, Wolkenfront, Backofen), bis die Wechselrichter sich angepasst haben.
- Prognose-Klassifikation: `<40 kWh = schlecht`, `40–100 = mittel`, `≥100 = gut` → bestimmt Freigabegrad pro Phase.
- AUS-Schwellen (immer aktiv): `WW_Temp ≥ 78 °C` (Hart), `SOC ≤ stop_entladung_unter` (5 %), `SOC ≤ extern_aus_soc_pct` (15 %, nur bei Extern-EIN), Netzbezug-Energie-Integral, `PV<1500 W` in PV-only-Phasen.
- **WP-Koordinations-Cap (`_dynamic_temp_max_c`, seit 2026-05-28):** kontextabhängige Verschaerfung der WW-Temp-Schwelle, damit der Dimplex-WP-Lauf möglich bleibt und der mechanische Thermostat (~72 °C) nicht hart abwirft.
  - `now_h < drain_fenster_ende_h` (Morgens) → Cap = `drain_aus_ww_temp_c` (Default 55 °C, Bereich 50–65).
  - `<= abend_ww_cap_aktiv_vor_sunset_h` vor Sunset → Cap = `abend_ww_temp_c` (Default 65 °C, Bereich 60–70).
  - Sonst → Hart-Cap `speicher_temp_max_c` (78 °C).
  Wirkt **sowohl AUS-Pfad als auch EIN-Pfad**; Phasen-Reihenfolge, Score, Forecast-Bedingungen, Netzbezug-Integral, ExternalRespect bleiben unberührt.
- **Netzbezug-AUS (`_netzbezug_aus_ausloesen`, seit 2026-05-16, Vorfall »3 h Netzbezug im Drain«):** Energie-Integral-Verfahren
  1. **Veto:** Aktueller Bezug `< aus_netzbezug_aktuell_veto_w` (200 W) → keine Auswertung (Historie evtl. veraltet, kein akuter Bezug).
  2. **Messung:** Σ der positiven `grid_power_w`-Samples der letzten `aus_netzbezug_fenster_min` (5) Engine-Ticks (≈ 60 s/Tick) als Energie (kWh = Σ_W / 60000).
  3. **Auslöser:** Energie ≥ `aus_netzbezug_energie_kwh` (0.1 kWh ≡ Ø 1200 W über 5 Min) → HP AUS. Schaltspitzen (z. B. einmal 3 kW für 30 s) bleiben darunter. Wert erhöht 2026-05-25 (vorher 0.02 kWh).
  Es gibt **keine Vetos durch Forecast-Rest, Winter-Schutz oder Transient-Fenster mehr**. Winter-Tiefentladung wird über das **dynamische SOC_MIN-Sliding (5–25 %)** in `RegelSocSteuerung` und die HART-Schwellen `stop_entladung_unter`/`extern_aus_soc_pct` abgesichert, nicht durch toleriertes HP-Netzbezug.
- Begriff **„Notaus"** ist reserviert für menschen-/spannungsbezogene Schutzkontexte (BYD-BMS, Tier-1-Alarm). Im HP-Kontext heißt es **„AUS"** (`aus_grund`, `_netzbezug_aus_ausloesen`, `extern_aus_soc_pct`, AUS-Pfad, AUS-Kriterienwerk).
- Externe Schaltung erkannt → `_cancel_conflicting_overrides()` annulliert offene Operator-Overrides + setzt 30-min-Respekt-Hold (`extern_respekt_s`).
- Schreibbestätigung: Aktor muss Engine-Wert registrieren, sonst falsch-positive Extern-Erkennung.
- Bei aktivem Nachmittags-Ladewunsch (`afternoon_charge_request` + `pause_hp_until_target=true`) schaltet die Engine HP AUS **nur wenn** `0 < batt_power_w < 8000 W` (Batterie laedt mit schwacher Leistung). Bei fehlender Ladung (Batterie idle/entlaedt) oder starker Ladung (>=8 kW) bleibt HP freigegeben.

## No-Gos
- Keine HP-Einschaltung bei Tier-1-Alarm.
- Keine HP-Einschaltung bei Operator-Override `hp_aus` ohne Respekt-Ablauf.
- Keine Hartcodierung von Schwellen — alles in Matrix.

## Häufige Aufgaben
- Phasenschwelle ändern → Matrix `heizpatrone.<phase>.<param>` (z. B. `phase2.soc_min_freigabe`).
- ExternalRespect-Dauer ändern → Matrix `heizpatrone.extern_respekt_s` (Default 1800).
- WP-Koordinations-Cap justieren → Matrix `heizpatrone.drain_aus_ww_temp_c` (Morgens, 50–65), `heizpatrone.abend_ww_temp_c` (Abends, 60–70), `heizpatrone.abend_ww_cap_aktiv_vor_sunset_h` (1–8 h).
- Neue Phase einbauen → `RegelHeizpatrone.bewerte` + Score-Logik + Matrix-Schema dokumentieren.
- HP-Startup-Check (Daemon-Restart schaltet HP AUS) → `automation/engine/automation_daemon.py:_hp_startup_check`.
- Ladewunsch-Pause anpassen → `RegelHeizpatrone.bewerte` und `RegelHeizpatrone.erzeuge_aktionen` (Intent-Lesepfad: `automation/engine/operator_intents.py`).

## Bekannte Fallstricke
- **Stale-Grid-History (2026-05-24):** `_grid_history` wird nur gepflegt wenn HP ON ist. Nach einer OFF-Pause (z.B. 10–30 Min) enthält der Deque noch hohe Bezugswerte aus dem vorherigen EIN-Zeitraum. Phase 1b schaltet HP EIN, Netzbezug-Integral feuert sofort auf Basis der alten Werte — Probe läuft nie durch. **Fix:** `_grid_history.clear()` am Anfang jedes neuen Bursts (beide Stellen in `erzeuge_aktionen`). Die `len < fenster_min`-Guard verhindert dann frühzeitiges Feuern.
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
