# NQ-Modul — Tiefenprüfung (Rolle N, PAC4200)

**Datum:** 2026-07-12
> **Archiv-Snapshot (2026-08-08):** Diese Tiefenpruefung beschreibt den Stand
> unmittelbar nach dem NQ-Modulaufbau. Kritische Punkte wurden spaeter behoben
> oder in Cards ueberfuehrt. Fuer aktuelle Arbeiten zuerst
> [`README.md`](README.md) und [`../llm/INDEX.md`](../llm/INDEX.md) nutzen.

**Prüfer:** Agent (autonome Tiefenprüfung)
**Umfang:** PAC4200 · Pi4-Tech (Collector) · Pi5-Primary (Aggregation/Analyse) ·
Pi5-FB (Offsite-Backup) · Pi4-Küche (Longterm-Backup)
**Status:** kritische + hohe Mängel korrigiert; **NQ-Pipeline am 2026-07-13 aktiviert
und end-to-end verifiziert** (inkl. Harmonische). Siehe §9.

> Zweck: belastbare Aussage zur Funktionsfähigkeit des NQ-Moduls entlang der vom
> Betreiber gesetzten Schwerpunkte. Kurzfassung zuerst, Details je Schwerpunkt.

---

## 0. Kurzfassung (Management Summary)

| # | Befund | Schwere | Status |
|---|---|---|---|
| 1 | `nq_raw_slow` fehlte im **Primary-Schema** → Transfer- **und** Aggregationslauf brachen mit „no such table" ab (Harmonik-Pipeline tot) | **kritisch** | **behoben** |
| 2 | Auf Primary war **nur** `pv-nq-energy-rollup` installiert — `pv-nq-agg-transfer`/`-aggregate` liefen **nie** → `nq_agg_10s`/`nq_5min`/`nq_events` dauerhaft leer, obwohl der Tech-Collector Daten liefert | **kritisch** | **Installer + Units bereitgestellt**, Aktivierung = PRIO-1-TODO |
| 3 | `nq_agg_transfer.py` enthielt einen doppelt einkopierten Alt-Block (tages-basierter Transfer), der beim Import `transfer()`/`main()` überschrieb | hoch | **behoben** |
| 4 | Keine Timer für **Analyse** (`nq_events`) und **Event-Kappung** (`nq_primary_cap`) → Mustererkennung/Retention liefen nie | hoch | **Units erstellt** (`pv-nq-analysis`, `pv-nq-primary-cap`) |
| 5 | Event-Snippet-Pipeline (RAW-Transfer, Drill-down, Marker) unvollständig | mittel (geplantes Feature) | TODO |
| 6 | Tote Stubs + Doku-Drift (Retention 12 h vs. 72 h, `CHANGE_ME_PRIMARY`, Card-Code-Anchor) | niedrig | TODO |

**Positiv bestätigt:** PAC4200-Registerwahl inkl. **Vorzeichenkonvention** ist
korrekt und gegen das reale Gerät verifiziert; Tech-Collector läuft stabil
(RAM-first, Restart=always); Backups (GFS + Offsite + Longterm) sind sauber
angelegt; Navigation/Darstellung im Maschinenraum ist eingebunden.

---

## 1. PAC4200 — Registerwahl & Vorzeichen (Betriebsanleitung)

**Ergebnis: korrekt.** Die Registerkarte in [`nq/pac_live.py`](../../nq/pac_live.py)
deckt sich mit der verifizierten Referenz in
[`MESSTECHNIK.md`](MESSTECHNIK.md) / [`PAC4200-Modbus.md`](PAC4200-Modbus.md) und
wurde 2026-07-11/12 gegen das reale Gerät bestätigt.

- **Block A (Adr. 1–73, FLOAT32, big-endian, High-Word zuerst):** U L-N (1/3/5),
  U L-L (7/9/11), I je Phase (13/15/17), S/P/Q je Phase, PF, THD-U **L-L**
  (43/45/47), Frequenz (55), Summen (63–73). Lesestart Adr. 1 (Adr. 0 wird nicht
  beantwortet) — korrekt umgesetzt.
- **Block B (Adr. 243–295):** cos φ (243–247), **THD-U L-N** (261–265),
  **THD-I** (267–271, nicht 49–53 = NaN), I_N (295). Lagekorrektur ist im Code
  dokumentiert und angewandt.
