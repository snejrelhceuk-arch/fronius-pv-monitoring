# WP2 — Aggregation: Fixpunkt-Zähler + Transienten (NQ2)

**Priorität:** High (kritischer Pfad)  
**Dauer:** ~6 h  
**Abhängig:** WP0 (Datenhygiene)

---

## Kontext

Du arbeitest am pv-system (Rolle N, PAC4200). Lies zuerst **AGENTS.md**, dann:
- `doc/netzqualitaet/NQ2_ROADMAP.md` §6.2 (WP2-Scope)
- `doc/dev_prompt/NQ2-Prompt.md` (Fixpunkt-Zähler Tag/Monat/Jahr; Transienten)
- `nq/transfer/nq_energy_rollup.py` (bestehend: tägliche Rollup)
- `nq/collector/nq_energy.py` (compute_daily, COUNTERS)
- `nq/aggregate/nq_aggregate.py` (Kaskade 10s→5min→hourly→daily)
- `nq/schema/nq_primary_schema.sql` (nq_energy_daily schema + neue Tabellen)
- `nq/schema/nq_tech_schema.sql` (nq_agg_10s für Transienten-Berechnung)
- `config/nq_config.json` (retention + event_filter)

---

## Aufgaben (3 Blöcke)

### 1. Fixpunkt-Zählertabellen: Monats- & Jahres-Ebene

**Problem:** Momentan nur nq_energy_daily (00:00–00:00 localtime). NQ2 verlangt auch:
- **nq_energy_monthly:** 1.→1. (00:00–00:00 localtime), Monatsdelta.
- **nq_energy_yearly:** 1.1.→1.1. (00:00–00:00 localtime), Jahresdelta.
- Beide: (Bezug Wh, Einspeisung Wh, Blindarbeit, Scheinarbeit, Zeitstempel).

**Aktion:**

a) **`nq/schema/nq_primary_schema.sql` erweitern:**
   ```sql
   CREATE TABLE IF NOT EXISTS nq_energy_monthly (
       month               TEXT PRIMARY KEY,   -- YYYY-MM (z.B. "2026-07")
       wh_imp_start    REAL, wh_imp_end    REAL, wh_imp_delta    REAL,
       wh_exp_start    REAL, wh_exp_end    REAL, wh_exp_delta    REAL,
       varh_imp_start  REAL, varh_imp_end  REAL, varh_imp_delta  REAL,
       varh_exp_start  REAL, varh_exp_end  REAL, varh_exp_delta  REAL,
       vah_start       REAL, vah_end       REAL, vah_delta       REAL,
       src             TEXT,   -- 'counter' | 'reset_fallback' | 'partial'
       n_samples       INTEGER,
       created_ts      INTEGER NOT NULL
   );
   
   CREATE TABLE IF NOT EXISTS nq_energy_yearly (
       year                TEXT PRIMARY KEY,   -- YYYY (z.B. "2026")
       wh_imp_start    REAL, wh_imp_end    REAL, wh_imp_delta    REAL,
       wh_exp_start    REAL, wh_exp_end    REAL, wh_exp_delta    REAL,
       varh_imp_start  REAL, varh_imp_end  REAL, varh_imp_delta  REAL,
       varh_exp_start  REAL, varh_exp_end  REAL, varh_exp_delta  REAL,
       vah_start       REAL, vah_end       REAL, vah_delta       REAL,
       src             TEXT,
       n_samples       INTEGER,
       created_ts      INTEGER NOT NULL
   );
   ```

b) **`nq/transfer/nq_energy_rollup.py` erweitern:**
   - Neue Funktionen: `rollup_month(month: str)`, `rollup_year(year: str)`.
   - Logik: Hole day_start-Checkpoint von 1.→1. und day_end-Checkpoint von 30./31.→1. → Delta.
   - Beide idempotent: `INSERT OR REPLACE`.
   - Systemd-Timer neu:
     - `pv-nq-energy-rollup-month.timer`: `00:10 1.→1. Tag` (cron: `0 0 1 * *` → systemd `*-*-01T00:10:00`)
     - `pv-nq-energy-rollup-year.timer`: `00:10 1.1. Tag` (cron: `0 0 1 1 *` → systemd `*-01-01T00:10:00`)

   ```python
   def rollup_month(month: str) -> dict:
       """Rollup Monats-Delta aus daily checkpoints."""
       # month = "2026-07"
       month_start = f"{month}-01 00:00:00"
       month_end = next_month_start(month)  # "2026-08-01 00:00:00"
       
       ts_start = int(time.mktime(parse_datetime(month_start)))
       ts_end = int(time.mktime(parse_datetime(month_end)))
       
       daily = compute_month_delta(ts_start, ts_end)  # Analogon zu compute_daily
       # Speichere in nq_energy_monthly
   ```

