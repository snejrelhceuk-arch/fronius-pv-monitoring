# Speicherausbau-Analyse — Amortisationsnachweis

Ansicht: **`/analyse/speicherausbau`** (Analyse-Bereich). Read-only Entscheidungsmodell
(Rolle B) auf Basis der realen 5-Minuten-Messdaten. Beantwortet: **Wie viel Netzbezug
vermeidet ein größerer Speicher zusätzlich — und amortisiert sich der Ausbau?**

## Fragestellung
Die Bestandsanlage (37,59 kWp PV, 20,48 kWh Speicher, **Nulleinspeiser**) performt
wirtschaftlich bereits stark. Zusätzliche Investitionen (Hybrid-WR + großer Speicher,
optional PV-Zubau an freien MPPT) müssen sich innerhalb der Amortisationsgrenze des
Bedieners (Default 10 Jahre) rechnen. Das Modell liefert den Nachweis über die gesamte
Speichergröße und zeigt das Optimum — kleiner *wie* größer ist wirtschaftlich schlechter.

## Datengrundlage
- **`data_5min_permanent`** (STATS-DB, permanent, 5-Minuten-Auflösung), read-only.
  Fenster = Jahresanfang bis gestern. Felder: `SOC_Batt_avg`, `W_Ertrag`, `W_Verbrauch`,
  `W_Einspeis`, `W_Bezug`.
- **`monthly_statistics`** als Referenz für den gemessenen Jahres-Netzbezug.
- **Clear-Sky-Kurve** aus `solar_geometry.get_clearsky_day_curve` (deterministisch je
  Kalendertag, im `tmp/`-Tagescache).
- Annualisierung: Ergebnisse des Fensters werden mit `×365/Tage` auf das Jahr projiziert
  (lineare Projektion, im UI mit Zeitraum ausgewiesen — **kein** vollständiges Messjahr,
  Herbst kann fehlen).

## Modell (inkrementell)
Statt das Gesamtsystem neu zu kalibrieren, simuliert das Modell einen **Zusatzspeicher
on-top**. Je Intervall:

- `available_surplus = curtailed + W_Einspeis` — der heute ungenutzte Überschuss.
- `residual_deficit  = W_Bezug` — der heute aus dem Netz gedeckte Bedarf.

Der virtuelle Zusatzspeicher (nutzbare Kapazität `A`, Round-Trip-Wirkungsgrad) lädt aus
`available_surplus`, sobald Platz ist, und deckt `residual_deficit`, solange Ladung da ist.
`avoided(A)` = Summe der so gedeckten Defizite. Es gilt `avoided(0)=0`, monoton steigend
und **sättigend** — daraus entsteht das wirtschaftliche Optimum.

### Abregelung rekonstruieren (der Kern)
Als Nulleinspeiser regelt die Anlage überschüssige PV bei vollem Bestandsspeicher ab
(SOC-Deckel ~75 %). Diese abgeregelte Energie steht **nicht** im Messwert `W_Ertrag` —
genau hier liegt das Einspeicher-Potenzial größerer Kapazitäten. Sie wird gegen die
Clear-Sky-Prognose rekonstruiert und dabei **selbstkalibriert**:

- `alpha_day` = realisierte Erzeugung / Clear-Sky-Erzeugung, gemessen in den
  **nicht gedeckelten** Tagesstunden (SOC unter dem Deckel, Sonne über Schwelle).
  Das entfernt die systematische Clear-Sky-Überschätzung und die Bewölkung.
- In gedeckelten Intervallen (SOC ≥ `soc_cap_detect_pct`):
  `curtailed = max(clearsky · alpha_day − W_Ertrag, 0)`.

An klaren Tagen ist `alpha_day` hoch → Abregelung wird sichtbar. An trüben Tagen ist
`alpha_day` niedrig → es wird kaum Abregelung angenommen (die geringe Erzeugung war
Wolken, keine Abregelung). Ohne verfügbares `solar_geometry` entfällt die Rekonstruktion;
`available_surplus` ist dann nur exportgebunden (Nulleinspeiser: klein) — im UI kenntlich.

