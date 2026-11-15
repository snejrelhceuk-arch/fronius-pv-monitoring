---
title: Web Analyse — Speicherausbau (Amortisationsnachweis)
domain: web
role: B
applyTo: "routes/analyse_speicher.py"
tags: [analyse, speicher, amortisation, batterie, pv-zubau, nulleinspeiser, abregelung, optimierung]
status: stable
last_review: 2026-11-15
---

# Web Analyse — Speicherausbau

## Zweck
Vorwaerts gerichtetes, read-only Entscheidungsmodell im Analyse-Bereich: belegt
messtechnisch/rechnerisch, wie viel **Netzbezug** ein groesserer Speicher (plus
optionaler PV-Zubau) zusaetzlich vermeidet — und ob sich der Ausbau innerhalb der
Amortisationsgrenze rechnet. Zeigt per Schieber, dass ein kleinerer *wie* groesserer
Ausbau schlechter ist als das Optimum. Ansicht: `/analyse/speicherausbau`.

## Modellkern (inkrementell, ohne Baseline-Kalibrierung)
- Treiber je 5-min-Intervall: `available_surplus = curtailed + W_Einspeis`,
  `residual_deficit = W_Bezug`. Der virtuelle Zusatzspeicher laedt aus dem Ueberschuss
  und deckt den gemessenen Bezug: `avoided(A)` = Summe gedeckter Defizite.
  `avoided(0)=0`, monoton, saettigend → Optimum ueber der Amortisationsgrenze.
- **Nulleinspeiser-Abregelung** (`curtailed`): bei vollem Bestandsspeicher (SOC ≥
  `soc_cap_detect_pct`, ~73 %) ist der Ueberschuss im Messwert `W_Ertrag` NICHT
  enthalten. Rekonstruktion gegen selbstkalibrierte Clear-Sky-Prognose:
  `alpha_day` = realisierte/Clear-Sky-Erzeugung in nicht gedeckelten Tagesstunden;
  `curtailed = max(clearsky·alpha − W_Ertrag, 0)` nur in gedeckelten Intervallen.
- **PV-Zubau**: `available_surplus += clearsky_norm · add_kwp · alpha_day` (Tag = Ueberschuss).
- Sweep vektorisiert ueber Kapazitaeten (numpy); Kapazitaets-Gitter in **ganzen kWh**
  (saubere X-Achse). Wirtschaft (Preis/Kosten/Amortisation) wird im Frontend live variiert.

## Annualisierung (saisonal, auf Messwerten gegruendet)
- **Baseline-Netzbezug/-Verbrauch** NICHT linear ×365/Tage, sondern aus den gemessenen
  Monatswerten der aktuellen Haushalts-Aera: `measured_profile()` nimmt die letzten ≤12
  *vollstaendigen* Monate ab `ERA_START` (Okt 2025; Jahre davor haben ein anderes
  Lastprofil → bewusst ausgeschlossen) inkl. Dezember. Das 5-min-Fenster beginnt erst
  Jan 2026 (dezember-los) → lineare Hochrechnung unterschaetzte den Winterbezug.
- **Simulierter vermiedener Bezug** wird je Kalendermonat annualisiert
  (`_annualize_by_month` + `_month_geometry`): Teilmonate (z. B. Nov) auf Vollmonat
  normalisiert, fehlende Monate (Dezember, keine 5-min-Daten) aus Kalendernachbarn
  geschaetzt, je Monat auf den gemessenen Netzbezug gedeckelt (`min(avoided, W_Bezug)`).
- **Herbst-Gleichwochen-Vergleich** (`autumn_comparison`): tag-genauer Effekt der
  Speichererweiterung aus `daily_data` (Okt/Nov 2025 vs. 2026, nur in beiden Jahren
  vorhandene Tage) — read-only Beleg, keine Simulationsgroesse.

## Code-Anchor
- **Modell:** `analysis/storage_model.py:run_sweep`, `analysis/storage_model.py:run_detail`,
  `analysis/storage_model.py:_reconstruct`, `analysis/storage_model.py:_dispatch`
- **Annualisierung/Baseline:** `analysis/storage_model.py:measured_profile`,
  `analysis/storage_model.py:_annualize_by_month`, `analysis/storage_model.py:_month_geometry`,
  `analysis/storage_model.py:autumn_comparison`
- **Blueprint (Rolle B):** `routes/analyse_speicher.py:speicherausbau_page`,
  `routes/analyse_speicher.py:api_sweep`, `routes/analyse_speicher.py:api_detail`
