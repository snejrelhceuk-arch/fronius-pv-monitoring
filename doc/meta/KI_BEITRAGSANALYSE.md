# KI-Beitragsanalyse (gepflegte Fassung)

Stand: 01.07.2026
Geltungsbereich: gesamtes Repository (tracked files)
Status: aktiv gepflegt

---

## 1) Zweck

Dieses Dokument ist die aktuelle Referenz fuer die Einschaetzung der
Mensch/KI-Anteile am Entwicklungs-Content. Historische Herleitung
liegt in der Git-History (frueheres `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md`,
2026-05 entfernt im Zuge der Doku-Bereinigung).

---

## 2) Aktueller Mengenstand (01.07.2026)

| Kennzahl | Wert | Δ seit 19.04 |
|---|---:|---:|
| Tracked Dateien gesamt | 371 | +125 (+50,8%) |
| Code/Config-Dateien | 224 | +54 (+31,8%) |
| Code/Config-Zeilen | 69.430 | +12.586 (+22,1%) |
| Doku-Dateien | 95 | +37 (+63,8%) |
| Doku-Zeilen | 16.315 | +6.210 (+61,4%) |

Top-Sprachen nach Zeilen:

| Sprache | Dateien | Zeilen | Δ Zeilen |
|---|---:|---:|---:|
| Python | 141 | 46.996 | +7.554 |
| Markdown | 95 | 14.446 | +4.341 |
| HTML | 15 | 12.731 | +3.172 |
| JSON | 11 | 3.354 | −247 |
| Shell | 39 | 3.303 | +1.244 |
| CSS | 4 | 1.104 | +208 |
| SQL | 8 | 974 | +5 |
| JavaScript | 4 | 894 | +622 |
| YAML | 1 | 23 | — |

**Entwicklung Q2 2026:** Signifikanter Ausbau der Dokumentations-Infrastruktur
(LLM-Cards, Index, Drift-Engine). Dokumentations-Zeilen +61%, Code +22%.

---

## 3) KI-Modellphasen (historisch, inhaltlich)

Die historische Phasenfolge bleibt unveraendert:

1. Gemini 2.0 Flash (Dez 2025)
2. Claude 3.5/4 Sonnet (Jan-Feb 2026)
3. Claude Opus 4 (ab Feb 2026)
4. Claude Sonnet 4.5 (ab Jun 2026) — primär Doku-Infrastruktur

Quelle und Detailbegruendung: Git-History (s. Hinweis in Abschnitt 1).

---

## 4) Hochgerechnete Anteile (arbeitsnahe Schaetzung)

Diese Werte sind eine gepflegte Arbeitsschaetzung auf Basis der bisherigen
Projektmethodik (Archiv-Analyse + laufende Repo-Entwicklung):

| Kategorie | Anteil | Bemerkung |
|---|---:|---|
| KI-Modelle (gesamt) am Code-Content | ~87% | +2pp durch Doku-Infrastruktur |
| Mensch am Code-Content | ~13% | Architektur, Reviews, Validierung |

Aufteilung innerhalb des KI-Anteils:

| Modellgruppe | Anteil am KI-Content | Schwerpunkt |
|---|---:|---|
| Gemini 2.0 Flash | ~4% | Initial-Scaffolding |
| Claude 3.5/4 Sonnet | ~26% | Collector, Automation |
| Claude Opus 4 | ~58% | Engine, Diagnos, Steuerbox |
| Claude Sonnet 4.5 | ~12% | LLM-Cards, Drift-Engine, Doku |

Wertschoepfung (nicht nur LOC):

| Kategorie | Anteil gesamt | Bemerkung |
|---|---:|---|
| Menschliche Wertschoepfung | ~58% | +3pp durch manuelle Kalibrierung |
| KI-Wertschoepfung | ~42% | Code-Volumen, Doku-Struktur |

Hinweis: Die Prozentwerte sind bewusst als Naeherung dokumentiert.
Sie sind fuer Projektsteuerung und Kommunikation geeignet, nicht als
forensischer Nachweis einzelner Zeilen.

---

## 5) Expliziter LLM-Modulanteil im Repo (technischer Teilbereich)

Separat vom obigen Entwicklungsanteil laesst sich der explizite
LLM-Infrastrukturteil im Repo messen (z. B. `ollama/`, `doc/llm/`):

| Kennzahl | Wert | Δ seit 19.04 |
|---|---:|---:|
| LLM-bezogene Dateien (explizit) | 52 | +48 |
| LLM-bezogene Zeilen (explizit) | ~9.200 | +8.453 |
| Anteil am Gesamt-Textbestand | ~10,7% | +9,6pp |
| Anteil am Code/Config-Bestand | ~1,1% | −0,2pp |

Detailaufteilung:
- `ollama/`: 4 Dateien, ~747 Zeilen (unverändert)
- `doc/llm/cards/`: 34 Dateien, ~5.100 Zeilen (neu)
- `doc/llm/INDEX.md`, `_drift/`: 14 Dateien, ~3.353 Zeilen (neu)

Interpretation: Das Produkt ist primaer ein PV-System mit KI-unterstuetzter
Entwicklung. Q2 2026 starker Ausbau der LLM-Entwickler-Infrastruktur (Cards,
Drift-Detection), die selbst wiederum KI-generiert ist.

---

## 6) Pflegeprozess

Empfohlene Aktualisierung:
- monatlich
- zusaetzlich nach groesseren Architektur- oder Modellwechseln

Update-Checkliste:
1. Mengenstand neu berechnen (Dateien, Codezeilen, Dokuzeilen)
2. Sprachverteilung aktualisieren
3. KI-Anteilsabschnitt gegen aktuelle Projektrealitaet plausibilisieren
4. README-Link pruefen
5. Kurznotiz im Changelog ergaenzen

Beispielkommandos:

```bash
git ls-files | wc -l
git ls-files | grep -E '\.(py|sh|js|ts|css|html|sql|json|toml|yml|yaml|service|conf|ini)$' | xargs -r wc -l | tail -n 1
git ls-files | grep -E '\.(md|rst|txt)$' | xargs -r wc -l | tail -n 1
```

---

## 7) Quellen

- Git-History (frueheres `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md`)
- `README.md`
- Live-Mengenscan vom 01.07.2026
