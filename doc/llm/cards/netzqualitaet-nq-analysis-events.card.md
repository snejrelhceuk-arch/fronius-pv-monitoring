---
title: NQ Analysetools Netzereignisse (HF/NF/VLF)
domain: netzqualitaet
role: N
applyTo: "nq/analysis/**"
tags: [netzqualitaet, nq, analyse, events, harmonische, frequenz, rolle-n]
status: experimental
last_review: 2026-07-12
changes:
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Analyse-Skelett + Ereignis-Katalog (nq_events) dokumentiert (Implementierung Phase 3).
---

# NQ Analysetools Netzereignisse

## Zweck
Ableitung **belastbarer Aussagen zur Netzqualität** aus den aggregierten
NQ-Daten + Event-RAW auf **Primary**. Klassifiziert Ereignisse in drei Bänder und
schreibt sie nach `nq_events`: lokal-hochfrequent (`HF_local`),
global-niederfrequent (`NF_global`), sehr niederfrequent (`VLF`).

## Code-Anchor
- **Orchestrator (Tageslauf):** `nq/analysis/nq_events.py:analyze_day`
- **Ereignis-Katalog + Datenquellen:** `nq/schema/nq_primary_schema.sql` (`nq_events`, `nq_5min`, `nq_hourly`, `nq_daily`, `nq_event_*`)
- **Gemeinsame Helfer:** `nq/nq_common.py`
- **Methodik-Vorbild:** Legacy `netzqualitaet/nq_analysis.py` (DFD, Boundary-Events)

## Inputs / Outputs
- **Inputs (read-only):** `nq_agg_10s`/`nq_5min`/`nq_hourly`/`nq_daily` + `nq_event_*` aus `nq/db/`.
- **Outputs:** klassifizierte Zeilen in `nq_events` (`band`, `kind`, `severity`, `origin`, `metrics`-JSON).

## Analyse-Ebenen
- **HF_local:** THD-/Harmonik-Auffälligkeiten (Ordnungen 2..64, U+I), kurze Transienten, **Korrelation U↔I_lokal** (lokale Rückwirkung vs. netzseitig).
- **NF_global:** Frequenz-/RMS-Muster (s–min), df/dt-Gradienten/Nadir, **DFD an 15-min-Handelsgrenzen**.
- **VLF:** Tages-/Wochen-/Saisonprofile, langsame U/f/THD-Drift, Changepoints, Kalenderprofile.

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
