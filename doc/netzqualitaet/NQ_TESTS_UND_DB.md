# NQ — Weitere Tests & Datenbank-Aufbau (Rolle N)

**Stand:** 2026-07-11
**Bezug:** [`NQ_MODUL.md`](NQ_MODUL.md) (Architektur), [`MESSTECHNIK.md`](MESSTECHNIK.md)
(verifizierte Register), [`PAC4200-Modbus.md`](PAC4200-Modbus.md) (vollständige
Registerreferenz).

Dieses Dokument bündelt (1) den **weiteren Testbedarf** am PAC4200 und (2) den
**Datenbank-Aufbau** inkl. **Differenzmethode für alle Zählerwerte**, GFS-Backup
und Härtung. Es ist die Umsetzungsgrundlage für Phase 1/2.

---

## 1. Verifizierungsstand (2026-07-11)

**Live gegen `192.0.2.111` bestätigt** (FLOAT32 big-endian, Adresse ab 1):

- **Betriebswerte** (U/I/P/Q/S, PF, f, Mittel/Total, Unsymmetrie): Adr. 1–73.
- **cos φ (Grundschwingung)** L1/L2/L3: Adr. 243/245/247.
- **THD-U L-N** je Phase: Adr. 261/263/265; **THD-U L-L**: Adr. 43/45/47.
- **THD-I** je Phase: **Adr. 267/269/271** (live 38–45 %). *Korrektur:* 49/51/53
  sind undefiniert (NaN) — die frühere Lage war falsch.
- **Neutralleiterstrom** I_N: Adr. 295.
- **Energiezähler** (FLOAT64 @801..817): Wirk Bezug/Lieferung, Blind
  Bezug/Lieferung, Schein.

**Noch offen:** Modbus-Adressen der **Einzelharmonischen 2..64** (U + I). Die
Registerreferenz [`PAC4200-Modbus.md`](PAC4200-Modbus.md) enthält THD, Phasenlage,
Verzerrungsstrom und gleitende Mittel — **aber kein Einzelharmonik-Spektrum**.
Solange diese Adressen nicht vorliegen, bleibt der **Slow-Block deferred**.

---

## 2. Weiterer Testbedarf

| Test | Ziel | Status |
|---|---|---|
| Refresh-Raten Fast/Medium | reale Aktualisierung ≤250 ms bestätigen | **erledigt** (Phase 0) |
| Frequenz-Kadenz | ~6–10 s bestätigen | **erledigt** |
| THD-I-Lage | 267/269/271 statt 49/51/53 | **erledigt** (korrigiert) |
| **Zähler-Differenzmethode** | Tages-Deltas + Reset-Erkennung | **startet jetzt** (§4) |
| **Zählervergleich** PAC↔Master-SM↔iMS | Abweichungen quantifizieren | **startet jetzt** (§5) |
| Einzelharmonik-Adressen | Slow-Block-Register bestimmen | **offen** (Siemens-Doku / Feldtest) |
| 48-h-Dauertest Slow-Block | Refresh Harmonische 2..64 | **erst nach** Adress-Klärung sinnvoll |
| Min/Max/Demand-Blöcke | Geräte-Extrema vs. Eigenberechnung | optional (Adr. 75–201 / 483–543) |

---

## 3. Datenbank-Aufbau

Zwei-Host-Muster (wie [`NQ_MODUL.md`](NQ_MODUL.md)): **Tech** sammelt RAM-first,
**Primary** hält die dauerhafte, aggregierte DB auf SD und schreibt **selten
(1×/Tag)**.

### 3.1 Tech (tmpfs, RAM-first) — [`../../nq/schema/nq_tech_schema.sql`](../../nq/schema/nq_tech_schema.sql)

- `nq_raw_fast` / `nq_raw_medium` / `nq_raw_slow` — Messwert-RAW (72 h Ring).
- `nq_agg_10s` — 3–10 s-Aggregat (min/avg/max), Transfer-Basis.
- **`nq_energy_raw`** — kumulative Energiezähler-Snapshots (langsamer Takt),
  Basis der Differenzmethode. Von der Kappung ausgenommen bis Transfer.

### 3.2 Primary (SD, 1×/Tag) — [`../../nq/schema/nq_primary_schema.sql`](../../nq/schema/nq_primary_schema.sql)

