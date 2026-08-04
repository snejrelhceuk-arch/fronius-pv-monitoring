# NQ-Pipeline — Ist-Stand & Reboot-Sicherheit (Audit 2026-08-04)

**Rolle N (Netzqualität, PAC4200).** Zweck dieses Dokuments: konsolidierter Ist-Stand
der Datenerfassung/-übertragung/-analyse als Startpunkt für die Fortsetzung der
NQ-Entwicklung in der nächsten Session. Alle Angaben verifiziert am Code-Stand 2026-08-04.

Hosts (Doku-IPs): **Pi4-Tech** `192.0.2.181` (Collector, RAM-first) · **Pi5-Primary**
`192.0.2.204` (Aggregation/Analyse/SD-Persistenz).

---

## 1. Erfassung (Tech, RAM-first)

- **PAC4200-Reader:** [nq/pac_live.py](../../nq/pac_live.py) — Modbus TCP read-only am PCC
  (`192.0.2.111:502`), roher Client [collector/modbus_client.py](../../collector/modbus_client.py)
  (`RawModbusClient`, **kein pymodbus**).
- **Poller-Dienst:** [nq/collector/nq_poller.py](../../nq/collector/nq_poller.py) →
  `pv-nq-poller.service` (Tech). Dual-Thread: Fast-Loop 200 ms (Block A+B: U/I/P/Q/S/PF/
  cosφ/THD/Freq/Unbal) + Medium-Loop 1 s (Harmonik H1–H31 @9001/@11001/@22001).
- **Energie-Dienst:** [nq/collector/nq_energy.py](../../nq/collector/nq_energy.py) →
  `pv-nq-energy.service` (Tech), 300 s-Snapshots der FLOAT64-Zähler (Wh/varh/VAh imp/exp).
- **RAM-DB:** `/dev/shm/nq_cache.db` (Live-Stand 2026-08-04: **222 MB**, `journal_mode=WAL`,
  `synchronous=NORMAL`). Schema: [nq/schema/nq_tech_schema.sql](../../nq/schema/nq_tech_schema.sql).

| Tabelle | Inhalt | Retention |
|---|---|---|
| `nq_raw_fast` | 200 ms Skalare | 12 h |
| `nq_raw_medium` | 1 s Freq/Harmonik-Roh | 12 h |
| `nq_raw_slow` | Harmonik H1–H31 (long) | 12 h |
| `nq_raw_max` | Max-Werte (300 s) | 12 h |
| `nq_5min` | 5min-Aggregate (min/avg/max/std, 35 Größen) | ~12 h (dann Transfer) |
| `nq_transient_5min` | Sprung-/Slew-Zähler pro 5 min | 12 h |
| `nq_energy_raw` | Energiezähler-Snapshots | daily |
| `nq_limit_alerts` | Grenzwert-Alarme | runtime |

- **Retention/Capping:** [nq/collector/nq_capping.py](../../nq/collector/nq_capping.py) —
  Zeit-Cap 12 h (Event-Zeilen ausgenommen), Event-Stale-Cap 3600 s, Größen-Cap bei >1200 MB
  (tmpfs-Budget 1500 MB). **Keine SD-Persistenz auf Tech.**

---

## 2. Übertragung Tech → Primary (Pull-Modell)

- **5min/Harmonik-Transfer:** [nq/transfer/nq_agg_transfer.py](../../nq/transfer/nq_agg_transfer.py)
  → `pv-nq-agg-transfer.timer` **alle 4 h** (`00,04,08,12,16,20:10`, `Persistent=true`).
  Primary zieht `nq_5min` + event-markierte `nq_raw_slow` via SSH (`admin@PV_TECH_IP`),
  idempotenter `INSERT OR REPLACE`, danach Löschung des Fensters auf Tech (at-least-once).
  Triggert Tech-seitig [nq/aggregate/nq_transients.py](../../nq/aggregate/nq_transients.py).
- **Event-Transfer:** [nq/transfer/nq_event_transfer.py](../../nq/transfer/nq_event_transfer.py)
  → `pv-nq-event-transfer.timer` **alle 5 min** (`OnBootSec=3min`, `OnUnitActiveSec=5min`).
  Zieht `event=1`-Segmente → `nq_events` + `nq_event_fast/medium/slow`. Dedup 120 s Cooldown,
  gleicher Trigger ≥24 h nur Log. `max_duration_s=300`.
- **Energie-Rollup:** [nq/transfer/nq_energy_rollup.py](../../nq/transfer/nq_energy_rollup.py)
  → daily 00:05 (+ monthly 1., yearly 1.1.). Differenzmethode mit Reset-Erkennung →
  `nq_energy_daily` + `nq_energy_checkpoint`.
- **Primary-Storage:** Monats-DBs `nq/db/nq_YYYY-MM.db` (SD). Retention: 5min 90 d, hourly
  365 d, daily 3650 d, rawslow 12 h. **Primary-NQ ist SD-persistent → kein Reboot-Verlust.**

---

## 3. Aggregation & Analyse (Primary)

- **Kaskade:** [nq/aggregate/nq_aggregate.py](../../nq/aggregate/nq_aggregate.py) →
  `pv-nq-aggregate.timer` alle 4 h :15. `nq_raw_slow → nq_5min → nq_hourly → nq_daily`
  (min/avg/max/std; Harmonik meas×phase×ord).
- **Analyse-Orchestrator:** [nq/analysis/nq_events.py](../../nq/analysis/nq_events.py).
  HF/NF alle 4 h :30 (`--bands HF_local,NF_global`), VLF daily 00:30 (`--date yesterday`).
  Loop-Impedanz aus [config/nq_impedance.json](../../config/nq_impedance.json); Ursachen-
  Cross-Check gegen Produktions-DB (WP/Heizpatrone/Wattpilot aktiv → `origin=lokal`).
