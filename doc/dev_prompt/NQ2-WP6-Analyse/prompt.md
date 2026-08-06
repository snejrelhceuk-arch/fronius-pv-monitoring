# WP6 — Analyse & Mustererkennung (HF/NF/VLF, experimentell, NQ2)

**Priorität:** Medium (experimentell, iterativ)  
**Dauer:** ~12 h (initial; weitere Iteration möglich)  
**Abhängig:** WP2 (Aggregate), WP5 (Chart für Darstellung)

---

## Kontext

NQ2: „Bevor weitere Analysen sinnvoll sind, müssen wir interne und externe Werte trennen...FILTERN geht mit den sauber getrennten Werten noch viel weiter...Mustererkennung auf 4h-Block sofort...modular-offen coden...Ziel A) Aufschwingen im europäischen Netz erkennen, Reflexionen an Netzgrenzen, LF-Schwingungspakete."

Basis: Bestehende Skelette `nq/analysis/nq_{events,hf,nf,vlf}.py` + `EXPERIMENTAL/prompt.md`.

---

## Aufgaben (5 Blöcke)

### 1. Intern/Extern-Trennung bidirektional (Residual-Filterung)

**Konzept:** Schleifenimpedanz Z_loop nutzen, um eigene Last (ΔI × Z) aus gemessenem ΔU zu filtern.

a) **`config/nq_impedance.json` (existiert):**
   ```json
   {
     "z_loop_ohms": {
       "l1": 0.15,   // Beispiel: 150 mΩ pro Phase (Kabel-Hin-Zurück)
       "l2": 0.15,
       "l3": 0.15
     }
   }
   ```

b) **Residual-Berechnung in `nq/analysis/nq_hf.py`:**
   ```python
   def compute_residual_voltage(u_delta, i_delta, z_loop):
       """
       ΔU_net = ΔU_gemessen - ΔI × Z_loop
       Falls ΔU_net ≈ 0: interner Stromsprung.
       Falls ΔU_net >> 0: netzseitige Spannungsänderung.
       """
       du_internal = i_delta * z_loop
       du_net = u_delta - du_internal
       return du_net, du_internal
   ```

c) **Event-Origin setzen:**
   - Wenn `abs(du_net) < 1.0 V`: `origin = 'lokal'` (eigene Last).
   - Wenn `abs(du_net) > 3.0 V`: `origin = 'netzseitig'` (Netz).
   - Sonst: `origin = 'unklar'`.
   - Speichern in `nq_events.origin`.

d) **Umgekehrte Nutzung:**
   - Wenn externes Event (du_net Sprung) erkannt: Abzug von internen Werten für Bereinigung.
   - Beispiel: Wenn Netz 2V springt, aber interne Last auch springt → Residual zeigt nur echte interne Komponente.

**Verifikation:**
- Test: WP-Einschaltvorgang erzeugen (32 A Sprung) → Residual-Filter setzt `origin='lokal'`.
- Test: Netzsprung simulieren (extern) → `origin='netzseitig'`.

---

### 2. HF-Detektor (Transienten, THD, U↔I-Korrelation)

a) **Bestehend (`nq/analysis/nq_hf.py`):** THD-Spike-Detektion + Phasenunsymmetrie.

b) **Erweiterung: U↔I-Korrelation (Kausalität):**
   - Im Event-Fenster (z.B. 60s): Pearson-Korrelation zwischen `d(U_L1)/dt` und `d(I_L1)/dt`.
   - Wenn Korr > 0.7: `origin='lokal'` (Ursache-Folge).
   - Wenn Korr < 0.3: `origin='netzseitig'` (unabhängig).

c) **Verzerrungsstrom-Detektor:**
   - Wenn `Idist_Lx` (Verzerrungsstrom) plötzlich steigt → nichtlineare Last aktiv.
   - Flag: `has_nonlinear_load = 1` im Katalog.

d) **Modular-offen:** Neue HF-Muster ohne Code-Änderung:
   - Config-Parameter ergänzen (z.B. `hf_correlation_threshold`, `hf_idist_threshold`).
   - Skelett für zukünftige Muster: `def detect_pattern_X(bucket): return {...}`

**Verifikation:**
- Event-Trigger U-Sprung + I-Sprung gleichzeitig → Korrelation >0.7 → origin=lokal.
- Idist-Anstieg → Flag sichtbar in Katalog.

---

### 3. NF-Detektor (DFD, f-Gradienten, Trafo-Filter, U-Band)

a) **Frequenz-Gradienten (df/dt):**
   - Fenster: 60 s rollendes (3 × 20-s-Buckets aus 5min-Aggregat).
   - Wenn `|df/dt| > 0.05 Hz/min`: Frequenz-Nadir-Event, `kind='freq_nadir'`.
   - Severity: `abs(df/dt) / 0.1` (normalisiert auf 0..1).