- Aggregatkaskade `nq_agg_10s → nq_5min → nq_hourly → nq_daily`.
- Event-RAW `nq_event_*` (Originalauflösung, dauerhaft).
- **Energie/Differenzmethode:** `nq_energy_daily`, `nq_energy_checkpoint`,
  `nq_ims_reading`, `nq_energy_compare` (siehe §4/§5).
- Monatsdatei `nq/db/nq_YYYY-MM.db` (Rotation wie Legacy `netzqualitaet/db/`).

---

## 4. Differenzmethode (alle Zählerwerte) — ab Start

**Prinzip (konsistent zur Produktion,** vgl. [`../../aggregate_1min.py`](../../aggregate_1min.py),
[`../../aggregate_daily.py`](../../aggregate_daily.py) `_counter_or_fallback`,
[`../../scripts/capture_energy_checkpoints.py`](../../scripts/capture_energy_checkpoints.py)):

Energiezähler sind **kumulativ**. Der Verbrauch/Ertrag eines Intervalls ist die
**Differenz** zweier Zählerstände:

$$\Delta E_{[t_1,t_2]} = E(t_2) - E(t_1)$$

- **RAW:** `nq_energy_raw` speichert die kumulativen Stände (ts, wh_imp, wh_exp,
  varh_imp, varh_exp, vah) im langsamen Takt.
- **Tag:** `nq_energy_daily` hält je Zähler **start / end / delta** plus `src`:
  - `src='counter'` — Normalfall `delta = end − start`.
  - `src='reset_fallback'` — Zähler-Reset erkannt (`delta < 0` oder Sprung
    `end−start ≫ Σ(Teil-Deltas)`) → Fallback auf Summe der Teil-Deltas.
  - `src='partial'` — Tag unvollständig (Start/Ende fehlt).
- **Checkpoints:** `nq_energy_checkpoint` fixiert die kumulativen Stände zum
  **day_start** (localtime) → Langfrist-Abgleich (Monats-/Jahresbilanz gegen
  Delta-Summen; Muster `energy_checkpoints` der Produktion).
- **Aggregation:** Energie wird **nicht** über min/avg/max aggregiert, sondern
  als **Summe der Deltas** (Tag → Monat → Jahr). Delta-Konsistenz prüfbar analog
  [`../../tools/validate_energy_data.py`](../../tools/validate_energy_data.py):
  `Σ(deltas) == end − start` (Toleranz ~1 Wh).

**Reset-Erkennung (Pseudocode, gespiegelt aus `_counter_or_fallback`):**

```text
if end is None or start is None:      -> src='partial', delta=Σ(teil-deltas)
elif (end - start) < -MIN:            -> src='reset_fallback' (negativ)
elif (end - start) > RESET_FACTOR*Σ:  -> src='reset_fallback' (Sprung)
else:                                  -> src='counter', delta=end-start
```

---

## 5. Zählervergleich: PAC4200 ↔ Master-SM ↔ iMS

**Ziel:** dauerhafte, belastbare Gegenüberstellung dreier Messquellen am PCC.

| Quelle | Herkunft | Ablage |
|---|---|---|
| **PAC4200** | eigene Messung (Differenzmethode) | `nq_energy_daily` |
| **Master-SM** | Fronius Primär-Smart-Meter (`W_Imp_Netz`/`W_Exp_Netz`), **read-only** aus Produktions-DB | `nq_energy_compare` (msm_*) |
| **iMS** | Netzbetreiber-Zähler (manuell/Portal/Foto) | `nq_ims_reading` → `nq_energy_compare` (ims_*) |

`nq_energy_compare` hält je Tag beide Abweichungen (PAC−MasterSM, PAC−iMS) für
Bezug und Lieferung.

> **Offener Befund (2026-07-11):** Der PAC4200 zählt `Wh_imp` und `VAh` hoch,
> aber **`Wh_exp`/`varh_exp` stehen auf 0** trotz Einspeisung. Ursache offen
> (Zähler-Konfiguration Lieferung? Wandler-Richtung?). Der Vergleich gegen
> Master-SM/iMS ist genau das Werkzeug, um das aufzuklären — deshalb **alle
> Zähler ab sofort mitführen**, auch die aktuell auf 0 stehenden.

**Master-SM read-only:** Nur lesend aus der Produktions-DB (Rolle N schreibt
nie in `data.db`). Kein neuer Schreibpfad in die Produktionskette.

---

## 6. GFS-Backup (konsistent mit pv-system)