c) **Systemd-Units anlegen (gitignore; real Betreiber-Pfade):**
   ```ini
   # /etc/systemd/system/pv-nq-energy-rollup-month.service
   [Unit]
   Description=PV NQ Energy Monthly Rollup
   After=pv-web.service
   
   [Service]
   Type=oneshot
   User=pi
   ExecStart=/usr/bin/python3 -m nq.transfer.nq_energy_rollup --month YYYY-MM
   StandardOutput=journal
   StandardError=journal
   
   # /etc/systemd/system/pv-nq-energy-rollup-month.timer
   [Unit]
   Description=PV NQ Energy Monthly Rollup Timer
   
   [Timer]
   OnCalendar=*-*-01 00:10:00
   Persistent=true
   
   [Install]
   WantedBy=timers.target
   ```

**Verifikation:**
- `SELECT * FROM nq_energy_monthly WHERE month='2026-07';` → Daten sichtbar nach Rollup.
- `nq_energy_yearly` analog.

---

### 2. Transienten messen & in nq_5min speichern

**Problem:** Momentan nur min/avg/max je 5min-Bucket. NQ2: auch Transienten erfassen (z.B. Spannungssprung 3 V in <1 s).

**Concept:**
- Transiente = schnelle Nulldurchgangs-Änderung in U oder I.
- Metriken je 5min-Fenster:
  - `trans_pos_count`: Anzahl pos. Spannungssprünge (z.B. >3 V in 200 ms).
  - `trans_neg_count`: Anzahl neg. Spannungssprünge.
  - `slew_avg_v_per_s`: durchschn. Anstiegsgeschwindigkeit ΔU/Δt.
  - `slew_max_v_per_s`: max. Anstiegsgeschwindigkeit.
  - Analog für Strom: `trans_pos_i_count`, `trans_neg_i_count`, `slew_avg_a_per_s`, `slew_max_a_per_s`.

**Aktion:**

a) **`nq_agg_10s` erweitern (auf Tech, vor Transfer nach Primary):**
   - Neu: beim Flush je 10-s-Bucket Transienten berechnen + speichern.
   - Oder: separate Tabelle `nq_transient_10s` mit ts, phase, count_pos, count_neg, slew_avg, slew_max.

b) **Transiente-Detektor in `nq/collector/nq_poller.py`:**
   ```python
   def _detect_transients_in_window(raw_rows, window_s=300):  # 5min
       """Analysiere nq_raw_fast über Fenster; zähle Sprünge."""
       transients = {}
       for phase in ['L1', 'L2', 'L3']:
           u_col = f'u_{phase.lower()}'
           i_col = f'i_{phase.lower()}'
           
           u_values = [r[u_col] for r in raw_rows if u_col in r]
           i_values = [r[i_col] for r in raw_rows if i_col in r]
           
           trans_u_pos, trans_u_neg, slew_u = analyze_jumps(u_values, threshold_v=3.0, dt_ms=200)
           trans_i_pos, trans_i_neg, slew_i = analyze_jumps(i_values, threshold_a=5.0, dt_ms=200)
           
           transients[phase] = {
               'trans_u_pos': trans_u_pos, 'trans_u_neg': trans_u_neg,
               'slew_u_avg': slew_u[0], 'slew_u_max': slew_u[1],
               'trans_i_pos': trans_i_pos, 'trans_i_neg': trans_i_neg,
               'slew_i_avg': slew_i[0], 'slew_i_max': slew_i[1],
           }
       return transients
   ```

c) **4h-Transfer ergänzen:**
   - `nq/transfer/nq_agg_transfer.py` speichert nicht nur nq_agg_10s → Primary, sondern auch berechnete Transienten-Aggregate.
   - Oder: speichere Transienten-Metriken direkt in `nq_agg_10s` als `quantity='trans_...'` (Long-Format).

d) **`nq_5min` erweitern:**
   ```sql
   -- Neue Spalten in nq_5min:
   trans_pos_u_l1, trans_neg_u_l1, slew_u_l1_avg, slew_u_l1_max,
   trans_pos_i_l1, trans_neg_i_l1, slew_i_l1_avg, slew_i_l1_max,
   -- ... wiederholt für L2, L3
   ```
   Oder Long-Format (wie `nq_agg_10s`): `(ts, quantity='trans_pos_u_l1', vavg, vmin, vmax, ...)`

