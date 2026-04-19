# Deep Audit — Automation Engine

**Datum:** 2026-06  
**Scope:** `automation/engine/` — Produktivsystem (Pi4, 37.59 kWp, BYD HVS 20.48 kWh)  
**Methode:** Vollständige statische Code-Analyse aller Engine-Module, Parametermatrix, Daemon, Aktoren, Collectors, Regeln, Konfiguration  

---

## A) Architektur-Übersicht

### Schichtenmodell

```
┌──────────────────────────────────────────────────────┐
│  S1  pv-config.py (SSH/Whiptail)                     │
│  S2  Steuerbox → operator_overrides (RAM-DB)         │
├──────────────────────────────────────────────────────┤
│  S4  automation_daemon.py (Orchestrator)             │
│      ┌────────────────────────────────────────┐      │
│      │  DataCollector (Tier-2, 10s)           │      │
│      │  ForecastCollector (Tier-3, trigger)   │      │
│      │  Tier1Checker (Schwellen, sofort)      │      │
│      │  Engine (fast=60s, strategic=900s)     │      │
│      │  Actuator → Aktoren (4 Plugins)        │      │
│      │  OperatorOverrideProcessor             │      │
│      │  EventNotifier                         │      │
│      └────────────────────────────────────────┘      │
├──────────────────────────────────────────────────────┤
│  S3  engine.py — Score-basierte Entscheidung         │
│      17 Regeln in 4 Modulen                          │
│      Schutz (alle ausführen) + Optimierung (Cascade) │
├──────────────────────────────────────────────────────┤
│  Hardware:  Modbus TCP (GEN24 + BYD)                 │
│             HTTP API  (Fronius SOC Config)            │
│             AHA-HTTP  (Fritz!DECT Steckdosen)        │
│             WebSocket (Wattpilot EV-Charger)          │
│             Modbus RTU (Dimplex Wärmepumpe)           │
└──────────────────────────────────────────────────────┘
```

### Datenfluss

| DB | Pfad | Zweck |
|---|---|---|
| RAM-DB | `/dev/shm/automation_obs.db` | ObsState Singleton + History-Ring (1000), param_matrix, action_plan, operator_overrides, heartbeat |
| Collector-DB | `/dev/shm/fronius_data.db` | raw_data, data_1min, wattpilot_readings (Read-Only für Engine) |
| Persist-DB | `data.db` | automation_log (Schalthistorie für Web-API) |

### Zyklen

| Tier | Intervall | Inhalt |
|---|---|---|
| Tier-1 | Jeder 10s-Zyklus | Batterie-Temp-Alarm, SOC-Kritisch, Netz-Überlast |
| Tier-2 | 60s (fast) | 15 von 17 Regeln: Schutz + Geräte + WP + SOC-Steuerung |
| Tier-2 | 900s (strategic) | 2 zusätzliche: NachmittagSocMax, Zellausgleich, ForecastPlausi |
| Tier-3 | Trigger-basiert (30s prüfen) | ForecastCollector (startup, sunrise, 10:00, 14:00, fallback 6h) |

### Regel-Registrierung

17 Regeln in `engine.py:_register_default_regeln()`:

| # | Name | Score | Zyklus | Aktor | Schutz? |
|---|---|---|---|---|---|
| 1 | sls_schutz | 95 | fast | wattpilot+fritzdect | Ja (Name) |
| 2 | komfort_reset | 70 | fast | batterie | Nein |
| 3 | morgen_soc_min | 72 | fast | batterie | Nein |
| 4 | nachmittag_soc_max | 55 | strategic | batterie | Nein |
| 5 | zellausgleich | 30 | strategic | batterie | Nein |
| 6 | forecast_plausi | 50 | strategic | batterie | Nein |
| 7 | wattpilot_battschutz | 60 | fast | batterie+wattpilot | Ja (Name) |
| 8 | klimaanlage | 52 | fast | fritzdect | Ja (Code)* |
| 9 | heizpatrone | 40 | fast | fritzdect | Ja (Code)* |
| 10 | ww_verschiebung | 47 | fast | waermepumpe | Ja (Code) |
| 11 | heiz_verschiebung | 46 | fast | waermepumpe | Ja (Code) |
| 12 | ww_boost | 48 | fast | waermepumpe | Ja (Code) |
| 13 | wp_pflichtlauf | 49 | fast | waermepumpe | Ja (Code) |
| 14 | heiz_bedarf | 50 | fast | waermepumpe | Ja (Code) |
| 15 | ww_absenkung | 45 | fast | waermepumpe | Ja (Code) |
| 16 | heiz_absenkung | 44 | fast | waermepumpe | Ja (Code) |

