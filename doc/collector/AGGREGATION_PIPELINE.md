# Aggregation-Pipeline — Fronius PV-Anlage

> Stand: 2026-08-18

## 1. Pipeline-Übersicht

```
raw_data (3s Modbus-Polling, Retention: 30 Tage)
│
├─── aggregate_1min.py ──► data_1min         (Tag-Chart)
│                          Retention: 90 Tage
│                          Energie: P×t-Integration, Batterieaufteilung
│
└─── aggregate.py ────────► data_15min       (Technische Basis)
                            │  Retention: 90 Tage
                            │  Energie: Zählerstand-Deltas, AVG/MIN/MAX
                            │
                            ├─► hourly_data  (Technisch)
                            │   Retention: 365 Tage
                            │
                            └─► aggregate_monthly.py ──► data_monthly
                                                         Retention: 3650 Tage
                                                         Technisches Monitoring
                                                         (76 Spalten, min/max/avg)

hourly_data
└─── aggregate_daily.py ──► daily_data       (Monat-Chart + Statistik-Basis)
                            Retention: 3650 Tage (10 Jahre)

daily_data
└─── aggregate_statistics.py ──► monthly_statistics  (Anlagen-Historie)
                                 │  Retention: permanent
                                 │  17 Spalten (kWh + Kosten)
                                 │  + optionale Monatskorrekturen aus config/statistics_corrections.json
                                 │
                                 └──► yearly_statistics  (Anlagen-Historie)
                                      Retention: permanent
                                      18 Spalten (kWh + Kosten)
```

## 2. Tabellen-Referenz

| Tabelle | Intervall | Retention | Spalten | Verwendung |
|---------|-----------|-----------|---------|------------|
| `raw_data` | 3s | 30 Tage | ~76 | Echtzeit-Visu, Fehleranalyse |
| `data_1min` | 1 min | 90 Tage | ~97 | Tag-Chart (P×t-Integration) |
| `data_15min` | 15 min | 90 Tage | ~99 | Technische Basis für hourly/monthly + Forecast/Clear-Sky |
| `hourly_data` | 1 h | 365 Tage | ~53 | Zwischenstufe für daily |
| `daily_data` | 1 Tag | 3650 Tage | ~46 | Monat-Chart, Statistik-Quelle |
| `data_monthly` | 1 Monat | 3650 Tage | ~76 | Technisches Monitoring (min/max/avg) |
| `monthly_statistics` | 1 Monat | permanent | 17 | Jahr-Chart, Gesamt-Chart, Amortisation |
| `yearly_statistics` | 1 Jahr | permanent | 18 | Gesamt-Chart (Zusammenfassung) |

### Designprinzip

- **Bis `data_monthly`**: umfangreiche technische Daten (min/max/avg, Zählerstände, Spannungen, Frequenzen) für Anlagenüberwachung
- **Ab `monthly_statistics`**: nur noch kWh-Energiesummen + Kosten/Kennzahlen für die Anlagen-Historie

## 3. Cron-Schedule

Alle Aggregationen laufen 4× pro Stunde, gestaffelt für korrekte Daten-Kette:

| Minute | Script | Quelle → Ziel |
|--------|--------|---------------|
| `*` | `aggregate_1min.py` | raw_data → data_1min |
| `0,15,30,45` | `aggregate.py` | raw_data → data_15min → hourly_data |
| `2,17,32,47` | `aggregate_daily.py` | hourly_data → daily_data |
| `6,21,36,51` | `aggregate_monthly.py` | data_15min → data_monthly |
| `8,23,38,53` | `aggregate_statistics.py` | daily_data → monthly_statistics → yearly_statistics |

**Staffelung**: Jede Stufe wartet 2–4 Minuten nach der Vorgängerstufe, damit die Quelldaten vollständig vorliegen.

## 4. Retention-Policies (config.py)

```python
RAW_DATA_RETENTION_DAYS = 30       # raw_data (3s-Rohdaten; techn. Rückverfolgung, RAM-tragbar auf Pi5)
DATA_1MIN_RETENTION_DAYS = 90      # data_1min
DATA_15MIN_RETENTION_DAYS = 90     # data_15min
HOURLY_RETENTION_DAYS = 365        # hourly_data
DAILY_RETENTION_DAYS = 3650        # daily_data (~10 Jahre)
DATA_MONTHLY_RETENTION_DAYS = 3650 # data_monthly (~10 Jahre)
# monthly_statistics + yearly_statistics: PERMANENT (kein Cleanup)
```

