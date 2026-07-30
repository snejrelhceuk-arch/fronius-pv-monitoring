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

Über allen Ansichten zeigen Kennzahlen-Chips den aktuellen SOC, Max/Min-SOC und
die integrierte Hoch-/Tief-Stress-Dauer des Zeitraums. Die Tooltips nennen je
Balken die Stunden/Minuten sowie die SOC-Spanne des Buckets.

## Datenquelle (read-only, Rolle B)

SOC-Werte stammen ausschließlich aus vorhandenen Aggregaten der RAM-DB
(`SOC_Batt_avg`). Es wird **keine** neue Spalte/Tabelle angelegt und keine
Hardware angesprochen.

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
- immer: `thresholds` (`{high, low}`), `table` (verwendete Quelle)

## Verwandte Doku

- LLM-Card: `doc/llm/cards/web-display-api.card.md`
- Schema: `doc/collector/DB_SCHEMA.md`