*) HP/Klima werden als Schutz klassifiziert wenn Score > score_gewicht (Notaus-Fall)

**Schutz-/Optimierungs-Trennung:** Die `_ist_schutz()`-Funktion in engine.py klassifiziert eine Regel als Schutz wenn:
1. Name enthält "schutz", ODER
2. Name in der WP/Geräte-Sollwert-Liste (ww_absenkung, heiz_absenkung, etc.), ODER
3. fritzdect-Aktor mit Score > score_gewicht (= Notaus)

Schutz-Regeln werden ALLE ausgeführt (dedupliziert per Kommando). Optimierungs-Regeln folgen Cascade: höchster Score gewinnt, nächster bei leerer Aktion.

---

## B) Safety & Restart-Resilienz

### Startup-Schutz

| Mechanismus | Status | Bewertung |
|---|---|---|
| HP-Startup-Check | ✅ Implementiert | Daemon prüft Fritz!DECT-Status bei Start, schaltet HP ab falls EIN |
| PID-File Stale-Detection | ✅ Implementiert | `/automation_daemon.pid`, `os.kill(old_pid, 0)` Prüfung |
| atexit PID-Cleanup | ✅ Implementiert | `atexit.register()` |
| Signal-Handler SIGTERM/INT | ✅ Implementiert | `daemon._running = False` → clean shutdown |
| SIGHUP → Matrix-Reload | ✅ Implementiert | Setzt auch WP-Extern-Tracking zurück |
| RAM-DB Recovery | ✅ Implementiert | Korrupte tmpfs-DB wird gelöscht + neu erstellt |

### Fehlende Startup-Schutzmaßnahmen

| Risiko | Bewertung |
|---|---|
| **Klimaanlage-Startup-Check fehlt** | ⚠️ HP wird geprüft, Klima nicht. Identisches Risiko bei Fritz!DECT-Steckdose mit Zustandshaltung |
| **WP-Sollwert-Startup-Check fehlt** | ℹ️ Geringeres Risiko — WP-Soll bleibt im Modbus-Register, keine Sicherheitsgefahr bei falschem Wert |
| **Wattpilot-Startup-Check fehlt** | ℹ️ Geringeres Risiko — EV-Charger hat eigene Sicherheitslogik |

### Tier-1 Alarm-Pause

Die Engine **pausiert komplett** wenn `alarm_batt_temp` oder `alarm_batt_kritisch` gesetzt sind. Dies ist korrekt — Tier-1-Aktionen laufen unabhängig im Daemon-Loop.

**Potenzielle Lücke:** Bei Tier-1-Alarm wird die HP nicht explizit abgeschaltet. Der Tier1Checker setzt nur Flags und erzeugt Wattpilot-Aktionen. Die HP läuft potenziell weiter wenn ein Tier-1-Alarm eine Engine-Pause auslöst. *In der Praxis mitigiert durch:* HP-Burst-Timer läuft ab → Notaus bei nächstem Engine-Zyklus nach Alarm-Ende. Risiko nur bei lang andauerndem Alarm + laufender HP.

### Deduplizierung & Oscillation Detection

| Mechanismus | Wert | Bewertung |
|---|---|---|
| Dedup-Intervall | 45s | ✅ Angemessen für 60s-Zyklen |
| Fehler-Cooldown | 300s | ✅ Verhindert Retry-Storm |
| Oszillationserkennung | 6+ Alternierungen in 20 min | ✅ Gut kalibriert |
| Oszillations-Warn-Cooldown | 30 min | ✅ Verhindert Log-Flood |
| Fail-Fast Plan-Execution | ✅ | Bricht bei erstem Fehler ab |

### Thread-Sicherheit

| Bereich | Status | Bewertung |
|---|---|---|
| ObsState-Zugriff (Daemon) | `_obs_lock` (threading.Lock) | ✅ |
| Forecast-Thread | Separater Daemon-Thread mit Lock | ✅ |
| RAM-DB (obs_state.py) | `_db_lock` (Lock), `check_same_thread=False` | ✅ |
| Schaltlog | `_lock` (threading.Lock) | ✅ |
| **Module-Level Mutable State (waermepumpe.py)** | `_verschoben`, `_wp_laufzeit`, `_boost` etc. — **KEIN Lock** | ⚠️ Siehe Finding F-02 |
| SocExternTracker | Module-Level Singleton, kein Lock, 1s-Guard | ⚠️ Funktional OK weil Single-Thread-Engine |

