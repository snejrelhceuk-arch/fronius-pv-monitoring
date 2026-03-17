# Statistik-Korrekturen 2026

## Ziel

Monatswerte in `monthly_statistics` sollen nachvollziehbar, konsistent und
reproduzierbar korrigiert werden, ohne Rohdaten zu verfaelschen und ohne
versteckte Hardcodes im Python-Code.

Die kanonische Korrekturstelle ist:

- `config/statistics_corrections.json`

`aggregate_statistics.py` liest diese Datei bei jedem Lauf ein und wendet die
freigegebenen Korrekturen auf die aus `daily_data` und `wattpilot_daily`
berechneten Monatswerte an.

## Datenquellen

### Waermepumpe

- Rohdaten: `raw_data.W_Imp_WP` und `raw_data.P_WP`
- Tagesaggregation: `aggregate_daily.py`
- Monats/Jahresstatistik: `aggregate_statistics.py`

Regel:

- Wenn `W_Imp_WP` Counter verfuegbar und plausibel ist, wird Counter-Differenz
  bevorzugt.
- Sonst faellt die Tagesaggregation auf `SUM(W_WP_total)` aus `hourly_data`
  zurueck.

### Wattpilot

- Rohdaten: `wattpilot_readings.energy_total_wh` (`eto` Gesamtzaehler)
- Tagesaggregation: `wattpilot_collector.py` -> `wattpilot_daily.energy_wh`
- Monats/Jahresstatistik: `aggregate_statistics.py`

Regel:

- Tagesverbrauch = erster bis letzter verfuegbarer `eto` eines Tages.
- Monatswert = Summe aus `wattpilot_daily.energy_wh`.

## Fehlerursachen 2026

### WP

- Jan 2026: WP-Monat konnte nicht aus belastbaren lokalen Countern rekonstruiert werden.
- Feb 2026: Rohdatenlage war nur teilweise belastbar.
- Ab Mitte Feb/Anfang Maerz ist die Counter-Kette deutlich besser, aber der offene Monat
  kann weiterhin einen Korrekturversatz brauchen.

### Wattpilot

- Der lokale Wattpilot-Collector begann erst am `2026-02-12 12:33:34`.
- Vorher existieren lokal keine `wattpilot_readings`.
- Deshalb sind Januar 2026 und der Monatsanfang Februar 2026 aus lokaler Sicht
  unvollstaendig und benoetigen freigegebene Monatskorrekturen.

## Korrektur-Modi

### `fixed`

Fester Monatswert. Verwenden fuer abgeschlossene Monate mit freigegebenem
Referenzwert.

Beispiel:

```json
{
  "year": 2026,
  "month": 2,
  "field": "wattpilot_kwh",
  "mode": "fixed",
  "value": 842.39
}
```

### `offset`

Additiver Monatsversatz. Verwenden fuer den laufenden Monat, damit neue Daten
weiter auflaufen koennen.

Beispiel:

```json
{
  "year": 2026,
  "month": 3,
  "field": "heizpatrone_kwh",
  "mode": "offset",
  "value": -0.47
}
```

## Operatives Vorgehen

1. Korrektur in `config/statistics_corrections.json` eintragen oder anpassen.
2. Quelle und Begruendung in derselben JSON-Zeile dokumentieren.
3. Statistik neu berechnen:

```bash
cd /srv/pv-system
source .venv/bin/activate
python aggregate_statistics.py
```

4. Ergebnis pruefen:

```bash
sqlite3 /dev/shm/fronius_data.db \
  "SELECT year, month, heizpatrone_kwh, wattpilot_kwh
   FROM monthly_statistics
   WHERE year = 2026
   ORDER BY month;"
```

## Governance-Regel

- Abgeschlossene Monate: bevorzugt `fixed`.
- Laufender Monat: bevorzugt `offset`.
- Jede Korrektur braucht `source` und `reason`.
- Keine verdeckten Monatswerte mehr in `config.py` oder direkt in SQL-Statements.