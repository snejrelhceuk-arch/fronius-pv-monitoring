# Audit — Collector (Rolle A)

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Rolle A sammelt (Modbus TCP read, Fritz!DECT) und schreibt nach `raw_data`; Aggregat-Pipeline `raw_data → data_1min → daily_data`.

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| C-01 | MITTEL | Card behauptete „`db_init.py` legt Pflichttabellen an". | **Verifiziert:** `db_init.py` (`REQUIRED_TABLES = {raw_data, data_1min, daily_data}`, [db_init.py](../../db_init.py#L37)) **prüft** nur deren Existenz ([db_init.py](../../db_init.py#L80)); CREATE der Kern-Tabellen erfolgt aus dem SQL-Schema ([doc/collector/schema/db_schema_v4_tech.sql](../collector/schema/db_schema_v4_tech.sql#L23), [db_schema_1min.sql](../collector/schema/db_schema_1min.sql#L9)). `db_init.py` legt nur Neben-/Forecast-Tabellen via `CREATE TABLE IF NOT EXISTS` an. **Card korrigiert.** |
| C-02 | MITTEL | `battery_control_log`-Zeile in [DB_SCHEMA.md](../collector/DB_SCHEMA.md#L30) suggerierte aktive Tabelle (16 Spalten, 90 Tage). | **Korrigiert:** als Legacy markiert (nicht von `db_init.py`/SQL angelegt, seit 2026-03 nicht beschrieben, nur Lese-Fallback). |
| C-03 | INFO | Aggregat-Pipeline (`collector/aggregate/`) | Konsistent mit Doku. Retention `DATA_1MIN_RETENTION_DAYS=90`. |
| C-04 | INFO | Human-Doku [DB_SCHEMA.md](../collector/DB_SCHEMA.md#L124) beschreibt `db_init.py` als „tmpfs-DB Initialisierung, Persist-Thread". | Korrekt — keine Änderung nötig. |

## Konsistenz Card ↔ Human-Doku

- Card [collector-db-schema.card.md](../llm/cards/collector-db-schema.card.md) jetzt mit Human-Doku konsistent; `last_review` auf 2026-05-29 (Pre-commit-Pflicht).

## Fazit

Sammel-/Aggregat-Pipeline solide. Wesentlicher Befund war Doku-Drift zum Schema-Init, im Audit behoben. Keine Code-Änderung.