---

## C) Regel-für-Regel-Analyse

### C1: RegelSlsSchutz (P1, fast, Score 95)

**Zweck:** SLS-Sicherungsschutz (35A/Phase am Zählerplatz).  
**Logik:** Phasenström-Monitoring aus SmartMeter. Bei Überschreitung: HP aus + Wattpilot proportional reduzieren.  
**Bewertung:** ✅ Robust. Proportionale Reduktion ist korrekt (Überschreitung + Sicherheitsmarge). Log-Throttling (5 min) verhindert Flood.  
**Konfigurierbar:** `sls_strom_max_a` (35A), `sls_leistung_max_w` (24kW Fallback), `sls_sicherheitsmarge_a` (2A).

### C2: RegelMorgenSocMin (P2, fast, Score 72)

**Zweck:** SOC_MIN morgens öffnen (25%→5%) wenn PV-Sunrise-Prognose ≥ 1500W.  
**Logik:** Dynamisches SOC_MIN aus Nachtverbrauchs-Prognose. Hold-Modus (Score×0.95=68). Veto bei `schlecht` Forecast. Verzögerung bei `mittel`. Nachtlast-Öffnung (Grid-Drain-Vermeidung).  
**Bewertung:** ✅ Durchdacht. Morgen-Vorlauf (30 min) korrekt an ForecastCollector übergeben. Hold-Score erzeugt leere Aktionen → Cascade korrekt.  
**Potenzial:** Die `_morgenfenster_sperrt_reset`-Guard gegen Ping-Pong mit KomfortReset ist im Code implementiert (Score-Dokumentation erwähnt es).

### C3: RegelNachmittagSocMax (P2, strategic, Score 55)

**Zweck:** SOC_MAX nachmittags von 75%→100% erhöhen.  
**Logik:** Clear-Sky-Peak + Power-Threshold-Algorithmus. Dynamische Startzeit aus Forecast-Profil. Effective Threshold erhöht bei EV/WP-Last. Dynamische SOC-Ziele aus historischem Nachtverbrauch.  
**Bewertung:** ✅ Komplexe aber korrekte Logik. Nacht-Dynamik mit Cache (1800s TTL) + min_samples (4) + Lookback (21 Tage) ist vernünftig kalibriert.  
**Risiko:** Strategic-Zyklus (15 min) bedeutet verzögerte Reaktion auf schnelle Wetterumschwünge. Mitigiert durch `wolken_schwer_pct` (85%) Sofort-Trigger und `max_stunden_vor_sunset` (2h) Deadline.

### C4: RegelKomfortReset (P2, fast, Score 70)

**Zweck:** Abends auf 25/75% zurücksetzen + intelligenter Früh-Reset bei schlechter Prognose.  
**Bewertung:** ✅ Score 70 < morgen_soc_min HALTE-Score (68) — Ping-Pong durch `_morgenfenster_sperrt_reset` Guard verhindert. Erholung-Hysterese (2 kWh) gegen Flicker (K4). Nachtlade-Logik korrekt: SOC > komfort_min + Morgen-Prognose ≥ 20 kWh → natürlicher Drain statt Reset.

### C5: RegelZellausgleich (P3, strategic, Score 30)

**Zweck:** Monatlicher BYD-Zellbalancing-Vollzyklus.  
**Logik:** Auto-Erkennung abgeschlossener Vollzyklen (SOC min→max). Forecast ≥ 50 kWh, Tag 1-28, max 1×/Monat. Notfall-Schwelle (25 kWh) nach 45 Tagen.  
**Bewertung:** ✅ Atomare JSON-Writes. Niedrigster Score (30) ist korrekt — übergibt bei jedem Konflikt. `max_tage_ohne_ausgleich` (45) ist ein sinnvoller Fallback.

### C6: RegelForecastPlausi (P2, strategic, Score 50)

