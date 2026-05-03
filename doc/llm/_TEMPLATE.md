---
title: <Modul-/Konzept-Name>
domain: automation | collector | diagnos | steuerbox | netzqualitaet | system | web | meta
role: A | B | C | D | E | meta
applyTo: ""        # optional: Glob für VS-Code-Instruction-Scoping, z. B. "automation/engine/**"
tags: []
status: stable     # stable | experimental | deprecated
last_review: YYYY-MM-DD
---

# <Titel>

## Zweck
1–3 Sätze. Was tut dieses Modul/Konzept aus Sicht eines Agenten, der eine Aufgabe darin lösen will?

## Code-Anchor
- **Hauptdatei:** `path/to/file.py:Symbol`
- **Zugehörige DBs/Tables:** `…`
- **Zugehörige Configs:** `config/…json`
- **systemd-Units (falls relevant):** `…`

## Inputs / Outputs
- **Inputs:** woher kommen Daten (DB-Tabellen, API-Calls, Configs, ObsState-Felder)
- **Outputs:** wohin gehen sie (DB-Schreibzugriff, HTTP-Calls, Logs, …)

## Invarianten
Was MUSS bei jeder Änderung gelten?
- …
- …

## No-Gos
Was darf NIEMALS passieren?
- …

## Häufige Aufgaben
3–6 Stichpunkte mit Code-Anchor, jede Zeile so spezifisch dass ein Agent sofort die richtige Stelle findet.
- Aufgabe X → `path/file.py:Funktion` (Hinweis: …)
- …

## Bekannte Fallstricke
Konkrete Stolperfallen, in die LLMs typischerweise treten.
- …

## Verwandte Cards
- [`<andere-card>.card.md`](./andere-card.card.md) — Stichwort warum verwandt

## Human-Doku
Verweis auf die ausführliche Manuelle / Architektur-Dokumentation für Hintergründe und Designentscheidungen:
- `doc/<bereich>/<datei>.md`

---

**Hinweise zum Schema:**
- Card max. 150 Zeilen. Wenn länger → in zwei Cards splitten.
- `last_review` bei jeder Änderung aktualisieren (Pre-commit-Hook prüft das).
- Wenn `status: deprecated`, bleibt die Card erhalten (LLM-Lenkung „nicht mehr verwenden"), aber INDEX markiert sie.
