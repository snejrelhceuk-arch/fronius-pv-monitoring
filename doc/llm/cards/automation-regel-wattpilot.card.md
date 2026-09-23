---
title: Regel Wattpilot (SOC-Schutz, WS-Kommandos, rbt-Reset)
domain: automation
role: C
applyTo: "automation/engine/aktoren/aktor_wattpilot.py"
tags: [wattpilot, ev-lader, websocket, soc-schutz]
status: stable
last_review: 2026-09-23
---

# Regel Wattpilot

## Zweck
Schützt die Hausbatterie vor EV-Ladung via Wattpilot (Fronius/go-e Wallbox). Hebt `soc_min` an, wenn EV-Last die Batterie unter den Sollwert ziehen würde. Kommandos via WebSocket (`wattpilot_api.py`).

## Code-Anchor
- **Schutzregel:** `automation/engine/regeln/geraete.py:RegelWattpilotBattSchutz.bewerte` (~L75) und `.erzeuge_aktionen` (~L160)
- **Aktor:** `automation/engine/aktoren/aktor_wattpilot.py:AktorWattpilot.ausfuehren` (Schreibpfad) + `AktorWattpilot.verifiziere` (Read-Back inkl. externer Pause-Erkennung)
- **API-Client:** `wattpilot_api.py:WattpilotClient` (WebSocket `setValue`)
- **Collector (lesend, nicht steuernd):** `collector/wattpilot.py`
- **Matrix:** `config/soc_param_matrix.json` Regelkreis `wattpilot_battschutz`

## Inputs / Outputs
- **Inputs:** ObsState (`SOC_Batt`, EV-Ladeleistung, Sunset-Zeit), Matrix (`puffer`, Aktiv-Zeitfenster), Operator-Overrides.
- **Outputs:** WS-Kommandos `set_max_current` (6–32 A), `pause`, `resume`, `reduce_current`. Ggf. SOC-Min-Anhebung über `aktor_batterie`.

## Invarianten
- Trigger 1: `SOC ≤ SOC_MIN + puffer` während Ladung → `soc_min` auf 20 % (`soc_min_netz`; Netzbezug erzwungen, Batterie wird nicht weiter entladen).
- Trigger 2: Letzte 2 h vor Sunset + `SOC < 20 %` → `soc_min = 20 %`.
- `verifiziere()` erkennt beim Read-Back eine *externe* Pause (`frc=1` ohne Engine-Pause-Kommando, z. B. HA/App/Taster) und meldet sie als `extern_pausiert` — nutzt den ohnehin nötigen Status-Read, kein Zusatz-Polling.
- Auth-Hash wird pro Session aus `authRequired.hash` abgeleitet (`bcrypt` für Flex, sonst `pbkdf2`) und gilt für Read + `setValue`.
- SLS-Schutz (Hauptsicherung 35 A) hat Vorrang: `RegelSlsSchutz` ruft `reduce_current` ohne Matrix-Pfad.
- WS-Sessions konkurrieren mit Fronius- und go-e-App; Aktor toleriert Verdrängung mit Retry (max 3).

## No-Gos
- **Kein automatischer `rbt`-Reset (Wattpilot-Reboot)** ohne explizite Freigabe — sensibler Recovery-Pfad (`reminders.md`, 2026-04-06: noch ungeprüft).
- Keine Strom-Reduktion unter 6 A (Mindestladestrom).
- Keine direkte Modifikation des `frc`-Modus (force charge) ohne Operator-Override.

## Häufige Aufgaben
- SOC-Schutz-Schwelle ändern → Matrix `wattpilot_battschutz.soc_min_puffer_pct` (Default abhängig von Setup).
- Ladestrom-Override (Operator) → Steuerbox-Intent `set_max_current` mit `respekt_s`.
- WS-Verbindungsabriss debuggen → `wattpilot_api.py:WattpilotClient` + `aktor_wattpilot.py:_get_client`.

## Bekannte Fallstricke
- WS-Konflikt mit Fronius/go-e App: bis zu 3 Retries, danach Cooldown — schwer reproduzierbar bei mehreren parallelen Clients.
- `eto`-Counter (Gesamt-Wh) ist Quelle für `wattpilot_daily.energy_wh` — Aktor verändert ihn nicht, aber Reset/Tausch der Hardware kann Sprünge erzeugen (siehe `collector-wattpilot-collector.card.md`).
- Bezeichnung: **Wattpilot ≠ WP**. WP=Wärmepumpe (Stiebel Eltron), Wattpilot=Wallbox (Fronius/go-e). Felder z. T. doppelt benannt.

## Verwandte Cards
- [`automation-battery-algorithm.card.md`](./automation-battery-algorithm.card.md) — SOC-Min-Anhebung
- [`automation-schutzregeln.card.md`](./automation-schutzregeln.card.md) — SLS-Vorrang
- [`collector-wattpilot-collector.card.md`](./collector-wattpilot-collector.card.md) — Lesepfad, `eto`/`session_wh`

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