**Zweck:** IST/SOLL-Vergleich, Restprognose korrigieren bei Abweichung.  
**Logik:** Unter 70% IST/SOLL → Rest × 0.7. Cloud-Weighted (80% → zusätzlich × 0.6). Opens SOC_MAX auf 100% wenn korrigierter Rest < 5 kWh.  
**Bewertung:** ✅ Sinnvoll. `min_betriebsstunden` (2h) verhindert Frühmorgen-Fehlalarme.

### C7: RegelWattpilotBattSchutz (P1, fast, Score 60)

**Zweck:** SOC_MIN anheben bei EV-Ladung nahe SOC_MIN + Sunset-Guard.  
**Logik:** Zwei Trigger: (a) SOC nahe SOC_MIN bei EV > 5kW, (b) Sunset-Guard (letzte 2h, SOC < 25%).  
**Bewertung:** ✅ Wolken-Toleranz (300s) verhindert Schaltungen bei kurzen Wolken.

### C8: RegelHeizpatrone (P2, fast, Score 40)

**Zweck:** 2kW-Heizstab via Fritz!DECT mit 6-Phasen-Burst-Strategie.  
**Phasen:**
- Phase 0: Morgen-Drain (SOC entleeren vor PV-Start)
- Phase 1: Vormittag (SOC≈MAX + starke Ladung)
- Phase 1b: Nulleinspeiser-Erkennung (Probe-Burst)
- Phase 2/3: Mittag/Nachmittag (Überlauf)
- Phase 4: Abend-Nachladezyklus (SOC≈MAX + Rest-PV)

**Bewertung:** ✅ Sehr ausgereift. Notaus-Hierarchie korrekt (HART: Übertemp 78°C, SOC≤5%; EXTERN-Override; KONTEXTABHÄNGIG). Kurz-Burst-Schutz (2× <7min → 30min Sperre). Auto-Verlängerung bei guten Bedingungen. Extern-Respekt (30 min) mit SOC-Override (≤15%).  
**Komplexität:** ~1600 Zeilen für HP+Klima — höchste Code-Komplexität im System. Durchdacht aber schwer wartbar.

### C9: RegelKlimaanlage (P2, fast, Score 52)

**Zweck:** Thermoschutz Heizhaus via Fritz!DECT.  
**Logik:** Erbt von RegelHeizpatrone, überschreibt Bewertungs-/Aktionslogik. Temperaturgesteuert mit Hysterese (1K). Vor Sunrise nur bei Forecast `gut`. Sunset/SOC-Stop.  
**Bewertung:** ✅ Eigenständige Extern-Erkennung (getrennt von HP). Steuerbox-Override-Integration (klima_toggle hold).

### C10-C16: Wärmepumpe-Regeln

| Regel | Score | Bewertung |
|---|---|---|
| **RegelWwAbsenkung** (45) | ✅ Einmal-pro-Tag-Transitionen (22:00→03:00). Respektiert Verschiebung/Boost | 
| **RegelHeizAbsenkung** (44) | ✅ 18:00→03:00. Respektiert FBH-Heizbedarf, Verschiebung, Pflichtlauf |
| **RegelWwVerschiebung** (47) | ✅ SOC<10%, PV<2kW, Forecast>20kWh, WW>50°C. Kompressorschutz (15 min). Sunset-Lock (<2h) |
| **RegelHeizVerschiebung** (46) | ✅ Identisches Muster wie WW. Korrekte Symmetrie |
| **RegelWwBoost** (48) | ✅ SOC≥90%, nicht ladend, WW<60°C. Cooldown 1h nach Rücknahme |
| **RegelWpPflichtlauf** (49) | ✅ 30h-Verbrauchsprüfung, einmalig morgens (9-10h). Heiz-Boost auf 45°C, max 30 min. Selbstlaufend saisonal |
| **RegelHeizBedarf** (50) | ✅ FBH-getriggert, Außentemperatur-gestuft (≤5°C=Boost, ≤15°C=Standard). Max 3h Timeout |

**Globaler Status waermepumpe.py:** Module-Level Dicts (`_verschoben`, `_wp_laufzeit`, `_wp_extern`, `_boost`, `_absenkung_done`) gehen bei Daemon-Restart verloren. Dies ist **beabsichtigt** — nach Restart werden Absenkungen/Verschiebungen beim nächsten Zeitfenster-Match erneut gesetzt.

---

## D) Aktor-für-Aktor-Analyse

### D1: AktorBatterie

