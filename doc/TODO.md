# Offene Aufgaben & Roadmap — Fronius PV-Monitoring

> Letzte Aktualisierung: 2026-03-01

---

## Sicherheit & Härtung (LAN-only, bei Bedarf nachrüsten)

- [ ] **API-Authentifizierung** — Kein Auth im privaten 192.x-Netz. Bei Remote-Zugriff (VPN/Port-Forwarding) nachrüsten.
- [ ] **Rate Limiting** — `flask-limiter` (60 req/min/IP) evaluieren.
- [ ] **CORS auf Frontend einschränken** — Default `*` für LAN akzeptabel, bei Öffnung anpassen.
- [ ] **TLS** — Unverschlüsselt auf Port 8000; bei Bedarf nginx-Proxy mit Let's Encrypt.
- [ ] **Fehlermeldungen entschärfen** — `str(e)` exponiert Python-Interna; generische Antworten.

---

## Priorität A — Kurzfristig

### A3: Monatlicher Solarweb-Abgleich
Seit Feb 6, 2026 arbeitet das System mit Zählerstand-Deltas (korrekt).
Davor war P×t-Integration im Einsatz, die ~50% systematisch zu niedrig lag.

- [ ] **Anfang März**: Feb-Abgleich durchführen, FIRST_AUTO_MONTH auf `(2026, 2)` hochsetzen
- [ ] **2022–2025 CSV-Import**: Solarweb-Jahreswerte prüfen (vermutlich korrekt, da Solarweb-Export)
- [ ] Langfristig: Abweichung Richtung 0 beobachten (Zählerstand-Delta = korrekt seit Feb 6)

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

---

## Priorität B — Mittelfristig

### B1: Redundantes System (Failover-Pi)
3-Host-Architektur dokumentiert in `doc/DUAL_HOST_ARCHITECTURE.md`.
DB-Replikation, Failover-Erkennung, Code-Sync und Rollen-Guard sind implementiert.

- [ ] **Automatische Übernahme**: Failover-Aktivierung noch manuell (bewusste Design-Entscheidung)
- [ ] **Automatischer Rückfall**: Primary → retake nach Recovery (manuell)

### B3: Warnungen & Infos pushen
Proaktive Warnungen und Empfehlungen — aktuell nicht implementiert.
Die Prognose-Engine liefert die Daten (Clear-Sky-Modell, Temperaturkoeffizient,
Forecast) — jetzt fehlt die Auswertung und Zustellung.

**Passive Warnungen (Web-Dashboard):**
- [ ] Inverter-Ausfall: kein neuer `raw_data` >10 min → rotes Banner in Tag-Ansicht
- [ ] Ertrag unter Erwartung: Clear-Sky-Abweichung >40% bei wolkenlosem Wetter → Hinweis
- [ ] Batterie-Anomalie: SOC-Sprünge >20% in einer Messung → Logfile-Warnung
- [ ] Hitze-Warnung: Temperaturkoeffizient ist modelliert → "35°C morgen = 8% weniger"

**Aktive Benachrichtigungen (Pushover/E-Mail):**
- [ ] Kanal: Pushover (einfachste Integration, ~5 Zeilen Python)
- [ ] Trigger: Inverter offline >30 min, Collector gestoppt, DB-Schreibfehler
- [ ] Tageszusammenfassung abends: Ertrag, Autarkie, Auffälligkeiten

**Forecast-getriebene Empfehlungen:**
- [ ] "Morgen erwartet: X kWh (schlecht) → Eigenverbrauch priorisieren"
- [ ] "Guter Tag morgen → EV-Ladung auf Mittagszeit verschieben"
- [ ] Wochenvorschau in der Web-Ansicht

### B3b: Wattpilot-Automation — Phase 2 Stubs implementieren
`automation/engine/aktoren/aktor_wattpilot.py` enthält 5× `TODO Phase 2`-Stubs.
Die Methoden loggen derzeit nur, steuern aber nicht.
Voraussetzung: stabile `wattpilot_api.py` Write-Funktionen (WebSocket-Befehle).

- [ ] `set_strom(ampere)` → `wattpilot_api.set_max_current(ampere)` anbinden
- [ ] `pause()` → `wattpilot_api.pause()` anbinden
- [ ] `resume()` → `wattpilot_api.resume()` anbinden
- [ ] `set_modus_pv_ueberschuss()` → `wattpilot_api.set_max_current()` anbinden
- [ ] `stoppe_laden()` → `wattpilot_api.set_max_current(MIN_CURRENT_A)` anbinden
- [ ] Integration in Engine-Regelkreis `wattpilot` (aktuell bewusst deaktiviert)

### B5: Heizpatrone (HP) — Prognosegesteuerte Automation via Fritz!DECT
HP (2 kW) wird über Fritz!DECT-Steckdose geschaltet. Ziel: Überschuss-Verwertung
ohne Batterie-Entladung. Forecast-gesteuerte Burst-Strategie (15–30 Min Laufzeit).
→ Detailstrategie dokumentiert in `automation/STRATEGIEN.md` §2.6

- [x] **AktorFritzDECT**: `automation/engine/aktoren/aktor_fritzdect.py` (~365 Z.) —
      Fritz!Box AHA-HTTP-API (SID-Cache 15 Min, Bulk-Query, Retry-Logik, Credentials aus .secrets)
- [x] **RegelHeizpatrone**: `automation/engine/engine.py` —
      4-Phasen-Logik, Trigger=P_Batt, Forecast-gesteuert, Notaus bei Netzbezug/Entladung/Übertemperatur
- [x] **Parametermatrix**: Regelkreis `heizpatrone` in `config/soc_param_matrix.json` (17 Parameter)
- [x] **Registrierung**: `AktorFritzDECT` in `actuator.py` (3 Aktoren: batterie, wattpilot, fritzdect)
- [x] **Config**: `config/fritz_config.json` + Credentials via .secrets
- [x] **pv-config.py**: Menüpunkt 6 "Heizpatrone (Fritz!DECT)"
- [x] **SOC-abhängiger Notaus**: Immer aktiv (auch bei aktiv=False)
- [x] **Fritz!Box-Optimierung**: Bulk-Query, SID-Cache (15 Min), 60 s Poll
- [x] **flow_view HP-Zeile**: Live-Status (EIN/AUS + Leistung), 120 s Cache
- [x] **Schutzregel-Klassifikation**: Engine erkennt FritzDECT-Regeln als Schutzregeln
- [ ] **Status-Anzeige tag_view**: HP-Schaltzustand in tag_view integrieren
      (flow_view zeigt bereits HP EIN/AUS + Leistung)

---

## Priorität C — Langfristig / Nice-to-have

### C2: Datenexport
- [ ] Export nach CSV/JSON für externe Analyse
- [ ] Optional: Influx/Grafana-Bridge für erweiterte Auswertungen
