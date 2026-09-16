# Akku-Stress-Analyse

> Seite `/analyse/batterie` — Menü **Analyse → Batterie**.
> Zweck: sichtbar machen, wie lange die Hausbatterie (LFP) in den zellschädigenden
> SOC-Randbereichen verweilt.

## Stress-Definition

LFP-Zellen altern beschleunigt bei dauerhaft sehr hohem oder sehr niedrigem
Ladezustand. Als Stress gilt daher die integrierte Verweildauer:

| Zone | Bedingung | Bedeutung |
|------|-----------|-----------|
| Hoch-Stress | `SOC > 95 %` | Vollladungs-Belastung |
| Tief-Stress | `SOC < 10 %` | Tiefentladungs-Belastung |

Die Schwellen sind serverseitig als `SOC_STRESS_HIGH_PCT`/`SOC_STRESS_LOW_PCT`
in [`routes/verbraucher.py`](../../routes/verbraucher.py) definiert. Grenzwerte
selbst (`= 95` / `= 10`) zählen **nicht** als Stress.

## Ansichten

| Ansicht | Zeitachse | Darstellung |
|---------|-----------|-------------|
| Tag | 00:00–24:00 (5-Min-Raster) | SOC-Verlauf als Fläche; Stresszonen als markierte Bänder + Schwellenlinien |
| Monat | alle Tage des Monats | schmale Balken je Tag: Hoch-/Tief-Stress in Stunden |
| Jahr | 12 Monate | Balken je Monat = Summe der Tages-Stressdauern |
| Gesamt | vorhandene Jahre | Balken je Jahr = Summe der Jahres-Stressdauern |

Eine **Kopfzeile** aus Kennzahlen-Chips (im `monitoring.css`-Stil wie Erzeuger/
Verbraucher) zeigt SOC, das SOC-Schaltband (`soc_min`–`soc_max`), den **Wirkungsgrad**
(Entladung/Ladung), die intervallbezogenen **Vollzyklen**, die Batterie-Temperatur und
den **SOH**. SOC/Schaltband/Temperatur/SOH kommen live aus `/api/flow_status`
(30-s-Poll), Wirkungsgrad und Vollzyklen aus der Perioden-Antwort. Der **Stress-Anteil**
(Stresszeit/ausgewertete Zeit) samt Hoch-/Tief-Dauer und der Vollzyklen-Wert stehen
zusätzlich im Titel über dem Stress-Balken-Chart. Die Datums-Schaltfläche zwischen den
Navigations-Pfeilen öffnet einen Kalender. Die Tooltips nennen je Balken die
Stunden/Minuten sowie die SOC-Spanne des Buckets.

## Datenquelle (read-only, Rolle B)

SOC-Werte für die Stress-Analyse stammen ausschließlich aus vorhandenen Aggregaten
der RAM-DB (`SOC_Batt_avg`); die Web-Route spricht keine Hardware an.

Die **Vollzyklen** berechnet die API intervallbezogen als Σ Batterie-Ladung /
Nominal-Kapazität der jeweiligen Ausbaustufe (`config.battery_capacity_kwh_for`:
10.24 kWh bis Feb 2026, 20.48 kWh ab März 2026, 25.6 kWh ab Okt 2026). Tag aus
`daily_data`, Monat/Jahr/Gesamt aus `monthly_statistics` (deckungsgleich mit der
Vollzyklen-Spalte der PV-Übersicht). SOH-Historie und Tages-Vollzyklen werden im
Tagesintervall in `battery_health_daily` geführt — befüllt von Rolle A
(`collector/aggregate/battery_health.py`, im Statistik-Cron-Takt), nicht von der
Web-Route.

`_resolve_soc_table` wählt abhängig vom Zeitraum die feinste Tabelle, die den
Perioden-Anfang abdeckt; deckt keine Tabelle den Anfang ab, gewinnt die mit der
weitesten Rückreichweite:

| Zeitraum | typische Quelle | Auflösung |
|----------|-----------------|-----------|
| Tag / Monat (letzte ~90 Tage) | `data_1min` | 1 min |
| Monat (älter) | `data_15min` / `hourly_data` | 15 min / 1 h |
| Jahr / Gesamt | `hourly_data` | 1 h |

Die Stress-Dauer wird als `Intervall × Anzahl Punkte in der Zone` integriert;
das Messintervall wird pro Tabelle aus den Zeitstempeln abgeleitet
(`_infer_soc_interval_s`). Dadurch ist die Jahres-/Gesamt-Dauer gröber (Stunden-
raster) als die Tages-/Monatsdauer — ein bewusster Auflösungs-Kompromiss ohne
Schema-Erweiterung.

## API

`GET /api/verbraucher/batterie?period=<tag|monat|jahr|gesamt>[&date=YYYY-MM-DD|&year=&month=]`

- `tag`: `points[]` (`ts`, `soc`) + `summary`
- `monat|jahr|gesamt`: `chart_points[]` (`label`, `soc_max`, `soc_min`,
  `high_stress_minutes`, `low_stress_minutes`) + `summary`
- `summary`: `current`, `high_stress_minutes`, `low_stress_minutes`,
  `available_hours`, `stress_pct`, `high_stress_pct`, `low_stress_pct`,
  `efficiency_pct` (Entl./Lad. in %, `null` wenn keine Ladeenergie vorliegt),
  `full_cycles` (intervallbezogene Vollzyklen; Tag mit 2 Nachkommastellen, ab
  Monat ganzzahlig dargestellt)
- immer: `thresholds` (`{high, low}`), `table` (verwendete Quelle)

## Verwandte Doku

- LLM-Card: `doc/llm/cards/web-display-api.card.md`
- Schema: `doc/collector/DB_SCHEMA.md`
