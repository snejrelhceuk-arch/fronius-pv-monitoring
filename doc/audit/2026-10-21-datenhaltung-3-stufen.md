# Audit: 3-Stufen-Datenhaltung (RAM → monitoring.db → analysis.db)

**Datum:** 2026-10-21
**Scope:** Datenerfassung und Aggregation in der neuen 3-Stufen-Datenhaltung
(RAM-DB `/dev/shm`, `monitoring.db` 5-min, `analysis.db` Tag/permanent).
**Geprüfte Pfade:** `collector/poller.py`, `collector/aggregate/*`,
`tools/build_tiered_dbs.py`, `scripts/sync_tiered_daily.sh`, `db_utils.py`,
`config.py`, `db_init.py`.

## Executive Summary

Die Architektur ist im Kern solide abgesichert. Der **korrelierte Delete** in
`_cleanup_tiered` ist ein echter Sicherheitsanker (RAM verliert nie Zeilen, deren
permanente Kopie in `analysis.db` fehlt) und entkoppelt das RAM-Cleanup korrekt von
der Cron-Reihenfolge. Schrumpf-Schutz beim `--build` und die `NOT EXISTS`-Dedup an
der Tagesgrenze verhindern die naheliegendsten Datenverlust-/Doppelzähl-Szenarien.
**Echte Datenverluste durch die Reihenfolge RAM-Cleanup vs. Sync bestehen nicht.**