Bereinigung erfolgt automatisch durch `collector/poller.py` `cleanup_db()` im laufenden `pv-collector` (stündlich).
Kein separater Cron-Job für Retention nötig.

## 5. Energie-Modell: Spalten-Mapping

### raw_data → data_1min (P×t-Integration)

`aggregate_1min.py` berechnet Energiewerte aus Leistungswerten:

```
W = P_avg × Δt / 3600  (Wh pro Minute)
```

Besonderheit: Batterieenergie wird auf PV-Direkt vs. Netz aufgeteilt:
```
W_Batt_Charge = W_Batt_Charge_PV + W_Batt_Charge_Netz
W_Batt_Discharge = W_Batt_Discharge_PV + W_Batt_Discharge_Netz
```

### raw_data → data_15min (Zählerstand-Deltas)

`aggregate.py` berechnet Energiedeltas aus Modbus-Zählerständen:

```
W_Exp_Netz_delta = MAX(W_Exp_Netz) - MIN(W_Exp_Netz)  (Wh pro 15min)
```

Zusatz: Prognose- und Clear-Sky-Kurven werden als 15min-Leistung (P) und
15min-Energie (W) in data_15min abgelegt, damit das Tag-Overlay und die
Monats-Prognose 90 Tage historisiert werden koennen.

### daily_data → monthly_statistics (kWh-Summen)

`aggregate_statistics.py` — Mapping daily_data (Wh) → monthly_statistics (kWh):

| daily_data (Wh) | monthly_statistics (kWh) |
|------------------|--------------------------|
| `W_PV_total` | `solar_erzeugung_kwh` |
| `W_Imp_Netz_total` | `netz_bezug_kwh` |
| `W_Exp_Netz_total` | `netz_einspeisung_kwh` |
| `W_Batt_Charge_total` | `batt_ladung_kwh` |
| `W_Batt_Discharge_total` | `batt_entladung_kwh` |
| `W_PV_Direct_total` | `direktverbrauch_kwh` |
| `W_Consumption_total` | `gesamt_verbrauch_kwh` |
| `W_WP_total` | `heizpatrone_kwh` |
| *(kein Sensor)* | `wattpilot_kwh = 0` |

**Hinweis**: Der WP-SmartMeter misst die Wärmepumpe. Ein separater Wattpilot-Sensor
existiert nicht. Für 2022–2025 stammen die getrennten Werte aus dem CSV-Import (Solarweb).

### Formale Monatskorrekturen

Wenn ein Monat lokal nicht vollstaendig oder nicht belastbar rekonstruiert werden kann,
greift `aggregate_statistics.py` auf das versionierte Korrekturregister
`config/statistics_corrections.json` zu.

Modi:

- `fixed`: fester Monatswert fuer abgeschlossene Monate
- `offset`: additiver Versatz fuer laufende Monate

Details siehe `doc/collector/STATISTICS_CORRECTIONS.md`.

### Berechnete Kennzahlen

```
Autarkie (%) = (Direktverbrauch + Batterie-Entladung) / Gesamtverbrauch × 100
Eigenverbrauch (%) = (Solar − Einspeisung) / Solar × 100
```

Bei `yearly_statistics` werden diese aus den Jahressummen berechnet (gewichtet),
nicht als Durchschnitt der Monatswerte.

## 6. Re-Aggregation

Jedes Script aktualisiert den **laufenden Zeitraum** bei jedem Aufruf:

| Script | Re-Aggregation |
|--------|----------------|
| `aggregate_1min.py` | Letzte 120 Sekunden |
| `aggregate.py` | Letztes 15-Minuten-Intervall |
| `aggregate_daily.py` | Aktueller Tag |
| `aggregate_monthly.py` | Aktueller Monat + Vormonat |
| `aggregate_statistics.py` | Letzte 3 Monate + alle Jahre |

