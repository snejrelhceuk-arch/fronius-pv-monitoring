# Datenbank-Schemata

## Aktuelle Schemata (definieren die laufende DB)

| Datei | Inhalt |
|---|---|
| `db_schema_v4_tech.sql` | Hauptschema: raw_data, data_15min, hourly_data, daily_data |
| `db_schema_1min.sql` | data_1min (Zwischenstufe für Tag-Visualisierung) |
| `db_schema_statistics.sql` | monthly_statistics + yearly_statistics |
| `db_schema_wattpilot.sql` | wattpilot_readings + wattpilot_daily |

## Schema-Erweiterungen (bereits eingebaut)

| Datei | Datum | Inhalt |
|---|---|---|
| `db_schema_absolute_values.sql` | 07.02.2026 | Absolute Zählerstände in raw_data |
| `schema_update_aggregations.sql` | 04.01.2026 | daily_data Detailspalten |
| `schema_update_battery_sources.sql` | 07.02.2026 | Batterie PV/Netz-Trennung in data_1min |

## Historisch (nur Referenz)

| Datei | Inhalt |
|---|---|
| `db_schema_aggregations.sql` | Altes data_weekly Schema (Tabelle gelöscht am 08.02.2026) |
