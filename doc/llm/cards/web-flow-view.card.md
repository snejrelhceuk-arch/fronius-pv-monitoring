---
title: Flow-Ansicht Rendering-Mechanik (SVG, Breakpoints, Mobile-Pan)
domain: web
role: B
applyTo: "templates/flow_view.html,routes/flow_greetings.py"
status: stable
last_review: 2026-09-29
---

# Flow-Ansicht Rendering-Mechanik

## Zweck
Erklärt **wie** die Energiefluss-Visualisierung (`/flow`) rendert — insbesondere die
SVG-Skalierung über Breakpoints und den Mobile-Portrait-Pan. Diese Mechanik ist ein
bekannter Fallstrick-Herd: Beschnitt entsteht an **drei** unabhängigen Stellen (viewBox,
`display`, SVG-Größe), die alle dasselbe Symptom erzeugen. Wer nur eine ändert, sieht keine
Wirkung.

## Code-Anchor
- **Seite/Route:** `routes/pages.py:flow` → `templates/flow_view.html` (injiziert `steuerbox_cockpit_url` aus `config.STEUERBOX_EXTERNAL_PORT`/`STEUERBOX_COCKPIT_URL`, getattr-robust)
- **SVG-Skalierung/Pan:** `templates/flow_view.html:adjustSvgViewBox` (setzt viewBox + Mobile-Wrapper)
- **Overlay-/Layout-Sync:** `templates/flow_view.html:syncOverlayLayout` (ruft `adjustSvgViewBox`)
- **Live-Daten:** `routes/realtime.py:/api/flow_realtime`, `/api/flow_devices`; `routes/system/battery.py:/api/flow_status`
- **Bubble-Kontext-Rollup (P1.0/P1.1/H1):** `static/js/flow-bubbles.js` + `static/css/flow-bubbles.css`; Bubbles tragen `data-bubble="…"` im SVG.
- **Begrüßungs-/Statuszeile:** `templates/flow_view.html:pvGreeting` (dezent, breitenrobust, kein Umbruch). Die **Kontext-Phrase** liefert das Backend: editierbarer Bausteinkatalog `routes/flow_greetings.py` (≤100 Schnipsel; Auswahl über Tageszeit × Prognosequalität × Lage `akku_voll`/`akku_leer`, Platzhalter {kwh}/{rest_kwh}/{morgen_kwh}/{morgen_qual}/{soc}) via `routes/system/battery.py:_apply_greeting` → Felder `greeting`/`greeting_short` in `/api/flow_status`. Der Client stellt Gruß + Ort voran und wählt lang/kurz nach Breite; Fallback = schlichte prognosebasierte Phrase, `<420 px` ausgeblendet.
- **Flow-Schnellzugriff in der Nav:** `static/js/nav-ui.js:initDrawer` (`.pv-flow-quick` neben dem Burger, außer auf `/flow`; Icon = bidirektionale Fluss-Pfeile). Das Seiten-Menü selbst ist ein aufklappbares Rollup (`nav-ui.js:makeGroup`, Gruppen Monitoring/Analyse/Netzqualität▸Spektralanalyse/Darstellung aller Einzelwerte) — **kein** eigener Flow-Eintrag mehr.
- **Tooltip-Skin (schwach transparent):** `static/js/nav-ui.js:tooltipResponsive` (+ `static/css/nav-ui.css:.pv-echarts-tip`)
- **Tagesgüte-Icon (ClearSky-relativ):** `routes/system/battery.py:_build_flow_status_result` setzt `pv_forecast_quality/-emoji` über `solar_forecast.classify_day_relative` (Prognose/ClearSky: <40 % ☁️ schlecht, 40–70 % ⛅ mittel, ≥70 % ☀️ gut) — **nicht** die absolute kWh-Einstufung. Renderer `templates/flow_view.html:setPvForecastIcon`.

## Kontext-Rollup je Bubble (Komfort/Info/Hinweis)
- Hover (Desktop) bzw. Long-Press (Touch, ~520 ms) auf einer Bubble öffnet ein **HTML-Overlay-Rollup** (`.fb-rollup`, `position:fixed`, an der Bubble-Bildschirmposition). Kurzer Tap behält die bestehende Schnell-Navigation der Haupt-Bubbles. Der Rollup-Skin ist identisch zum ECharts-Tooltip (`rgba(15,23,42,0.60)` + `blur(3px)`, s. `.pv-echarts-tip`).
- Gruppen: **Komfort · Cockpit** = segmentierte **Mini-Schalter** (`sw` im `MENU`, Optik wie das Cockpit-Statebar; z. B. Ladestrom 8/16/24 A), jedes Segment ein **Deep-Link** auf die passende Cockpit-Karte (Schicht E, `#card-wp`/`#card-wattpilot`/`#card-battery`/`#card-toggles`); **[I] Info** = read-only Navigations-/Monitoring-Links; **[D] Hinweis** = reiner Guard-Hinweis (kein Link).
- **Keine Maschinenraum-Deep-Links mehr aus den Bubbles.** Der Maschinenraum ist ausschließlich über den 60-s-Button unterhalb der Netz-Bubble erreichbar; dessen Sub-Button ist **ein** `ssh://admin@<host>`-Link auf `pv-config` (kein Ausführen aus der API).
- **Rolle B bleibt read-only:** kein direkter Aktor-/POST-Pfad aus der Bubble. Komfort läuft ausschließlich als Deep-Link ins Cockpit (mTLS/Allowlist der Steuerbox). Wattpilot-Komfort trägt einen Multi-Master-Hinweis (kein paralleler WS-Client).
- Menü-Katalog + Interaktionslogik in `static/js/flow-bubbles.js` (`MENU`, `makeSwitchRow`), Bubble-Zuordnung über `data-bubble` im SVG.

