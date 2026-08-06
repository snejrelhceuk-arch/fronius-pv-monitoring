# FILE STATISTICS SUMMARY

Stand: 2026-05-16 16:00 CEST

## Scope (was ist enthalten)

Enthalten sind nur Dateien, die fuer den Betrieb/Codebestand relevant sind, inklusive Doku unter `doc/`.

Ausgeschlossen sind explizit:
- `backup/`
- Datenbanken (`*.db`, `*.db-*`) und Backup-Archive (`*.gz`)
- Laufzeit-/Build-Artefakte (`*.pyc`, `*.pid`)
- `logs/`, `reports/`, `tmp/`, `__pycache__/`, `.ruff_cache/`, `.state/`, `nq/legacy/db/`
- `.git/`, `.venv/`

## Schnellueberblick

| Bereich | Dateien | Zeilen | Zeichen | Bytes |
| --- | ---: | ---: | ---: | ---: |
| Code | 183 | 61,074 | 2,416,747 | 2,472,665 |
| Doku | 92 | 15,613 | 660,211 | 686,845 |
| Konfiguration | 42 | 4,159 | 118,629 | 121,087 |
| Sonstiges | 31 | 2,109 | 122,582 | 140,310 |
| **Gesamt** | **348** | **82,955** | **3,318,169** | **3,420,907** |

## Code vs. Doku

- Codezeilen: **61,074**
- Dokuzeilen: **15,613**
- Verhaeltnis Code:Doku: **3.91 : 1**

## Module (nach Zeilen, absteigend)

| Modul | Dateien | Zeilen | Zeichen | Bytes |
| --- | ---: | ---: | ---: | ---: |
| doc | 87 | 14,787 | 616,218 | 638,482 |
| automation | 36 | 13,792 | 566,964 | 584,039 |
| templates | 13 | 11,761 | 544,601 | 553,507 |
| ROOT | 25 | 9,415 | 353,847 | 367,218 |
| routes | 11 | 7,511 | 292,614 | 294,543 |
| scripts | 49 | 5,266 | 168,350 | 172,047 |
| collector | 18 | 4,380 | 193,043 | 193,993 |
| tools | 19 | 4,280 | 176,919 | 181,904 |
| config | 31 | 3,892 | 110,482 | 112,927 |
| steuerbox | 10 | 2,001 | 62,692 | 62,750 |
| netzqualitaet | 4 | 1,458 | 52,965 | 53,081 |
| ollama | 7 | 1,261 | 52,907 | 59,819 |
| diagnos | 4 | 1,141 | 41,191 | 42,868 |
| static | 9 | 1,101 | 46,203 | 61,638 |
| OLLI | 9 | 417 | 13,151 | 15,968 |
| .github | 5 | 220 | 11,442 | 11,532 |
| imports | 8 | 177 | 11,893 | 11,904 |
| .vscode | 3 | 95 | 2,687 | 2,687 |

## Dateitypen (fuer schnellen Ueberblick)

### Code-Dateien

| Typ | Dateien | Zeilen |
| --- | ---: | ---: |
| .py | 117 | 43,998 |
| .html | 15 | 12,216 |
| .sh | 42 | 3,388 |
| .css | 3 | 896 |
| .js | 2 | 381 |
| .bat | 4 | 195 |

### Doku-Dateien

| Typ | Dateien | Zeilen |
| --- | ---: | ---: |
| .md | 92 | 15,613 |

### Konfigurationsdateien

| Typ | Dateien | Zeilen |
| --- | ---: | ---: |
| .json | 19 | 3,655 |
| .service | 7 | 125 |
| .timer | 1 | 10 |
| .toml | 1 | 23 |
| .yml | 1 | 23 |
| .crt/.key/.p12/.srl | 8 | 206 |
| .local/.example/.role/.secrets/.publish-guard | 5 | 117 |

## Groesste Einzeldateien (Top 15 nach Bytes)

| Datei | Kategorie | Zeilen | Bytes |
| --- | --- | ---: | ---: |
| templates/tag_view.html | Code | 2,633 | 118,808 |
| templates/analyse_primaerenergie_view.html | Code | 2,035 | 112,185 |
| automation/engine/regeln/geraete.py | Code | 2,116 | 107,636 |
| templates/flow_view.html | Code | 2,073 | 99,692 |
| routes/system.py | Code | 1,971 | 82,338 |
| solar_geometry.py | Code | 1,979 | 77,798 |
| pv-config.py | Code | 2,145 | 77,036 |
| doc/automation/PV_CONFIG_HANDBUCH.md | Doku | 918 | 60,572 |
| config/soc_param_matrix.json | Konfiguration | 1,709 | 58,202 |
| solar_forecast.py | Code | 1,368 | 54,678 |
| automation/engine/regeln/waermepumpe.py | Code | 1,176 | 50,108 |
| automation/engine/regeln/soc_steuerung.py | Code | 1,010 | 45,796 |
| automation/engine/event_notifier.py | Code | 1,126 | 45,573 |
| doc/automation/AUTOMATION_ARCHITEKTUR.md | Doku | 805 | 39,593 |
| templates/netzqualitaet_view.html | Code | 862 | 37,526 |

## Kurzfazit

- Dein repo-relevanter Bestand (ohne DB/Backups) hat **82,955 Zeilen**.
- Davon sind **61,074 Codezeilen** und **15,613 Dokuzeilen**.
- Die meiste Struktur-/Textmasse liegt in `doc/`, die meiste Code-Masse in `automation`, `templates`, `routes` und ROOT-Python-Dateien.
