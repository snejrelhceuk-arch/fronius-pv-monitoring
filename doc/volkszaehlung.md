# Volkszählung — PV-System Workspace

> Stand: 2026-07-25

## Übersicht

**Gesamtgröße:** 925 MB  
**Gesamtzeilen (Code/Doku):** 259.996 Zeilen  
**Ausgeschlossene Verzeichnisse:** 268 (.venv, __pycache__, node_modules)

## Nach Sprache/Typ

| Sprache/Typ | Dateien | Zeilen | Anteil | Bemerkung |
|---|---|---|---|---|
| **Python** | 174 | 53.735 | 20,7% | Hauptsprache — Automation, Collector, Web-API |
| **Markdown** | 156 | 26.138 | 10,1% | Dokumentation (LLM-Cards, Manuals, Systemdoku) |
| **CSV** | 29 | 151.024 | 58,1% | Daten (Import-Dateien, Logs, Statistiken) |
| **HTML** | 19 | 14.501 | 5,6% | Templates (Jinja2), Dashboard |
| **Shell** | 54 | 4.242 | 1,6% | OLLI-Scripts, Systemd, Deployment |
| **JSON** | 20 | 4.002 | 1,5% | Konfiguration, State-Persistenz |
| **TXT** | 28 | 2.360 | 0,9% | Logs, Notizen, Requirements |
| **SQL** | 10 | 1.377 | 0,5% | DB-Schema, Migrationen, Queries |
| **JavaScript** | 4 | 900 | 0,3% | Frontend (minimal) |
| **CSS** | 4 | 1.104 | 0,4% | Styling |
| **YAML** | 3 | 559 | 0,2% | HA-Testcases, Konfiguration |
| **TOML** | 1 | 54 | <0,1% | pyproject.toml |
| **CONF** | 1 | — | — | Nginx-Konfiguration |

**Total:** 503 Dateien, 259.996 Zeilen

## Python-Code nach ABCDEN-Rollen

| Rolle | Verzeichnis | Dateien | Top-Datei (Zeilen) |
|---|---|---|---|
| **C** Automation | `automation/` | 41 | `engine/regeln/geraete.py` (2.299) |
| **N** Netzqualität | `nq/` | 25 | — |
| **B** Web-API | `routes/` | 19 | `verbraucher.py` (1.027) |
| **A** Collector | `collector/` | 18 | — |
| **E** Steuerbox | `steuerbox/` | 5 | — |
| **D** Diagnos | `diagnos/` | 5 | — |
| *Legacy* | `netzqualitaet/` | 4 | (wird nach `nq/` migriert) |

**Top 10 Python-Dateien (nach Zeilen):**

1. `automation/engine/regeln/geraete.py` — 2.299 Zeilen
2. `solar_geometry.py` — 1.979 Zeilen
3. `pv-config.py` — 1.311 Zeilen
4. `solar_forecast.py` — 1.142 Zeilen
5. `automation/engine/regeln/waermepumpe.py` — 1.131 Zeilen
6. `automation/engine/event_notifier.py` — 1.045 Zeilen
7. `automation/engine/regeln/soc_steuerung.py` — 1.036 Zeilen
8. `routes/verbraucher.py` — 1.027 Zeilen
9. `routes/pac4200.py` — 951 Zeilen

## Dokumentation (Markdown)

**156 Dateien, 26.138 Zeilen**

Hauptbereiche:
- `doc/llm/` — LLM-Cards (Domain-Knowledge für Agenten)
- `doc/automation/` — Automation-Engine-Doku
- `doc/system/` — System-Architektur, Deployment
- `doc/collector/` — Datenerfassung (Modbus, SunSpec)
- `doc/netzqualitaet/` — PAC4200, Netzanalyse
- `doc/web/` — Web-API-Doku
- `doc/dev_prompt/` — Entwickler-Prompts (historisch)

Zentrale Dokumente:
- `AGENTS.md` — Pflicht-Einstieg für alle LLM-Agenten
- `README.md` — Projekt-Übersicht
- `CHANGELOG.md` — Versions-Historie
- `doc/TODO.md` — Offene Aufgaben (zentral)

## CSV-Dateien (Daten)

**29 Dateien, 151.024 Zeilen**

Hauptquellen:
- `imports/solarweb/` — Fronius-Solar.web-Export (historisch)
- `doc/csv/` — Auswertungen, Statistiken
- `logs/` — Schaltzähler, WP-Leistungsprotokolle

## Besonderheiten

- **OLLI-Scripts:** 54 Shell-Scripts für CLI-Abfragen und Reports (`OLLI/`)
- **Ollama-Integration:** Lokales LLM-Setup (`ollama/`)
- **Nginx-Konfiguration:** `config/nginx/` — Reverse-Proxy
- **Systemd-Units:** `config/systemd/` — Service-Definitionen
- **Pre-commit-Hook:** `tools/pre_commit_doc_check.py` — Card-Drift-Check

## Code-Qualität & Struktur

- Rollentrennung (ABCDEN-Modell) konsequent durchgesetzt
- DRY < ABCDE-Reinheit (gewollte Duplikation für Sicherheit)
- Dokumentation eng mit Code verzahnt (LLM-Cards + Human-Manuals)
- Zentrale TODO-Verwaltung (`doc/TODO.md`)
- Drift-Detection via Cron + `tools/drift_engine.py`

## Ausgeschlossene Bereiche

- `.venv/` — Python-Virtual-Environment (268 Verzeichnisse)
- `__pycache__/` — Python-Bytecode-Cache
- `node_modules/` — (falls vorhanden)
- `*.pyc`, `*.pyo` — Kompilierte Python-Dateien

---

**Erzeugungsmethode:** `find` + `wc -l` + `awk` (2026-07-25)
