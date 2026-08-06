---
title: NQ Analysetools Netzereignisse (HF/NF/VLF)
domain: netzqualitaet
role: N
applyTo: "nq/analysis/**"
tags: [netzqualitaet, nq, analyse, events, harmonische, frequenz, rolle-n]
status: stable
last_review: 2026-08-06
changes:
	- 2026-08-06 (Musteranalyse-Datensatz): Neuer **sauberer Netz-Signaldatensatz** `nq/analysis/nq_pattern.py:build_range`/`build_day`/`backfill` → `nq_pattern_5min` (Primary). Residual-Deconvolution (ΔU_int = I·(R·cosφ + X·sinφ), Z aus `nq_impedance.json`) entfernt **interne** (hinter-PCC) Lasteffekte → netzseitige U + f + PF + φ + `origin` (intern/extern). `analyze_day` triggert `build_day` (best-effort). Rückwirkend erzeugt (6526 Buckets, 2026-07-12…08-06). API `routes/pac4200.py:/api/nq/pattern`.
	- 2026-08-06: Methodik-Verweis auf `nq/legacy/nq_analysis.py` umgestellt (Modul `netzqualitaet/` → `nq/legacy/` konsolidiert); Kommentar in `nq/analysis/nq_nf.py` nachgezogen.
	- 2026-07-16 (l): **Dual-Modus: 4h HF/NF + täglich VLF.** `nq/analysis/nq_events.py` Refactor: neue `analyze_window(ts_start, ts_end, bands=[...])` für Fenster-basierte Analysen (HF/NF alle 4h), alte `analyze_day(day)` → Backward-Compat-Wrapper; CLI: `--hours N --bands HF_local,NF_global` für 4h-Läufe. Systemd: `pv-nq-analysis` = VLF täglich 00:30 (Vortag), `pv-nq-analysis-hf-nf` = HF/NF alle 4h (00:30,04:30,...,20:30, aktuelle Daten). Idempotent per INSERT OR REPLACE; Duplikat-Key bleibt Trigger+Stunden-Bucket.
	- 2026-07-14 (d): **Events lesen keine 10s-Skalare mehr.** `nq/analysis/nq_events.py:_load_ts_series` nutzt jetzt `nq_5min` (meas='', phase=0, ord=0) als Skalarquelle; Meldungstexte entsprechend angepasst.
	- 2026-07-14 (c): **NQ2 WP4.** Der `nq_events`-Katalog wird zusätzlich vom Schnipsel-Transfer `nq/transfer/nq_event_transfer.py` befüllt (`derive_event`): `has_snippet`, `peak_quantity`/`peak_value`, normierte `severity`, Cooldown- + Ähnlichkeits-Dedup (<24 h → nur Beschreibung), Log-Cap `event_max_count`=10000. Drill-down-RAW liegt in `nq_event_fast`/`nq_event_medium` (API `/api/nq/event/<id>`). `analyze_day` (HF/NF/VLF) bleibt unverändert der Tages-Klassifikator.
	- 2026-07-12: Vollimplementierung HF/NF/VLF-Detektoren (nq_hf.py, nq_nf.py, nq_vlf.py, nq_events.py). analysis-Block in nq_config.json ergänzt.
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Analyse-Skelett + Ereignis-Katalog (nq_events) dokumentiert (Implementierung Phase 3).
---

# NQ Analysetools Netzereignisse

## Zweck
Ableitung **belastbarer Aussagen zur Netzqualität** aus den aggregierten
NQ-Daten + Event-RAW auf **Primary**. Klassifiziert Ereignisse in drei Bänder und
schreibt sie nach `nq_events`: lokal-hochfrequent (`HF_local`),
global-niederfrequent (`NF_global`), sehr niederfrequent (`VLF`).

## Code-Anchor
- **Orchestrator (Fenster + Tag):** `nq/analysis/nq_events.py:analyze_window` (Fenster-Basis), `analyze_day` (Tag-Wrapper, Backward-Compat)
- **CLI mit Dual-Modus:** `nq/analysis/nq_events.py:main` — `--date YYYY-MM-DD` (täglich VLF), `--hours N --bands ...` (4h HF/NF)
- **Systemd Timer-Dual:** `pv-nq-analysis.timer` (00:30, VLF täglich), `pv-nq-analysis-hf-nf.timer` (00,04,08,12,16,20:30, HF/NF 4h)
- **HF-Detektoren:** `nq/analysis/nq_hf.py` — `run_hf`, `detect_thd_spikes`, `detect_ui_correlation`
- **NF-Detektoren:** `nq/analysis/nq_nf.py` — `run_nf`, `detect_dfd_events`, `detect_freq_gradient`, `detect_tap_and_u_steps`, `detect_u_rms_violations`
- **VLF-Detektoren:** `nq/analysis/nq_vlf.py` — `run_vlf`, `detect_profile_anomalies`, `detect_changepoints`
- **Ereignis-Katalog + Datenquellen:** `nq/schema/nq_primary_schema.sql` (`nq_events`, `nq_5min`, `nq_hourly`, `nq_daily`, `nq_event_*`)
- **Konfiguration:** `config/nq_config.json` → `analysis`-Block
- **Impedanz:** `config/nq_impedance.json` (R=163 mΩ, X=251 mΩ, Z=299 mΩ)
- **Musteranalyse-Datensatz (residual-bereinigt):** `nq/analysis/nq_pattern.py:build_range` → `nq_pattern_5min` (netzseitige U/f/PF/φ, `origin`); Serve: `routes/pac4200.py:api_nq_pattern` (`/api/nq/pattern`)
- **Gemeinsame Helfer:** `nq/nq_common.py`
- **Methodik-Vorbild:** Legacy `nq/legacy/nq_analysis.py` (DFD, Boundary-Events)

