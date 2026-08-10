---
title: Flow-Ansicht Rendering-Mechanik (SVG, Breakpoints, Mobile-Pan)
domain: web
role: B
applyTo: "templates/flow_view.html"
status: stable
last_review: 2026-08-10
---

# Flow-Ansicht Rendering-Mechanik

## Zweck
Erklärt **wie** die Energiefluss-Visualisierung (`/flow`) rendert — insbesondere die
SVG-Skalierung über Breakpoints und den Mobile-Portrait-Pan. Diese Mechanik ist ein
bekannter Fallstrick-Herd: Beschnitt entsteht an **drei** unabhängigen Stellen (viewBox,
`display`, SVG-Größe), die alle dasselbe Symptom erzeugen. Wer nur eine ändert, sieht keine
Wirkung.

## Code-Anchor
- **Seite/Route:** `routes/pages.py:flow` → `templates/flow_view.html`
- **SVG-Skalierung/Pan:** `templates/flow_view.html:adjustSvgViewBox` (setzt viewBox + Mobile-Wrapper)
- **Overlay-/Layout-Sync:** `templates/flow_view.html:syncOverlayLayout` (ruft `adjustSvgViewBox`)
- **Live-Daten:** `routes/realtime.py:/api/flow_realtime`, `/api/flow_devices`; `routes/system/battery.py:/api/flow_status`

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
- Keine Aktor-/Schreibzugriffe (Rolle B, read-only).

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
