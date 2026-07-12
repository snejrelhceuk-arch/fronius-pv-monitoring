# Prompt: Experimentelle NQ-Analyse (HF/NF/VLF — Mustererkennung, Filterung, Darstellung)

**Kontext:** Du arbeitest am pv-system (repo `{REPO_DIR}`,
branch `feat/reformation-wp-bridge`). Lies zuerst AGENTS.md vollständig. Dann:
- `doc/netzqualitaet/NQ_MODUL.md` §8 (Analysetools)
- `doc/netzqualitaet/NQ_TESTS_UND_DB.md` §9 (Event-Schnipsel), §10 (Status)
- `doc/netzqualitaet/METHODEN.md` (bisherige NQ-Methoden: DFD, Boundary-Events)
- `nq/schema/nq_primary_schema.sql` (nq_events, nq_agg_10s, nq_5min, nq_hourly, nq_daily)
- `nq/analysis/nq_events.py` (Skelett → Implementierung)
- `netzqualitaet/nq_analysis.py` (Legacy DFD-Code als Vorbild für NF-Mustererkennung)
- `doc/llm/cards/netzqualitaet-nq-analysis-events.card.md`
- `doc/llm/INDEX.md` (für Card-Pflicht)

**Voraussetzung:** Die Aggregate-Kaskade (AGGREG-Prompt) muss laufen —
die Analyse arbeitet auf `nq_5min/hourly/daily`.

---

## Zielbild (aus Nutzergespräch)

Der Nutzer möchte belastbare, automatisierte Aussagen über drei Frequenzbereiche:

### Ebene 1: Hochfrequente Ereignisse (HF_local) — Transienten, THD, Oberwellen
Analysiert `nq_agg_10s` und `nq_event_fast/medium` (Event-Schnipsel).

**Methoden:**
- **THD-Spike-Detektion**: THDu_Lx oder THDi_Lx > konfigurierbarer Schwelle
  über N aufeinanderfolgende Buckets → `kind='thd_spike'`
- **U↔I-Korrelation** (Kausalitätspfad lokaler Verbraucher vs. Netz):
  Wenn ΔU_Lx und ΔIs_Lx gleichzeitig springen und ΔU/ΔI dem lokalen Schleifenwiderstand
  entspricht → `origin='lokal'` (eigene Last/PV). Wenn ΔU ohne gleichzeitiges ΔI →
  `origin='netzseitig'`. Methode: Pearson-Korrelation im Ereignisfenster.
- **Phasenunsymmetrie-Anstieg**: Unbal_U > 2 % oder Unbal_I > 10 % → Event
- **Verzerrungsstrom**: Idist_Lx als Indikator für nichtlineare Lasten

**Wichtige Einschränkung (Nutzeranforderung):**
„Die Spannungen müssen so gut es geht gefiltert werden, um interne Stromänderungen
als Ursache der Spannungsänderungen zu beseitigen."
Konkret: Abziehe den erwarteten Spannungsabfall durch eigene Lasten
(ΔU_internal = ΔI × Z_loop, wobei Z_loop = Schleifenimpedanz aus `config/nq_impedance.json`)
vom gemessenen ΔU ab. Nur das **Residual ΔU_net** wird für die Netz-Mustererkennung
verwendet. `config/nq_impedance.json` liegt bereits vor (Impedanz-Messdaten).

### Ebene 2: Niederfrequente Ereignisse (NF_global) — s..min-Muster
Analysiert `nq_agg_10s` (10s-Buckets) und `nq_5min`.

**Methoden:**
- **Frequenz-Gradienten** (df/dt): rollendes Fenster 60 s → df/dt > 0.05 Hz/min →
  Frequenz-Nadir (`kind='freq_nadir'`) oder -Gipfel. Bekannt aus ENTSO-E Ereignissen.
- **DFD an 15-min-Handelsgrenzen** (Diskrete Frequenzänderung): Muster aus dem
  Legacy-Code `netzqualitaet/nq_analysis.py:_detect_dfd` adaptieren. An :00 :15 :30 :45
  treten regelmäßig kleine f-Sprünge durch Fahrplanwechsel auf — diese sind *normal*
  und von echten Störungen zu trennen.
- **Spannungs-Gradientenfilter**: Trafoumschaltungen (diskrete U-Sprünge von ±1–3 V
  in <1 s, periodisch alle 15 min oder bei Lastwechseln) müssen herausgefiltert werden:
  Methode: Median-Filter über ±5 min + Schwellwert-Klassifikation
  (`thres_tap_v` in config). Nur wenn Sprung außerhalb des Trafo-Musters →
  echtes Netz-Ereignis.