| Aspekt | Status |
|---|---|
| Kommandos | set_soc_min, set_soc_max, set_soc_mode (HTTP), grid_charge (Modbus) |
| Retry | ✅ MAX_RETRIES=2, RETRY_DELAY=1.5s, generische Retry-Logik |
| **Verifikation** | ❌ **TODO-Stub** — `verifiziere()` gibt immer `ok=True` zurück. Kein Read-Back. |
| DRY-RUN | ✅ |

→ **Finding K-01: AktorBatterie verifiziere() ist ein TODO-Stub**

### D2: AktorWattpilot

| Aspekt | Status |
|---|---|
| Kommandos | set_max_current, pause/resume_charging, set_phase_mode, reduce_current, set_power, set_charge_mode_eco/default |
| Verifikation | ✅ Vollständige Read-Back-Verifikation für alle Kommandos |
| IEC 61851 | ✅ 6-32A Limits |

### D3: AktorFritzDECT

| Aspekt | Status |
|---|---|
| Kommandos | hp_ein/aus, klima_ein/aus, lueftung_ein/aus |
| Auth | ✅ MD5 Challenge-Response, SID-Cache (15 min) |
| Multi-Device | ✅ `geraete[]` Array, Fallback zu legacy `ain` |
| Retry | ✅ SID-Invalidierung bei Fehler → frischer Login |
| Verifikation | ✅ `getdevicelistinfos` für Single-Request Device-Status |

### D4: AktorWaermepumpe

| Aspekt | Status |
|---|---|
| Kommandos | set_ww_soll (Reg 5047, 10-85°C), set_heiz_soll (Reg 5037, 18-60°C) |
| Sicherheit | ✅ Whitelist-geschützt in wp_modbus |
| Verifikation | ✅ Read-Back via get_wp_status() |

---

## E) Parameter-Konsistenz (soc_param_matrix.json)

### E1: Score-Gewicht-Hierarchie

```
95  sls_schutz           ← Höchste Priorität (P1)
72  morgen_soc_min       ← HALTE-Score 68 (int(72×0.95))
70  komfort_reset        ← Unter HALTE-Score → kein Ping-Pong
60  wattpilot_battschutz ← P1-Schutz
55  nachmittag_soc_max   ← Strategic-Zyklus
52  klimaanlage
50  forecast_plausi / heiz_bedarf
49  wp_pflichtlauf
48  ww_boost
47  ww_verschiebung
46  heiz_verschiebung
45  ww_absenkung
44  heiz_absenkung
40  heizpatrone
30  zellausgleich        ← Niedrigste Priorität (P3)
```

**Bewertung:** ✅ Konsistent. Sicherheit > Steuerung > Wartung. HALTE-Score-Logik (68 > 70 ist falsch? Nein — 68 < 70, HALTE-Score blockiert Cascade, KomfortReset wird durch Guard gesperrt, nicht durch Score).  

### E2: Bereichsprüfung

Alle Parameter haben `bereich: [min, max]`. Validierung in `pv-config.py:_edit_parameter()` prüft Bereichsgrenzen korrekt. `param_matrix.py:validiere_matrix()` existiert für Startup-Validierung.

### E3: Forecast-Bewertungs-Schwellen

| Qualität | Schwelle | Verwendung |
|---|---|---|
| schlecht | < 40 kWh | morgen_soc_min Veto, heizpatrone Potenzial |
| mittel | < 100 kWh | morgen_soc_min Verzögerung |
| gut | ≥ 100 kWh | Volle Öffnung |

**Bewertung:** ✅ Zentral definiert in `forecast_bewertung` Regelkreis. Konsistent referenziert via `classify_forecast_kwh()`.

### E4: Inkonsistenzen gefunden

| Parameter | Regelkreis | Problem |
|---|---|---|
| `soc_schutz.stop_entladung_unter_pct` | Referenced in heizpatrone Notaus | ⚠️ **Regelkreis `soc_schutz` existiert nicht in der Matrix.** `get_param()` fällt auf Default 5 zurück. Funktional korrekt aber inkonsistent. |

→ **Finding N-02: Phantom-Regelkreis-Referenz `soc_schutz`**

---

## F) pv-config Konsistenz

### F1: Regelkreis-Abdeckung

`pv-config.py` nutzt `alle_regelkreise()` → iteriert über alle Regelkreise in der Matrix. **Vollständig konsistent** — neue Regelkreise in der JSON werden automatisch im Menü angezeigt.