Analog [`../../scripts/backup_db_gfs.sh`](../../scripts/backup_db_gfs.sh)
(Sohn-Vater-Großvater):

- **Quelle:** die Primary-NQ-Monats-DB `nq/db/nq_YYYY-MM.db` (SD, 1×/Tag frisch).
- **Rotation/Verzeichnisse:** `backup/db/nq/{daily,weekly,monthly,yearly}`.
- **Retention:** wie Produktion — `DAILY_KEEP=7`, `WEEKLY_KEEP=5`,
  `MONTHLY_KEEP=12` (+ yearly).
- **Integrität:** gzip + `PRAGMA integrity_check` + Kerntabellen-Check
  (`nq_daily`, `nq_energy_daily`, `nq_agg_10s`) vor Gültig-Markierung.
- **Offsite:** zusätzliche Kopie nach Pi5-FB/NVMe (wie bestehende GFS-Kopie).
- **Cron (Primary):** im 03:00-Fenster, **nach** dem täglichen NQ-Ingest/Aggregat.
- **Umsetzung:** entweder Schwester-Skript `scripts/backup_nq_gfs.sh` oder
  Erweiterung des bestehenden Laufs; identische Helfer (`load_infra_env.sh`,
  `check_backup_integrity`).

---

## 7. Härtung (Neustart / stale / Prozess / Systemfehler)

Gespiegelt aus den Collector-Mustern der Produktion:

- **Single-Instance:** PID-Lock (`collector/pid_lock.py`-Muster), je Prozess
  eigener Lock (`nq_collector.pid`, `nq_energy.pid`).
- **Neustart-fest:** systemd-Unit mit `Restart=always`, `WatchdogSec`; DB-Öffnen
  mit WAL + `busy_timeout`; Schema idempotent (`CREATE TABLE IF NOT EXISTS`).
- **tmpfs-Verlust bei Reboot (Tech):** akzeptiert — nur RAW/Aggregat im RAM.
  **Energie-Snapshots** werden vor Verlust geschützt, indem der **Tages-Transfer**
  (start/end) **idempotent** und **at-least-once** läuft; day_start-Checkpoint
  sichert den Fixpunkt auf Primary-SD.
- **Stale-Data-Erkennung:** Freshness-Check (jüngster `ts` älter als N× Poll-Takt
  → Alarm/Statusflag), analog Diagnos-Freshness. Live-Anzeige `/pac4200` bleibt
  read-only und markiert Unerreichbarkeit statt hart zu failen.
- **Monotonie-/Plausibilität:** Energiezähler auf Rücksprünge prüfen (Muster
  [`../../scripts/check_energy_counters.py`](../../scripts/check_energy_counters.py)),
  implausible Messwerte (U, f außerhalb Bereich) verwerfen.
- **Systemfehler:** Modbus-Timeouts/Reconnects tolerant (Fehler zählen, nicht
  crashen); Kappung schützt tmpfs vor Überlauf; „echte Lücken sichtbar lassen"
  (Kappungs-/Ingest-Log statt stiller Datenverlust).
- **Rolle-N-Grenze:** niemals Schreibzugriff auf `data.db`/Aktoren; PAC4200 nur
  Modbus `read`.

---

## 8. Phasen-Status

| Phase | Inhalt | Status |
|---|---|---|
| 0 | Refresh-Raten (Fast/Medium/Freq) | erledigt (bekannte Register) |
| 1a | **Energie-Snapshotter (Differenzmethode) auf Tech** | **PRODUKTIV** (systemd, seit 2026-07-12) |
| 1b | **Fast/Medium-Poller (nq_agg_10s + RAW + Event-Vorfilter) + Ring-Kappung** | **PRODUKTIV** (systemd `pv-nq-poller`, seit 2026-07-12) |
| 2a | **Energie-Tages-Rollup + Zählervergleich auf Primary** | **PRODUKTIV** (systemd-Timer 00:05) |
| 2b | RAW/Aggregat-Transfer + Kaskade + GFS | Schema steht, Umsetzung folgt |
| 3a | **DB-umschaltbares Charting (Kern-DB / NQ-DB) im Maschinenraum** | **PRODUKTIV** (2026-07-12) |
| 3b | Analyse HF/NF/VLF + Event-Chart-Drilldown | folgt |
| Slow | Einzelharmonische 2..64 | **blockiert** bis Register-Adressen vorliegen |

