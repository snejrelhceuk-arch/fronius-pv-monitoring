---
title: Web Display/API (Blueprints, Read-only Zugriff, Formatierung)
domain: web
role: B
applyTo: "routes/**"
tags: [web-api, blueprints, templates, formatting, read-only]
status: stable
last_review: 2026-06-27

---

# Web Display/API

## Zweck
Schicht B fuer UI und API-Ausgabe: Blueprints registrieren, Daten read-mostly bereitstellen und Werte konsistent im Frontend darstellen.

## Changes
- 2026-06-27 (b): Responsive-Feinschliff kleine Screens. Gemeinsame Helfer `PVChart.xAxisLabel`/`PVChart.tooltipResponsive` (`static/js/nav-ui.js`): X-Achsen-Labels dünnen auf schmalen Screens automatisch aus (`interval:'auto'`, `hideOverlap`), Tooltips bleiben im Viewport (`confine:true`) und werden bei Bedarf größenbegrenzt + ohne sichtbaren Scrollbalken scrollbar (Klasse `pv-echarts-tip`, Scrollbar-Ausblendung in `static/css/nav-ui.css`). Eingehängt in Balken-/Tages-Charts von `tag_view.html`, `erzeuger_view.html`, `verbraucher_view.html`; Verbraucher-Tageschart nutzt jetzt dieselbe breitenabhängige Label-Ausdünnung wie Erzeuger. Desktop/Tablet unverändert.
- 2026-06-27: Zentraler Zeit-Navigationsspeicher. `static/js/nav-context.js` neu: `PVNavContext.commit/getState/currentQuery` als EINE Quelle der Wahrheit für `period/date/year/month` (localStorage `pvNavState` + URL via `replaceState`, Verfall nach 1 h). Jeder Chart-View (`tag_view`/`erzeuger_view`/`verbraucher_view`) committet bei jedem Navigationswechsel; die Seiten-Schublade (`static/js/nav-ui.js`) baut die Links beim Öffnen frisch aus `currentQuery()`. Behebt: Kalender-/Zeitraum-Verlust beim Seitenwechsel, Einstieg Erzeuger/Verbraucher aus Monitoring/Gesamt landet jetzt im Gesamt-Chart (vorher Tag), Rücksprung Jahr→Monitoring behält Jahr; aktive View-Buttons werden bei Direkteinstieg synchronisiert (`setActiveViewButton`).
- 2026-06-20 (c): Doku-Hinweis geschärft: lokale Web-/Smoke-Tests laufen auf Port **8000** (nicht 5000), damit Route-Checks reproduzierbar sind.
- 2026-06-20 (b): Extremwerte-Tooltips v3 + Peak-Fix + Navigation. (1) Peak-Leistung Monat/Jahr/Gesamt war falsch (`P_AC_Inv_max` = nur F1, ~12 kW HW-Limit): `routes/visualization.py:/api/period_extremes` nutzt jetzt `daily_data.P_PV_total_max` (zeitgleicher System-Peak, COALESCE-Fallback). (2) V/Frequenz/cos φ in allen Tooltips + Statistik-Tabelle MIT Datum/Uhrzeit (`_vf_pf_extremes`, data_1min ≤90 Tage, Fallback data_monthly). (3) `static/js/extremes.js` ohne bunte Icons, deutsche Komma-Zahlen, „Größter/Kleinster Tagesertrag/Monat"; Konkurrenz ohne Prozent. (4) Peak-Label weißer Hintergrund. (5) Balken ohne Hover-Fade + `animation:false`. (6) Verbraucher-Legende + Klima/Gefriertruhe/Lüftung. (7) Statistik-Tabelle via `routes/pages.py:_get_pv_grenzwerte_yearly` → `_extremes_gesamt`. (8) Seiten-Schublade + Kalender: `static/js/nav-ui.js` + `static/css/nav-ui.css` (Drawer für Seiten, Zeit oben; Tag/Monat/Jahr=Tageskalender, Gesamt=Monats-Overlay) in tag_view/erzeuger/verbraucher/analyse. (9) Primärenergie-Aktualitätshinweis (`config.PRIMAERENERGIE_STAND`, Verfallstimer 3 Monate) + Menü-Marker.
- 2026-06-20: Extremwerte-Tooltips v2 + Chart-UX. Neuer Endpoint `routes/visualization.py:/api/period_extremes` (period=tag|monat|jahr|gesamt) liefert einheitliche Perioden-Extremwerte (Peak-Leistung, Ertrag best/schwach, Spannung L-L, Frequenz, cos φ) keyed per Tag/Monat/Jahr. Geteilter Formatter `static/js/extremes.js` (`PVExtremes.fetchFor/lines/tagLines`, mobil verkürzt) wird in `tag_view.html`, `erzeuger_view.html`, `verbraucher_view.html` in die Monat/Jahr/Gesamt-Tooltips eingehängt (konsistente Gleichschaltung Monitoring↔Analyse). Peak-Marker neu gestylt (kleiner, Label = Marker-Farbe, nicht fett/weiß). Balken-Charts: Hover-Fade (`emphasis.focus`) entfernt → `emphasis.disabled` + `animation:false`. „Konkurrent"-Anzeige ohne Prozent (nur Wert+Datum). cos φ historisch nur ≤7 Tage (raw_data); Monat-PF füllt sich nach PF-Aggregation in data_1min.
- 2026-06-20: Extremwerte/Navigation/Responsive-Paket. (1) `routes/netzqualitaet.py:_fetch_maxima_raw` liefert zusaetzlich `pf_netz_max`/`pf_netz_min` (Leistungsfaktor PF_Netz, nur raw_data ≤7 Tage); Anzeige in `templates/netzqualitaet_view.html` (Statuszeile, cos φ inkl. Uhrzeit). (2) `routes/erzeuger.py:api_erzeuger_jahr` liefert je Monat `best_day`/`worst_day` (aus `daily_data.W_PV_total`); Tooltip in `templates/erzeuger_view.html`. (3) `routes/pages.py:analyse` + neue Helper `_get_pv_grenzwerte_yearly` → jaehrliche Netz-Extremwerte-Tabelle (Spannung L-L, Frequenz) in `templates/analyse_pv_view.html` (`pv_grenzwerte`). (4) Frontend-only: Peak-Leistungs-Marker (ECharts markPoint) in tag_view/erzeuger/verbraucher Tag-Charts; Rekord-/Konkurrent-Relation in erzeuger/verbraucher Balken-Tooltips; Querformat-Handy-Layout (monitoring.css + tag_view, `isMobile()` Hoehe<500). (5) Nav-Konsistenz: `static/js/nav-context.js` neue Helfer `clampDayOfMonth`/`syncAnchorFrom`; Aufloesungswechsel behaelt Zeitraum (tag_view/erzeuger/verbraucher); localStorage `pvViewState` mit Verfallszeit.
- 2026-06-14: Flow-Fix in `routes/system/battery.py`: falscher Import `SolarGeometry` (Klasse nicht vorhanden) auf `get_clearsky_day_curve` korrigiert; damit liefert `/api/flow_status` wieder Forecast-kWh und ratio-basierte Qualitaet fuer das Flow-Prognoseicon.
- 2026-06-14: `/api/flow_status` (`routes/system/battery.py`) nutzt fuer die Flow-Prognoseanzeige bei fehlendem Live-Forecast einen Fallback auf `get_stored_forecast(heute)`, damit Icon/Klassifikation und kWh-Wert stabil angezeigt werden.
- 2026-06-14: Flow-Ansicht-Prognoseicon in `templates/flow_view.html` nutzt jetzt Forecast/Clear-Sky-Verhaeltnis aus `/api/flow_status` (`routes/system/battery.py`): `mittel` bei <70%, `schlecht` bei <40%; zusaetzlich wird die Tages-Prognose als kWh-Wert unter dem Icon angezeigt.
- 2026-06-02: `routes/system/info.py:/api/ticker` bleibt schlanker Proxy auf den konfigurierten Ticker-Upstream; Quoten-/Mischlogik liegt ausschliesslich im Ticker-Service (`tools/ticker_service/ticker_server.py`).
- 2026-05-29: `routes/system` (Monolith, ≈1950 Z.) in das Paket `routes/system/` aufgeteilt (Audit-Refactor 2026-05-16). Submodule: `automation.py`, `battery.py`, `ha.py`, `wattpilot.py`, `failover.py`, `info.py`, gemeinsames `_shared.py`; `routes/system/__init__.py` definiert das geteilte `bp` und importiert die Submodule (Blueprint-Sharing). Verhalten/Endpunkte unverändert (14 Routen), `web_api.py` unverändert.
- 2026-05-25: Konsistenz Monat/Jahr/Gesamt → `routes/visualization.py` nutzt jetzt `gesamt_verbrauch_kwh` aus `monthly_statistics` (Counter-basiert); Autarkie-Anzeige in `templates/tag_view.html` mit 1 Nachkommastelle.
- 2026-05-23: Adjusted ticker animation duration and increased ticker font sizes in `templates/flow_view.html` (UI tweak to slow ticker by ~20%).