- **Energie (FLOAT64 @801 ff., Tarif 1):** Wh_imp @801, **Wh_exp @809**,
  varh_imp @817, varh_exp @825, VAh @833. Die frühere Fehllage (@805 = Bezug T2)
  ist korrigiert; `_DOUBLE_READ_COUNT=36` erreicht @833. Korrekt.
- **Einzelharmonische (A.3.10):** ungerade H1/H3…H31, Schrittformel
  `base + ordinal*6 + phase_offset`, Blöcke @9001 (U L-N), @11001 (I),
  @22001 (U L-L), je 96 Register. End-Adressen @9095/@11095/@22095 passen.
  Korrekt umgesetzt.

**Vorzeichenkonvention (Zweirichtungszähler am PCC):** Der PAC4200 liefert
RMS-Ströme (13/15/17) **vorzeichenlos**. Die Richtung wird korrekt aus dem
**Vorzeichen der Phasen-Wirkleistung P** (25/27/29) abgeleitet
([`_decode_ab`](../../nq/pac_live.py)): `P_Lx < 0` → Strom negativ (Einspeisung),
sonst positiv; `Isum` netzt Bezug gegen Einspeisung. Der vorzeichenlose
Geräte-Mittelwert `Iavg` (61) wird bewusst **nicht** für die Richtung genutzt.
Konvention ist konsistent zwischen Live-Snapshot, Screens und Poller.

> Keine „erfundenen" Register gefunden; alle Adressen sind belegt/verifiziert.
> Kein Schreibpfad zum Gerät (nur FC3-Read) — Rolle-N-Reinheit gewahrt.

---

## 2. Systemische Einbindung, Neustartfestigkeit, Prozessprüfung

### 2.1 Prozess-Topologie (Soll)

| Host | Prozess | Typ | Restart/Nachhol |
|---|---|---|---|
| Pi4-Tech | `pv-nq-poller` (Block A/B fast + Harmonik slow) | Dauerläufer | `Restart=always`, `RestartSec=15`, `StartLimitIntervalSec=0` |
| Pi4-Tech | `pv-nq-energy` (Zähler-Snapshotter) | Dauerläufer | `Restart=always` |
| Pi5-Primary | `pv-nq-agg-transfer` | Timer 4-stündl. (:10) | `Persistent=true` |
| Pi5-Primary | `pv-nq-aggregate` | Timer 4-stündl. (:15) | `Persistent=true` |
| Pi5-Primary | `pv-nq-energy-rollup` | Timer tägl. 00:05 | `Persistent=true` |
| Pi5-Primary | `pv-nq-analysis` *(neu)* | Timer tägl. 00:30 | `Persistent=true` |
| Pi5-Primary | `pv-nq-primary-cap` *(neu)* | Timer tägl. 00:40 | `Persistent=true` |

### 2.2 Ist-Zustand (gemessen 2026-07-12)

- **Tech-Collector lebt:** `tech_read.fetch_agg` lieferte 61 Buckets / 35 Größen
  in der letzten Stunde ohne Fehler; `nq_energy_daily` auf Primary hat einen
  Eintrag → Poller **und** Energie-Snapshotter laufen auf Tech.
- **Primary-Pipeline dormant:** In `/etc/systemd/system` war **nur**
  `pv-nq-energy-rollup` installiert. `pv-nq-agg-transfer.timer` und
  `pv-nq-aggregate.timer` **fehlten** → Transfer/Aggregation liefen nie.
  Cron enthält nur die **Legacy**-Jobs (`nq/legacy/nq_export.py`,
  `nq_analysis.py`), nicht die Rolle-N-Pipeline.
- **Folge:** `nq_agg_10s`, `nq_5min`, `nq_hourly`, `nq_daily`, `nq_events`,
  `nq_ingest_log` in `nq/db/nq_2026-07.db` = **0 Zeilen**.

### 2.3 Korrektur

- Neue rollenbewusste Installation: [`scripts/install_nq_services.sh`](../../scripts/install_nq_services.sh)
  (tech → Dauerläufer, primary → Timer; `install -m 0644` + `daemon-reload` +
  `enable --now`, idempotent).
- **Aktivierung ist ein `sudo`-Eingriff auf Produktions-Hosts** und wurde daher
  **bewusst nicht autonom ausgeführt** (Betriebssicherheit: Shared-Infra).
  → **PRIO-1-TODO**, Befehl unten.

```bash
# auf Pi5-Primary
scripts/install_nq_services.sh
systemctl list-timers 'pv-nq-*'
sudo systemctl start pv-nq-agg-transfer.service   # erster Sofortlauf
# auf Pi4-Tech (Enable-Status nach Reboot sichern)
scripts/install_nq_services.sh
```