Verbleibende Risiken waren struktureller/latenter Natur und wurden im Rahmen dieses
Audits **behoben** (siehe „Behobene Befunde"): positions-basierte Shadow-View-Union,
Surrogat-Dedup-Key für Statistik-Tabellen, Ganzzeilen-Replace beim Sync,
doppelter Retention-Pfad für `daily_data`, WAL-rsync ohne Checkpoint.

## Befundtabelle

| # | Severity | Datei:Zeile | Befund | Status |
|---|----------|-------------|--------|--------|
| 1 | Hoch | db_utils.py `_attach_tiered_ro` | Shadow-View `SELECT * … UNION ALL` ist positions-basiert → Schema-Drift ergibt stillen Historienverlust oder Spaltenvertauschung | **behoben** |
| 2 | Mittel | db_utils.py `_ANALYSIS_SHADOW` | Dedup-Key für `monthly_statistics`/`yearly_statistics` = surrogater `id` statt Natur-Schlüssel → Doppelzählung bei ID-Divergenz | **behoben** |
| 3 | Hoch | tools/build_tiered_dbs.py `_sync_table` | `--sync` = `INSERT OR REPLACE` (Ganzzeilen-Replace) → analysis-only-Spalten im 120-T-Fenster werden auf NULL gewiped | **behoben** |
| 4 | Mittel | collector/poller.py Retention | `daily_data` hatte zwei Retention-Pfade (nicht-korreliert + korreliert) → abgesenktes `DAILY_RETENTION_DAYS` könnte ungeschützt löschen | **behoben** |
| 5 | Mittel | db_utils.py / aggregate | Shadow-Views nur auf RO-Verbindung; Aggregatoren/Leser nutzten RW (nur RAM) → stille Kopplung „Aggregationsfenster < 120 T" | **behoben** (Tagesmail-Leser auf Tiered-RO; Invariante in Card) |
| 6 | Niedrig | poller.py `_cleanup_tiered` | `data_monthly`, `*_statistics`, `*_monthly`, `price_history` werden nicht getrimmt | akzeptiert (unkritisch, klein — dokumentiert) |
| 7 | Niedrig | scripts/sync_tiered_daily.sh | rsync der Live-WAL-DB ohne vorherigen Checkpoint → Empfänger evtl. Pre-WAL-Stand | **behoben** |
| 8 | Niedrig | collector/aggregate/daily.py | `W_Consumption/W_PV_Direct` setzen `W_Exp_Netz` positiv voraus (durch Reset-Fallback abgefangen) | **behoben** (Netzzähler explizit auf ≥ 0 normalisiert) |
| 9 | Niedrig | Cards | Doku-Wording „INSERT … ON CONFLICT" ↔ Code; „120 vs 90 T" | behoben (Cards) |

## Behobene Befunde

### 1 — Positions-basierte Shadow-View-Union (Hoch)
`UNION ALL` matcht in SQLite nach **Position**, nicht nach Name. Additive
`ALTER … ADD COLUMN` im Sync vs. mittige Schema-Migration in der RAM-DB konnten zu
divergierenden Spaltenzahlen (→ View-Fehler → Fallback auf reine RAM-Tabelle →
stiller Historienverlust > 120 T) oder zu stiller Spaltenvertauschung führen.
**Fix:** `_attach_tiered_ro` unioniert jetzt nur die in **beiden** DBs vorhandenen
Spalten, benannt und in RAM-Reihenfolge; fehlt ein Schlüssel in der Schnittmenge,
wird die Tabelle übersprungen (Fallback auf RAM-only statt Korruption).

### 2 — Surrogat-Dedup-Key für Statistik-Tabellen (Mittel)
`monthly_statistics`/`yearly_statistics` wurden über `id` dedupliziert. Bei einem
RAM-Reseed divergierender Auto-Increment-IDs hätte die Union ganze Monate/Jahre
doppelt geliefert. **Fix:** Dedup-Key auf den natürlichen `UNIQUE`-Schlüssel
`(year, month)` bzw. `(year)` umgestellt.

### 3 — Ganzzeilen-Replace beim Sync (Hoch)
`INSERT OR REPLACE` löscht bei PK-Konflikt die komplette Zielzeile. Spalten, die nur
in `analysis.db` existieren (z. B. historisch rekonstruierte Werte), wurden für Tage
im 120-T-Fenster auf Default/NULL gewiped. **Fix:** spalten-selektiver Upsert
`ON CONFLICT(pk) DO UPDATE SET` nur der RAM-Quellspalten für Tabellen mit echtem
natürlichem PK; Ziel-only-Spalten bleiben erhalten (per Test verifiziert). Für
`monthly/yearly_statistics` (Surrogat-PK `id` + zusätzlicher Natur-UNIQUE) bleibt
`INSERT OR REPLACE`, damit UNIQUE-Konflikte korrekt greifen.

### 4 — Doppelter Retention-Pfad für `daily_data` (Mittel)
`daily_data` wurde sowohl im nicht-korrelierten `RETENTION`-Lauf als auch im
korrelierten `_cleanup_tiered` getrimmt. Der Sicherheits-Guard gilt nur im
korrelierten Pfad. **Fix:** Im Tiered-Mode (`ana_attached`) wird `daily_data` aus
der nicht-korrelierten Retention entfernt — ausschliesslich der korrelierte Delete
trimmt sie.

### 7 — WAL-rsync ohne Checkpoint (Niedrig)
`sync_tiered_daily.sh` rsyncte die `.db`-Dateien ohne `-wal`. Da Sync im WAL-Modus
schreibt, hätte der Empfänger einen Pre-WAL-Stand erhalten können. **Fix:** vor dem
rsync wird für `monitoring.db` und `analysis.db` ein `wal_checkpoint(TRUNCATE)`
erzwungen.

## Behandelte Empfehlungen

- **5 — RW/RO-Kopplung:** Der Tagesbericht-Leser (`event_notifier._sammle_tagesdaten`)
  nutzt jetzt `db_utils.get_db_connection_ro()` (Tiered-Shadow-Views) → Jahr/Gesamt
  lesen die volle Historie aus `analysis.db` statt nur des 120-T-RAM-Fensters
  (vorher stiller Minderausweis, z. B. Netzbezug). Aggregatoren sehen die
  Shadow-Views weiterhin nicht (nur RAM); das statistics-3-Monats-Fenster muss
  `< TIERED_DAILY_RETENTION_DAYS` (120 T) bleiben — als Invariante in der Card geführt.
- **6 — „RAM konstant":** `data_monthly`, `*_statistics`, `*_monthly`,
  `price_history` wachsen (monatlich/klein). Als unkritisch **akzeptiert**; Card-Wording
  präzisiert („RAM konstant" gilt für die hochfrequenten Tabellen, nicht die kleinen
  Monats-/Statistik-Tabellen).
- **8 — Vorzeichen `W_Exp_Netz`:** In `daily.py` sind `W_Imp_Netz`/`W_Exp_Netz` nach
  dem Counter/Fallback-Schritt explizit auf `max(0.0, …)` normalisiert — kein
  Verlass mehr auf den Reset-Fallback. **Behoben.**

## Positiv-Befunde (korrekt umgesetzt)

- Korrelierter Delete als Sicherheitsanker (`poller.py:_cleanup_tiered`) — RAM kann
  keine un-gespiegelten Daten verlieren; `ATTACH`-Fehler → Cleanup übersprungen
  (fail-safe).
- Schrumpf-Schutz in `--build` verhindert Kürzung der analysis-Historie nach RAM-Trim.
- `NOT EXISTS`-Dedup (RAM gewinnt den laufenden Tag) → keine Doppelzählung an der Naht.
- Zukunfts-Prognosen (`forecast_daily.date > heute`) werden nie getrimmt.
- P×t-Integration statt Counter-Sprüngen, flächige Negativ-Guards, Counter/SUM-Fallback
  mit Reset-Erkennung (`min1.py`, `daily.py`).
- RO-Pfad doppelt abgesichert (`mode=ro` + `query_only=ON` nach TEMP-View-Anlage).
- Konsistente UTC-Mitternacht-Tagesschlüssel über Aggregat- und FritzDECT-Pfade.

## Verifikation

- `python3 -c "ast.parse(...)"` für alle drei geänderten Python-Module: OK.
- RO-Views nach Fix gegen Live-DBs gelesen: alle 8 Tabellen liefern plausible Zeilen.
- `_sync_table` Dry-Run gegen temporäre `analysis.db`-Kopie: Historie bewahrt,
  idempotent, keine Fehler; analysis-only-Spalte bleibt nach Resync erhalten (42.0).