- **Spannungs-RMS-Drift**: U_LxN außerhalb EN-50160-Band (207..253 V = ±10% von 230 V)
  über 10 min → Event `kind='u_rms_violation'`.

### Ebene 3: Sehr niederfrequente Muster (VLF) — Tages/Wochen/Saisonmuster
Analysiert `nq_5min`, `nq_hourly`, `nq_daily`.

**Methoden:**
- **Tages-/Wochenprofil**: rollender Median je Stunde des Tages (24-h-Profil, 7-d-Profil)
  für U, f, THDu. Abweichungen > 2σ vom Langzeitprofil → Anomalie-Flag.
- **Changepoint-Erkennung**: CUSUM oder Ruptures (optional mit `ruptures`-Bibliothek,
  falls vorhanden) für dauerhafte Shifts in U-Mittelwert oder THD-Basislinie.
  Alternativ: vereinfachte Variante als rollende Mittelwert-Differenz (kein Extern-Paket).
- **Saisonale Drift**: Monats-Mittelwert U vs. Vorjahres-Median (sobald >12 Monate Daten).
- **Langfristiger PF-Trend**: cos φ-Drift als Indikator für Blindleistungsänderung.

### Abgleich mit pv-system
**Nutzeranforderung:** „Die Analyse schneller Änderungen aller elektrischen Größen
sollte immer mit dem pv-system abgeglichen werden. Bekannte Verbraucher können leicht
als Verursacher identifiziert oder ausgeschlossen werden."

Konkret: Beim Erstellen eines HF-Events prüfe in der Produktions-DB (read-only):
- Schaltet die Heizpatrone (FritzDECT-Steckdose) zu diesem Zeitpunkt? → origin='lokal'
- Springt die WP (W_Imp_WP)? → origin='lokal'
- Ändert sich der Wattpilot-Ladestrom? → origin='lokal'
Wenn keine dieser Quellen aktiv → origin='unklar' oder 'netzseitig'.
API: read-only `raw_data` oder `data_1min` aus der Produktions-DB (wie Legacy nq_analysis).

---

## Implementierungsreihenfolge
1. `nq/analysis/nq_events.py:analyze_day(day)` — Orchestrator
2. `nq/analysis/nq_hf.py` — HF: THD-Spikes, U↔I-Korrelation, Residual-Filterung
3. `nq/analysis/nq_nf.py` — NF: DFD, f-Gradienten, Trafofilter, U-Band-Überwachung
4. `nq/analysis/nq_vlf.py` — VLF: Tages-/Wochenprofil, Changepoint
5. Event-Vergleich mit pv-system (Hilfsfunktion `_check_pvsystem_cause`)

---

## Architektur-Grenzen (Rolle N)
- Read-only auf `nq/db/` und `data.db`
- Kein Schreibpfad außer `nq_events` (+ abgeleitete Tabellen)
- Keine externen Bibliotheken ohne Check in `requirements.txt`
  (kein `scipy`, `numpy`, `ruptures` ohne Prüfung der installierten Pakete)
- Keine Halluzination von Registeradressen; keine Spekulation über nicht gemessene Größen

## Parameter in config/nq_config.json erweitern (analysis-Block)
```json
"analysis": {
  "thd_u_spike_pct": 5.0,
  "thd_i_spike_pct": 80.0,
  "u_band_min_v": 207.0,
  "u_band_max_v": 253.0,
  "df_gradient_hz_per_min": 0.05,
  "dfd_window_s": 180,
  "thres_tap_v": 2.0,
  "z_loop_source": "config/nq_impedance.json",
  "vlf_sigma_threshold": 2.0,
  "pvsystem_crosscheck": true
}
```

## Darstellung und Warnung (Zukunft)
- Events → `nq_events`-Tabelle (vorhanden); Severity 0..1 (normierte Überschreitung)
- Darstellung in Maschinenraum-Chart: Marker-Icons (⚡ HF, 〰 NF, 📉 VLF)
- Warnung: Integration in `diagnos/` (Diagnos-Alert-System, Rolle D) sobald Severity > 0.8
  über mehrere aufeinanderfolgende Tage → E-Mail-Notification (analog diagnos/health.py)

## Definition of Done
- `analyze_day(day)` läuft für Testtag, schreibt Events in `nq_events`
- Idempotent (Doppel-Lauf ändert Ergebnis nicht)
- Residual-Filterung nachweislich aktiv (Test: simulierter WP-Einschaltvorgang)
- DFD-Detektion an 15-min-Grenzen mit Unterscheidung Normal/Anomalie
- VLF-Profil-Anomalie für Testtag korrekt erkannt
- doc-check exit 0 (Card `netzqualitaet-nq-analysis-events` aktualisiert)