---

## 3. Datenbankintegrität & Aggregationspipeline

### 3.1 Kritischer Bug (behoben)

`nq_raw_slow` (1-s-Harmonik-RAW) wird von Tech nach Primary übertragen und dort
zu `nq_5min` aggregiert — **fehlte aber im Primary-Schema**
([`nq_primary_schema.sql`](../../nq/schema/nq_primary_schema.sql)). Damit brachen
**beide** Primary-Pfade ab:

- `nq_agg_transfer.transfer()` → `INSERT INTO nq_raw_slow` → *no such table*
- `nq_aggregate._run_harm_5min()` → `SELECT FROM nq_raw_slow` → *no such table*
  (unterbricht die ganze Kaskade inkl. hourly/daily).

**Fix:** Tabelle `nq_raw_slow` ins Primary-Schema aufgenommen (identisch zu Tech),
Retention `primary_rawslow_hours` (Default 12 h) in `config/nq_config.json` +
Löschung in `nq_agg_transfer._enforce_retention` (SD-Schonung, Fenster >
Aggregationszyklus).

**Verifiziert** (Temp-DB, synthetische Daten): 5min-Skalar + 5min-Harmonik +
hourly + daily werden befüllt; Retention-Prune entfernt >12 h alte Harmonik-RAW.

### 3.2 Transfer-Modul bereinigt (behoben)

`nq_agg_transfer.py` enthielt nach dem `if __name__=="__main__"`-Guard einen
**vollständigen zweiten (alten, tages-basierten) Implementierungsblock**, der beim
**Import** `transfer()`/`main()`/`_enforce_retention()` überschrieb (Shadowing,
fragil). Der Alt-Block wurde entfernt; es bleibt die 4-stündliche
Fenster-Implementierung (`--hours`, at-least-once, idempotent).

### 3.3 Bewertung der Pipeline-Semantik

- **At-least-once / Idempotenz:** Tech-Delete erst nach Primary-`INSERT OR REPLACE`;
  PK-basierte Upserts → korrekt.
- **Retention:** agg10s 72 h, 5min 90 d, hourly 365 d, daily 10 a, raw_slow 12 h
  (neu). Event-Snippets via `nq_primary_cap` (Alter + Anzahl).
- **Energie-Differenzmethode:** `compute_daily` mit Reset-Erkennung, Checkpoints
  und `nq_energy_compare` (PAC ↔ Master-SM) — sauber, konsistent zur Produktion.
- **Kappung Tech:** Zeit-Ring + Größen-Kappung + Stale-Event-Kappung; der frühere
  `ts`/`ts_ms`-Bug bei `nq_raw_medium` ist bereits behoben.

---

## 4. Navigation (Maschinenraum) & Darstellung neuer Daten

**Eingebunden.** Erreichbarkeit ist gegeben:

- `static/js/nav-ui.js`: Untermenü „Maschinenraum" → **Netzqualität (NQ-DB)**,
  **Screens (Live-Tableau)**, **PAC4200 (Gerät)**, **NQ DFD-Analyse**,
  **NQ Musteranalyse**.
- `templates/flow_view.html`: Sub-Buttons PAC4200 + Netzqualität unter Maschinenraum.
- `templates/echtzeit_view.html`: DB-Umschalter Kern-DB ↔ **PAC4200 (NQ)**;
  liest über `/api/nq/realtime_smart` → [`nq/tech_read.py`](../../nq/tech_read.py).
- Blueprint `pac4200_bp` registriert in `web_api.py`; Live-Screens
  (`/pac4200`), Live-Tableau (`/netzqualitaet/live`), Musteranalyse
  (`/netzqualitaet/analyse`).

**Grenze (TODO):** Der Maschinenraum-Chart liest ausschließlich das **Tech-tmpfs**
(letzte ~12 h). Die Langzeit-Aggregate auf Primary (`nq_5min/hourly/daily`) sind
noch **nicht** per API/Chart abrufbar.

---

## 5. Auswertung / Analyse / Mustererkennung / Event-Management

- **Detektoren vorhanden & importierbar:** `nq_hf` (THD-Spikes, U↔I-Residual),
  `nq_nf` (DFD an 15-min-Grenzen, df/dt, U-Band EN 50160), `nq_vlf`
  (Profil-z-Score, CUSUM-Changepoint), orchestriert in
  [`nq/analysis/nq_events.py`](../../nq/analysis/nq_events.py) (idempotent je Tag,
  Cross-Check gegen Produktions-DB für `origin`). numpy 1.19.5 verfügbar.