## Code-Anchor
- **App + Blueprint-Setup:** `web_api.py` (`app.register_blueprint(...)`)
- **Read-only Fronius-Zugriff:** `routes/helpers.py:FroniusReadOnly`, `routes/helpers.py:get_fronius_api`
- **DB-Zugriff:** `routes/helpers.py:get_db_connection`
- **Page-Routen:** `routes/pages.py` (z. B. `maschinenraum`, `netzqualitaet`)
- **Forecast-API + Persistierung:** `routes/forecast.py:api_forecast_tag`, `routes/helpers.py:store_forecast_daily`
- **Display-Formatter:** `templates/tag_view.html:formatValue`

## Inputs / Outputs
- **Inputs:** Aggregat-/Rohdaten aus SQLite ueber `routes/helpers.py`, Forecastdaten, Query-Parameter der API-Endpunkte.
- **Outputs:** HTML-Views (`templates/*.html`) und JSON-Endpunkte unter `/api/*`.

### HA-Export (neu)
- Lesepfade für Home Assistant: `/api/ha/flow`, `/api/ha/wattpilot`, `/api/ha/automation`, plus Discovery über `/api/ha`, `/api/ha/device`, `/api/ha/entities`.
- Optionaler MQTT-Adapter konsumiert diese Lesepfade (`steuerbox/ha_mqtt_bridge.py`) und bleibt damit read-only in Rolle B.

