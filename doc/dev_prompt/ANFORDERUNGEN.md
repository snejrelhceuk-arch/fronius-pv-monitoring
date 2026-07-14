# NQ-Modul — Nutzeranforderungen (Zusammenfassung aus Chat 2026-07-11/12)

**Zweck:** Konsolidierte, detaillierte Anforderungsliste für das Netzqualitäts-Modul
(Rolle N, PAC4200) aus den Gesprächen vom 11./12. Juli 2026. Basis für sub-Chat-Prompts.

---

## 1. Systemarchitektur und Hostverteilung

- PAC4200 (Siemens SENTRON) am Netzanschlusspunkt (PCC, 192.0.2.111, Modbus TCP 502)
- **Tech (Pi4-Tech, 4 GB RAM)**: Collector, RAM-first (`/dev/shm`), kein SD-Nutzdaten-Write
- **Primary (Pi5-Primary)**: Aggregation, Analyse, Dauerhafte SD-Speicherung
- SD-Karte auf Tech nur selten beschreiben; Hauptspeicher dominiert
- Alle Dienste gehärtet: `systemd Restart=always`, `EnvironmentFile=.infra.local`,
  Neustart-fest, Stale-Data-Erkennung, Crash-tolerant

---

## 2. PAC4200-Browser-Clone (erreichbar über Flow/Maschinenraum/PAC4200)

- Nachbildung des realen PAC4200-LCD-Displays im Browser, read-only
- Alle elektrischen Größen des Geräts sollen darstellbar sein
- **F1–F4 Tasten** (nicht allgemeine Pfeiltasten): F1=ESC, F2=▲/+, F3=▼/−, F4=Menü/OK
- **Menü-Overlay** (Tastenfeld F4): Bildschirmliste scrollbar, Auswahl per F2/F3/F4
- Darstellung insgesamt **etwas größer** als die frühere Version (≈460px)
- **Zentrierte Tastenbeschriftung** (CSS fix `text-align: center` auf `.key small`)
- **Zeigerdiagramm-Bildschirm** (inline SVG): Spannungs- und Stromzeiger mit Phasenwinkel
- **Alle verfügbaren Bildschirme**:
  - Spannung L-N, Spannung L-L, Strom (vorzeichenbehaftet + I_N), P, Q/S,
    PF/cos φ, THD-U (L-N + L-L), THD-I, Phasenwinkel, Verzerrungsstrom,
    Frequenz/Unsymmetrie, Energie (Differenzmethode), Extremwerte (Max/Min aus Gerät),
    Gleitende Mittelwerte, Demand/Periode, Zeigerdiagramm (neu)
- **Harmonische**: Die **Standard**-Modbus-Map liefert nur THD-Gesamtwerte. Die
  **Siemens-Erweiterungsregister** @9001 (U L-N), @11001 (I), @22001 (U L-L)
  liefern jedoch die ungeraden Einzelharmonischen **H3..H31** (% der Grundschwingung).
  Verifiziert & produktiv gepollt im Medium-Tier (1 s) seit 2026-07-12 → `nq_raw_slow`.

---

## 3. Navigation / Systemhierarchie

**Gesamthierarchie (verbindlich):**
Flow → Maschinenraum → {
  - Echtzeit (Kern-DB = pv-system data.db/raw_data)
  - Netzqualität (NQ-DB = PAC4200 nq_agg_10s) → Screens (Live-Tableau)
  - PAC4200 (Geräte-Clone)
}

- **Ein Programm, zwei Datenbanken**: `/maschinenraum` (Kern-DB) und `/maschinenraum?db=nq`
  (NQ-DB) sind **dasselbe Frontend**, umgeschaltet über DB-Selektor oben
- Links im Rollup: Feldliste aus der gewählten DB
- Feldkategorien und Einheiten DB-spezifisch (PAC hat eigene Kategorien)
- Alle Navigationen (Drawer, Flow-SVG, Maschinenraum-Header) müssen diese Hierarchie
  widerspiegeln

---

## 4. Live-Tableau (Screens, `/netzqualitaet/live`)

- Pendant zum PAC-Clone: alle 12+ PAC-Messgruppen als **Datentabelle** nebeneinander
- Auto-Refresh 2 s
- Negative Werte farblich hervorgehoben (Export/Einspeisung)
- Drawer-Navigation eingebunden

---

## 5. Energie-Differenzmethode

- **Alle Energiezähler** (Wh_imp/exp, varh_imp/exp, VAh) vom PAC ab Start mitführen
- Tages-Deltas: `delta = end - start` mit Reset-Erkennung (neg. Delta oder Sprung)
- **Zählervergleich** gegen:
  1. Master-SM (Fronius Primär-SM, read-only aus data_1min)
  2. iMS (Netzbetreiber-Abrechnungszähler, manuelle Eingabe)
- Tages-Checkpoints für Langzeitabgleich
- **Wh_exp=0-Befund** beobachten: PAC zählt Lieferung nicht trotz Einspeisung
  → Ursachenforschung über Vergleich mit Master-SM
- 1×/Tag auf Primary-SD schreiben (systemd-Timer 00:05)

---

## 6. Aggregationskaskade (analog pv-system)

- `nq_agg_10s` (10 s, 72 h auf Tech) → täglicher Transfer vor Verfall (<72 h!)
- **Kaskade auf Primary**:
  - `nq_5min` (~90 Tage, min/avg/max/std)
  - `nq_hourly` (~365 Tage)
  - `nq_daily` (~10 Jahre)
  - Energie: Summe der Deltas (nicht min/avg/max!)