b) **DFD an 15min-Handelsgrenzen:**
   - Legacy `nq/legacy/nq_analysis.py:_detect_dfd` adaptieren.
   - At :00 :15 :30 :45 regelmäßig kleine f-Sprünge durch Fahrplanwechsel.
   - Filter: Wenn f-Sprung <0.5 Hz AND Uhrzeit ∈ [HH:00, HH:15, HH:30, HH:45] ± 5min: markiere als `kind='dfd_normal'` (nicht anomale).
   - Wenn Sprung außerhalb Muster: `kind='dfd_anomaly'` → Event.

c) **Spannungs-Gradientenfilter (Trafo-Tap-Schaltung):**
   - Diskrete U-Sprünge ±1–3 V in <1 s, periodisch alle 15 min → Trafo-Umschaltung (normal).
   - Filter: Median über ±5 min + Schwellwert-Klassifikation (`thres_tap_v` in config).
   - Nur wenn außerhalb Trafo-Muster: echtes Netz-Ereignis, `origin='netzseitig'`.

d) **Spannungs-Band-Überwachung (EN-50160):**
   - 10-min-Fenster: Mittenwert je 10min.
   - Wenn U_LxN <207 V oder >253 V (per config): `kind='u_rms_violation'`, `severity=...`
   - Permanent-Flag: `has_voltage_violation` im Katalog.

e) **Modular-offen:** Config-Parameter für alle Schwellen + zukünftige NF-Muster.

**Verifikation:**
- f-Nadir erkannt bei steiler df/dt.
- DFD an :00 + :15 Grenzen als normal markiert; außerhalb als Anomalie.
- U-Sprung ±2 V um :30 Trafo-Zeit → filter out (nicht im Event-Katalog).
- U-Band-Verletzung erkannt + geloggt.

---

### 4. VLF-Detektor (Tages-/Wochen-/Saisonprofile, Changepoint)

a) **Tages-Profil:**
   - Für jede Stunde des Tages (00–23): Median je Phase/Größe über 30 Tage (rollierend).
   - Normalwert = Median, Anomalie = Abweichung > 2σ.
   - Wenn heute 12:00 U_L1 außerhalb Norm: `kind='daily_anomaly'`, `metrics={'expected': 230, 'actual': 245}`.

b) **Wochenprofil:**
   - Analog: Median je Wochentag (Mo–So).
   - Erkennt saisonale Muster (Wochenende vs. Wochentag).

c) **Changepoint-Erkennung (CUSUM oder vereinfacht):**
   - Rollender Mittelwert über 7 Tage + Std.
   - Wenn MW plötzlich um >1 σ driftet: Changepoint erkannt, `kind='u_drift_positive'` oder `'u_drift_negative'`.
   - Timestamp: Punkt der Kursänderung.

d) **Saisonale Drift (>12 Monate Daten):**
   - Monats-Median U_LN Jahresvergleich (Jan 2025 vs. Jan 2026).
   - Wenn Diff >10 V: mögliche Jahreszeit-Drift (Laständerung, Netz-Upgrade, etc.).

e) **Modular-offen:** Config `vlf_sigma_threshold`, `vlf_changepoint_z`, `vlf_drift_threshold`.

**Verifikation:**
- Tages-Anomalie erkannt, wenn Wert >2σ vom Median.
- Wochenprofil-Abweichung logged.
- Changepoint erkannt nach 7-Tage-Drift.

---

### 5. Integration & pv-system-Cross-Check (read-only)

a) **Orchestrator `analyze_day(day)` in `nq/analysis/nq_events.py`:**
   ```python
   def analyze_day(day: str):
       """Analyze 4h-blocks over day; run HF/NF/VLF; populate nq_events."""
       blocks = get_4h_blocks(day)
       for block_ts in blocks:
           # HF-Analyse
           hf_events = nq_hf.detect_hf_patterns(block_ts)
           # NF-Analyse
           nf_events = nq_nf.detect_nf_patterns(block_ts)
           # VLF (für VLF nur am Ende des Tages, nicht je 4h)
       vlf_events = nq_vlf.detect_vlf_patterns(day)
       # Katalog füllen
       for evt in [*hf_events, *nf_events, *vlf_events]:
           insert_event_catalog(evt)
       return len(hf_events), len(nf_events), len(vlf_events)
   ```

b) **pv-system-Cross-Check (read-only aus data.db):**
   ```python
   def check_pvsystem_cause(event_ts, phase):
       """Prüfe in data.db: War Heizpatrone/WP/Wattpilot aktiv?"""
       # Read-only SELECT auf raw_data / data_1min
       # FritzDECT-Steckdose kontrolle (Power >500 W)?
       # W_Imp_WP springt?
       # Wattpilot-Ladestrom ändert sich?
       if any_match:
           return 'lokal'
       return 'unklar' or 'netzseitig'
   ```