Alle Scripts verwenden `INSERT OR REPLACE` bzw. `ON CONFLICT DO UPDATE` (UPSERT),
sodass Wiederholungen sicher sind (idempotent).

## 7. Historische Daten (2022–2025)

Die Daten in `monthly_statistics` und `yearly_statistics` für 2022–2025
stammen aus dem CSV-Import (Solarweb-Export). Da `daily_data` erst ab
07.01.2026 existiert, überschreibt `aggregate_statistics.py` diese
historischen Werte **nicht** — es gibt schlicht keine daily_data für diese
Zeiträume.

Für `yearly_statistics` werden alle Jahre aus `monthly_statistics` summiert.
Die historischen Monatswerte (CSV) fließen somit korrekt in die Jahressummen ein.

## 8. Frontend-Zuordnung

| Ansicht | API-Endpunkt | Datenquelle |
|---------|-------------|-------------|
| Tag | `/api/tag_visualization` | `data_1min` (≤90 T) → `stats.data_5min_permanent` (ältere Tage, 5-min, permanent) + Forecast aus `data_15min` |
| Monat | `/api/monat_visualization` | `daily_data` + Forecast aus `data_15min` |
| Jahr | `/api/jahr_visualization` | `monthly_statistics` |
| Gesamt | `/api/gesamt_visualization` | `monthly_statistics` |
| Amortisation | `/amortisation` | `monthly_statistics` |
| Echtzeit | `/echtzeit` | RAM-DB (aus raw_data) |

**Netzfrequenz-Info**: Monat/Jahr/Gesamt/Analysen zeigen eine kompakte
Infozeile mit MIN/MAX der Netzfrequenz (aus `data_1min.f_Netz_min/max`).
Der separate Frequenz-Chart in der Monatsansicht wurde in v6.1.0 entfernt.

Hinweis: Die Web-API liest fuer Charts aus der RAM-DB; die Persist-DB wird
regelmaessig aus der RAM-DB ueberschrieben.

## 9. Überwachung / Debugging

### Logs prüfen
```bash
tail -f /tmp/aggregate_statistics.log    # Statistik-Pipeline
tail -f /tmp/aggregate.log               # 15min/hourly
tail -f /tmp/aggregate_daily.log         # Daily
tail -f /tmp/aggregate_monthly.log       # Monthly technisch
tail -f /tmp/aggregate_1min.log          # 1-Minuten-Werte
```

### Datenkette manuell prüfen
```bash
cd /srv/pv-system

# Anzahl Datensätze pro Tabelle
sqlite3 data.db "SELECT 'raw_data', COUNT(*) FROM raw_data
UNION SELECT 'data_1min', COUNT(*) FROM data_1min
UNION SELECT 'data_15min', COUNT(*) FROM data_15min
UNION SELECT 'hourly_data', COUNT(*) FROM hourly_data
UNION SELECT 'daily_data', COUNT(*) FROM daily_data
UNION SELECT 'data_monthly', COUNT(*) FROM data_monthly
UNION SELECT 'monthly_statistics', COUNT(*) FROM monthly_statistics
UNION SELECT 'yearly_statistics', COUNT(*) FROM yearly_statistics;"

# Letzter Eintrag pro Tabelle
sqlite3 data.db "SELECT 'raw_data', datetime(MAX(ts),'unixepoch','localtime') FROM raw_data
UNION SELECT 'data_1min', datetime(MAX(ts),'unixepoch','localtime') FROM data_1min
UNION SELECT 'monthly_statistics', MAX(year)||'-'||printf('%02d',MAX(month)) FROM monthly_statistics;"
```

### Manuell nachberechnen
```bash
python3 aggregate_statistics.py   # monthly_statistics + yearly_statistics
python3 aggregate_monthly.py      # data_monthly (technisch)

# Forecast/Clear-Sky Backfill (90 Tage, RAM-DB)
python3 scripts/backfill_forecast_15min.py --days 90

# Dry-Run
python3 scripts/backfill_forecast_15min.py --days 90 --dry-run

# Persist-DB explizit
python3 scripts/backfill_forecast_15min.py --days 90 --persist
```

## 10. Datenmengen, Skalierung & Backup-Impact (Pi5-Primary)

