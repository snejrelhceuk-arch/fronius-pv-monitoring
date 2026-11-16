# Strompreis-Analyse — Dynamischer Börsentarif vs. Fixtarif

Entscheidungsgrundlage für die Frage: **einen dynamischen Spotmarkt-Tarif
(Tibber-Schiene) wählen oder beim bestehenden Fixtarif bleiben?** Die Analyse
rekonstruiert aus realen Börsenpreisen und dem real gemessenen Netzbezug, was
jede bezogene kWh im dynamischen Tarif tatsächlich gekostet hätte, und stellt
das dem im selben Zeitraum gezahlten Fixtarif gegenüber.

## Datenquelle (Börsenpreis)

Zuverlässigste freie Quelle: **Fraunhofer ISE — Energy-Charts**
(`https://api.energy-charts.info/price?bzn=DE-LU`, CC BY 4.0, ohne API-Key). Sie
liefert die **EPEX Day-Ahead** Preise für das Marktgebiet **DE-LU** in
**15-Minuten-Auflösung** (96 Werte/Tag, EUR/MWh) — exakt die Börsenbasis, die
auch Tibber/aWATTar abrechnen. Ganz 2026 liegt in 15-min vor.

## Gesamtkosten einer kWh (Mittelsachsen / MITNETZ)

Der Börsenpreis ist nur der **variable** Anteil. Der Endpreis ergibt sich als:

```
Gesamt_brutto (ct/kWh) = (Börsenpreis + Σ feste Netto-Adder) × (1 + MwSt.)
```

Feste Netto-Adder (Stand 2026, ct/kWh), gepflegt in `config.DYN_TARIF`:

| Komponente | ct/kWh (netto) | Quelle |
|---|---|---|
| Netzentgelt (Arbeitspreis) | 6,31 | MITNETZ STROM Preisblatt NS SLP 2026 |
| Konzessionsabgabe | 1,32 | Gemeinde < 25.000 EW |
| KWKG-Umlage | 0,446 | EnFG 2026 |
| Offshore-Netzumlage | 0,941 | EnFG 2026 |
| Aufschlag § 19 StromNEV | 1,559 | EnFG 2026 |
| Stromsteuer | 2,05 | Haushalt (EU-Regelsatz) |
| Anbieteraufschlag (Tibber) | 2,15 | Tibber „weitere Beschaffungskosten" |
| **Summe Netto-Adder** | **14,776** | |

Darauf 19 % MwSt. Feste Grundkosten (nicht pro kWh): Tibber-Grundgebühr
5,99 €/Monat (brutto), MITNETZ Netz-Grundpreis 73,00 €/a (netto),
Messstellenbetrieb iMSys 20,00 €/a.

Beispiel: Börse 13,5 ct → (13,5 + 14,776) × 1,19 ≈ **33,6 ct/kWh** brutto.

## Verbrauchsgewichtung

Maßgeblich ist nicht das Zeit-Mittel, sondern die **verbrauchsgewichtete**
Gesamtkosten einer bezogenen kWh:

```
dyn_avg_ct = Σ(Bezug_15min × Gesamtpreis_15min) / Σ Bezug_15min
```

Teure Verbrauchsstunden (Winterabend) schlagen so stärker durch. Datenquelle
für den 15-min-Bezug: `monitoring.db.data_5min_permanent.W_Bezug` (5-min →
15-min gebucketet).

## Datenfluss

1. **Spot holen** (`collector/dynamic_price.py`) → `spot_price_15min` (EUR/MWh).
2. **Aggregieren** (`collector/aggregate/tariff_cost.py`) → `tariff_cost_daily`
   (verbrauchsgewichtete Kosten + Fixtarif-Vergleich), Roll-up Monat/Jahr.
3. **Spiegeln** nach `analysis.db` (nächtlicher Tiered-Sync; permanent).
4. **Anzeige** (Rolle B, `routes/tarif.py`): Chart-Overlay + Analyse-Seite.

