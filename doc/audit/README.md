# Audit DEEP-2026-05-29 — PV-System

**Datum:** 2026-05-29
**Umfang:** Tiefes Audit aller Rollen (A–E) + Netzqualität + System/Ops, inkl. Konsistenzprüfung der dualen Doku (LLM-Cards vs. Human-Docs) und der zentralen `doc/TODO.md`.
**Methode:** Pro Domäne Code- und Doku-Abgleich; kritische Befunde manuell gegen den Quellcode verifiziert (mehrere automatische Vorbefunde waren falsch und wurden verworfen — s. „Verworfene Vorbefunde").

## Berichte je Bereich

### 2026-06-30 — Tiefpruefung Betrieb/LLM/Steuerbox

- [deep-2026-06-30.md](deep-2026-06-30.md) — Tiefpruefung LLM-Doku, Collector, Automation, Diagnos/Steuerbox, Web-Monitoring und Pi-/OS-Betrieb; kritische Steuerbox-/Monitor-/Backup-Befunde im Lauf behoben.

### 2026-05-29 — Rollen-/Doku-Audit

| Bereich | Rolle | Bericht |
|---|---|---|
| Automation | C | [automation.md](automation.md) |
| Collector | A | [collector.md](collector.md) |
| Web/Routes | B | [web.md](web.md) |
| Diagnos | D | [diagnos.md](diagnos.md) |
| Steuerbox | E | [steuerbox.md](steuerbox.md) |
| Netzqualität | — | [netzqualitaet.md](netzqualitaet.md) |
| System / Ops | — | [system-ops.md](system-ops.md) |

## Severity-Legende

- **HOCH** — funktional/sicherheitsrelevant oder irreführende Doku, sollte zeitnah behoben werden.
- **MITTEL** — Drift/Tech-Debt mit begrenztem Risiko.
- **NIEDRIG** — kosmetisch, Aufräumen.
- **INFO** — bestätigt korrekt / bewusste Designentscheidung.

## Im Audit bereits behobene Inkonsistenzen (Doku + TODO)

Diese wurden im selben Lauf direkt korrigiert (reine Doku-/TODO-Änderungen, kein Code):

- [AGENTS.md](../../AGENTS.md) — Pi4-Primary UFW „noch nicht aktiviert (TODO)" → „aktiv (seit 2026-05-03)".
- [doc/collector/DB_SCHEMA.md](../collector/DB_SCHEMA.md) — `battery_control_log`-Zeile als Legacy klargestellt (nicht von `db_init.py`/SQL angelegt, seit 2026-03 nicht beschrieben, nur Lese-Fallback).
- [doc/llm/cards/collector-db-schema.card.md](../llm/cards/collector-db-schema.card.md) — Invariante korrigiert: `db_init.py` **prüft** `REQUIRED_TABLES`, **legt Kern-Tabellen nicht an** (Anlage via SQL-Schema); `last_review` auf 2026-05-29.
- [ollama/system_prompt_kern.md](../../ollama/system_prompt_kern.md) — nicht-existente `battery_control_log(90d)`-Retention aus dem Prompt entfernt.
- [doc/steuerbox/ARCHITEKTUR.md](../steuerbox/ARCHITEKTUR.md) — Port `8001` → `11933`; veraltete Endpunkt-Tabelle (Endpunkt-pro-Aktion) durch den real implementierten Single-Intent-Endpunkt ersetzt.
- [doc/steuerbox/SICHERHEIT.md](../steuerbox/SICHERHEIT.md) — UFW-Beispiele + Port-Beschreibung `8001` → `11933`.
- [doc/steuerbox/LLM_AUSFUEHRUNG.md](../steuerbox/LLM_AUSFUEHRUNG.md) — Port-Hinweis auf Produktion `11933` (konfigurierbar via `PV_STEUERBOX_PORT`).
- [doc/automation/AUTOMATION_ARCHITEKTUR.md](../automation/AUTOMATION_ARCHITEKTUR.md) — Rollen-Label `A/B/C/D` → `A/B/C/D/E`.
- [doc/TODO.md](../TODO.md) — erledigten K-02-Teil („9 fehlende Regeln") korrigiert (Vorausschau vollständig); Steuerbox-`pause_hp_until_target`-Default-Drift als neues Item aufgenommen; Stand-Datum aktualisiert.

## Verworfene Vorbefunde (automatisch erhoben, manuell widerlegt)

- **Heizpatrone-Mathematik in Card falsch** — FALSCH. Matrixwert `aus_netzbezug_energie_kwh = 0.1` (≡ 1200 W über die Fensterlogik) ist korrekt; Card stimmt.
- **NQ `role: B` ist CRITICAL** — kein besserer Enum-Wert vorhanden (Pre-commit erlaubt A/B/C/D/E/meta), die NQ-Web-API ist tatsächlich read-only B. Belassen, nur im Bericht vermerkt.
- **`db_init.py` legt Kern-Tabellen nicht an = kaputt** — teils wahr: `db_init.py` legt sie wirklich nicht an, aber das ist korrekt (Anlage via SQL-Schema). Konsequenz war nur eine Card-Korrektur, kein Code-Defekt.

## Offene Code-Aufgaben aus diesem Audit

Alle als Code zu behebenden Punkte stehen ausschließlich in [doc/TODO.md](../TODO.md) (kein TODO in Subdirectories). Dieses Audit hat **keinen Code** geändert.