e) **Aggregation → `nq_hourly`/`nq_daily`:**
   - Transienten aggregieren nicht sinnvoll (Sum oder Max je Stufe).
   - Logik: `trans_pos_u_l1` aus 5min: Summe über Stunde = `SUM(trans_pos_u_l1)` für hourly.
   - Oder: Median/Max, je nach Anwendungsfall.

f) **Config-Parameter:**
   ```json
   "event_filter": {
     "trans_threshold_v": 3.0,
     "trans_threshold_a": 5.0,
     "trans_dt_ms": 200
   }
   ```

**Verifikation:**
- Synthetischer Test: Schreibe manuell Datensätze mit 32 A-Sprung in nq_raw_fast.
- Aggregation: `SELECT trans_pos_i_l1 FROM nq_5min WHERE ...;` → Nicht-NULL-Wert.
- Extremen-Test: extremer Stromsprung erzeugt (Heizpatrone EIN) → sollte in `trans_pos_i_l*` sichtbar.

---

### 3. 5min-RAW-Retention 90 Tage + Kappung

**Aufgabe:** Stellen sicher, dass 5min-RAW lange genug lebt für VLF-Analysen, aber nicht SD über~Bord lädt.

a) **Config aktuell:** `retention.primary_5min_days = 90`. OK.

b) **Enforcement in Aggregation:**
   - Nach täglicher `_run_5min`-Aggregation: `DELETE FROM nq_5min WHERE ts < now - 90d`.
   - Optional: vor `_run_hourly`, damit hourly nicht auf verwaiste 5min zugreift.

c) **Logging:** `nq_ingest_log` oder separater Log dokumentiert Retention-Pruning.

**Verifikation:**
- `SELECT COUNT(*) FROM nq_5min;` + `SELECT MIN(ts), MAX(ts) FROM nq_5min;` → Alter ~90 d.

---

## Abhängigkeiten & Blockaden

- WP0 muss abgeschlossen (Tier-Benennung klargestellt).
- WP3 wartet auf WP2 (Tooltip-Spiegelung braucht Fixpunkt-Zähler).
- WP5 wartet auf WP2 (Transienten-Darstellung im Chart).

## Definition of Done

- [ ] `nq_energy_monthly`, `nq_energy_yearly` Tabellen angelegt (Primary-Schema).
- [ ] `rollup_month(month)`, `rollup_year(year)` implementiert, idempotent.
- [ ] Systemd-Timer `pv-nq-energy-rollup-month.timer` + `-year.timer` erstellt (gitignore).
- [ ] Erste Monats-/Jahres-Rollup getestet (synthetische Daten oder Produktion).
- [ ] Transiente-Detektor `_detect_transients_in_window()` implementiert.
- [ ] `nq_agg_10s` oder `nq_raw_slow` erweitert um Transient-Metriken.
- [ ] `nq_5min` um Transienten-Spalten erweitert.
- [ ] Transfer-Logik Transienten von Tech nach Primary.
- [ ] Aggregation: Transienten in hourly/daily aggregiert (SUM oder MAX).
- [ ] Retention 90 d auf `nq_5min` enforced + geloggt.
- [ ] Config: `trans_threshold_v`, `trans_threshold_a`, `trans_dt_ms` konfigurierbar.
- [ ] Synthetischer Test: Spannungssprung 32 A in Raw → sichtbar in `trans_pos_i_l*`.
- [ ] `python3 -m py_compile nq/transfer/nq_energy_rollup.py nq/collector/nq_poller.py nq/aggregate/nq_aggregate.py`.
- [ ] Doc-Check exit 0; Card-Update last_review=2026-07-13.

---

## Commit-Message

```
feat(nq/wp2): Energy Fixpoints (Monthly/Yearly) + Transient Detection

- Add nq_energy_monthly, nq_energy_yearly tables + rollup functions
- Implement rollup_month(month), rollup_year(year) — idempotent, from daily checkpoints
- Add systemd timers pv-nq-energy-rollup-{month,year}.timer (cron: 1.*T00:10, 1.1.*T00:10)
- Detect transients in 5min windows: count_pos, count_neg, slew_avg, slew_max per phase
- Extend nq_agg_10s with transient metrics (or separate nq_transient_10s)
- Extend nq_5min schema: columns trans_pos_u_l1..trans_i_l3, slew_*
- Aggregate transients to hourly/daily (SUM or MAX per interval)
- Enforce 5min retention 90 days + logging in nq_ingest_log
- Config: trans_threshold_v, trans_threshold_a, trans_dt_ms

NQ2-Roadmap §6.2. Fixpoint counters at exact boundaries for tooltip mirroring.
Transients captured for drift detection & grid event analysis.
Blocks: WP3, WP5. Depends: WP0.

Related: doc/netzqualitaet/NQ2_ROADMAP.md#WP2
```

