# AGENTS.md — Pflichteinstieg für jedes LLM/Agent

> **Du arbeitest am PV-System.** Lies diese Datei vollständig, bevor du irgendetwas tust.
> Nach diesem Dokument lädst du je nach Aufgabe gezielt weiter — die Lade-Hierarchie steht unten.

## ABCDEN-Rollenmodell (Sicherheits-Anker)

| Rolle | Schreibt | Hardware | Bemerkung |
|---|---|---|---|
| **A** Collector | `raw_data` (DB) | Modbus TCP read | nur sammeln |
| **B** Web-API | **nichts** | **nichts** | `FroniusReadOnly` — Duplette gewollt |
| **C** Automation | DB + HTTP/Modbus write | Inverter, HP, Fritz!DECT, Wattpilot | einzige Schreib-Rolle |
| **D** Diagnos | DB read + Mail | — | Phase 1+2 produktiv |
| **E** Steuerbox | `operator_overrides` (Intent-DB) | **nichts** (Intents an C) | eigener Port, validiert, zeitlich begrenzt |
| **N** Netzqualität | eigene NQ-DBs (`nq/db/`, tmpfs auf Tech) | PAC4200 Modbus TCP **read** | Tech = RAM-first-Collector, Primary = Aggregation/Analyse; kein Produktions-Write |

**Architektur-Regel:** DRY < ABCDE-Reinheit. Code-Dupletten (z. B. `FroniusReadOnly` vs. `BatteryConfig`) sind erforderlich, wenn sie die Rollentrennung absichern.

## No-Gos (gelten immer)

1. **Kein Code-Refactor** ohne explizite Aufforderung. Auch keine "Verbesserungen", Docstrings, Type-Hints in unberührtem Code.
2. **Kein Hardware-Schreibzugriff aus Rolle B oder D.** Niemals.
3. **Keine Ratenlimits per Software** (InWRte/OutWRte/StorCtl_Mod) — GEN24 HW-Limit ist die einzige Wahrheit. Steuerung ausschließlich über SOC_MIN/SOC_MAX via Fronius HTTP-API.
4. **Wattpilot ≠ WP.** „WP" = Wärmepumpe (Dimplex). „Wattpilot" = EV-Lader (Fronius). Niemals verwechseln.
5. **Keine destruktiven Git-Aktionen** (`push --force`, `reset --hard` auf Published, `--no-verify`) ohne explizite Freigabe.
6. **Keine TODOs in Subdirectories.** Alle offenen Aufgaben gehören in `doc/TODO.md`.
7. **Veröffentlichung:** Vor jedem Push prüft der Publish-Guard (s. `doc/system/PUBLISH_GUARD.md`). Niemals umgehen.
8. **Rolle N ist read-only gegenüber Produktions-DATEN.** PAC4200/NQ schreibt nur eigene NQ-DBs, niemals `data.db` oder Aktoren. Tech-Collector arbeitet RAM-first (tmpfs), SD nur selten. (Betrifft **Runtime-Daten**, nicht Code-Deployment — s. Deployment-Policy unten.)
9. **Doku = IST-Zustand.** Cards und Human-Docs beschreiben ausschließlich den *aktuellen* Stand/Funktion — **kein** „was wann warum geändert" (kein Changelog, keine `## Changes`-Sektion, kein `changes:`-Frontmatter, keine datierten Verlaufslisten). Historie lebt in **git**. Einzige Ausnahme: `doc/meta/KI_BEITRAGSANALYSE.md`.
10. **UI-Änderungen visuell verifizieren.** Vor „fertig": Ziel-Viewport headless rendern + screenshotten (Browser-Tools) und den Effekt belegen — nicht den Bediener prüfen lassen. Mobile/Portrait immer bei 390×844 gegenprüfen.
## Hosts (knapp)

Nach der **REFORMATION** (Umzug der Produktion auf Pi5, 2026-07-11) gilt die Vier-Host-Topologie:

- **Pi5-Primary** `192.0.2.204` (admin) — Produktion, Vollsystem A–E. Pi 5 Rev 1.0 · Cortex-A76 4×2,4 GHz · 4 GB RAM · microSD 64 GB · Debian 12 · Py 3.11. WP-Zugriff via Pi4-Tech-Bridge (`WP_BACKEND_MODE=remote`). UFW aktiv.
- **Pi5-FB** `192.0.2.195` (admin) — Failover (read-only) + Backup-Empfänger + Dashboard-Ticker. Pi 5 Rev 1.0 · Cortex-A76 4×2,4 GHz · 8 GB RAM · NVMe 512 GB · Debian 12 · Py 3.11 · `.role=failover`. UFW aktiv.
- **Pi4-Küche** `192.0.2.105` (jk) — Kiosk-Display (Touch) + Longterm-GFS (monthly/yearly). Pi 4 · Cortex-A72 4×1,8 GHz · 8 GB RAM · SD 128 GB · Debian 13. UFW aktiv.
- **Pi4-Tech** `192.0.2.181` (admin) — WP/HW-Bridge (RS485, `WP_BACKEND_MODE=local`), **keine** Engine; **PAC4200-RAM-Collector (Rolle N)**. Pi 4 Rev 1.5 · Cortex-A72 4×1,8 GHz · 4 GB RAM · microSD 64 GB · Debian 13. UFW aktiv.