c) **Timer: `pv-nq-analysis.service`** (täglich 00:30, nach Transfer/Aggregation).
   - Läuft idempotent (INSERT OR REPLACE).
   - Bei Fehler: log + weiter (kein Fail-Stop).

d) **Marker-Speicherung:**
   - Jedes erkannte Muster → Eintrag in `nq_events` mit Muster-`kind`, Severity, Metrics (JSON).
   - Im NQ-Chart (WP5): Marker-Icons (⚡ HF, 〰 NF, 📉 VLF) zeigen Muster-Typ.

e) **Bericht-Generierung (optional, Phase 2):**
   - Text-Report: `/netzqualitaet/berichte?day=YYYY-MM-DD` oder monatlich.
   - Zusammenfassung: häufigste Muster, Trends, Empfehlungen.

---

## Architektur-Grenzen

- Read-only auf Primary `nq/db/`, read-only auf Produktions-DB `data.db`.
- Keine neuen externen Abhängigkeiten ohne requirements.txt-Check.
- Keine Halluzination von Messgrößen (nur PAC4200 + Master-SM).

---

## Config-Erweiterung (analysis-Block)

```json
"analysis": {
  "thd_u_spike_pct": 5.0,
  "thd_i_spike_pct": 80.0,
  "hf_correlation_threshold": 0.7,
  "hf_idist_threshold": 2.0,
  
  "df_gradient_hz_per_min": 0.05,
  "dfd_window_s": 180,
  "dfd_tolerance_hz": 0.5,
  "dfd_normal_times": [":00", ":15", ":30", ":45"],
  "dfd_normal_window_min": 5,
  
  "thres_tap_v": 2.0,
  "u_band_min_v": 207.0,
  "u_band_max_v": 253.0,
  
  "vlf_sigma_threshold": 2.0,
  "vlf_changepoint_z": 2.5,
  "vlf_drift_threshold_v": 10.0,
  
  "z_loop_source": "config/nq_impedance.json",
  "pvsystem_crosscheck": true
}
```

---

## Definition of Done

- [ ] Residual-Filterung (`compute_residual_voltage()`) implementiert.
- [ ] HF-Detektor: THD-Spike + U↔I-Korrelation + Verzerrungsstrom.
- [ ] NF-Detektor: df/dt Gradienten + DFD-Filter (an 15min) + Trafo-Tap-Filter + U-Band.
- [ ] VLF-Detektor: Tages-/Wochen-Profil + Changepoint + saisonale Drift.
- [ ] `analyze_day(day)` orchestriert alle Detektoren; schreibt `nq_events` idempotent.
- [ ] pv-system-Cross-Check (read-only) implementiert.
- [ ] Alle Detektoren modular-offen (Config-Parameter ohne Code-Änderung erweiterbar).
- [ ] Marker-Icons (⚡ HF, 〰 NF, 📉 VLF) im Chart sichtbar.
- [ ] Systemd-Timer `pv-nq-analysis.service/.timer` (00:30 täglich).
- [ ] Test: ein HF-Event + ein NF-Event + ein VLF-Event erkannt + im Katalog.
- [ ] Config `analysis`-Block erweitert; alle Parameter konfigurierbar.
- [ ] `python3 -m py_compile nq/analysis/nq_{events,hf,nf,vlf}.py`.
- [ ] Doc-Check exit 0; Card-Update last_review=2026-07-13.

---

## Commit-Message

```
feat(nq/wp6): Analysis & Pattern Recognition (HF/NF/VLF, experimental, modular-open)

- Implement residual-voltage filtering: ΔU_net = ΔU_measured - ΔI × Z_loop
  → distinguish lokal vs. netzseitig origin bidirectionally
- HF-detector: THD-spike, U↔I-correlation (Pearson >0.7 → lokal), Verzerrungsstrom
- NF-detector: df/dt gradients, DFD at 15min boundaries (normal vs. anomaly),
  Trafo-tap-filter (±1-3V discretes), U-band violation (EN-50160 207-253V)
- VLF-detector: Daily profile (hourly median, anomaly >2σ), weekly profile,
  changepoint detection (7d roll + 1σ drift), seasonal drift (>12mo data)
- Implement analyze_day(day): 4h-block HF/NF + end-of-day VLF; populate nq_events idempotently
- Add pv-system cross-check (read-only data.db): identify lokal cause (Heizpatrone, WP, Wattpilot)
- Modular-open: all thresholds configurable (no code change for new patterns)
- Add systemd timer pv-nq-analysis (00:30 daily, after transfer/aggregation)
- Marker-icons in chart: ⚡ (HF), 〰 (NF), 📉 (VLF)
- Extend config/nq_config.json: hf_correlation_threshold, df_gradient, dfd_*, vlf_*, etc.

NQ2-Roadmap §6.6. Pattern recognition: oscillations, grid reflexions, LF-packets.
Experimental, iterative. Depends: WP2, WP5. Related: EXPERIMENTAL/prompt.md + NQ2_ROADMAP.md#WP6
```

