# KI-Beitragsanalyse (gepflegte Fassung)

Stand: 14.11.2026 (forensische Modell-Differenzierung ergänzt, Abschn. 5a; Mengenstand Abschn. 2 unverändert Stand 01.07.2026)
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
5. Claude Opus 4.x (ab Nov 2026) — tragende Feature-/Qualitätsarbeit (u. a. Web-Charts). In derselben Phase zeitweise **Copilot-Fusion-Routing** auf ein kleineres Modell (vermutlich MAI-Code) für Micro-Tasks; direkter Qualitätsvergleich s. Abschnitt 5a.

Quelle und Detailbegruendung: Git-History (s. Hinweis in Abschnitt 1).

**Wichtig:** Alle Commits tragen denselben Git-Autor `Copilot`. Die Modellklasse
ist daher **nicht** aus Commit-Metadaten ableitbar, sondern nur aus
Betreiber-Beobachtung der Routing-Umgebung plus code-forensischen Markern
(Methodik in Abschnitt 5a).

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

## 5a) Forensische Modell-Differenzierung — Fallstudie „Tag-Ansichten" (14.11.2026)

Am 14.11.2026 wurde dieselbe Aufgabe (Wisch-Navigation + progressives Laden der
Tag-Charts) innerhalb **einer** Sitzung von **mehreren LLMs nacheinander**
bearbeitet. Betreiber-Beobachtung der Routing-Umgebung (Copilot Fusion): die frühen
Turns liefen auf einem kleineren Modell (vermutlich MAI-Code), der Abschluss-Turn auf
einem Star-Modell (Claude Opus). Da alle Commits denselben Autor `Copilot` tragen,
stützt sich die Zuordnung auf diese Beobachtung **plus** code-forensische Marker.

### Commit-Timeline (Sitzung 14.11.2026)

| Commit | Zeit | Umfang | Zuordnung (Konfidenz) |
|---|---|---|---|
| a78c6f5 feat: stabilize day-view loading and swipe | 09:47 | 9 Dateien, +170/−22 | klein/Fusion (mittel) |
| 41161b9 chore: keep swipe fix scoped to UI | 09:48 | 2 Dateien (Revert fremder Daten) | klein/Fusion (mittel) |
| 2f41beb fix: progressive chart load shell | 09:58 | 8 Dateien, +87/−21 | klein/Fusion (mittel) |
| d31b2dd fix: hide stale day chart | 10:11 | 8 Dateien, +67/−26 | klein/Fusion (mittel) |
| 93d1267 feat(web): staggered reveal + non-blocking load; fix leaks | 10:48 | 8 Dateien, +111/−43 | Star/Opus (hoch) |

### Beobachtete Marker (Belege aus der Git-History, nicht Meinung)

