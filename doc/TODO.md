# Offene Aufgaben & Roadmap — Fronius PV-Monitoring

> Letzte Aktualisierung: 2026-02-13

---

## Priorität A — Kurzfristig (nächste Wochen)

### A3: Monatlicher Solarweb-Abgleich
Seit Feb 6, 2026 arbeitet das System mit Zählerstand-Deltas (korrekt).
Davor war P×t-Integration im Einsatz, die ~50% systematisch zu niedrig lag.

**Korrekturverfahren ("Hubble-Konstante für PV"):**
- [ ] **Anfang jeden Monats**: Solarweb-Monatssummen mit `monthly_statistics` vergleichen
- [ ] Bei Abweichung >2%: Skalierungsfaktoren berechnen, `daily_data` proportional korrigieren
- [ ] `aggregate_statistics.py` FIRST_AUTO_MONTH hochsetzen, korrigierten Monat schützen
- [ ] Langfristig: Abweichung sollte gegen 0 konvergieren (Zählerstand-Delta = korrekt)

**Referenz-Workflow (bewährt für Jan+Feb 2026):**
```
1. Solarweb → Monatssummen ablesen (Solar, Bezug, Einsp, Batt, Direkt, Gesamt)
2. monthly_statistics mit Solarweb-Werten überschreiben
3. daily_data: Korrekte Tage (Zählerstand-Delta) identifizieren
4. Restliche Tage: Faktor = (Solarweb - korrekte Tage) / (P×t-Summe der Resttage)
5. UPDATE daily_data SET spalte = spalte * faktor WHERE ts BETWEEN ...
6. yearly_statistics neu berechnen
7. FIRST_AUTO_MONTH in aggregate_statistics.py hochsetzen
```

**Status der Korrekturen:**
| Zeitraum | Methode | Abweichung vorher |
|---|---|---|
| 2022–2025 | CSV-Import (unkalibriert) | unbekannt — TODO: Solarweb-Jahreswerte prüfen |
| Jan 2026 | Solarweb-Korrektur ✅ | ~50% (P×t-Drift) |
| Feb 1–5, 2026 | Solarweb-Korrektur ✅ | ~50% (P×t-Drift) |
| Ab Feb 6, 2026 | Zählerstand-Delta (auto) | <1% erwartet |

### A5: Tag-Anzeige — Batterie-Zeile überarbeiten
- [ ] Batterie-Daten oben in der Batterie-Info-Zeile (SOC, Ladestatus, SOC_MIN/MAX)
- [ ] "Netzladung" und "Reserve" entfernen (redundant, steht in battery_control.json)
- [ ] Override-Buttons in die Batterie-Zeile: [SOC_MIN → 5%] [SOC_MAX → 100%] [Reset]
- [ ] Status-Anzeige: nächste geplante Aktion des Schedulers

### A6: Batterie-Scheduler beobachten
- [x] `battery_scheduler.py` implementiert (Morgen + Nachmittag + Zellausgleich)
- [x] `config/battery_control.json` parametrisiert
- [x] `battery_control_log` DB-Tabelle angelegt
- [x] Cron-Job alle 15 Min aktiv (seit 2026-02-10)
- [ ] Wochen-Beobachtung: Log auswerten, Schwellen kalibrieren
- [ ] API-Endpunkt `/api/battery_control` in web_api.py
- [ ] UI-Buttons in tag_view.html (→ A5)
- [ ] `battery_control.py` + `battery_scheduler.py` auf `config.py` umstellen

---

## Priorität B — Mittelfristig (diesen Monat)

### B0: Solar Geometry Engine — nachhaltig nutzen
`solar_geometry.py` + `solar_forecast.py` = **3.026 Zeilen Engine** (läuft, ~30% genutzt).

*Automation (→ battery_scheduler.py):*
- [ ] **Geometry-Prognose statt GHI-Skalierung:** `get_remaining_pv_surplus_kwh()` nutzt
      rohe GHI×Faktor statt der viel genaueren `get_hourly_power_forecast()` → umstellen
- [ ] **Vorausschauende Nachtladung:** Morgens-Prognose ist seit Abend vorher verfügbar →
      "Morgen schlecht + SOC abends niedrig" → Netz-Ladung nachts (günstiger Tarif wenn vorhanden)
- [ ] **Mehrtages-Strategie:** `get_week_forecast()` existiert, wird nicht genutzt →
      z.B. 2-Tages-Vorausschau für Batterie-Management

*Warnungen/Alerting (→ B3 unten):*
- [ ] **Clear-Sky-Abweichung live:** Real vs. Modell → "Produktion 40% unter Erwartung" → String-Problem?
- [ ] **String-Vergleich:** Per-String Soll/Ist → F2 fällt ab → automatische Warnung
- [ ] **Hitze-Warnung:** Temperaturkoeffizient ist modelliert → "35°C morgen = 8% weniger"

*Selbst-Optimierung:*
- [ ] **Auto-Kalibrierung:** `calibrate(days=90)` existiert → wöchentlicher Cron statt manuell
- [ ] **Forecast-Accuracy-Dashboard:** `get_accuracy_stats()` existiert → API-Endpunkt + Anzeige

### B3: Warnungen & Proaktives Alerting
Die Prognose-Engine liefert die Daten — jetzt fehlt die Auswertung.

**Stufe 1 — Passive Warnungen (Web-Dashboard, kein Push):**
- [ ] Inverter-Ausfall: kein neuer `raw_data` >10min → rotes Banner in Tag-Ansicht
- [ ] Ertrag unter Erwartung: Clear-Sky-Abweichung >40% bei wolkenlosem Wetter → Hinweis
- [ ] Batterie-Anomalie: SOC-Sprünge >20% in einer Messung → Logfile-Warnung