Rollen werden über die `.role`-Datei (gitignored) gesteuert, nicht über divergenten Code.

**Deployment-Policy (erlaubt & teils notwendig):** Entwickelt wird auf **Primary**; von dort wird per
`rsync` zu den integrierten Hosts (Tech/FB/Küche) synchronisiert und der jeweilige Dienst neu gestartet.
Code-Deployment + Service-Restart auf **allen** integrierten Pi's ist **autorisiert** — genau wie auf
Primary (z. B. Rolle-N-Collector auf Tech, Ticker/LLM-Sync auf FB). Das berührt **nicht** No-Go #8:
der Runtime-Read-only-Grundsatz (Rolle N schreibt keine Produktionsdaten/Aktoren) bleibt; hier geht es
rein ums **Ausrollen von Code**. Auf den Hosts liegende pv-system-Programme/Skripte/Docs, die im
Primary-Workspace fehlen, werden **in den Primary-Workspace integriert** (nicht der volkszaehlung-Hook
angepasst) — Primary ist die vollständige Quelle. Deploy-Kommandos + Dienst→Host-Zuordnung:
[`doc/llm/cards/system-hosts.card.md`](doc/llm/cards/system-hosts.card.md).

## Lade-Hierarchie für deine Aufgabe

1. **Diese Datei** (jetzt gelesen) — No-Gos, Rollen, Architektur-Skelett. Ersetzt das frühere `doc/SYSTEM_BRIEFING.md` (nie committet, Inhalt hier konsolidiert).
2. **`doc/llm/INDEX.md`** — Trigger→Card-Mapping. Such hier deine Aufgabe und folge dem Verweis.
3. **`doc/llm/cards/<domäne>-<modul>.card.md`** — kompakte, einheitliche Module-Card (≤150 Zeilen) mit Code-Anchor, Invarianten, No-Gos, häufigen Aufgaben, verwandten Cards, Human-Doku-Link.

**Wenn du zur richtigen Card gefunden hast und deine Aufgabe innerhalb der Card-Invarianten liegt, brauchst du nichts weiter zu lesen.** Tiefere Hintergründe stehen im verlinkten Human-Doku-Manual (`doc/<bereich>/<datei>.md`) — nur lesen, wenn nötig.

## Pflege-Pflicht (für Agenten, die Code ändern)

- Wenn du Code änderst, der durch eine Card abgedeckt ist, **musst** du die Card im selben Commit aktualisieren (mind. `last_review` auf heute).
- Pre-commit-Hook prüft das (`tools/pre_commit_doc_check.py`).
- Drift-Engine (Pi5-Cron) erzeugt täglich Tasks in `doc/llm/_drift/tasks/` für übersehene Drift.

## Doku-Prinzip: IST-Zustand-only

- **Human-Docs & Cards = Gegenwart.** Beschreibe, *wie das System heute funktioniert*, nicht seinen Entstehungsweg. Kein Changelog, keine Änderungshistorie, keine Datums-Verlaufslisten, keine „vorher/nachher"-Notizen.
- **Historie = git.** `git log`/`git blame` ist die vollständige, portable Entwicklungsgeschichte. Kein separater `History/`-Ordner, keine Verlaufs-Doku im Workspace.
- **Entwicklungsartefakte gehören nicht ins Doku-Set.** Datierte Audits, Tiefenprüfungen, Roadmaps, Entscheidungsvorlagen, Snapshots, Dev-Prompts sind flüchtig — nach Einarbeitung in den IST-Stand entfernen (git bewahrt sie).
- **Einzige Ausnahme:** `doc/meta/KI_BEITRAGSANALYSE.md` (Mensch/KI-Beitragsanalyse) darf datierte Stände führen.
- Erzwungen durch den Pre-commit-Hook (`tools/pre_commit_doc_check.py`) für geänderte Cards/Docs.

## Konvention für deine Antworten

- Knapp. Keine Floskeln.
- Code-Refs als Markdown-Links: `[file.py](file.py#L42)`.
- Bei Unsicherheit über Fakten: lade die zuständige Card, statt zu raten.

## Datei- und Ordneranlage (LLM-Richtlinien)

- **Rollentrennung beachten:** Dateien müssen der Rolle (A-E) zugeordnet werden.
- **Root-Level vermeiden:** Nur für rollenübergreifende Module.
- **Namenskonventionen:** Python-Dateien `snake_case.py`, Ordner `lowercase/`, zentrale Doku `UPPERCASE.md`.
- **Rollenbasierte Ablage:**
  - A → `collector/` (z. B. `aggregate/`, `fritzdect.py`)
  - B → `routes/` (z. B. `realtime.py`)
  - C → `automation/` (z. B. `engine/`)
  - D → `diagnos/` (z. B. `health.py`)
  - E → `steuerbox/`
  - N → `nq/` (Collector auf Tech, Aggregation/Analyse auf Primary)
- **Entscheidungsbaum:**
  1. Rollenspezifisch → Rollenpaket.
  2. Konfiguration → `config/`.
  3. Temporär → `tmp/`, persistent → Rollenpaket.