Kleineres Modell (a78c6f5 … d31b2dd):
- **Scope-Hygiene-Verstoß:** a78c6f5 mischte sachfremde Datendateien
  (`doc/csv/daily_2026.csv`, `doc/volkszaehlung.md`) in einen UI-Commit (AGENTS
  No-Go #11) und benötigte den Folge-Commit 41161b9 nur zum Zurücknehmen → zwei
  Commits für ein sauberes Scope.
- **Iteration ohne Konvergenz:** drei Anläufe (a78c6f5 → 2f41beb → d31b2dd) für
  dieselbe Lade-UX, die danach immer noch fehlerhaft war.
- **Harter Korrektheitsfehler ohne Validierung:** d31b2dd fügte in
  `templates/tag_view.html` zweimal `const chartShell` im selben `try`-Scope ein
  (Z. 1020 + 1146) → `SyntaxError: Identifier 'chartShell' has already been declared`.
  Das deaktiviert das **gesamte** Inline-Script der Monitoring-Seite. Die Prüfung
  erfolgte nur per HTTP-200 (Seite ausgeliefert ≠ JS lauffähig) — eine simple
  Syntaxprüfung hätte den Fehler gefunden.

Star-Modell (93d1267):
- **Root-Cause-Dichte:** ein kohärenter Commit behob den o. g. SyntaxError, baute
  einen geteilten DRY-Helfer (`static/js/nav-ui.js:PVChart.staggerReveal`), fand +
  behob **vorbestehende** Resize-Listener-Lecks in erzeuger/verbraucher und
  entkoppelte einen blockierenden API-Call (`/api/period_extremes`, nur Tooltip) →
  Chart-Anzeige von ~5 s auf ~1 s.
- **Belegte Validierung:** Syntaxprüfung aller fünf Templates, Headless-Browser-
  Render + Screenshots (Desktop + Mobile 390×844), simulierter Wisch-Test.
- **Scope-Disziplin:** genau ein thematischer Commit, zugehörige Card im selben
  Commit gepflegt.

### Heuristik: Star-LLM vs. kleines LLM (wiederverwendbar)

Ohne Metadaten lässt sich die Modellklasse näherungsweise an diesen Zeichen ablesen
(je mehr erfüllt, desto eher **kleines** Modell):

1. **Hohe Iterationszahl pro Thema** (viele kleine „fix:"-Commits für eine Anforderung).
2. **Revert-/Scope-Korrektur-Commits** nötig (sachfremde Dateien, Nachjustieren).
3. **Harte Fehler ausgeliefert** (Syntaxfehler, kaputtes Script, falsche Selektoren).
4. **Oberflächliche Validierung** (nur „Seite lädt" statt Funktion/Render geprüft).
5. **Wenig DRY** (dupliziertes Verhalten statt geteilter Helfer).
6. **Symptom- statt Ursachenfix** (Lade-Overlay sichtbar lassen statt Altinhalt entfernen).

Star-Signatur umgekehrt: **wenige, größere, kohärente Commits**, Ursachenbehebung
inkl. vorbestehender Bugs, geteilte Helfer, belegte Verifikation (Browser/Tests),
saubere thematische Trennung.

### Einordnung für die Projektsteuerung

Nicht-triviale Änderungen an diesem System profitieren messbar von einem Star-Modell:
die tragende Architektur- und Qualitätsarbeit (Engine, Diagnos, Steuerbox, Web-Charts)
stammt durchgängig aus der Opus-/Sonnet-Linie. Kleinere/kostengünstigere Modelle (hier
Copilot Fusion/MAI-Code) sind für eng umrissene Mikro-Tasks brauchbar, lieferten bei
dieser mehrschrittigen UI-Aufgabe jedoch Nacharbeit und einen produktionsbrechenden
Fehler. Methodische Einschränkung: Stichprobe n=1 Sitzung; die Zuordnung „klein vs.
Star" bleibt teils hypothetisch, die Marker (Scope-Verstoß, SyntaxError, Iterationszahl)
sind aber objektiv aus der Git-History belegbar.

---

## 5b) Modell-Einordnung — Recovery/Reboot-Sitzung (Sonnet, 14.11.2026)

Betreiber-Beobachtung: Die Rolle-R-Einführung (`f13e0d7`) und das koordinierte
Reboot-Werkzeug (`5509619`) entstanden auf **Claude Sonnet**. Opus hat die Arbeit
anschließend geprüft; diese Einordnung ist das Ergebnis.

### Commit-Bezug

| Commit | Umfang | Thema |
|---|---|---|
| f13e0d7 feat(recovery): Rolle R | 27 Dateien, +~1000 | Orthogonale Meta-Rolle R, Manifeste, Rebuild, Paket/USB/Secrets, Timer, Doku |
| 5509619 feat(recovery): all-safe-reboot | 3 Dateien, +403/−6 | Koordinierter 4-Host-Reboot + Post-Reboot-Check |

### Stärken (Star-Signatur, belegt)

- **Architektur-Kohärenz:** R als orthogonale Rolle ohne `.role`, dry-run-default,
  Selbstschutz (Ziel-Rolle == lokale Rolle → Abbruch), **kein** Auto-Writer
  (Split-Brain-Schutz). Publish-sichere Manifeste (IP nur via `*_env`).
- **Datensicherheits-Sequenz** im Reboot: Tech-NQ-Flush → FB-Mirror-Force →
  Primary-Persist+Stop, Reihenfolge Tech→Küche→FB→Primary (Primary zuletzt).
- **Wiederverwendung statt Dup:** Primary-Persist/Stop spiegelt `4_reboot_Prim.sh`
  getreu; Installer idempotent; Doku vollständig (RECOVERY.md + 3 Cards + INDEX +
  ABCDEN→ABCDENR-Governance).

### Vermeidbare Lücken (von Opus gefunden/behoben)

- **Unvollständige Verifikation vs. Kanon:** Das konsolidierte
  `pv_all_safe_reboot.sh` prüfte Küche nur gegen `pv-failover-init.service` und
  ließ `pv-backup-2d.timer` + `pv-failover-health.timer` weg, die die
  handgeschriebene `2_reboot_K.sh` prüft → schwächere Post-Boot-Prüfung (gleicher
  Fehler im `pv_post_reboot_check.py`). Behoben.
- **Unvollständiges Provisioning (Kern-Miss):** Der Küche-Rebuild installierte
  Browser-Autostart, **aber kein Autologin**. Ein so rekonstruierter Kiosk bootet
  in den Login-Greeter und startet den Browser nie. Die Autologin-Schicht fehlte
  komplett im Repo (nur host-seitig) — genau der Produktionsausfall, der real
  auftrat. Rolle R verspricht, einen Host „zu installieren, zu rekonstruieren und
  aktuell zu halten", konnte den Kiosk aber **nicht end-to-end** reproduzieren.
  Behoben via `scripts/install_kiosk_autologin.sh` + Einhängen in den Rebuild.
- **Scope-Rauschen (gering):** Beide Feature-Commits trugen die
  autogenerierte `doc/volkszaehlung.md` (Code-Statistik) mit — vermutlich
  Hook-generiert, aber thematisch fremd.

### Wie Opus es gemacht hätte

- **End-to-end-Vollständigkeit vor Feature-Breite:** Ein Provisioning-Werkzeug ist
  erst korrekt, wenn es einen **lauffähigen** Host reproduziert. Die vollständige
  Kiosk-Kette (Autologin → Session → Autostart → Browser) hätte ich modelliert und
  den Rebuild-Dry-Run je Host gegen das Manifest geprüft → die Autologin-Lücke wäre
  vor dem Commit aufgefallen.
- **DRY für Host-Unit-Listen:** Die zu prüfenden Units stehen dreifach
  (`pv_all_safe_reboot.sh`, `pv_post_reboot_check.py`, `2_reboot_K.sh`) und sind
  bereits gedriftet. Sie gehören aus den Host-Manifesten (`recovery/hosts/*.yaml`
  `services`/`timers`) abgeleitet — eine Quelle der Wahrheit.
- **Belegte Verifikation:** Dry-Run-Ausgabe aller vier Hosts + Post-Reboot-Check
  als Commit-Evidenz.

### Einordnung

Klar **Star-Band**: die tragende Design-Arbeit (orthogonale Rolle R,
Sicherheits-Invarianten, Datensequenz) ist hochwertig und frei von den groben
Korrektheitsfehlern (SyntaxError, kaputtes Script) der kleinen Modelle aus 5a. Der
Opus-vs-Sonnet-Unterschied liegt hier **nicht** in der Architektur, sondern in
**Vollständigkeit, DRY und belegter End-to-end-Validierung**: Sonnet baute das
Gerüst vollständig und sicher, verfehlte aber die letzte Meile (reproduzierbares
Autologin) und ließ Verifikationslisten driften. Stichprobe n=1 Sitzung; die
Marker (fehlende Autologin-Schicht, gedriftete Unit-Listen) sind objektiv belegbar.

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
6. Bei Multi-Modell-Sitzungen: forensische Marker (Abschn. 5a) prüfen und je Sitzung
   eine knappe Zuordnung „klein vs. Star" mit Commit-Belegen ergänzen

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
- Live-Mengenscan vom 01.07.2026; laufende Mengen in `doc/volkszaehlung.md` (auto-generiert)
- Fallstudie 5a: Commits `a78c6f5`, `41161b9`, `2f41beb`, `d31b2dd`, `93d1267` (14.11.2026)
