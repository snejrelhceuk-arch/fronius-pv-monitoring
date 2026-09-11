---
title: Web Analyse — Speicherausbau (Amortisationsnachweis)
domain: web
role: B
applyTo: "routes/analyse_speicher.py"
tags: [analyse, speicher, amortisation, batterie, pv-zubau, nulleinspeiser, abregelung, optimierung]
status: stable
last_review: 2026-09-11
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
- Sweep vektorisiert ueber Kapazitaeten (numpy); Wirtschaft (Preis/Kosten/Amortisation)
  wird im Frontend live variiert.

## Code-Anchor
- **Modell:** `analysis/storage_model.py:run_sweep`, `analysis/storage_model.py:run_detail`,
  `analysis/storage_model.py:_reconstruct`, `analysis/storage_model.py:_dispatch`
- **Blueprint (Rolle B):** `routes/analyse_speicher.py:speicherausbau_page`,
  `routes/analyse_speicher.py:api_sweep`, `routes/analyse_speicher.py:api_detail`
- **Registrierung:** `web_api.py` (`analyse_speicher_bp`)
- **Ansicht:** `templates/analyse_speicherausbau_view.html`
- **Parameter/Presets:** `config/storage_expansion.json`
- **Nav-Eintrag:** `static/js/nav-ui.js` (`/analyse/speicherausbau`)
- **Clear-Sky-Quelle:** `solar_geometry.py:get_clearsky_day_curve` (Tagescache unter `tmp/`)

## Inputs / Outputs
- **Inputs:** `data_5min_permanent` (STATS-DB, permanent 5-min) read-only; `monthly_statistics`
  (Annualisierungs-Referenz); Clear-Sky aus `solar_geometry`; `config/storage_expansion.json`.
- **Outputs:** HTML-Ansicht; `GET /api/analyse/speicher/sweep` (Kurve + Wirtschaft + Optimum);
  `GET /api/analyse/speicher/detail` (Monatsaufschluesselung eines Szenarios).

## Invarianten
- Rolle B: read-only. Kein Hardware-Zugriff, kein DB-Write, keine Aktorik.
- Datenquelle ist die permanente 5-min-Tabelle; Ergebnisse werden per `×365/Tage`
  auf das Jahr projiziert und mit dem Zeitraum im UI ausgewiesen.
- `avoided` ist durch `residual_deficit` (gemessener Bezug) begrenzt: Sommerueberschuss
  laesst sich nicht saisonal in den Winter verschieben — das begrenzt den Nutzen.
- Wirtschaft ist Nulleinspeiser: vermiedene Bezugs-kWh = voller Bezugspreis, Ueberschuss = 0.

## No-Gos
- Keine Nutzung von `fronius_api.BatteryConfig` oder Aktoraufrufen (Schicht B).
- `curtailed` ist eine *Schaetzung* (Groessenordnung) — nicht als eichgenaue Energie ausgeben.
- Kein Schreiben in `data.db`/STATS-DB; STATS-DB immer `mode=ro` oeffnen.

## Häufige Aufgaben
- Kosten/Preis-Defaults aendern → `config/storage_expansion.json` (`kosten`/`wirtschaft`).
- Abregelungs-Erkennung justieren → `technik.soc_cap_detect_pct` (Bestands-SOC-Deckel).
- Neues Angebot als Preset → `config/storage_expansion.json:presets`.
- Lokaler Smoke-Test → `http://127.0.0.1:8000/analyse/speicherausbau` (Prod-Port).

## Bekannte Fallstricke
- Clear-Sky `total_ac` ist absolut ueberschaetzt; erst `alpha_day` kalibriert es an die
  Realitaet. Ohne Clear-Sky (Modul fehlt) faellt die Abregelungs-Rekonstruktion aus →
  `avoided` ist dann nur exportgebunden (Nulleinspeiser: klein) — im UI kenntlich.
- Datenfenster ist der Umfang von `data_5min_permanent` (Jahresanfang bis gestern); Herbst
  kann fehlen → Annualisierung ist eine lineare Projektion, kein Messjahr.
- Jinja/Gunicorn cached Templates: Template-Aenderungen erst nach Web-Reload
  (`kill -HUP $(cat /tmp/pv_web.pid)` bzw. `pv-web.service` neu starten).

## Verwandte Cards
- [`web-display-api.card.md`](./web-display-api.card.md) — Blueprint-/Read-only-Muster
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md) — `W_Ertrag`/`W_Verbrauch`/`W_Bezug`
- [`collector-db-schema.card.md`](./collector-db-schema.card.md) — `data_5min_permanent`, Retention

## Human-Doku
- `doc/web/SPEICHERAUSBAU_ANALYSE.md`
