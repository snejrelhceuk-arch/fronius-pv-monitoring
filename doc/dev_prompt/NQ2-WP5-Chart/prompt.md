# WP5 — NQ-Chart + Event-Marker/Drill-down + Langzeit-Aggregate-API (NQ2)

**Priorität:** High (großes Frontend-Update)  
**Dauer:** ~9 h  
**Abhängig:** WP2 (Aggregate), WP4 (Event-API)

---

## Kontext

NQ2: „Die Darstellung im Chart sollte initial den Tag im 5min-Raster zeigen...Auflösung 200ms ausschließlich Event-Schnipseln vorbehalten...feste Darstellung (kein dynamisches Zoom/Pan in den Tag)...Herauszoomen über Tage fließend möglich."

---

## Aufgaben (3 Blöcke)

### 1. Feste Tag-Ansicht im 5min-Raster (kein Zoom/Pan in Tag)

a) **Route: `/netzqualitaet/chart?day=YYYY-MM-DD`**
   - Parameter: `day`, optional `quantity='u_l1'|'i_l1'|'p_tot'|'thd_u_l1'|...`
   - Default: zeige Alle großen Größen (U, I, P, THD, f).

b) **Chart-Rendering (Client-seitig, z.B. ECharts):**
   - **Feste Struktur:** 288 Buckets (5min × 24h = 1440min).
   - **X-Achse:** Uhrzeit 00:00–24:00, 5min-Gitternetz.
   - **Y-Achse:** Einheit je Größe (V, A, W, %).
   - **Daten:** Min/Avg/Max aus `nq_5min` via `/api/nq/aggregates?range=5min&start=...&end=...`.
   - **Darstellung:** Band (min/max als Fläche, Avg als Linie), optional std als Fehlerbalken.
   - **Keine dynamischen Zoom/Pan**: Tag ist kleinste Einheit.

c) **Markierungen im Chart:**
   - Event-Marker: vertikal Linie + Icon (⚡) wenn `[event.ts_start, event.ts_end] ∩ 5min-bucket`.
   - Extremwert-Marker: max/min je Größe als kleine ✕ oder Punkt am Chart.

d) **Navigation über Tage:**
   - Buttons ← Prev Day / Next Day →.
   - Date-Picker zur direkten Auswahl.
   - **Zoom-out fließend:** Optional: Tasten für Month/Year-Ansicht (aggregiert 5min→Daily je Tag-Punkt).

**Verifikation:**
- Öffne `/netzqualitaet/chart?day=2026-07-13`.
- Chart zeigt 288 Buckets, fixe Breite, Band-Visualisierung.
- Click auf Event-Marker → Drill-down (siehe 2).

---

### 2. Event-Marker + Snippet-Drill-down (Overlay-Chart 300s)

a) **Event-Marker (⚡) sichtbar im 5min-Chart.**
   - Query: `SELECT * FROM nq_events WHERE ts_start >= day_start AND ts_end <= day_end + 86400`.
   - Für jeden Event: Finde 5min-Bucket(s), setze Marker.
   - Click-Handler: `showSnippetOverlay(event_id)`.

b) **Overlay-Chart (300s, 200ms-Auflösung):**
   - Zeigt Wide-Format RAW aus `/api/nq/event/<event_id>`.
   - X-Achse: 300 s (1500 Punkte bei 200ms), fixe Pixel-Breite (z.B. 800px).
   - Y-Achse: wie Parent-Chart.
   - **Modal/Sidebar:** Nicht im Hauptchart, sondern separate Komponente (leichter close-bar).

c) **Multi-Segment-Navigation (wenn Event >5min):**
   - Wenn Snippet länger als 5min: zeige nur 300s-Chunk (z.B. erste 5min+).
   - Pfeile ← Prev 300s / Next 300s → zum Scrollen durch Schnipsel.
   - Status: „Showing 300–600s of 900s event".

d) **Drill-down-Link:**
   - Ebenfalls möglich: Click auf Event-Name in Liste (siehe /netzqualitaet/live).

**Verifikation:**
- Event-Marker sichtbar im Tag-Chart.
- Click → Overlay-Chart öffnet mit 200ms-Auflösung.
- Pfeile scrollen durch Multi-Segment-Event.
- Close-Button schließt Overlay.

---

### 3. Langzeit-Aggregate-API + Maschinenraum-Umstellung

a) **API: `/api/nq/aggregates?range=5min&start=ts1&end=ts2`**
   - Parameter: `range` ∈ {5min, hourly, daily}, `start`/`end` (Unix epoch).
   - Query: entsprechende Tabelle `nq_5min`, `nq_hourly`, `nq_daily`.
   - Response: Wide-Format wie `/api/realtime_smart`:
     ```json
     {
       "data": [
         {"ts": 1689262800, "u_l1": 230.2, "u_l1_min": 229.5, "u_l1_max": 231.0, ...},
         ...
       ],
       "quantities": ["u_l1", "i_l1", ...],
       "resolution": "5min",
       "points": 288
     }
     ```

