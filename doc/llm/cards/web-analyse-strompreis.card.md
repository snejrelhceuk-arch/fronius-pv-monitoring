---
title: Web — Strompreis-Tarifvergleich + Chart-Preis-Overlay
domain: web
role: B
applyTo: "routes/tarif.py"
tags: [tarif, strompreis, analyse, chart, overlay, tibber, dynamisch, ct-kwh]
status: stable
last_review: 2026-11-16
---

# Web — Strompreis (Fixtarif vs. dynamisch)

## Zweck
Read-only Analyse + Chart-Overlay zum dynamischen Börsentarif:
1. **Preis-Overlay** auf den Tag-Charts (Produktion, Verbrauch, Lasten) als dünne
   **schwarze Punktelinie** mit eigener **rechter ct/kWh-Achse** + Tooltip-Bilanz.
2. **Analyse-Seite** `/analyse/strompreis`: Tarifvergleich (Monat/Jahr), Kosten-
   Aufschlüsselung einer kWh, Methodik + Quellen. Beantwortet: dynamischer Tarif
   wählen oder beim Fixtarif bleiben?

## Ansichten / Endpunkte
- `/analyse/strompreis` → `templates/analyse_strompreis_view.html`
- `GET /api/tarif/tag?date=YYYY-MM-DD` → 15-min-Gesamtpreis-Kurve (brutto ct/kWh,
  live aus `spot_price_15min` via Kostenmodell) + Tagesbilanz aus `tariff_cost_daily`.
- `GET /api/tarif/analyse?year=` → Monats-/Jahresvergleich (`tariff_cost_*`),
  Komponenten-Breakdown, Fixkosten, Quellen.

## Chart-Overlay (ECharts)
Die Tag-Charts (`tag_view.html` Produktion+Verbrauch, `verbraucher_view.html`
Lasten) laden `tariffData` über `/api/tarif/tag` und zeichnen eine zusätzliche
**dritte Achse** (`position:'right'`, ct/kWh) + Stufen-Linie (`step:'end'`,
`type:'dotted'`, `#111`, `width:1`). Bewusst andere Optik als alle Mess-Serien.
Auf Mobile werden die Achsen-Labels ausgeblendet (Linie + Tooltip bleiben), um
Kollision mit der SOC-%-Achse zu vermeiden.

## Code-Anchor
- **Blueprint (Rolle B):** `routes/tarif.py:strompreis_page`,
  `routes/tarif.py:api_tarif_tag`, `routes/tarif.py:api_tarif_analyse`
- **Registrierung:** `web_api.py` (`tarif_bp`)
- **Analyse-Ansicht:** `templates/analyse_strompreis_view.html`
- **Overlay Produktion/Verbrauch:** `templates/tag_view.html`
  (`tariffPriceSeries`, `tariffPriceYAxis`, `applyTariffOverlay`, `tariffTooltipFooter`)
- **Overlay Lasten:** `templates/verbraucher_view.html` (`createDayChart`, `priceByQuarter`)
- **Nav-Eintrag:** `static/js/nav-ui.js` (`/analyse/strompreis`)
- **Kostenmodell:** `dynamic_tariff.py`

## Inputs / Outputs
- **Inputs:** `spot_price_15min`, `tariff_cost_daily/monthly/yearly` (über Tiered-
  Shadow-Views read-only: RAM ∪ analysis.db); `config.DYN_TARIF`.
- **Outputs:** HTML-Ansicht + JSON-APIs. Kein DB-Write, kein Hardware-Zugriff.

## Invarianten
- Rolle B: strikt read-only. Preis-Kurve wird live aus Spot abgeleitet (nicht
  persistiert); Tages-/Monats-/Jahresbilanz kommt fertig aus `tariff_cost_*`.
- Gesamtpreis-Logik ausschliesslich über `dynamic_tariff` (keine Duplikate im JS/Route).
- Fixtarif-Vergleich tagesgenau (`dynamic_tariff.fixtarif_ct`) — Tarifwechsel
  22.02.2026 korrekt berücksichtigt.

## No-Gos
- Keine Aktor-/BatteryConfig-Aufrufe (Schicht B).
- Spot/Adder NICHT im Template hart kodieren — immer aus der API/`config.DYN_TARIF`.
- Preis-Serie nicht in den Leistungs-Stack mischen (eigene yAxis, eigene Optik).

## Häufige Aufgaben
- Preis-Parameter ändern → `config.DYN_TARIF` (+ Reaggregation, s. Collector-Card).
- Overlay-Optik/Achse anpassen → `tariffPriceYAxis`/`tariffPriceSeries` (tag_view),
  `createDayChart` Preis-Serie (verbraucher_view).
- Smoke-Test → `http://127.0.0.1:8000/analyse/strompreis`, `…/monitoring`, `…/verbraucher`.

## Bekannte Fallstricke
- Jinja/Gunicorn cachen Templates: nach Template-Änderung Web neu laden
  (`systemctl restart pv-web.service`). Neue `config`-Attribute → voller Restart.
- Zwei rechte Achsen (SOC % + ct/kWh): Desktop versetzt (`offset`), Mobile Labels aus.
- `/api/tarif/tag` ohne Spot-Daten (Zukunft > morgen) → leere `points`, Overlay entfällt.

## Verwandte Cards
- [`collector-dynamic-price.card.md`](./collector-dynamic-price.card.md) — Datenbasis + Kostenmodell
- [`web-display-api.card.md`](./web-display-api.card.md) — Blueprint-/Read-only-Muster
- [`collector-db-schema.card.md`](./collector-db-schema.card.md) — `spot_price_15min`, `tariff_cost_*`

## Human-Doku
- `doc/web/STROMPREIS_ANALYSE.md`