### F2: Parameter-Bearbeitung

- ✅ Typ-Erhaltung (int/float)
- ✅ Bereichsprüfung
- ✅ Concurrent-Safety (Matrix frisch laden vor Speichern)
- ✅ P1-Sicherheitswarnung bei Deaktivierung

### F3: Matrix-Reload-Pfad

Änderung via pv-config.py → JSON auf Disk → nächster Engine-Zyklus lädt Matrix (≤1 min). **Kein SIGHUP nötig** — Engine prüft Matrix-mtime nicht automatisch.

**Beobachtung:** Der SIGHUP-Handler in `automation_daemon.py` existiert, wird aber **nicht automatisch** bei pv-config Änderungen getriggert. Laut Code lädt die Engine die Matrix nur bei:
1. Explizitem SIGHUP-Signal
2. Daemon-Neustart

→ **Finding N-03: Matrix-Reload ohne SIGHUP**

**Nachtrag:** Nach genauerer Analyse: `Engine._lade_matrix()` wird nur bei `__init__` und `reload_matrix()` aufgerufen. Die Matrix wird **nicht** periodisch geladen. Das bedeutet: pv-config Änderungen werden erst nach SIGHUP oder Daemon-Restart wirksam.

→ **Korrektur: Dies ist tatsächlich Finding N-03, kein kritisches Problem** — pv-config zeigt korrekt "Wirksam ab nächstem Engine-Zyklus (≤1 Min)" an, was **irreführend** ist. Tatsächlich wird ein SIGHUP (`systemctl reload pv-automation`) oder Restart benötigt.

→ **Aufstufung zu Finding K-04: Irreführende Wirksamkeits-Angabe in pv-config**

---

## G) Kritische Findings

### K-01: AktorBatterie verifiziere() ~~ist ein TODO-Stub~~ → BEHOBEN

**Status:** ✅ BEHOBEN (2026-06)  
**Datei:** `aktoren/aktor_batterie.py`, `verifiziere()`  
**Fix:** Read-Back via `BatteryConfig.get_values()` nach 0.5s Pause. Prüft `BAT_M0_SOC_MIN` / `BAT_M0_SOC_MAX` gegen Sollwert. Cache-Invalidierung für frischen Read. Logging bei Abweichung.

### K-02: engine_vorausschau() registriert nur 8 von 17 Regeln

**Datei:** `automation_daemon.py`, `engine_vorausschau()` (Standalone-Funktion)  
**Schwere:** MITTEL  
**Beschreibung:** Die Web-API-Funktion `engine_vorausschau()` (ab Zeile ~470) registriert nur:
```python
regeln = [
    RegelSlsSchutz(),
    RegelKomfortReset(),
    RegelMorgenSocMin(), RegelNachmittagSocMax(), RegelZellausgleich(),
    RegelForecastPlausi(), RegelWattpilotBattSchutz(),
    RegelHeizpatrone(),
]
```
Es fehlen: **RegelKlimaanlage, RegelWwAbsenkung, RegelHeizAbsenkung, RegelWwVerschiebung, RegelHeizVerschiebung, RegelWwBoost, RegelWpPflichtlauf, RegelHeizBedarf** (9 Regeln).

**Auswirkung:** Die Web-API-Vorausschau zeigt kein vollständiges Bild der Engine-Entscheidungen. WP-Sollwertregeln und Klimaanlage sind unsichtbar. Betrifft nur die Anzeige, nicht die Ausführung.

**Kontextuelle Mitigierung:** Die Daemon-interne `vorausschau()`-Methode (Zeile ~370) nutzt korrekt `self._engine._regeln` mit allen 17 Regeln. Nur die Standalone-Funktion ist betroffen.

**Empfehlung:** Fehlende Regeln in `engine_vorausschau()` nachtragen. Idealerweise Code-Duplikation eliminieren durch Extraktion der Regelregistrierung.

### K-03: Keine Klimaanlagen-Startup-Prüfung

**Datei:** `automation_daemon.py`, `_hp_startup_check()`  
**Schwere:** MITTEL  
**Beschreibung:** Bei Daemon-(Neu-)Start wird nur der HP-Status (Heizpatrone) geprüft und ggf. abgeschaltet. Die Klimaanlage (ebenfalls Fritz!DECT mit Zustandshaltung) wird NICHT geprüft. Wenn der Daemon nach einem Crash neu startet und die Klimaanlage noch läuft, erkennt die Engine dies erst beim nächsten bewerte()-Zyklus als "extern EIN" und respektiert den Zustand für 30 Minuten — obwohl es ein unkontrollierter Restlauf war.

