# KI-Beitragsanalyse (gepflegte Fassung)

Stand: 19.04.2026
Geltungsbereich: gesamtes Repository (tracked files)
Status: aktiv gepflegt

---

## 1) Zweck

Dieses Dokument ist die aktuelle Referenz fuer die Einschaetzung der
Mensch/KI-Anteile am Entwicklungs-Content. Historische Herleitung und
langere Interpretation bleiben im Archivdokument:

- `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md`

---

## 2) Aktueller Mengenstand (19.04.2026)

| Kennzahl | Wert |
|---|---:|
| Tracked Dateien gesamt | 246 |
| Code/Config-Dateien | 170 |
| Code/Config-Zeilen | 56.844 |
| Doku-Dateien | 58 |
| Doku-Zeilen | 10.105 |

Top-Sprachen nach Zeilen:

| Sprache | Dateien | Zeilen |
|---|---:|---:|
| Python | 100 | 39.442 |
| HTML | 14 | 9.559 |
| JSON | 10 | 3.601 |
| Shell | 31 | 2.059 |
| SQL | 8 | 969 |
| CSS | 3 | 896 |
| JavaScript | 1 | 272 |

---

## 3) KI-Modellphasen (historisch, inhaltlich)

Die historische Phasenfolge bleibt unveraendert:

1. Gemini 2.0 Flash (Dez 2025)
2. Claude 3.5/4 Sonnet (Jan-Feb 2026)
3. Claude Opus 4 (ab Feb 2026)

Quelle und Detailbegruendung:
- `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md`

---

## 4) Hochgerechnete Anteile (arbeitsnahe Schaetzung)

Diese Werte sind eine gepflegte Arbeitsschaetzung auf Basis der bisherigen
Projektmethodik (Archiv-Analyse + laufende Repo-Entwicklung):

| Kategorie | Anteil |
|---|---:|
| KI-Modelle (gesamt) am Code-Content | ~85% |
| Mensch am Code-Content | ~15% |

Aufteilung innerhalb des KI-Anteils:

| Modellgruppe | Anteil am KI-Content |
|---|---:|
| Gemini 2.0 Flash | ~5% |
| Claude 3.5/4 Sonnet | ~30% |
| Claude Opus 4 | ~65% |

Wertschoepfung (nicht nur LOC):

| Kategorie | Anteil gesamt |
|---|---:|
| Menschliche Wertschoepfung | ~55% |
| KI-Wertschoepfung | ~45% |

Hinweis: Die Prozentwerte sind bewusst als Naeherung dokumentiert.
Sie sind fuer Projektsteuerung und Kommunikation geeignet, nicht als
forensischer Nachweis einzelner Zeilen.

---

## 5) Expliziter LLM-Modulanteil im Repo (technischer Teilbereich)

Separat vom obigen Entwicklungsanteil laesst sich der explizite
LLM-Infrastrukturteil im Repo messen (z. B. `ollama/`):

| Kennzahl | Wert |
|---|---:|
| LLM-bezogene Dateien (explizit) | 4 |
| LLM-bezogene Zeilen (explizit) | 747 |
| Anteil am Gesamt-Textbestand | ~1,1% |
| Anteil am Code/Config-Bestand | ~1,3% |

Interpretation: Das Produkt ist primaer ein PV-System mit KI-unterstuetzter
Entwicklung, nicht ein reines LLM-Produkt.

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

- `doc/archive/LEISTUNGSANTEILE_KI_BEDIENER.md`
- `README.md`
- Live-Mengenscan vom 19.04.2026
