---
title: Web Display/API (Blueprints, Read-only Zugriff, Formatierung)
domain: web
role: B
applyTo: "routes/**"
tags: [web-api, blueprints, templates, formatting, read-only]
status: stable
last_review: 2026-05-03
---

# Web Display/API

## Zweck
Schicht B fuer UI und API-Ausgabe: Blueprints registrieren, Daten read-mostly bereitstellen und Werte konsistent im Frontend darstellen.

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
- HA-Entitäten erweitern -> `routes/system.py` im Abschnitt `/api/ha/*` anpassen und den Katalog in `/api/ha/entities` aktualisieren.

## Bekannte Fallstricke
- Display-Formatter sind template-lokal; parallele Formatter in anderen Views koennen driften.
- Forecast-Persistierung schreibt in DB-Tabellen (`forecast_daily`, `data_15min`) und ist damit eine kontrollierte Ausnahme vom read-only Zielbild.
- Mirror-/CORS-Umgebungsvariablen beeinflussen Verhalten stark; lokale Abweichungen zuerst dort pruefen.

## Verwandte Cards
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`netzqualitaet-analysis.card.md`](./netzqualitaet-analysis.card.md)

## Human-Doku
- `doc/web/DISPLAY_CONVENTIONS.md`
- `doc/web/HA_INTEGRATION.md`
- `doc/SYSTEM_BRIEFING.md`