**Auswirkung:** Klimaanlage kann nach Daemon-Crash ≤30 Minuten unkontrolliert weiterlaufen (bis Extern-Respekt abläuft).

**Mitigierung:** Klimaanlage hat keine Sicherheitsrisiken (kein Heißwasser, keine Übertemperatur). Energieverschwendung ist das einzige Risiko.

**Empfehlung:** `_hp_startup_check()` auf alle Fritz!DECT-Geräte erweitern oder einen generischen `_fritzdect_startup_check()` implementieren.

### K-04: pv-config meldet "Wirksam ab nächstem Engine-Zyklus" — Matrix wird aber nicht periodisch geladen

**Datei:** `pv-config.py` (mehrere Stellen), `engine.py`  
**Schwere:** MITTEL  
**Beschreibung:** pv-config zeigt nach Parameter-Änderung: "Wirksam ab nächstem Engine-Zyklus (≤1 Min)". Die Engine lädt die Matrix aber **nur** bei Daemon-Start oder explizitem SIGHUP-Signal. Ohne Reload-Trigger bleiben Änderungen unwirksam bis zum nächsten Daemon-Restart.

**Auswirkung:** Operator ändert Parameter und erwartet sofortige Wirksamkeit. Tatsächlich ist ein `systemctl reload pv-automation` oder `kill -HUP <pid>` nötig.

**Empfehlung:** Entweder:
- (a) pv-config sendet automatisch SIGHUP nach Speichern (PID-File vorhanden), ODER
- (b) Engine prüft Matrix-mtime periodisch (z.B. alle 60s), ODER
- (c) pv-config Text korrigieren auf "Wirksam nach `systemctl reload pv-automation`"

---

## H) Nicht-kritische Findings

### N-01: Module-Level Mutable State in waermepumpe.py

**Datei:** `regeln/waermepumpe.py`  
**Schwere:** NIEDRIG  
**Beschreibung:** Mindestens 5 Module-Level Dicts (`_verschoben`, `_wp_laufzeit`, `_wp_extern`, `_boost`, `_absenkung_done`, `_pflichtlauf`, `_heizbedarf`) speichern Regelzustand ohne Thread-Lock.  
**Aktuell kein Problem:** Engine-Zyklus läuft single-threaded. Forecast-Thread schreibt nicht in diese Dicts. Aber: wenn die Engine jemals multi-threaded oder multi-process wird, sind Race-Conditions möglich.  
**Empfehlung:** Dokumentation-Comment "Single-Thread-Engine vorausgesetzt" an die Dicts. Keine Änderung nötig.

### N-02: Phantom-Regelkreis-Referenz `soc_schutz`

**Datei:** `regeln/geraete.py` (RegelHeizpatrone.erzeuge_aktionen)  
**Schwere:** NIEDRIG  
**Beschreibung:** `get_param(matrix, 'soc_schutz', 'stop_entladung_unter_pct', 5)` referenziert einen Regelkreis `soc_schutz`, der in der soc_param_matrix.json nicht existiert (wurde 2026-03-07 entfernt). `get_param()` fällt korrekt auf den Default-Wert 5 zurück.  
**Auswirkung:** Keine funktionale Auswirkung. Der Wert 5% ist hardcoded als Default und entspricht dem beabsichtigten Verhalten.  
**Empfehlung:** Referenz durch konstanten Wert oder expliziten Parameter in `heizpatrone` ersetzen.

### N-03: ForecastCollector Sunrise-Fallback-Kette

**Datei:** `collectors/forecast_collector.py`  
**Schwere:** NIEDRIG  
**Beschreibung:** Dreistufiger Fallback (API → Vortages-DB → 7/17 Defaults). Der letzte Fallback (7:00/17:00) ist ein Jahresmittel, das im Sommer (Sunrise ~5:30) und Winter (Sunrise ~8:00) deutlich abweicht.  
**Auswirkung:** Bei komplettem API- + DB-Ausfall werden Morgen-Entscheidungen um bis zu 1.5h verzögert oder verfrüht getriggert. Mitigiert durch Forecast-Qualitäts-Veto.  
**Empfehlung:** Saisonalen Default (Monat→Sunrise-Lookup) als dritte Stufe einbauen, statt festes 7/17.

