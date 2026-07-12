---
mode: agent
description: "NQ Phase 3 — Analysetools für Netzereignisse (lokale HF, globale NF, sehr niederfrequente Ereignisse)"
---

# NQ Phase 3 — Analysetools Netzereignisse (Primary)

Du bist Senior-Entwickler am **PV-System**, Rolle **N**. Host: **Pi5-Primary**.

## Pflichtlektüre zuerst
1. [`AGENTS.md`](../../AGENTS.md) — Rollen, No-Gos (read-only ggü. Produktion).
2. [`doc/netzqualitaet/NQ_MODUL.md`](../../doc/netzqualitaet/NQ_MODUL.md) — §8 (Analysetools), Schema-Bezug.
3. [`doc/llm/cards/netzqualitaet-nq-analysis-events.card.md`](../../doc/llm/cards/netzqualitaet-nq-analysis-events.card.md) — Invarianten, Anchor.
4. [`doc/netzqualitaet/METHODEN.md`](../../doc/netzqualitaet/METHODEN.md) — vorhandene Analyseverfahren (DFD, Boundary-Events) als methodische Basis.
5. Schema [`nq/schema/nq_primary_schema.sql`](../../nq/schema/nq_primary_schema.sql) — `nq_agg_10s`, `nq_5min/hourly/daily`, `nq_event_*`, `nq_events`.

## Ziel
Analysetools, die aus den aggregierten NQ-Daten + Event-RAW **belastbare
Aussagen zur Netzqualität** auf drei Ebenen liefern und Ereignisse klassifiziert
nach `nq_events` schreiben (Band `HF_local` | `NF_global` | `VLF`).

## Drei Analyse-Ebenen
- **Lokal / hochfrequent (HF_local):**
  - THD- und Harmonik-Auffälligkeiten (Einzelordnungen 2..64, U + I).
  - Kurze Spannungs-/Strom-Transienten (Fast-/Event-RAW).
  - **Korrelation U↔I_lokal**: unterscheidet lokale Rückwirkung (eigene Last/PV) von netzseitiger Ursache (Strom-getrieben vs. Spannungs-getrieben).
- **Global / niederfrequent (NF_global):**
  - Frequenz- und RMS-Muster im s–min-Bereich; Nadir/Gradienten (df/dt).
  - **DFD an 15-min-Handelsgrenzen** (Muster aus Legacy `netzqualitaet/nq_analysis.py` / METHODEN.md).
- **Sehr niederfrequent (VLF):**
  - Tages-/Wochen-/Saisonprofile von U/f/THD; langsame Drift; Changepoints; Kalenderprofile.

## Zu implementierende Skelette (vorhanden, jetzt füllen)
- [`nq/analysis/nq_events.py`](../../nq/analysis/nq_events.py) — `analyze_day(day)`: Orchestrator, ruft Band-Detektoren, schreibt `nq_events`.
- Weitere Module bei Bedarf: `nq/analysis/nq_hf.py`, `nq/analysis/nq_nf.py`, `nq/analysis/nq_vlf.py` (jeweils reine Detektor-Funktionen, read-only auf NQ-DB).
- Nutze [`nq/nq_common.py`](../../nq/nq_common.py) für DB-Zugriff.

## Fachliche Vorgaben
- **Read-only** auf `nq/db/` — keine Schreibpfade außer in die Analyse-Tabelle `nq_events` (und ggf. abgeleitete Reports).
- Ergebnis je Ereignis: `ts_start/ts_end`, `band`, `kind`, `severity`, `origin` (`lokal`/`unklar`/`netzseitig`), `metrics` (JSON).
- Schwellen/Parameter konfigurierbar (erweitere `config/nq_config.json` um `analysis`-Block, nicht hart kodieren).
- **Statistische Sauberkeit:** sparse Tage / Mindest-Samplezahlen verwerfen (Muster METHODEN.md), Messrauschen nicht als Erkenntnis werten.
- Idempotenz: erneuter Lauf für denselben Tag ersetzt dessen Events (kein Duplikat).
- Keine Overengineering-Helfer; klare, testbare Detektor-Funktionen.

## Optional (nur wenn gefordert)
- Read-only-Report/CLI (`--date`, `--band`) und/oder Anbindung an bestehende `routes/`-Muster (Blueprint, read-only) — **nicht** ohne separate Freigabe scharf schalten.

## Definition of Done
- `python3 -m nq.analysis.nq_events --date YYYY-MM-DD` erzeugt klassifizierte Einträge in `nq_events`, idempotent.
- Detektoren je Band vorhanden, dokumentiert, mit Testdaten belegt.
- Card [`netzqualitaet-nq-analysis-events.card.md`](../../doc/llm/cards/netzqualitaet-nq-analysis-events.card.md) aktualisiert (`last_review` heute, reale Anchor).
- Neue `analysis`-Parameter in [`config/nq_config.json`](../../config/nq_config.json) + [`NQ_MODUL.md`](../../doc/netzqualitaet/NQ_MODUL.md) §8 nachgeführt.