---

## 9. Event-Schnipsel (kurze Transienten, dauerhaft)

Kurze Ereignisse werden bei Schwellenüberschreitung als **vollständige RAW-Serie
mit allen verfügbaren Größen** dauerhaft gespeichert (nicht aggregiert).

- **Trigger** (aus `event_filter`): Spannungssprung `du_step_v`, Frequenzsprung
  `df_step_hz`, THD-U `thd_u_pct`, Stromsprung `di_step_a`. Um das Ereignis
  herum werden `pre_window_s` / `post_window_s` mitgeschnitten.
- **Maximale Dauer 60 s** (`max_duration_s`) — längere Störungen werden
  gekappt; der Rest ist über die Aggregate (Extremwerte) sichtbar.
- **Wiederholungsfilter/-cutter** (`cooldown_s`, `dedup_same_trigger`): derselbe
  Trigger löst innerhalb des Cooldowns **kein** neues Schnipsel aus
  (`dedup_key` in `nq_events`) — verhindert Sturm-Duplikate.
- **Speicherung:** RAW-Serie in `nq_event_fast/medium/slow` (Originalauflösung),
  Katalogeintrag in `nq_events` mit `ts_start/ts_end`, `duration_s`, `band`,
  `kind`, `trigger`, `peak_quantity`/`peak_value`, `severity`, `has_snippet`.
- **Auffindbarkeit:** Das Event zeigt sich in den Aggregaten als **Extremwert**
  (min/avg/**max**). Charts markieren die betroffenen Buckets (Zeitüberlappung
  mit `nq_events`) und bieten einen **Drill-down** auf die RAW-Serie des
  Schnipsels. Kein zusätzliches Aggregat-Flag nötig — Zeitbereichs-Join genügt.

---

## 10. Betrieb / Deployment (Stand 2026-07-12)

**Tech (Pi4-Tech, RAM-first)** — Energie-Snapshotter läuft produktiv:

- Unit: [`../../config/systemd/pv-nq-energy.service`](../../config/systemd/pv-nq-energy.service)
  (`Restart=always`, `EnvironmentFile=.infra.local` → `PV_PAC_IP`, read-only PAC,
  Ziel `/dev/shm/nq_cache.db`, Takt `polling.energy_s`=60 s).
- Härtung: Auto-Start bei Boot (`enabled`), Neustart bei Crash, tmpfs-only
  (keine SD-Nutzdaten), `NoNewPrivileges`/`ProtectSystem=full`.

**Primary (Pi5-Primary, SD)** — Tages-Rollup läuft produktiv:

- Units: [`../../config/systemd/pv-nq-energy-rollup.service`](../../config/systemd/pv-nq-energy-rollup.service)
  + `.timer` (`OnCalendar=00:05`, `Persistent=true` → holt verpasste Läufe nach).
- Rollup: [`../../nq/transfer/nq_energy_rollup.py`](../../nq/transfer/nq_energy_rollup.py)
  holt Tech-Snapshots read-only (SSH), schreibt `nq_energy_daily` +
  `nq_energy_checkpoint` + `nq_energy_compare` (PAC vs Master-SM) in
  `nq/db/nq_YYYY-MM.db`.

**Viewing:** Read-only Live-Anzeige `/pac4200` (Geräte-Clone, F1–F4 + Menü, alle
Live-Bildschirme). Netzqualität-Live-Tableau `/netzqualitaet/live` (Pendant zu
„Echtzeit", alle Messwerte als Datentabelle). **DB-umschaltbares Charting** im
Maschinenraum (`/maschinenraum` = Kern-DB „Echtzeit", `/maschinenraum?db=nq` =
NQ-DB „Netzqualität"): dasselbe Programm, DB-Umschalter oben, Feldkategorien +
Einheiten je Quelle. NQ-Zeitreihe read-only von Tech (`nq/tech_read.py` →
`/api/nq/realtime_smart`, Wide-Format wie `/api/realtime_smart`).

Navigationshierarchie: Flow → Maschinenraum → { Echtzeit (Kern-DB), Netzqualität
(NQ-DB) → Screens (Live-Tableau), PAC4200 (Gerät) }.

**Offen für Vollbetrieb:** RAW-Transfer/Aggregat-Kaskade auf Primary + GFS (2b),
Event-Chart-Drilldown + HF/NF/VLF-Analyse (3b).