b) **Erweiterung `nq/tech_read.py`:**
   - Bestehend: `fetch_agg()` liest Tech-tmpfs.
   - Neu: `fetch_aggregates(range, start, end)` liest Primary-DB (SD-Aggregate).
   - Fallback: Wenn Primary nicht erreichbar, nutze Tech-tmpfs (alt, aber verfügbar).

c) **Maschinenraum DB-Switch erweitern:**
   - Tab-Buttons: Kern-DB / **NQ (Langzeit)** / PAC4200-Clone.
   - Click auf „NQ (Langzeit)" → Lade `nq_5min/hourly/daily` (nicht tmpfs, sondern SD).
   - Chart-Source: `/api/nq/aggregates` statt `/api/nq/realtime_smart`.

d) **Navigation im Langzeit-Chart:**
   - Monat-Ansicht: Tag als X-Punkt (24 Punkte/Tag), Monat komplett sichtbar.
   - Jahr-Ansicht: Woche als X-Punkt, Jahr komplett sichtbar (52 Punkte).
   - Zoom-out fließend (bei Bedarf: Spline-Interpolation).

**Verifikation:**
- `/api/nq/aggregates?range=5min&start=X&end=Y` antwortet mit Daten.
- `/api/nq/aggregates?range=daily&start=X&end=Y` antwortet mit Daily-Daten (7 Punkte für Woche).
- Maschinenraum: Tab „NQ (Langzeit)" zeigt Aggregates (nicht Live-Tmpfs).
- Chart laden & sichtbar.

---

## Abhängigkeiten & Blockaden

- WP2: Aggregate (`nq_5min`, etc.) müssen vorhanden.
- WP4: Event-API muss verfügbar (Drill-down).

## Definition of Done

- [ ] Tag-Chart-Route `/netzqualitaet/chart?day=YYYY-MM-DD` implementiert.
- [ ] Chart-Rendering: 288 Buckets (5min), Band-Visualisierung (min/avg/max).
- [ ] Event-Marker (⚡) sichtbar bei 5min-Bucket-Intersection.
- [ ] Click-Handler auf Marker → Overlay-Drill-down.
- [ ] Overlay-Chart: 300s, 200ms-Auflösung, Wide-Format-Daten.
- [ ] Multi-Segment-Navigation (← Prev / Next →) für Events >5min.
- [ ] Navigation über Tage: ← / → Buttons + Date-Picker.
- [ ] Zoom-out fließend über Tage (optional: Month/Year-View).
- [ ] `/api/nq/aggregates?range={5min,hourly,daily}&start=&end=` implementiert.
- [ ] `nq/tech_read.py` um `fetch_aggregates()` erweitert.
- [ ] Maschinenraum: DB-Switch erweitert um Tab „NQ (Langzeit)".
- [ ] Chart-Source wechselt zwischen `/api/nq/realtime_smart` (Live, tmpfs) und `/api/nq/aggregates` (Langzeit, SD).
- [ ] Test: Tag-Chart zeige, Drill-down, Langzeit-Aggregate load.
- [ ] `python3 -m py_compile routes/pac4200.py nq/tech_read.py`.
- [ ] Doc-Check exit 0.

---

## Commit-Message

```
feat(nq/wp5): NQ-Chart Refactor — Fixed 5min-Raster + Event Drill-down + Longterm-Aggregates-API

- Implement /netzqualitaet/chart?day=YYYY-MM-DD: 288 5min-buckets, band visualization
- Fixed display (no dynamic zoom/pan into day); day = smallest unit; zoom-out over days fluent
- Event-marker (⚡) visible at bucket intersections; click → overlay-chart drill-down (300s, 200ms)
- Multi-segment nav (← / →) for events >5min (300s chunks)
- Add /api/nq/aggregates?range={5min|hourly|daily}&start=&end=: longterm aggregates from Primary-SD
- Extend nq/tech_read.py: fetch_aggregates(range, start, end)
- Maschinenraum DB-switch: new tab „NQ (Langzeit)" → /api/nq/aggregates source (not Live-tmpfs)
- Month/Year-views with aggregated-to-daily rendering (optional, smooth zoom-out)

NQ2-Roadmap §6.5. Charting per NQ2-UI-spec (day 5min fixed, events 200ms overlay).
Blocks: nothing. Depends: WP2 (Aggregates), WP4 (Event-API).
Related: doc/netzqualitaet/NQ2_ROADMAP.md#WP5
```