- **Lücke (behoben, Deployment offen):** Es gab **keinen Timer**, der
  `analyze_day` ausführt → `nq_events` blieb leer. Neu:
  [`pv-nq-analysis.service`](../../config/systemd/pv-nq-analysis.service) +
  `.timer` (täglich 00:30, Vortag, nach Transfer/Aggregation).
- **Event-Snippet-Pipeline unvollständig (geplantes Feature,
  `doc/dev_prompt/EVENT/prompt.md`):** Der Poller setzt zwar `event=1` auf
  `nq_raw_fast/medium`, aber es gibt **kein** `nq_event_transfer.py`; event-markierte
  RAW-Zeilen werden nach `event_stale_cap_s` (1 h) gekappt und nie nach
  `nq_event_*` übertragen; `has_snippet` bleibt 0; `/api/nq/event/<id>` +
  Chart-Marker/Drill-down fehlen. → TODO (Umsetzung gemäß EVENT-Prompt).

---

## 6. Dokumentation (human / LLM-differenziert)

- **Human:** [`NQ_MODUL.md`](NQ_MODUL.md), [`MESSTECHNIK.md`](MESSTECHNIK.md),
  [`METHODEN.md`](METHODEN.md), [`PAC4200-Modbus.md`](PAC4200-Modbus.md),
  [`NQ_TESTS_UND_DB.md`](NQ_TESTS_UND_DB.md) — inhaltlich belastbar; dieser Bericht
  ergänzt sie.
- **LLM-Cards:** `netzqualitaet-nq-collector`, `-aggregation`, `-analysis-events`.
  Die Aggregations-Card wurde mit dem `nq_raw_slow`-Fix + Deployment-Befund
  aktualisiert (`last_review` heute).
- **Doku-Drift (TODO):** `retention.raw_hours=12` vs. „72 h"-Kommentare in
  `nq_tech_schema.sql`/`nq_capping.py`/`NQ_MODUL.md §3`; `transfer.primary_host=
  "CHANGE_ME_PRIMARY"` (im Pull-Modell ungenutzt); Collector-Card-Code-Anchor zeigt
  auf den Stub `pac_client.py` statt auf `pac_live.py`.

---

## 7. Backups (Pi5-FB Offsite, Pi4-Küche Longterm)

- **GFS + Offsite:** [`scripts/backup_nq_gfs.sh`](../../scripts/backup_nq_gfs.sh)
  sichert die NQ-Monats-DB nach `backup/db/nq/{daily,weekly,monthly}` (7/5/12),
  mit `gzip` + `PRAGMA integrity_check` + Kerntabellen-Check
  (`nq_daily`/`nq_energy_daily`/`nq_agg_10s`) und rsync-Offsite nach **Pi5-FB**.
  Sauber.
- **Longterm:** [`scripts/backup_longterm_offload.sh`](../../scripts/backup_longterm_offload.sh)
  spiegelt `monthly`/`yearly` best-effort auf **Pi4-Küche** (`PV_KUECHE_HOST`,
  überspringt bei Nichterreichbarkeit ohne Fehler).
- **Wirksamkeit hängt an Schwerpunkt 2/3:** Solange die Aggregation nicht läuft,
  enthält die Monats-DB kaum aggregierte Nutzdaten — die Backups sind dann
  technisch korrekt, aber inhaltlich dünn. Nach PRIO-1-Aktivierung greift der
  volle Nutzen.

---

## 8. Durchgeführte Korrekturen (Dateien)

| Datei | Änderung |
|---|---|
| [`nq/schema/nq_primary_schema.sql`](../../nq/schema/nq_primary_schema.sql) | `nq_raw_slow`-Tabelle ergänzt |
| [`config/nq_config.json`](../../config/nq_config.json) | `retention.primary_rawslow_hours: 12` |
| [`nq/transfer/nq_agg_transfer.py`](../../nq/transfer/nq_agg_transfer.py) | Alt-Block entfernt; `_enforce_retention` prunt `nq_raw_slow` |
| [`config/systemd/pv-nq-analysis.service`](../../config/systemd/pv-nq-analysis.service) + `.timer` | **neu** — Netzereignis-Analyse (tägl. 00:30) |
| [`config/systemd/pv-nq-primary-cap.service`](../../config/systemd/pv-nq-primary-cap.service) + `.timer` | **neu** — Event-Kappung (tägl. 00:40) |
| [`scripts/install_nq_services.sh`](../../scripts/install_nq_services.sh) | **neu** — rollenbewusster Installer |
| [`doc/llm/cards/netzqualitaet-nq-aggregation.card.md`](../llm/cards/netzqualitaet-nq-aggregation.card.md) | Changes/`last_review` |
| [`doc/TODO.md`](../TODO.md) | NQ-Abschnitt (PRIO 1 + Folgeaufgaben) |