**Stufe 2 — Aktive Benachrichtigungen (Pushover/E-Mail):**
- [ ] Kanal: Pushover (einfachste Integration, ~5 Zeilen Python)
- [ ] Trigger: Inverter offline >30min, Collector gestoppt, DB-Schreibfehler
- [ ] Tageszusammenfassung abends: Ertrag, Autarkie, Auffälligkeiten

**Stufe 3 — Forecast-getriebene Empfehlungen:**
- [ ] "Morgen erwartet: X kWh (schlecht) → Batterie wird vorgeladen"
- [ ] "Guter Tag morgen → EV-Ladung auf Mittagszeit verschieben"
- [ ] Wochenvorschau in der Web-Ansicht

### B1: Redundantes System (Failover-Pi)
Konzept: Zweiter Pi (Pi4 oder Pi5) als Hot-Standby.

- [ ] **DB-Replikation**: Regelmäßiger rsync/scp der `data.db` vom Primary
- [ ] **Failover-Erkennung**: Heartbeat-Mechanismus (Primary → Secondary)
- [ ] **Automatische Übernahme**: Secondary startet Modbus-Collector
      wenn Primary >N Minuten nicht antwortet
- [ ] **Rückfall**: Manuell oder automatisch zurück auf Primary
- [ ] **Identische Installation**: Alle Scripts + Config identisch,
      nur `INVERTER_IP` bzw. Collector-Enable unterscheiden sich

Offene Fragen:
- SQLite WAL-Mode + rsync: Nur wenn DB idle? → Checkpoint vor Sync
- Split-Brain vermeiden: Nur EIN Collector darf gleichzeitig schreiben
- Netzwerk: Beide Pis im selben Subnetz, Modbus TCP nur von einem

### B2: Pi4/SD-Karten-Portabilität (Restarbeiten)
tmpfs-Architektur läuft seit 2026-02-12. Offene Punkte:
- [ ] DB-Größe monitoren (aktuell ~129MB, Ziel <200MB)
- [ ] SD-Karte Sohn-Vater-Großvater-Backup einrichten (`/mnt/sd-karte`)
- [ ] Reboot-Test: `ensure_tmpfs_db()` NVMe→tmpfs verifizieren

### B4: Mirror/Service-Aufräumen
- [ ] `scripts/monitor_health.sh`: Service-Check von `modbus-collector.service` auf `pv-collector.service` umstellen (verhindert False-Kritisch)
- [ ] README Pfade `Documents` → `Dokumente` in Schnellstart + Troubleshooting aktualisieren

---

## Priorität C — Langfristig / Nice-to-have

### C1: Amortisation verfeinern
- [ ] Strompreise pro Monat statt pro Jahr (Tarifwechsel abbilden)
- [ ] Einspeisevergütung als Config-Wert statt hardcoded 0.082 EUR/kWh
- [ ] Batterie-Amortisation: Anschaffungskosten + Lebensdauer eingeben

### C2: Datenexport / Backup
- [ ] SD-Karte Backup: Sohn-Vater-Großvater-Rotation auf `/mnt/sd-karte`
- [ ] Export nach CSV/JSON für externe Analyse
- [ ] Optional: Influx/Grafana-Bridge für erweiterte Auswertungen

### C3: Alerting → **Hochgestuft nach B3** (siehe Priorität B)

### C4: Code-Qualität
- [ ] **K7:** `web_api.py` Monolith aufteilen (3.400 Zeilen → Module)
- [ ] **K9:** Dual-Modbus-Clients eliminieren
- [ ] `modbus_v3.py` umbenennen → `collector.py` oder `modbus_collector.py`
- [ ] Collector als systemd-Service (aktuell nohup + monitor_collector.sh cron)
- [ ] Unit-Tests für Aggregation-Scripts (Testdaten in SQLite)
- [ ] Type-Hints in allen Scripts
- [ ] CI: Syntax-Check vor Deployment (aktuell manuell)
- [ ] data_15min/hourly_data Lücke vor 04.02. untersuchen

---

## Erledigte Aufgaben (Archiv)

Komprimierte Übersicht — Details in Git-History.

| Datum | Thema | Highlights |
|-------|-------|------------|
| 2026-02-13 | Flow-View Enhancements + Bugfixes | Gauge-Arcs 360° (PV/Netz/SOC), Responsive Mobile, Aktivitätslevel-Farben, **WP-Vorzeichen-Bug** (`P_WP` negiert), Strompreise korrigiert, Heizkosten-Logik, SOH-Fix, Code-Bereinigung (10 Dateien), pgrep-Pattern-Fix |
| 2026-02-12 | tmpfs-Architektur + Energieflow | DB→`/dev/shm` (RAM), 3→1 Schicht, `db_init.py`, 8 Dateien migriert, 0.04 GB/d I/O, SVG-Energieflow-Chart mit Partikeln |
| 2026-02-11 | Wattpilot + Bugfixes | Wattpilot WebSocket-API, f_Netz Chart-Bug (`category`→`time`) |
| 2026-02-10 | System-Audit v4.0.0 + K1–K11 | Bewertung 7.0/10, `db_utils.py`, bare-except→Exception, config.py zentralisiert, ChaSt-Bug, Service-Crash-Loops behoben |
| 2026-02-08 | Pipeline + Solarweb-Abgleich | Audit 6.5/10, modbus_v3 1956→880 Zeilen, Aggregation-Pipeline, Solarweb-Datenkorrektur (Jan+Feb 2026), config.py erstellt |