> Gemessen 2026-08-18 auf **Pi5-Primary** (4 GB RAM, tmpfs `/dev/shm` 2,0 GB, microSD 64 GB / 43 GB frei) via `dbstat`. Werte = Tabelle **inkl. Indizes**, gerundet.

### 10.1 Ist-Belegung je Tabelle

| Tabelle | Retention | Speicher (gemessen, inkl. Index) | Ø/Tag |
|---------|-----------|----------------------------------|-------|
| `raw_data` | 30 T | ~495 MB @30 T (115 MB/7 T gemessen) | ~16,5 MB |
| `data_1min` | 90 T | ~107 MB | ~1,2 MB |
| `data_15min` | 90 T | ~7 MB | ~0,08 MB |
| `hourly_data` | 365 T | ~3 MB (365 T) | — |
| `daily_data` | 3650 T | ~2 MB (10 J) | — |
| `data_monthly` | 3650 T | <0,1 MB | — |
| `monthly_statistics` | permanent | <0,1 MB | — |
| `yearly_statistics` | permanent | <0,1 MB | — |
| `fritzdect_readings` | 7 T | ~31 MB | ~4,4 MB |
| `wattpilot_readings` | 90 T | ~17 MB | ~0,2 MB |
| `forecast_daily` | wächst langsam | ~5 MB | — |

### 10.2 RAM-DB (`/dev/shm/fronius_data.db`, tmpfs)

- **Vorher** (raw_data 7 T): **285 MB** gemessen.
- **Nachher** (raw_data 30 T, eingeschwungen): **~665 MB** (+~380 MB durch die zusätzlichen 23 T raw_data).
- tmpfs 2,0 GB → **~33 % belegt**; RAM 4 GB → nach Umstellung noch ~1,5 GB frei.
- Der SD-Spiegel `data.db` wächst identisch (SD 43 GB frei → trivial). Pi5-FB (8 GB RAM) hat noch mehr Reserve.

### 10.3 Langzeit-Skalierung (10 / 30 Jahre)

**Kernbefund: RAM-DB und `data.db` sind retention-begrenzt → sie erreichen einen _stabilen Endzustand_ (~665 MB) und wachsen NICHT über die Jahre.** Nur die permanente 5-min-DB wächst nennenswert linear:

| Speicher | Ort | Wachstum | 10 Jahre | 30 Jahre |
|----------|-----|----------|----------|----------|
| RAM-DB / `data.db` | RAM + SD | begrenzt (Retention) | ~665 MB | ~665 MB |
| `data_stats.db` (5-min-permanent) | SD | ~80 MB/Jahr | ~0,8 GB | ~2,4 GB |
| `monthly`/`yearly_statistics` | RAM + SD | ~KB/Jahr | <5 MB | <15 MB |

`data_stats.db` (aktuell 50 MB für ~7,5 Monate, 64 664 Zeilen) ist der einzige nennenswerte Dauerwachser — auf **SD, nicht im RAM**. Selbst „für immer" bleibt die SD-Last im einstelligen GB-Bereich.

### 10.4 Auswirkung auf die GFS-Backups

`scripts/backup_db_gfs.sh` sichert die **gesamte** `data.db` (RAM-DB-Snapshot, gzip). Retention: **7 Sohn + 5 Vater + 12 Großvater + jährl. Urgroßvater** (≈ 24 Dauer-Kopien + 1/Jahr), zusätzlich Offsite-Kopie auf Pi5-FB (NVMe 512 GB).

- Kompression gemessen: `data.db` 285 MB → **102 MB gzip** (2,79×); `raw_data` allein 108 MB → 31 MB (0,29×).
- Nach raw_data 30 T: `data.db` ~665 MB → **~239 MB gzip/Kopie** (+~137 MB je Kopie).
- **Mehrbedarf GFS je Standort:** ~24 Kopien × ~137 MB ≈ **~3,3 GB**; Urgroßvater +~239 MB/Jahr.
- Ziel-Medien: SD 58 GB (43 GB frei) + NVMe 512 GB → **unkritisch**.
- `data_stats.db` läuft **nicht** über die GFS-Kette, sondern per Tages-Sync (`scripts/stats_archive_daily.sh`, jeweils aktuelle Kopie) nach Pi5 + Failover.