- **Registrierung:** `web_api.py` (`analyse_speicher_bp`)
- **Ansicht:** `templates/analyse_speicherausbau_view.html`
- **Parameter/Presets:** `config/storage_expansion.json`
- **Nav-Eintrag:** `static/js/nav-ui.js` (`/analyse/speicherausbau`)
- **Clear-Sky-Quelle:** `solar_geometry.py:get_clearsky_day_curve` (Tagescache unter `tmp/`)

## Inputs / Outputs
- **Inputs:** `data_5min_permanent` (STATS-DB, permanent 5-min) read-only; `monthly_statistics`
  + `daily_data` (ANALYSIS-DB, gemessene Baseline/Herbstvergleich) read-only; Clear-Sky aus
  `solar_geometry`; `config/storage_expansion.json`.
- **Outputs:** HTML-Ansicht; `GET /api/analyse/speicher/sweep` (Kurve + Wirtschaft + Optimum
  + `autumn`-Vergleich); `GET /api/analyse/speicher/detail` (repraesentative Monatsaufschluesselung).

## Invarianten
- Rolle B: read-only. Kein Hardware-Zugriff, kein DB-Write, keine Aktorik.
- Dispatch-Datenquelle ist die permanente 5-min-Tabelle; Baseline (Netzbezug/Verbrauch)
  ist gemessen (`measured_profile`, Aera ab Okt 2025), vermiedener Bezug saisonal je
  Kalendermonat annualisiert — keine globale `×365/Tage`-Projektion mehr.
- `avoided` ist je Kalendermonat durch den gemessenen Bezug gedeckelt und in Summe ≤
  Baseline-Netzbezug: Sommerueberschuss laesst sich nicht in den Winter verschieben.
- Wirtschaft ist Nulleinspeiser: vermiedene Bezugs-kWh = voller Bezugspreis, Ueberschuss = 0.

## No-Gos
- Keine Nutzung von `fronius_api.BatteryConfig` oder Aktoraufrufen (Schicht B).
- `curtailed` ist eine *Schaetzung* (Groessenordnung) — nicht als eichgenaue Energie ausgeben.
- Kein Schreiben in `data.db`/STATS-DB/ANALYSIS-DB; immer `mode=ro` oeffnen.
- Baseline-Mittel NICHT auf Jahre vor Okt 2025 ausdehnen (anderes Lastprofil: E-Autos).

## Häufige Aufgaben
- Kosten/Preis-Defaults aendern → `config/storage_expansion.json` (`kosten`/`wirtschaft`).
- Abregelungs-Erkennung justieren → `technik.soc_cap_detect_pct` (Bestands-SOC-Deckel).
- Baseline-Aera-Start aendern → `storage_model.ERA_START_YEAR/MONTH`.
- Neues Angebot als Preset → `config/storage_expansion.json:presets`.
- Lokaler Smoke-Test → `http://127.0.0.1:8000/analyse/speicherausbau` (Prod-Port).

## Bekannte Fallstricke
- Clear-Sky `total_ac` ist absolut ueberschaetzt; erst `alpha_day` kalibriert es an die
  Realitaet. Ohne Clear-Sky (Modul fehlt) faellt die Abregelungs-Rekonstruktion aus →
  `avoided` ist dann nur exportgebunden (Nulleinspeiser: klein) — im UI kenntlich.
- 5-min-Fenster beginnt Jan 2026 (dezember-los) → Dezember im Monatschart ist aus
  Nachbarmonaten geschaetzt (`estimated`, gedimmt); Baseline-Winter kommt aus Messwerten.
- Jinja/Gunicorn cached Templates: Template-Aenderungen erst nach Web-Reload
  (`kill -HUP $(cat /tmp/pv_web.pid)` bzw. `pv-web.service` neu starten). **Neue
  config.py-Modulattribute** brauchen einen vollen `systemctl restart pv-web.service`
  (HUP allein zieht sie nicht).

## Verwandte Cards
- [`web-display-api.card.md`](./web-display-api.card.md) — Blueprint-/Read-only-Muster
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md) — `W_Ertrag`/`W_Verbrauch`/`W_Bezug`
- [`collector-db-schema.card.md`](./collector-db-schema.card.md) — `data_5min_permanent`, Retention

## Human-Doku
- `doc/web/SPEICHERAUSBAU_ANALYSE.md`