## Rendering-Mechanik (IST)
- **Ein festes SVG** mit `viewBox="130 -40 590 460"` (Konstante `DEFAULT_VIEWBOX`). Alle Knoten
  liegen in diesem Koordinatenraum (x = 130…720). `preserveAspectRatio="xMidYMin meet"` → Inhalt
  wird **immer vollständig** eingepasst (kein Beschnitt durch den viewBox, solange er `DEFAULT` ist).
- **Desktop/Querformat:** SVG ist Flex-Kind der `.flow-chart` (`flex:1`), Breite 100 % (max 960 px),
  Höhe = verfügbarer Flex-Platz. Keine Sonderbehandlung.
- **Mobile-Portrait (`innerWidth<600 && Höhe>Breite`):** `adjustSvgViewBox` erzeugt einen
  **Scroll-Wrapper** `#flow-svg-scroll` (per JS in den DOM eingefügt, SVG hineingeschoben) und setzt
  das SVG auf **feste Pixelgröße**: Breite = `max(480, sichtbareBreite×1.35)`, Höhe = `Breite×460/590`
  (= viewBox-Seitenverhältnis → **kein Leerraum**). Der Wrapper (`overflow-x:auto`) macht das breitere
  SVG **horizontal wischbar**; so werden die rechten Bubbles erreichbar. Pinch-Zoom = Seiten-Zoom
  (Viewport-Meta erlaubt es).
- **Rückbau:** Bei Querformat/Desktop entfernt `adjustSvgViewBox` den Wrapper wieder und setzt die
  Inline-Größen zurück. Aufgerufen bei Load, Resize und Maschinenraum-Toggle.

## Bubble-Koordinaten (viewBox-Raum)
- **Hauptknoten:** Netz, PV Gesamt, Verbrauch, Batterie (mittlere x-Spalte).
- **Sub-Erzeuger** `.sub-producers` (oben): F1 (250,30), F2 (350,15), F3 (450,30).
- **Sub-Verbraucher** `.sub-consumers` (rechts): HP/Heizpatrone (565,50), Klima (660,80),
  Haushalt (665,190), WP/Wärmepumpe (500,340), Wattpilot (660,315).
- Die **rechte Gruppe** (x≈565…665) liegt am rechten viewBox-Rand → auf schmalen Screens nur per Pan sichtbar.

## Invarianten
- Mobile-Portrait zeigt das **vollständige** Chart in angenehmer Größe und ist horizontal wischbar —
  **nicht** auf Bildschirmhöhe gezoomt und **nicht** beschnitten.
- SVG-Höhe folgt dem viewBox-Seitenverhältnis (Breite×460/590) → kein vertikaler Leerraum.
- viewBox bleibt `DEFAULT_VIEWBOX` auf allen Breakpoints.

## No-Gos
- **viewBox nie beschneiden** (kein `"80 70 500 320"` o. ä.) — schneidet die rechten Knoten hart ab.
- **Sub-Bubbles nie per `display:none` ausblenden** — dann laufen die Flussleitungen ins Leere.
- **SVG nicht per `height:100%` auf die Wrapper-Höhe strecken** — erzeugt Leerraum + Kleinskalierung.
- Keine Aktor-/Schreibzugriffe (Rolle B, read-only). Bubble-Komfort **nur** als Deep-Link ins Cockpit (E), nie als direkter POST/WS aus der Web-UI.
- Begrüßungszeile nie mehrzeilig: bei wenig Platz kürzen (Stufen in `pvGreeting`) bzw. `<420 px` ausblenden — kein Zeilenumbruch.

## Häufige Aufgaben
- Bubble verschieben/hinzufügen → SVG-Koordinaten in `templates/flow_view.html` **innerhalb**
  x=130…720 halten, sonst am Rand/Beschnitt. Danach Mobile-Portrait bei 390×844 gegenprüfen.
- Mobile-Größe justieren → Faktor `1.35`/Mindestbreite in `adjustSvgViewBox`.
- Änderung prüfen → Ziel-Viewport headless rendern + screenshotten (s. AGENTS.md „UI visuell verifizieren").

## Bekannte Fallstricke
- **Drei-Ursachen-Falle:** viewBox-Beschnitt, `display:none` der Sub-Gruppen und `height:100%`-Streckung
  erzeugen dasselbe „Kappung"-Symptom. Immer **alle drei** prüfen, bevor eine Änderung als wirkungslos gilt.
- `overflow-x` auf dem Flex-Kind allein scrollt auf iOS nicht zuverlässig → dedizierter Wrapper nötig.
- Unter Gunicorn cached Jinja Templates; `templates/*.html`-Änderungen erst nach Web-Reload sichtbar.

## Verwandte Cards
- [`web-display-api.card.md`](./web-display-api.card.md) — Blueprints, Read-only API, Formatierung

## Human-Doku
- `doc/web/DISPLAY_CONVENTIONS.md`