- GFS-Backup (son/vater/großvater, 7/5/12, gzip+integrity+offsite, analog backup_db_gfs.sh)
- Systemd-Timers: Transfer 00:10, Aggregat 00:15, GFS 03:00

---

## 7. Event-Schnipsel (Transienten, dauerhaft gespeichert)

**Trigger:** Schwellüberschreitungen in konfigurierbaren Größen:
- Spannungssprung > 3 V (z.B. du_step_v)
- Frequenzsprung > 0.02 Hz
- THD-U ≥ 5 %
- THD-I ≥ 80 %
- **Stromsprung > 32 A** (Nutzerbeispiel: „Strom schwankt, aber nicht um >32A!")
- Weitere konfigurierbare Schwellen

**Schnipsel-Konzept:**
- Max. 60 s Länge (Pre-Window 30 s + Post-Window 30 s)
- **Alle verfügbaren Messgrößen** (U, I, P, Q, S, PF, THD-U/I, cos φ, Phasenwinkel,
  Verzerrungsstrom, I_N, f)
- **Sofortiger Transfer** zu Primary (nicht erst beim Tages-Transfer, da tmpfs volatil)
- **Wiederholungsfilter/-cutter**: gleicher Trigger = kein neuer Schnipsel für 120 s
- Katalog (`nq_events`): ts_start/end, band, kind, trigger, peak_quantity, peak_value,
  severity, origin, dedup_key, n_samples, has_snippet

**Darstellung:**
- In Charts als **Ereignis-Marker** (vertikale Linie + Icon ⚡) sichtbar
- **Drill-down** auf Klick: Overlay-Chart mit der RAW-Serie des Schnipsels
- **Auffindbarkeit**: Extremwerte in Aggregaten zeigen den Schnipsel an
- Event-Liste auf `/netzqualitaet/live`-Seite

---

## 8. Analyse-Tools (Netzqualität, automatisiert)

**HF_local (Transienten, THD, Verzerrung):**
- THD-Spike-Detektion über konfigurierbare Schwellen
- U↔I-Korrelation: lokale Last vs. Netz (Schleifenimpedanz aus `config/nq_impedance.json`)
- **Spannungsfilterung**: interne Stromänderungen als Ursache herausrechnen
  (ΔU_net = ΔU_gemessen - ΔI × Z_loop) — dann erst Mustererkennung auf Residual
- **Abgleich mit pv-system**: War die WP/Heizpatrone/Wattpilot aktiv? → origin='lokal'

**NF_global (s..min-Muster):**
- Frequenz-Gradienten (df/dt), Nadir-Detektion
- DFD an 15-min-Handelsgrenzen (aus Legacy nq_analysis.py adaptieren)
- **Trafoumschaltungsfilter**: Diskrete U-Sprünge ±1..3 V bei :00/:15/:30/:45 herausfiltern
  (periodisches Tap-Muster, Parameter `thres_tap_v`), danach Residual analysieren
- U-Band-Überwachung: EN-50160 (207..253 V über 10 min)

**VLF (Tage/Wochen/Saison-Muster):**
- Tages-/Wochenprofil (Stunden-Median, Abweichung > 2σ = Anomalie)
- Changepoint-Erkennung (CUSUM oder vereinfacht ohne Extern-Bibliothek)
- Langfristiger PF-/THD-Trend

**Darstellung und Warnung:**
- Events in `nq_events` mit Severity 0..1
- Marker-Icons im NQ-Chart (⚡ HF, 〰 NF, 📉 VLF)
- Integration in Diagnos-Alert-System (Rolle D) bei persistenter Severity > 0.8

---

## 9. Pollings

- **Fast**: 500 ms — RMS U/I, P/Q/S, PF, THD-U/I, Unsymmetrie, Phasenwinkel,
  Verzerrungsstrom, cos φ, I_N, f  
  (Refresh-Rate: alle Größen außer FREQ ändern sich ≤250 ms)
- **Medium**: 1 s — identische Größen, aber geglättet (gleitende MW vom Gerät)
- **Slow/Harmonische**: **NICHT MÖGLICH** — PAC4200 liefert keine Einzel-Harmonischen
  per Modbus. Kein Slow-Block.
- **Energie**: 60 s — Energiezähler (FLOAT64, kumulativ)
- **Frequenz**: gehört in eigenen langsamen Takt (Gerät aktualisiert nur alle 6–10 s)

---

## 10. Commit-Disziplin

- Keine echten IPs (192.168.2.x) in committetem Code → 192.0.2.x Platzhalter
- Systemd-Units mit real Betreiber-Pfaden → `.gitignore` (wie pv-wp-bridge)
- Publish-Guard + Role-Guard(primary) + doc-check bei jedem Commit
- Nicht pushen ohne explizite User-Freigabe
- Nach jeder Sitzung konsolidiert committen, Gruppen nach Thema

---

## 11. Qualitätsanforderungen (durchgehend)

- „Senior-Programmierer"-Niveau: professionell, fehlerfrei, systemkonsistent
- Kein Overengineering; nur was nötig ist
- Alle Docs dual nachziehen (MESSTECHNIK.md, NQ_MODUL.md, NQ_TESTS_UND_DB.md, Cards)
- Pre-commit-Hook: `last_review=heute` auf geänderten Cards
- RAM auf Tech hat Priorität; SD-Schreibrate gering halten