### PV-Zubau
Zusätzliche Module an freier MPPT-Kapazität:
`available_surplus += clearsky_norm · add_kwp · alpha_day` (tagsüber = Überschuss, da der
Haushalt mittags meist gedeckt ist). Der neue Ertrag wirkt über den Speicher auf den
Winter-/Übergangsbezug.

## Wirtschaft
- **Ersparnis** = vermiedener Netzbezug × Bezugspreis (Nulleinspeiser: Überschuss = 0 €,
  daher zählt jede vermiedene Bezugs-kWh voll).
- **Investition** = WR-Fixkosten (einmalig) + Speicherpreis × Nominal-kWh + PV-Kosten × kWp.
- **Amortisation** = Investition / Jahresersparnis; optional mit jährlicher
  Strompreissteigerung (dynamisch, in die Zukunft).
- **Optimum** = minimale Gesamt-Amortisation über die Kurve; zusätzlich die marginale
  Grenze (größte Kapazität mit Grenz-Amortisation ≤ Limit).
- **Vollzyklen/Jahr** des Zusatzspeichers sinken mit der Größe → Überdimensionierung
  drückt die Auslastung unter die Wirtschaftlichkeit.

Defaults und Angebots-Presets stehen in `config/storage_expansion.json`
(u. a. „Solis S6-EH3P 50K-H + Dyness Stack100 51,2 kWh" und „50 kW WR + 25 kWh").

## Bedienung
- **Schieber** Zusatz-Speicher / PV-Zubau / Strompreis / Speicherpreis / WR-Fixkosten /
  PV-Kosten. Preis- und Kostenschieber rechnen sofort (ohne Neuberechnung der Physik);
  PV-Zubau und der Abregelungs-Schalter lösen eine Neuberechnung aus.
- **Presets** setzen Speichergröße und Preis eines konkreten Angebots.
- **Hauptdiagramm**: vermiedener Netzbezug (Fläche) + Amortisation (Linie) über der
  Speichergröße, mit Optimum-, Auswahl- und Grenz-Markern.
- **Monatsbilanz**: Rest-Netzbezug vs. Vermieden je Monat, dazu die Abregelung als
  Potenziallinie — macht die **saisonale Lücke** sichtbar (Sommerüberschuss lässt sich
  nicht in den Winter verschieben).

## Grenzen / Interpretation
- `curtailed` ist eine **Schätzung** (Größenordnung), keine eichgenaue Energie.
- `avoided` ist durch den gemessenen Netzbezug begrenzt; der Winterbezug ist mit
  Tagesspeichern nur teilweise vermeidbar.
- Das Fenster ist kein volles Messjahr; die Jahreswerte sind projiziert.

## API
- `GET /api/analyse/speicher/sweep?add_pv=<kWp>&curtail=<0|1>` → Kurve über die Kapazität
  (vermiedener Bezug, Autarkie, Zyklen) + Basis-Kennzahlen + Wirtschafts-Defaults + Presets.
- `GET /api/analyse/speicher/detail?batt=<kWh>&add_pv=<kWp>&curtail=<0|1>` → Monatsaufschlüsselung
  eines Szenarios (Bezug, vermieden, Rest, Abregelung).

## Quellcode
- Modell: [`analysis/storage_model.py`](../../analysis/storage_model.py)
- Blueprint: [`routes/analyse_speicher.py`](../../routes/analyse_speicher.py)
- Ansicht: [`templates/analyse_speicherausbau_view.html`](../../templates/analyse_speicherausbau_view.html)
- Parameter: [`config/storage_expansion.json`](../../config/storage_expansion.json)
- LLM-Card: [`doc/llm/cards/web-analyse-speicherausbau.card.md`](../llm/cards/web-analyse-speicherausbau.card.md)
