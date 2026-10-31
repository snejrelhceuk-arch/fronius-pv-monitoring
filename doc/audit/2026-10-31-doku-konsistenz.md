# Doku-Konsistenz-Audit — 2026-10-31

Tiefenprüfung der gesamten pv-system-Dokumentation auf **Konsistenz** und
**Vollständigkeit**. Prüfmaßstab: alle Docs beschreiben den **IST-Zustand** des
Produktionssystems; Entwicklungs-/Verlaufs-Content gehört nicht in den
versionierten Doc-Satz (er lebt in git und in den Workspace-Backups).

## Prüfumfang: zwei Systeme

Das Repo trägt **zwei** Systeme, die je in sich **und** gegenseitig konsistent
sein müssen:

1. **PV-Monitoring/Steuerung** — Rollen A–E (`collector/`, `routes/`, `web_api.py`,
   `automation/`, `diagnos/`, `steuerbox/`, `wp_bridge/`), DB `data.db`.
2. **Netzqualität (NQ)** — Rolle N (`nq/`, PAC4200), eigene NQ-DBs.

Beide teilen die Vier-Host-Topologie (Primary/FB/Küche/Tech) und die
Backup-Strategie — dort entstehen die gegenseitigen Konsistenzpflichten.

## Methodik

- Host-Hardware **live** gegen die vier Hosts verifiziert (`/proc`, `lsblk`,
  `free`, `df`), nicht nur Doc gegen Doc.
- Info-Overlay (`templates/info_overlay.html`) Kategorie für Kategorie gegen
  Referenz-Doc (`doc/meta/PV_REFERENZSYSTEM_DOKUMENTATION.md`) und Live-System.
- Card-Coverage: Code-Module der Hook-Pflichtverzeichnisse gegen `applyTo`-Globs.
- Published-vs-local: versionierter Doc-Satz vs. gitignorierte lokale Docs.

## Befunde & sofort behobene Fehler

### 1. Host-Hardware — Pi4-Küche-Disk falsch (Fehler)
Dokumentiert als **128 GB**, real **31,9 GB (32-GB-SD-Karte)**. Korrigiert in:
`AGENTS.md`, `templates/info_overlay.html`, `doc/system/SYSTEM_ARCHITECTURE.md`*,
`doc/system/DUAL_HOST_ARCHITECTURE.md`* (Tabelle + ASCII-Grafik).

Alle übrigen HW-Werte **live bestätigt**: RAM (Primary 4 GB, FB 8 GB, Küche 8 GB,
Tech 4 GB), CPU (Pi5 A76 / Pi4 A72), OS/Python (Pi5 Debian 12/3.11, Pi4
Debian 13/3.13), Disks (Primary microSD 64 GB, FB NVMe 512 GB als Root,
Tech microSD 64 GB).