### N-04: Observer.py nicht im Daemon-Pfad genutzt

**Datei:** `observer.py`  
**Schwere:** INFO  
**Beschreibung:** `observer.py` ist ein standalone lightweight Observer mit TODO "Actuator noch nicht verbunden — nur Log" für Tier-1-Aktionen. Er wird im Produktivbetrieb **nicht** verwendet (der Daemon orchestriert direkt). Code existiert als alternative Deployment-Option.  
**Empfehlung:** Keine. Dokumentation ist vorhanden.

### N-05: DataCollector Modbus fail_count als Class-Attribut

**Datei:** `collectors/data_collector.py`  
**Schwere:** NIEDRIG  
**Beschreibung:** `_modbus_fail_count` ist als Class-Level Variable (`int`) definiert (Zeile ~130), nicht als Instanz-Variable. Bei mehreren DataCollector-Instanzen (aktuell nicht der Fall) wäre der Zähler geteilt.  
**Auswirkung:** Keine — es gibt nur eine Instanz. Allerdings inkonsistent zum Kommentar "W4: Cache-Variablen als Instanzvariablen".  
**Empfehlung:** In `__init__` verschieben (Konsistenz mit W4-Kommentar).

### N-06: Schaltlog Truncation bei jedem Eintrag

**Datei:** `schaltlog.py`, `_truncate_if_needed()`  
**Schwere:** NIEDRIG  
**Beschreibung:** Bei **jedem** Schaltlog-Eintrag wird die gesamte Datei gelesen und ggf. gekürzt (10000 Zeilen). Bei hoher Schaltfrequenz (z.B. SLS-Schutz im Minutentakt) ist dies unnötig I/O-intensiv.  
**Empfehlung:** Truncation nur alle N Einträge oder bei Dateigrößen-Check prüfen.

### N-07: Tier-1 Netz-Überlast sendet `reduce_power` ohne Wert

**Datei:** `collectors/tier1_checker.py`, `_check_netz_ueberlast()`  
**Schwere:** NIEDRIG  
**Beschreibung:** Bei Warn-Stufe (24-26 kW) wird `kommando: 'reduce_power'` ohne `wert`-Feld erzeugt. AktorWattpilot muss dieses Kommando ohne expliziten Zielwert interpretieren können.  
**Empfehlung:** Expliziten Reduktionswert berechnen (proportional zur Überschreitung) oder `reduce_power` Kommando in AktorWattpilot auf Default-Behavior prüfen.

### N-08: Heizpatrone HP_NENN_W als Klassen-Konstante

**Datei:** `regeln/geraete.py`  
**Schwere:** INFO  
**Beschreibung:** `HP_NENN_W = 2000` ist hardcoded als Klassen-Konstante, nicht aus der Parametermatrix geladen. Bei Änderung der Hardware (z.B. 3kW Heizstab) muss Code geändert werden.  
**Empfehlung:** In soc_param_matrix.json als `hp_nenn_w` Parameter aufnehmen.

---

## Zusammenfassung

| Kategorie | Anzahl | Gesamtbewertung |
|---|---|---|
| Kritische Findings (K) | 4 | Keines ist ein sofortiges Sicherheitsrisiko. K-01 (Batterie-Verifikation) hat das höchste Risiko für stille Fehler. |
| Nicht-kritische Findings (N) | 8 | Wartbarkeit und Konsistenz, keine funktionalen Auswirkungen |

**Gesamtbewertung der Engine:** Das System ist für ein Produktivsystem **gut konstruiert**. Die Score-basierte Entscheidungs-Engine mit Schutz/Optimierungs-Trennung, Extern-Respekt-Mechanismen, Burst-Timer-Strategien und Multi-Layer-Notaus ist durchdacht. Die Code-Qualität ist hoch mit konsistentem Logging, sinnvollen Defaults und defensiver Programmierung.

Die größten Verbesserungspotenziale liegen in:
1. **K-01:** Batterie-Verifikation implementieren (höchstes stilles Fehlerrisiko)
2. **K-04:** Matrix-Reload-Pfad klarstellen (Operator-Erwartung vs. Realität)
3. **K-02:** engine_vorausschau() vervollständigen (Web-API-Vollständigkeit)