## Inputs / Outputs
- **Inputs (read-only):** `nq_5min`/`nq_hourly`/`nq_daily` + `nq_event_*` aus `nq/db/`.
- **Outputs:** klassifizierte Zeilen in `nq_events` (`band`, `kind`, `severity`, `origin`, `metrics`-JSON).

## Analyse-Ebenen
- **HF_local:** THD-Spikes (vmax > Schwelle über ≥2 aufeinanderfolgende 10s-Buckets), U↔I-Residual-Filterung (ΔU_net = ΔU − ΔI × Z_loop, Pearson-Korrelation → lokal/netzseitig/unklar).
- **NF_global:** DFD an :00/:15/:30/:45-Grenzen (normal vs. Anomalie), rollendes df/dt (60s, Hz/min → freq_nadir/freq_peak), Tap-Filter (Sprünge in ±30s der 15-min-Grenze → ignoriert), U-Band EN 50160 (207..253V, ≥2 × 5min-Buckets → u_rms_violation).
- **VLF:** Stündlicher z-Score gegen 30-Tage-Rollprofil (|z| > sigma_thr → profile_anomaly), CUSUM-Changepoint (7d-pre vs. 7d-post auf nq_daily, z > vlf_changepoint_z → changepoint).

## Konfiguration (config/nq_config.json → "analysis")
| Parameter | Default | Bedeutung |
|---|---|---|
| `thd_u_spike_pct` | 5.0 | THD-U Spike-Schwelle (%) |
| `thd_i_spike_pct` | 80.0 | THD-I Spike-Schwelle (%) |
| `du_net_step_v` | 1.5 | RMS(ΔU_net) Schwelle Residualfilter (V) |
| `u_band_min_v` | 207.0 | EN 50160 Untergrenze (V) |
| `u_band_max_v` | 253.0 | EN 50160 Obergrenze (V) |
| `df_gradient_hz_per_min` | 0.05 | df/dt-Schwelle (Hz/min) |
| `dfd_window_s` | 180 | Fenster vor/nach DFD-Grenze (s) |
| `dfd_anomaly_hz` | 0.1 | DFD anomaly ab dieser Amplitude (Hz) |
| `thres_tap_v` | 2.0 | Tap-Filter U-Sprung-Schwelle (V) |
| `vlf_sigma_threshold` | 2.0 | Profil-Anomalie z-Score-Schwelle |
| `vlf_changepoint_z` | 2.5 | Changepoint z-Score-Schwelle |
| `pvsystem_crosscheck` | true | Cross-Check mit pv-system DB |

## Invarianten
- **Read-only** auf `nq/db/`; einziger Schreibpfad ist `nq_events` (+ optionale Reports).
- **Idempotenz:** erneuter Lauf für denselben Tag ersetzt dessen Events (kein Duplikat).
- Schwellen/Parameter konfigurierbar (`analysis`-Block in `config/nq_config.json`), nicht hart kodiert.
- `origin` sauber trennen: `lokal` | `unklar` | `netzseitig` (nur bei belastbarer U↔I-Evidenz festlegen).

## No-Gos
- Kein Schreibpfad in `data.db`/Produktion oder Aktoren.
- Messrauschen nicht als Erkenntnis werten; sparse Tage/Mindest-Samplezahlen verwerfen.
- Kein Overengineering; klare, testbare Detektor-Funktionen statt generischer Frameworks.

## Häufige Aufgaben
- Neuen Detektor ergänzen → Funktion in `nq/analysis/nq_events.py` (oder `nq_hf.py`/`nq_nf.py`/`nq_vlf.py`) + Registrierung im Orchestrator.
- Schwellen kalibrieren → `analysis`-Parameter in `config/nq_config.json`.
- Ereignis-Typ ergänzen → `kind`-Wert dokumentieren + `metrics`-Schema anpassen.

## Bekannte Fallstricke
- Aggregierte min/avg/max verdecken kurze Transienten → für HF auf Event-RAW zurückgreifen.
- Frequenz-/Spannungsartefakte durch Messkette (Implausible Extrema filtern, vgl. Legacy-Maxima-Filter).
- 15-min-Grenzen über `localtime` prüfen (DST-Kanten).

## Verwandte Cards
- [`netzqualitaet-nq-collector.card.md`](./netzqualitaet-nq-collector.card.md)
- [`netzqualitaet-nq-aggregation.card.md`](./netzqualitaet-nq-aggregation.card.md)
- [`netzqualitaet-analysis.card.md`](./netzqualitaet-analysis.card.md)

## Human-Doku
- `doc/netzqualitaet/NQ_MODUL.md` (§8)
- `doc/netzqualitaet/METHODEN.md`
- `.github/prompts/nq-3-analysis-tools.prompt.md`
