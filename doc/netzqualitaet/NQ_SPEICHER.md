# NQ-Speicherhaushalt & Datenhaltbarkeit (Rolle N)

**Stand:** 2026-08-08 · Betrifft `nq/db/nq_YYYY-MM.db` (Primary, SD)

Analyse des Platzbedarfs der NQ-Monats-DBs, der Struktur nach Einführung der
permanenten SM-Historie (`nq_sm_15min`) und der Reclaim-Mechanik gegen
SD-Aufblähung. Ergebnis vorweg: **langfristig unkritisch** (~0,6 GB nach 20 a),
sofern der Reclaim (Prune + VACUUM) läuft.

## 1. Tabellenstruktur & Lebensdauer

| Tabelle | Größe/Monat¹ | Retention | Zweck |
|---|---|---|---|
| `nq_5min` | ~49 MB | 90 d (`primary_5min_days`) | 5-min-Aggregat (Skalare + Harmonische) |
| `nq_hourly` | ~4,1 MB | 365 d (`primary_hourly_days`) | Stunden-Aggregat |
| `nq_daily` | ~0,2 MB | 3650 d = 10 a (`primary_daily_days`) | **Tages-Extremwerte** (min/avg/max U, f) |
| `nq_pattern_5min` | ~0,9 MB | keine (permanent) | residual-bereinigter Netz-Signaldatensatz |
| `nq_transient_5min` | ~0,7 MB | keine (permanent) | 5-min-Transienten |
| `nq_events` + Snippets | ~0,1 MB | 90 d / 10 000 Cap | Netzereignis-Katalog + RAW |
| `nq_energy_*` | <0,1 MB | permanent (winzig) | Zähler-Fixpunkte |
| `nq_sm_15min` | ~0,5 MB (nur 2026-01…06) | permanent | **Vor-PAC-SM-Netzqualität** (einmaliger Backfill) |
| ~~`nq_raw_slow`~~ | ~158 MB Churn | 12 h (ephemer) | 1-s-Harmonik-RAW → nach 5-min-Aggregation entbehrlich |
| ~~`nq_agg_10s`~~ | — | **tot** | Legacy 10s-Architektur (entfernt 2026-07-14) |

¹ Gemessen an `nq_2026-07.db` (erster voller PAC-Monat) via `dbstat`.

## 2. Das Aufblähungsproblem (behoben 2026-08-08)

Ein **voller PAC-Monat fror mit ~237 MB ein** — obwohl der langfristig nützliche
Inhalt nur ~6 MB ausmacht. Ursachen:

1. **`nq_raw_slow`** (67 %, ~158 MB): Die 12-h-Retention (`nq_agg_transfer._enforce_retention`)
   greift zeilenlogisch korrekt, aber **SQLite gibt gelöschte Seiten ohne `VACUUM`
   nicht frei** (kein `auto_vacuum`). Der Datei-Peak aus dem 1-s-Harmonik-Churn
   (~6,2 Mio Zeilen/12 h) blieb als Freispeicher stehen.
2. **`nq_agg_10s`** (10 %, ~24 MB): tote Legacy-Tabelle, nur noch in `nq_2026-07.db`
   (letzter Write 2026-07-14, dem Tag der 10s-Architektur-Entfernung).
3. **`nq_5min`** (21 %, ~49 MB): retention-verwaltet (90 d), aber die Alt-Monats-DBs
   froren ein, bevor die Zeilen ausliefen — freie Seiten nach späterem DELETE
   wurden ebenfalls nie zurückgewonnen.

**Ohne Gegenmaßnahme:** 237 MB/Monat × Akkumulation → **~57 GB nach 20 a** →
**würde die 58-GB-SD sprengen.**

## 3. Reclaim-Mechanik

- **Zeilen-Retention** (bestehend): `nq_aggregate` (alle 4 h) löscht
  `nq_5min`/`nq_hourly`/`nq_daily` jenseits der Retention über **alle** Monats-DBs;
  `nq_agg_transfer` hält `nq_raw_slow` im **laufenden** Monat auf 12 h.
- **Speicher-Reclaim** (neu): `nq/aggregate/nq_prune_months.py` bereinigt
  **eingefrorene** Monate (nie den laufenden): droppt tote `nq_agg_10s`, löscht
  `nq_raw_slow` vollständig und **`VACUUM`t nur bei Bedarf** (etwas gelöscht ODER
  Freelist ≥ `--min-free-pct`, Default 20 %). Der Freelist-Guard minimiert
  SD-Schreiblast → ein Monat wird über seine Lebenszeit nur ~3× vacuumt
  (Freeze → 90 d → 365 d).
- **Zeitplan:** best-effort täglich aus `nq_primary_cap` (Timer `pv-nq-primary-cap`,
  00:40). Kein neuer Timer, kein Eingriff in die Live-Aggregation.
- **Einmal-Reclaim 2026-08-08:** `nq_2026-07.db` **236,7 → 55,2 MB** (−181 MB, −77 %);
  `nq/db` gesamt 503 → 321 MB (Rest = laufender August-Churn, self-limitierend).

## 4. Lebenszyklus eines PAC-Monats (Steady State)

| Alter | Behaltene Tabellen | Größe |
|---|---|---|
| < 90 d | 5min + hourly + daily + pattern + transient | **~55 MB** |
| 90 d … 1 a | hourly + daily + pattern + transient | **~6 MB** |
| 1 a … 10 a | daily + pattern + transient | **~2 MB** |
| > 10 a | pattern + transient (+ Events/Energie) | **~1,6 MB** |

## 5. Projektion (Primary, SD)

| Horizont | PAC-Monate | Rechnung | **Gesamt `nq/db`** |
|---|---|---|---|
| **1 Jahr** | 12 | 3×55 + 9×6 + SM 3 | **~0,22 GB** |
| **5 Jahre** | 60 | 165 + 54 + 48×1,8 + 3 | **~0,31 GB** |
| **20 Jahre** | 240 | 165 + 54 + 108×1,8 + 120×1,6 + 3 | **~0,6 GB** |

Vergleich **ohne Reclaim:** ~57 GB nach 20 a. Der Reclaim reduziert den
20-Jahres-Fußabdruck um **~100×**.

**Bewertung:** Auf der 58-GB-SD (aktuell 43 GB frei) und erst recht auf dem
Pi5-FB-Backup (512-GB-NVMe) ist der Bedarf über 20 Jahre **trivial**. Die vom
Nutzer priorisierten **Langzeit-Extremwerte** (`nq_daily`, min/max U + f) kosten
nur ~0,2 MB/Monat → **~48 MB über 20 Jahre**.

## 6. Offene Stellschrauben (optional, später)

- `nq_pattern_5min`/`nq_transient_5min` haben **keine** Primary-Retention
  (~1,6 MB/Monat, permanent). Über 20 a ~0,38 GB — vertretbar; bei Bedarf
  Retention analog `primary_hourly_days` ergänzbar.
- `nq_5min`-Aufbewahrung (90 d) bestimmt den größten Steady-State-Block (~165 MB).
  Verlängern nur, wenn 5-min-Historie länger gebraucht wird.

## Verwandte Doku
- `doc/llm/cards/netzqualitaet-nq-aggregation.card.md`
- `doc/netzqualitaet/NQ_TESTS_UND_DB.md`
- Code: `nq/aggregate/nq_prune_months.py`, `nq/transfer/nq_sm_backfill.py`