Der Tarifwechsel am **22.02.2026** (33,0 → 30,30 ct/kWh Fixtarif) ist tagesgenau
über `config.STROMTARIFE` berücksichtigt.

## Darstellung

- **Tag-Charts** (Produktion, Verbrauch, Lasten): dünne **schwarze Punktelinie**
  mit eigener **rechter ct/kWh-Achse**; Tooltip zeigt den Viertelstundenpreis und
  die Tagesbilanz (Ø dynamisch gewichtet vs. Fixtarif, Kosten je Tarif).
- **Analyse-Seite** `/analyse/strompreis`: Jahresbilanz, Monatstabelle (reale
  Kosten), Monatschart (Ø-Preis dynamisch vs. Fix + Netzbezug), Aufschlüsselung
  einer kWh, feste Grundkosten, Methodik und Quellen.

## Automatische Pflege

`scripts/dynamic_price_update.sh` (Timer **pv-dynamic-price**, täglich ~14:30 nach
Day-Ahead-Veröffentlichung) holt die aktuellen Preise und aktualisiert die
Aggregate. Vollständige Rückrekonstruktion jederzeit per
`python -m tools.backfill_dynamic_price`.

## Quellen

- Fraunhofer ISE Energy-Charts — EPEX Day-Ahead DE-LU (15-min):
  `https://api.energy-charts.info/price?bzn=DE-LU`
- MITNETZ STROM — Preisblatt Netznutzung 2026:
  `https://www.mitnetz-strom.de/online-services/download-center/preise`
- Netztransparenz / EnFG — Umlagen 2026 (KWKG, Offshore, § 19 StromNEV):
  `https://www.netztransparenz.de/de-de/Erneuerbare-Energien-und-Umlagen`
- Tibber — Preiskonditionen (Grundgebühr, Beschaffungsaufschlag):
  `https://tibber.com/de/preise`

## Lastverschiebungs-Potenzial (Best-Case)

Der verbrauchsgewichtete Vergleich nutzt das **heutige** Verbrauchsprofil — das
liegt meist nicht in den günstigen Börsenstunden. Der eigentliche Sinn eines
dynamischen Tarifs ist die **Lastverschiebung**. Die Analyse-Seite zeigt daher
zusätzlich eine Best-Case-Obergrenze (`routes/tarif.py:_shift_potential`):

- Verschiebbare Tagesenergie = min(Energie flexibler Verbraucher, Netzbezug);
  flexible Verbraucher in `config.DYN_TARIF.shiftable_devices` (E-Auto/Wattpilot,
  Heizpatrone), Leistungsdeckel `shift_max_kw`.
- Diese Energie wird in die **billigsten 15-min-Fenster** des jeweiligen Tages
  verschoben und zum Tiefpreis neu bewertet (reale Spotpreise, inkl. Winter-Wind-
  und Negativpreise). Referenz = Tages-Ø der dynamischen Gesamtkosten.
- Ergebnis: verschiebbare kWh, Best-Case-Ersparnis, „dynamisch optimiert"-Kosten
  und die Empfehlung unter Optimierung. So wird sichtbar, dass sich das Bild erst
  mit konsequenter Verschiebung zugunsten des dynamischen Tarifs dreht.

Es handelt sich um eine **Obergrenze** (ideale Verschiebung) — eine reale
Steuerung/Direktvermarktung ist damit nicht verbunden (Rolle B, read-only).

## Negative Börsenpreise

Der EPEX-Spot kann negativ werden (bis −500 EUR/MWh an sonnig-windigen
Schwachlaststunden). Der Gesamtpreis kann dadurch unter 0 ct/kWh fallen
(`spot_ct < −14,776`). Chart-Achse und Aggregation bilden das korrekt ab: die
ct/kWh-Achse wird nicht bei 0 gekappt, negative Viertelstunden senken die
verbrauchsgewichteten Tageskosten.

## Verwandte Doku

- LLM-Cards: `doc/llm/cards/collector-dynamic-price.card.md`,
  `doc/llm/cards/web-analyse-strompreis.card.md`
- DB-Schema: `doc/collector/DB_SCHEMA.md`