### 2. NQ-Rolle-N als „(geplant)" — Divergenz zwischen den zwei Systemen (Fehler)
Die NQ-Präsenz auf den Hosts (Tech = NQ-Collector `pv-nq-poller`/`pv-nq-energy`;
Primary = NQ-Primary Aggregation/Analyse/Rollup) ist **produktiv** und in der
`system-hosts.card.md` korrekt. Die Architektur-Docs beschrieben PAC4200 noch als
**„(geplant)"** bzw. „Ausblick: … künftig". Das ist der zentrale
Zwei-System-Widerspruch (PV-Arch-Docs vs. NQ/Hosts-Card). Auf IST gezogen in:
`doc/system/SYSTEM_ARCHITECTURE.md`* (Host-Tabelle, Primary- + Tech-Dienste,
„Ausblick" entfernt), `doc/system/DUAL_HOST_ARCHITECTURE.md`* (Tabelle + ASCII),
`doc/netzqualitaet/NQ_MODUL.md` („künftig" → IST).

### 3. Info-Overlay — DB-Tabellenzahl veraltet (Fehler)
„SQLite (13 Tabellen)" → real **27 Nutz-Tabellen** (Live-`data.db`/tmpfs).
Korrigiert in `templates/info_overlay.html` und — gleicher Altwert — in
`doc/meta/PV_REFERENZSYSTEM_DOKUMENTATION.md` („11 MB, 13 Tabellen" → „27 Tabellen").
Übrige Overlay-Kategorien (Anlage, Verbraucher, Software/ECharts 5.4.3,
Daten 06.02.2026) **vollständig deckungsgleich** mit dem Referenz-Doc.

### 4. Card-Coverage — Lücken geschlossen
- `web_api.py` ist Hook-pflichtig, wurde aber von **keinem** `applyTo`-Glob
  erfasst → `web-display-api.card.md` auf `routes/**,web_api.py` erweitert.
- Nicht alle **Wattpilot**-Codestellen waren namentlich einer Card zugeordnet.
  `automation-regel-wattpilot.card.md` deckt jetzt zusätzlich
  `regeln/geraete_wattpilot_schutz.py` und `wattpilot_recovery.py` ab.
- `collector/wp_power_protocol.py` (Netzbetreiber-Nachweis WP-/Wattpilot-Leistung)
  bleibt korrekt über den breiten `collector/**`-Glob abgedeckt.

## Strukturelle Einordnung (kein Fehler, dokumentiert)

- **Published vs. local:** Ein Block entwicklungslastiger/lokaler Docs ist bewusst
  **gitignored** (`.gitignore`): `doc/system/SYSTEM_ARCHITECTURE.md`,
  `doc/system/DUAL_HOST_ARCHITECTURE.md`, `doc/system/GIT_WORKFLOW.md`,
  `doc/SYSTEM_BRIEFING.md`, `doc/automation/HARDWARE_SETUP.md`,
  `doc/automation/SCHUTZREGELN.md`, `doc/collector/WATTPILOT_ARCHITECTURE.md`,
  `doc/meta/TODO.md`, `doc/archive/`. Das ist der Mechanismus, der
  Entwicklungs-/Planungs-Content (z. B. SCHUTZREGELN mit „Geplant"-Statuslisten)
  aus dem veröffentlichten Doc-Satz heraushält. Die mit `*` markierten Fixes oben
  betreffen diese lokalen Docs — sie verbessern den lokalen IST, erscheinen aber
  nicht in Commits.
- **`doc/TODO.md` / `doc/PLAN/`** sind die sanktionierten Orte für offene Punkte
  und Roadmaps (AGENTS No-Go #6). Verweise darauf aus Cards sind IST-konform
  (sie beschreiben, dass etwas offen ist) und wurden nicht entfernt.

## Ergebnis

Der **versionierte** Doc-Satz ist nach den Fixes frei von den gefundenen Fehlern
(verifiziert: keine „128 GB"-Küche, keine „PAC4200 (geplant)", keine
„13 Tabellen"). Beide Systeme (PV A–E und NQ Rolle N) sind in der
veröffentlichten Doku intern und gegenseitig konsistent; die Live-Hardware deckt
sich mit der Doku. Info-Overlay in allen Kategorien gegen IST abgeglichen.

## Nachtrag: Human-Docs ↔ LLM-Cards (zweites Audit-System)

Auf Nachfrage wurden die **zwei Doku-Systeme** (Human-Docs vs. LLM-Cards) zusätzlich
auf gegenseitige Konsistenz geprüft.

### Befunde und sofort behobene Fehler

**WP-Hersteller-Widerspruch (kardinal, Cards vs. Human-Docs):**
- `collector-feldnamen-referenz.card.md:32` und `automation-regel-wattpilot.card.md:50`
  nannten die Wärmepumpe „Stiebel Eltron" — alle anderen Quellen (AGENTS.md, Overlay,
  `doc/meta/PV_REFERENZSYSTEM_DOKUMENTATION.md`, `doc/automation/WP_INTEGRATION.md`,
  `config/soc_param_matrix.json`, `doc/automation/STRATEGIEN.md`) sagen einheitlich
  **„Dimplex SIK 11 TES"**. Korrigiert in beiden Cards.

**Fehlende Human-Doku-Links (LLM-Cards ohne Verweis auf existierende tracked Human-Docs):**

| Card | fehlender Link |
|---|---|
| `automation-battery-algorithm.card.md` | `doc/automation/BATTERY_ALGORITHM.md` |
| `automation-regel-heizpatrone.card.md` | `doc/automation/WP_INTEGRATION.md` (Dimplex-WP-Koordination) |
| `automation-steuerungsphilosophie.card.md` | `doc/automation/STRATEGIEN.md`, `doc/system/PARAMETER_MATRIZEN.md` |
| `system-hosts.card.md` | `doc/system/FAILOVER_STATUS.md`, `doc/system/PI4_TECH_BRIDGE_HANDBUCH.md` |
| `web-display-api.card.md` | `doc/web/TICKER.md` (Pi5-FB Ticker) |

Alle ergänzt.

### Strukturbefund: Broken-Refs = keine

Alle 36 von Cards referenzierten Human-Doc-Pfade existieren (live geprüft).

### Weitere NOCARD-Human-Docs (tracked, aber keine Card referenziert sie)

Folgende tracked Docs sind inhaltlich deckend durch übergeordnete Cards (kein
eigenständiges LLM-Einstiegsmuster erforderlich) oder durch AGENTS/INDEX ausreichend
adressiert:
`doc/automation/BEOBACHTUNGSKONZEPT.md`, `doc/automation/WP_REGISTER.md`
(von WP_INTEGRATION abgedeckt), `doc/collector/COLLECTOR_HARDENING.md`,
`doc/collector/SOLAR_FORECAST_SCAFFOLD.md` (kein produktiver Collector),
`doc/netzqualitaet/NQ_SPEICHER.md`, `doc/netzqualitaet/NQ_TESTS_UND_DB.md`,
`doc/netzqualitaet/ENERGIE_ABLESEMETHODE.md`, `doc/system/ABCDEN_ROLLENMODELL.md`
(durch AGENTS.md abgedeckt), `doc/system/FILESYSTEM.md`,
`doc/system/PARAMETER_MATRIZEN.md` (jetzt in steuerungsphilosophie verlinkt),
`doc/system/SINGLE_INSTANCE_PROTECTION.md`, `doc/system/REFORMATION_RUNBOOK.md`.

Gitignored (bewusst lokal): `doc/automation/SCHUTZREGELN.md`,
`doc/automation/HARDWARE_SETUP.md`, `doc/collector/WATTPILOT_ARCHITECTURE.md`.


- **Dateiname `DUAL_HOST_ARCHITECTURE.md`** ist historisch (Inhalt/Titel sind
  bereits „Multi-Host / Vier Hosts"). Da die Datei gitignored ist und 8 Verweise
  bestehen, lohnt eine Umbenennung nur zusammen mit einem Verweis-Sweep — bewusst
  offen gelassen.

## Rest-Empfehlung (nicht sofort umgesetzt)

- **Dateiname `DUAL_HOST_ARCHITECTURE.md`** ist historisch (Inhalt/Titel sind
  bereits „Multi-Host / Vier Hosts"). Da die Datei gitignored ist und 8 Verweise
  bestehen, lohnt eine Umbenennung nur zusammen mit einem Verweis-Sweep — bewusst
  offen gelassen.

## Nachtrag 2: Tiefe Human↔LLM-Inhaltsprüfung (Explore-Agent)

### Kritische Widersprüche — behoben

**D1 — NQ RAW-Retention: `NQ_MODUL.md` 72 h vs. Card + Code 12 h**
`doc/netzqualitaet/NQ_MODUL.md` §3.3 (Stand 2026-08-08) beschrieb die
initiale Design-Entscheidung „72 h RAW im tmpfs". Das produktive System
(`config/nq_config.json:raw_hours=12`, Capping-Code default=12,
Schema-Kommentar „12 h Ring-Buffer") läuft auf 12 h. Die Card war korrekt,
das Human-Doc veraltet. Korrigiert: §3.3, Zeit-Ring-Löschung, Mermaid-Diagramm.

**D2 — NQ Transfer-Tabelle: `NQ_MODUL.md` `nq_agg_10s` vs. Card/Code `nq_5min`**
`NQ_MODUL.md` §6.1 + Aggregationskaskade beschrieben `nq_agg_10s` als
Transfer-Objekt von Tech → Primary. `nq_agg_10s` existiert **nicht** im
produktiven Schema (`nq/schema/nq_tech_schema.sql`) und nicht in der
Live-DB auf Tech. Der produktive Transfer (`nq/transfer/nq_agg_transfer.py`)
überträgt `nq_5min` + `nq_transient_5min`. Human-Doc auf IST gebracht.

**C2 — Pi4-Tech `.role=tech` (nicht `failover`)**
Live verifiziert: Tech-Host hat `.role=tech`. Gitignorierte Arch-Docs sagten
`failover*`, `system-hosts.card.md` trug keinen Wert — beides korrigiert
(Card: `.role=tech`; Arch-Docs lokal). Küche live: `.role=kiosk` (in Card ergänzt).

**C1 — `pv-nq-backup` in Primary-Dienstliste fehlend**
`SYSTEM_ARCHITECTURE.md` Primary-Dienste enthielten den NQ-GFS-Backup-Timer
nicht (`BACKUP_STRATEGY.md` und systemd-Timer-Liste kennen ihn). Lokal ergänzt.

### Strukturelle Stale-Human-Docs (gitignored, lokal korrigiert)

`WATTPILOT_ARCHITECTURE.md`: 10 s Polling (real 30 s) + 4 fehlende
Schema-Spalten (`amp`, `trx`, `lmo`, `frc`). Da gitignored und Cards
korrekt, ist das kein LLM-Risiko — aber für künftige manuelle Arbeit
mit dem Doc irreführend.