**Verifikation:** `ast.parse` aller berührten Module OK; `nq_config.json` valide;
Primary-Schema erzeugt `nq_raw_slow`; Harmonik-Aggregationskaskade auf Temp-DB
grün; Installer `bash -n` + Unit-Parsing OK.

Offene Aufgaben stehen ausschließlich in [`doc/TODO.md`](../TODO.md) (Abschnitt
„NQ-Modul (Rolle N)").

---

## 9. Aktivierung & Verifikation (2026-07-13)

Nach Freigabe („alle Erlaubnisse") wurde die Pipeline in Betrieb genommen.

**Durchgeführte Schritte:**

1. **Primary-Timer installiert + aktiviert** via `scripts/install_nq_services.sh`
   → `pv-nq-agg-transfer`, `pv-nq-aggregate`, `pv-nq-energy-rollup`,
   `pv-nq-analysis`, `pv-nq-primary-cap` (`enable --now`, `list-timers` bestätigt).
2. **Host-Auflösung gehärtet:** `_tech_host` in `nq_agg_transfer.py` **und**
   `nq_energy_rollup.py` fallen jetzt auf `config.NQ_TECH_IP` zurück (wie
   `tech_read.py`) — vorher scheiterten CLI-Läufe ohne `.infra.local`-Env
   („Network is unreachable" gegen den anonymisierten Default).
3. **Tech-Code war veraltet:** Der Tech-Poller lief seit 2026-07-12 ohne
   Harmonik-Thread (`nq_poller.py` ohne `_slow_thread`; `pac_live.py` ohne
   Harmonik-Maps). Das gesamte `nq/`-Paket + `config/nq_config.json` wurde per
   `rsync` (git-tracked, ohne Daten) auf Tech deployt und `pv-nq-poller` neu
   gestartet.
4. **tmpfs-Schema-Migration:** Die alte `/dev/shm/nq_cache.db` hatte ein
   veraltetes `nq_raw_medium` (`ts` statt `ts_ms`) → Insert-Fehler. Tabellen
   `nq_raw_medium` + `nq_raw_slow` wurden verworfen (transient) und vom neuen
   Poller korrekt neu angelegt; `nq_energy_raw` blieb erhalten.

**Verifiziertes Ergebnis (Live):**

| Stufe | Nachweis |
|---|---|
| Tech Fast/Medium | `nq_raw_fast`/`nq_raw_medium` wachsen (~5 Zeilen/s = 200 ms) |
| Tech Harmonik | `nq_raw_slow` füllt (I + U_LN + U_LL × 3 Phasen × 16 Ordnungen) |
| Transfer | `agg_written`/`harm_written` > 0 (Skalare **und** Harmonische) |
| Primary-Aggregat | `nq_agg_10s` 62 k, `nq_5min` 2135, `nq_hourly` 210, `nq_daily` 70; U_L1N ≈ 237 V |
| Primary-Harmonik | `nq_5min` (meas≠'') = 144 (z. B. I-L1 H1 = 1,90 A, H3 = 0,46 %) |
| Analyse | `analyze_day` läuft (0 Events = ruhiges Netz) |
| Timer | 5 `pv-nq-*`-Timer enabled + terminiert |

**Rest-Hinweis:** `nq_capping` meldet zyklisch „stale Event-Zeilen gelöscht" —
erwartet, weil die **Event-Snippet-Übertragung** (`nq_event_transfer.py`) noch
fehlt (event=1-RAW wird nach 1 h vom Sicherheitsnetz gekappt). Abgedeckt durch
den TODO „Event-Snippet-Pipeline fertigstellen".

**Neu erkannte Betriebsrisiken (→ TODO):** (a) Tech hat **keinen automatischen
Code-Sync** (driftete ~1 Tag) — Mechanismus nötig; (b) tmpfs-Tabellen migrieren
bei Schemaänderung nicht automatisch (`CREATE IF NOT EXISTS`) → Poller-Neustart
nach Schemaänderung braucht Drop/Neuanlage der betroffenen tmpfs-Tabellen.