## Invarianten
- Keine Hardware-Schreibzugriffe in Schicht B; Fronius nur ueber `FroniusReadOnly`.
- API-CORS bleibt auf GET/OPTIONS ausgelegt (`web_api.py:add_cors_headers`).
- Route-Logik bleibt in Blueprints; gemeinsame DB-/API-Helfer in `routes/helpers.py`.
- Mirror-Modus darf Anzeige beeinflussen, aber keine Aktorik ausloesen.

## No-Gos
- Keine Nutzung von `fronius_api.BatteryConfig` in Web-Routen.
- Keine direkten Aktoraufrufe aus `routes/*` oder `web_api.py`.
- Keine inkonsistente Wertformatierung ohne Anpassung der Display-Konventionen.

## Häufige Aufgaben
- Neue API-Route -> passendes Blueprint-Modul in `routes/` erweitern und in `web_api.py` registrieren.
- Einheitendarstellung korrigieren -> Formatter in `templates/tag_view.html` und Konventionen in `doc/web/DISPLAY_CONVENTIONS.md` synchron halten.
- Forecast-Fehler analysieren -> `routes/forecast.py` und `routes/helpers.py:store_forecast_daily` gemeinsam debuggen.
- HA-Entitäten erweitern -> `routes/system/ha.py` im Abschnitt `/api/ha/*` anpassen und den Katalog in `/api/ha/entities` aktualisieren.
- Lokaler Smoke-Test von Web-Routen -> immer `http://127.0.0.1:8000/...` verwenden (Produktionsport), nicht `:5000`.

## Bekannte Fallstricke
- Display-Formatter sind template-lokal; parallele Formatter in anderen Views koennen driften.
- **Template-/Static-Deploy:** Unter Gunicorn (Prod) cached Jinja kompilierte Templates; `templates/*.html`-Änderungen werden erst nach Reload des Web-Workers wirksam (`sudo kill -HUP $(cat /tmp/pv_web.pid)` bzw. Restart `pv-web.service`). `static/*` (JS/CSS) liefert dagegen mit `Cache-Control: no-cache` + ETag frisch aus.
- Forecast-Persistierung schreibt in DB-Tabellen (`forecast_daily`, `data_15min`) und ist damit eine kontrollierte Ausnahme vom read-only Zielbild.
- Mirror-/CORS-Umgebungsvariablen beeinflussen Verhalten stark; lokale Abweichungen zuerst dort pruefen.
- Zeit-Navigationszustand liegt zentral in `nav-context.js` (`pvNavState` + URL); Monitoring führt zusätzlich `pvViewState` nur für die Ertrag/Verbrauch-Unteransicht.

## Verwandte Cards
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`netzqualitaet-analysis.card.md`](./netzqualitaet-analysis.card.md)

## Human-Doku
- `doc/web/DISPLAY_CONVENTIONS.md`
- `doc/web/HA_INTEGRATION.md`
- `AGENTS.md` (Architektur-Skelett)