- **Primary-Cap:** [nq/transfer/nq_primary_cap.py](../../nq/transfer/nq_primary_cap.py) →
  daily 00:40. Events >90 d bzw. >10000 löschen (Kaskade auf `nq_event_*`).

**Ausführungsreihenfolge je Zyklus:** transfer(:10) → aggregate(:15) → analyse(:30) → cap(:40).

### Implementiert vs. geplant (Analyse)

| Feature | Status | Datei |
|---|---|---|
| THD-Spike-Detektion | ✅ | [nq/analysis/nq_hf.py](../../nq/analysis/nq_hf.py) `detect_thd_spikes()` |
| U↔I-Korrelation (Pearson-r, origin lokal/netz) | ✅ | nq_hf.py `detect_ui_correlation()` |
| Residual-Filter ΔU_net = ΔU − ΔI·Z_loop | ✅ | nq_hf.py (Z aus nq_impedance.json) |
| DFD an 15-min-Grenzen + df/dt-Nadir | ✅ | [nq/analysis/nq_nf.py](../../nq/analysis/nq_nf.py) |
| U-Band EN 50160 (207–253 V) | ✅ | nq_nf.py `detect_uband_violations()` |
| VLF Profil-Anomalie (30-d Stunden-z-Score) | ✅ | [nq/analysis/nq_vlf.py](../../nq/analysis/nq_vlf.py) |
| CUSUM-Changepoint | ⚠️ partiell (7-d Mean-Shift, kein scipy) | nq_vlf.py |
| **Trafo-Tap-Filter** (diskrete ±2–3 V @Grenzen) | ❌ geplant (`thres_tap_v` da, Logik stub) | nq_nf.py |

→ Abgleich Ziel-Vision: [doc/dev_prompt/ANFORDERUNGEN.md](../dev_prompt/ANFORDERUNGEN.md) §8 +
[doc/dev_prompt/NQ2-WP6-Analyse/prompt.md](../dev_prompt/NQ2-WP6-Analyse/prompt.md).

---

## 4. Reboot-Sicherheit Tech — Analyse & Entscheidung

**Problem:** Tech hält alles in tmpfs; ein Reboot verliert `nq_cache.db`. Verlust =
un-transferierte 5min-Aggregate (bis 4 h) + Event-Fenster (bis 5 min) + der komplette
RAM-Rohstrom (200 ms/1 s). Primary-Daten sind sicher (SD).

**Bewertung SD-Persistierung (alle 4–8 h):**
- SD-Platz unkritisch (45 GB frei, Snapshot 222 MB). WAL ⇒ Read-Kopie stört den
  PAC→RAM-Schreibprozess **nicht** (kein Writer-Lock).
- **ABER:** widerspricht der bewussten RAM-first-Architektur (SD-Wear minimieren), und der
  Nutzen ist gering — die Wertdaten (5min-Aggregate/Events) sind ohnehin alle 4 h/5 min auf
  Primary; die Rohdaten sind bauartbedingt flüchtig (12-h-Ring, nie langfristig gedacht).

**Entscheidung:** **Kein** periodischer SD-Persist. Stattdessen **Pre-Reboot-Flush** für
planmäßige Reboots + der 4-h-Transfer (`Persistent=true`) begrenzt den Verlust bei
ungeplanten Reboots auf <4 h Aggregate (für Netzqualitäts-Trends akzeptabel).

**Werkzeuge (neu, 2026-08-04):**
- [scripts/pv_nq_flush.sh](../../scripts/pv_nq_flush.sh) — erzwingt Transfer+Aggregation+
  Event-Transfer+Analyse+Cap (auf Primary, zieht von Tech).
- [scripts/pv_tech_safe_reboot.sh](../../scripts/pv_tech_safe_reboot.sh) — Flush → Reboot Tech
  (von Primary). **Tech immer hierüber neu starten, nicht per blankem `sudo reboot`.**

**Graceful-Degradation:** Der Poller ist idempotent/`Restart=always`; nach Reboot startet er
neu, legt Schema per `CREATE TABLE IF NOT EXISTS` an, PAC-Ausfälle blocken max. 0,5 s.
Fehlende Daten führen nicht zum Crash (Aggregation/Analyse überspringen leere Fenster).

---

## 5. Ansatzpunkte nächste Session (NQ-Weiterentwicklung)

1. **Trafo-Tap-Filter** implementieren (nq_nf.py) — diskrete ±2–3 V-Sprünge an 15-min-Grenzen
   sauber aus dem Residual herausrechnen (aktuell nur `thres_tap_v`-Config, Logik stub).
2. **CUSUM-Changepoint** vervollständigen (nq_vlf.py) — aktuell simpler 7-d-Mean-Shift.
3. **Pre-Reboot-Flush** ggf. als Tech-seitigen `shutdown`-Hook ergänzen (falls jemand doch
   direkt auf Tech `reboot`; Pull-Modell macht das nicht-trivial — bewusst offen gelassen).
4. **Datenreduktion/Bänder-Darstellung** (min/max-Fläche + Mittel-Linie) — steht in
   [doc/TODO.md](../TODO.md) unter Netzqualität.
5. **Stale tmpfs-Leichen** auf Tech: `/dev/shm/fronius_data.db` (286 MB, alt) + `nq_test.db`
   belegen tmpfs unnötig; werden beim nächsten Reboot ohnehin geräumt.

**Vollständige Trigger-Referenz (manuell, auf Primary):** siehe
[scripts/pv_nq_flush.sh](../../scripts/pv_nq_flush.sh).
