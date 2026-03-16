# Tiefenprüfung PV-Automation — 8. März 2026

**Scope:** Vollständige Analyse des Automation-Systems (Engine, Regeln, Aktoren,
Collectors, Config, Architektur). Audit + Umsetzung der Empfehlungen.

**Zustand:** 7.334 LOC im Engine-Paket, alle Dateien kompilieren fehlerfrei,
Parametermatrix validiert, keine Import-Zyklen. System ist seit ~2 Wochen produktiv.

**Umsetzung (8. März 2026):** S1–S3, K1–K2, K4, W3–W5 implementiert. K3 war
bereits korrekt (Tomorrow-Forecast läuft über \_do\_fetch bei startup). W2 auf
HP-Refactoring (W1) verschoben. F2 zurückgestellt (WW-Sensor noch nicht installiert).
F1 (WattPilot-Aktor) wartet auf separate Freigabe.

---

## Inhaltsverzeichnis

1. [Gesamtbewertung](#1-gesamtbewertung)
2. [Architektur-Analyse](#2-architektur-analyse)
3. [Regel-Algorithmen im Detail](#3-regel-algorithmen-im-detail)
4. [Heizpatrone: Neudenk-Analyse](#4-heizpatrone-neudenk-analyse)
5. [Konfigurationsinkonsistenzen](#5-konfigurationsinkonsistenzen)
6. [Code-Gesundheit](#6-code-gesundheit)
7. [Sicherheits-Review](#7-sicherheits-review)
8. [Test-Abdeckung](#8-test-abdeckung)
9. [Offene Architektur-Entscheidungen](#9-offene-architektur-entscheidungen)
10. [Empfehlungen (priorisiert)](#10-empfehlungen-priorisiert)

---

## 1. Gesamtbewertung

### Stärken
- **Klare Schichtentrennung** (S1–S4): Config → Observer → Engine → Actuator
- **Score-basiertes Regelsystem** mit sauberer Schutz/Optimierung-Trennung
- **Parametermatrix-System** erlaubt Config-Änderungen ohne Code-Deployment
- **Extern-Erkennung** (SocExternTracker, HP-Extern) → System respektiert manuelle Eingriffe
- **Defensive Programmierung**: None-Safety in Regeln, RAM-DB Korrupt-Recovery,
  Dedup-Sperre im Actuator, Read-Back-Verifikation
- **GEN24 HW-Limit**: Korrekte Entscheidung, wirkungslose Modbus-Ratenlimits zu entfernen
  und auf HTTP-API SOC_MIN/SOC_MAX als Steuerungsinstrument umzusteigen

### Schwächen
- **RegelHeizpatrone**: 903 LOC in einer Datei, `bewerte()` ~300 Zeilen, `erzeuge_aktionen()` ~335 Zeilen
  → zu komplex für eine einzelne Klasse (Refactoring-Kandidat #1)
- **Konfigurationsdivergenz**: 3 Config-Dateien mit teils widersprüchlichen Werten
- **WattpilotAktor**: Komplett Stub → EV-Schutzregeln können nichts ausführen
- **WW-Temperatursensor fehlt**: HP-Übertemperaturschutz (`≥78°C`) ist funktionslos
- **Vorausschau unvollständig**: Web-API zeigt nur 7 von 8 aktiven Regeln

### Reifegrad-Einschätzung

| Subsystem | Reifegrad | Anmerkung |
|---|---|---|
| Engine-Kern (Score/Dispatch) | ★★★★☆ | Stabil, Cascade-Logik gut |
| SOC-Steuerung (Morgen/Nachmittag/Reset) | ★★★★☆ | Bewährt, Extern-Toleranz solide |
| Heizpatrone (6 Phasen) | ★★★☆☆ | Funktional, aber Monolith |
| SLS-Schutz | ★★★★★ | Einfach, deterministisch, korrekt |
| Tier-1 Checker | ★★★★☆ | Richtig entschlackt (nur Flags+Log) |
| Forecast-Collector | ★★★★☆ | Trigger-basiert statt blind, gut |
| WattPilot-Aktor | ★☆☆☆☆ | Reiner Stub |
| Test-Framework | ★★★☆☆ | test_skeleton guter Ansatz, aber kein CI |
| Dokumentation | ★★★☆☆ | Umfangreich, aber inkonsistent |

---

## 2. Architektur-Analyse

### 2.1 Datenfluss (IST)

```
Config JSON ─────┐
                  v
Collector-DB ──→ DataCollector ──→ ObsState ──→ RAM-DB
                                    ↑                ↓
SolarForecast ──→ ForecastCollector─┘         Engine (fast/strategic)
                                                ↓
Fritz!Box ──→ FritzDECT-Collector               ActionPlan
                                                ↓
                                            Actuator
                                          ┌────┼────┐
                                          v    v    v
                                     Batterie WP  Fritz
                                     (HTTP)  (Stub) (AHA)
                                          ↓
                                     Persist-DB + Schaltlog
```

### 2.2 Architektur-Bewertung

**Gut:**
- Single-Process mit Threads vermeidet IPC-Komplexität
- RAM-DB in tmpfs `/dev/shm/` → kein SD-Card-Verschleiß für Hochfrequenz-Daten
- Observer + Daemon als zwei Laufmodi (Diagnose vs. Produktion)
- Rollenmodell A/B/C/D (Web-API read-only, Config nur via SSH, Diagnos getrennt)

**Kritisch zu hinterfragen:**

1. **Globaler Singleton `soc_extern_tracker`**: Module-Level-Instanz, die von allen
   SOC-Regeln geteilt wird. Funktioniert nur weil Engine single-threaded ist.
   Bei jeder Parallelisierung (Async, Multi-Thread-Engine) → Race Condition.

2. **ObsState als flat Dataclass mit ~60 Feldern**: Monolithischer Zustand.
   Alternative: Verschachtelte Datenmodelle (ErzeugerState, SpeicherState, etc.)
   oder Event-basierter Ansatz (nur Delta-Updates).
   → **Empfehlung: NICHT jetzt umbauen** — der flache Ansatz ist für den aktuellen
   Regelumfang wartbar und performant.

3. **Engine bewertet alle Regeln sequentiell**: Bei 8 Regeln kein Problem.
   Bei Skalierung auf 20+ Regeln → Zykluszeit steigt. Score-Berechnung selbst
   ist schnell (~µs), aber `erzeuge_aktionen()` macht teils DB-Zugriffe
   (Zellausgleich: `battery_scheduler_state.json`).

4. **Forecast-Thread schreibt ObsState mit Lock**: Thread-Safety ist korrekt
   implementiert (obs_lock), aber der Lock wird im Hauptloop 6× pro Zyklus
   akquiriert. Bei 10s-Zyklen und 30s-Forecast ist das unkritisch, aber
   der Lock-Scope ist unnötig groß (ganzer collect()-Aufruf statt einzelner Felder).

### 2.3 Single-Point-of-Failure-Analyse

| Komponente | SPOF? | Mitigation |
|---|---|---|
| RAM-DB korrupt | ✅ | Automatische Neu-Erstellung, tmpfs |
| Collector-DB nicht lesbar | ⚠️ | obs-Felder bleiben None, Regeln testen None |
| Fritz!Box nicht erreichbar | ⚠️ | HP-Status unklar → Engine macht nichts |
| Fronius API Timeout | ⚠️ | SOC_MIN/MAX bleiben stale (30s Cache) |
| Modbus-Verbindung verloren | ⚠️ | StorCtl_Mod bleibt stale, aber informativ |
| Daemon-Crash | ✅ | systemd Restart, PID-File Stale-Check |
| SD-Card Persist-DB voll | ⚠️ | Logging schlägt fehl, kein Audit-Trail |

---

## 3. Regel-Algorithmen im Detail

### 3.1 Tagesverlauf der Regelkreise

```
05:00    06:00    08:00    10:00    12:00    14:00    16:00    18:00    20:00
  │        │SR      │        │FC      │        │FC      │SS      │        │
  │   ┌────┴────┐   │   ┌────┴────┐   │        │        │   ┌────┴────┐   │
  │   │MorgenMin│   │   │FcastPl. │   │  SOC_MAX Öffnung │   │Komfort  │   │
  │   │SOC→5%   │   │   │Korrektur│   │     ┌───┴───┐    │   │Reset    │   │
  │   └─────────┘   │   └─────────┘   │     │NM Max │    │   │25/75%   │   │
  ├─── HP Phase 0 ──┤── HP Phase 1/1b─┤── HP Phase 2/3 ──┤── HP Ph. 4 ┤   │
  │   (Drain)       │   (Vormittag)   │   (Mittag/NM)    │   (Abend)  │   │
  └─────────────────┴─────────────────┴──────────────────┴────────────┘   │
  ←────── Tier-1: SLS-Schutz, Temp-Alarm, SOC-Alarm permanent ──────────→
  ←────── WP Battschutz: aktiv wenn EV lädt + SOC nahe MIN ─────────────→
```

**SR** = Sunrise, **FC** = Forecast-Trigger, **SS** = Sunset

### 3.2 Score-Konkurrenz-Analyse

Die Engine bewertet pro Zyklus alle Regeln und wählt den Gewinner.
Potenzielle Konflikte:

| Regel A | Regel B | Konflikt? | Auflösung |
|---|---|---|---|
| morgen_soc_min (72) | komfort_reset (70) | ⚠️ Morgens überlappend | morgen gewinnt (Score 72 > 70), Komfort nur im Abend-Fenster |
| nachmittag_soc_max (55) | forecast_plausi (50) | ⚠️ Beide setzen SOC_MAX | nachmittag gewinnt, Cascade → forecast als Fallback |
| heizpatrone (40) | wattpilot_battschutz (60) | Nein | Verschiedene Aktoren |
| morgen_soc_min HALTE (68) | komfort_reset frueh (70) | ⚠️ Nachmittags | Komfort-Reset gewinnt → richtig (SOC_MIN hoch) |

**Systemischer Schwachpunkt:** Wenn morgen_soc_min im HALTE-Modus ist (Score 68 = 72×0.95)
und komfort_reset nachmittags den Früh-Reset auslöst (Score 70), gewinnt komfort_reset
korrekt. ABER: Falls forecast_rest_kwh gerade noch knapp ≥ erholung_schwelle (10 kWh),
**schwankt** der Früh-Reset bei Wolkendurchzügen ein/aus.

→ **Empfehlung:** Hysterese für `erholung_schwelle_kwh` einbauen (z.B. EIN bei <10, AUS erst bei >12).

### 3.3 SOC-Extern-Tracker: Korrektheit

Der Tracker erkennt externe SOC-Änderungen über Delta-Vergleich `prev_min ≠ obs.soc_min`.
Engine-eigene Aktionen werden über `registriere_aktion()` vorab registriert.

**Edge Case:** Wenn die Engine eine Aktion erzeugt (`set_soc_min=5`), der Actuator
sie aber NICHT ausführt (z.B. Dedup-Sperre), bleibt `_engine_set_min=5` als
Pending registriert. Wenn dann jemand manuell SOC_MIN=5 setzt, wird das fälschlich
als Engine-Aktion erkannt und NICHT als Extern gewertet.

→ **Empfehlung:** `registriere_aktion()` erst NACH erfolgreichem `ausfuehren()` aufrufen,
   nicht schon in `erzeuge_aktionen()`. Aktuell ist die Reihenfolge:
   1. `erzeuge_aktionen()` → `registriere_aktion()` (zu früh!)
   2. `actuator.ausfuehren_plan(aktionen)` (kann dedup/fail)

### 3.4 Nachtlade-Vermeidung (komfort_reset)

Die `_nachtladung_vermeidbar()` Logik prüft `forecast_tomorrow_kwh ≥ 20 kWh`.
Bei fehlender Morgen-Prognose (`None`) → "sicherheitshalber Nachtladung".

**Problem:** Der ForecastCollector holt `forecast_tomorrow_kwh` erst bei Trigger-Zeitpunkten
(startup, sunrise, 10:00, 14:00). Wenn der Daemon nach 14:00 neu startet, wird
`forecast_tomorrow_kwh` erst beim nächsten 6h-Fallback geholt. Bis dahin liegt der
Komfort-Reset (Sunset + offset) möglicherweise schon vorbei → Nachtladung wird
erzwungen obwohl morgen genug PV käme.

→ **Empfehlung:** `_do_fetch()` im startup-Trigger auch `_fetch_tomorrow_forecast()` aufrufen
   (aktuell geschieht das nur bei den Fixed-Triggern 10:00 und 14:00).

---

## 4. Heizpatrone: Neudenk-Analyse

### 4.1 Ist-Zustand

`RegelHeizpatrone` in [geraete.py](automation/engine/regeln/geraete.py) ist mit
**903 Zeilen** die mit Abstand komplexeste Regel. Sie implementiert:

- 6 Phasen (Phase 0: Drain, 1: Vormittag, 1b: Nulleinspeiser-Probe, 2: Mittag, 3: NM, 4: Abend)
- Potenzial-Klassifikation (4 Stufen)
- Verbraucher-Konkurrenz (WP, EV)
- Parallelbetrieb-Matrix (potenzialabhängig)
- Extern-Erkennung (HP manuell ein/aus)
- Probe-Logik (2-Min-Testpuls für WR-Drosselungserkennung)
- Netzbezug-Glättung (7-Zyklen-Durchschnitt)
- Burst-Timer mit Verlängerung
- Phase-4-Nachladezyklus (SOC-nahe-MAX → Burst → SOC sinkt → Pause → Nachladung → Burst)

### 4.2 Bewertung

**Verdienst:** Die Phasen-Logik ist inhaltlich durchdacht — jede Phase adressiert
einen realen Betriebszustand. Die HP-Extern-Erkennung und die Probe-Logik für
Nulleinspeiser sind innovative Lösungen.

**Problem:** Die gesamte Logik lebt in `bewerte()` und `erzeuge_aktionen()`,
die zu 80% dupliziert sind (gleiche Phasenerkennung, gleiche Grenzwertprüfungen).
Die Methoden sind so lang, dass ein Leser den Überblick verliert.

### 4.3 Refactoring-Vorschlag: Phase-Objekt-Muster

```python
# Statt einer monolithischen bewerte()/erzeuge_aktionen():

class HPPhase(ABC):
    """Abstrakte HP-Betriebsphase."""
    name: str
    def ist_aktiv(self, ctx: HPContext) -> bool: ...
    def bewerte(self, ctx: HPContext) -> int: ...
    def erzeuge_aktionen(self, ctx: HPContext) -> list[dict]: ...
    def notaus_grund(self, ctx: HPContext) -> str | None: ...

@dataclass
class HPContext:
    """Gemeinsamer Kontext für alle Phasen."""
    obs: ObsState
    matrix: dict
    potenzial: str
    now_h: float
    rest_h: float
    soc_max_eff: int
    wp_aktiv: bool
    ev_aktiv: bool
    parallel_ok: bool
    grid_avg: float
    forecast_jetzt_w: float
    burst_state: BurstState  # Burst-Timer, Drain-Modus etc.

class PhaseDrain(HPPhase): ...       # Phase 0
class PhaseVormittag(HPPhase): ...   # Phase 1
class PhaseNulleinspeiser(HPPhase):  # Phase 1b
class PhaseMittag(HPPhase): ...      # Phase 2
class PhaseNachmittag(HPPhase): ...  # Phase 3
class PhaseAbend(HPPhase): ...       # Phase 4

class RegelHeizpatrone(Regel):
    def __init__(self):
        self._phasen = [PhaseDrain(), PhaseVormittag(), ...]
        self._burst = BurstState()

    def bewerte(self, obs, matrix):
        ctx = self._build_context(obs, matrix)
        # Notaus immer zuerst (über alle Phasen)
        for phase in self._phasen:
            if phase.notaus_grund(ctx):
                return score * 1.5
        # Beste Phase wählen
        for phase in self._phasen:
            if phase.ist_aktiv(ctx):
                return phase.bewerte(ctx)
        return 0
```

**Vorteile:**
- Jede Phase ist unabhängig testbar
- Notaus-Logik an einer Stelle (statt in bewerte() UND erzeuge_aktionen())
- HPContext eliminiert Duplizierung der Grenzwertberechnungen
- Neue Phasen (z.B. "Klima" im Sommer) → neue Klasse, kein Monolith-Wachstum

**Aufwand:** ~2–3 Stunden. Die Logik bleibt identisch, nur die Struktur ändert sich.

### 4.4 Alternative: Zustandsautomat (State Machine)

Die HP durchläuft de facto bereits Zustände (AUS, DRAIN, BURST, PROBE, PAUSE).
Ein expliziter Zustandsautomat würde die Übergänge formalisieren:

```
         ┌──────────────────────────────────────┐
         │                AUS                    │
         │  (min_pause, extern_sperre)           │
         └──┬───────┬───────┬───────┬──────┬────┘
            │       │       │       │      │
       Phase 0  Phase 1  Phase 1b Phase 2-3 Phase 4
            │       │       │       │      │
            v       v       v       v      v
         ┌─────────────────────────────────────┐
         │              BURST                   │
         │  (burst_start, burst_ende)           │
         │  └→ Probe-Modus (Unterzustand)      │
         └──────────┬──────────────────────────┘
                    │ Notaus / Timer abgelaufen
                    v
         ┌─────────────────────────────────────┐
         │              AUS                     │
         │  (min_pause Countdown)               │
         └─────────────────────────────────────┘
```

→ **Empfehlung:** Phase-Objekt-Muster bevorzugen (weniger Overhead als vollständige
State-Machine, deckt den Use Case ab).

---

## 5. Konfigurationsinkonsistenzen

### 5.1 Kritisch: Battery-Kapazität divergiert

| Quelle | Wert | Kontext |
|---|---|---|
| `config.py` → `PV_BATTERY_KWH` | **20.48 kWh** | Global, korrekt (2× Tower) |
| `battery_control.json` → batterie.kapazitaet_kwh | **20.48 kWh** | Korrekt |
| `soc_param_matrix.json` → hardware.kapazitaet_kwh | **10.24 kWh** | **FALSCH** (1× Tower) |

Die Param-Matrix-Hardware-Sektion wird aktuell nicht direkt von Regeln ausgelesen
(Regeln nutzen `config.PV_BATTERY_KWH`). Aber die Information ist irreführend.

→ **Aktion:** `soc_param_matrix.json` → `hardware.kapazitaet_kwh` auf 20.48 korrigieren.

### 5.2 Duplikate mit Divergenz-Risiko

| Parameter | param_matrix | battery_control.json | Status |
|---|---|---|---|
| nachmittag.start_stunde | 11 | 12 | ⚠️ Divergent |
| surplus_sicherheitsfaktor | 1.3 (param) | 1.3 | OK |
| wolken_schwer_pct | 85 | 85 | OK |
| max_stunden_vor_sunset | 1.5 | 1.5 | OK |
| komfort SOC_MIN/MAX | 25/75 | 25/75 | OK |
| stress SOC_MIN/MAX | 5/100 | 5/100 | OK (leicht unterschiedliche Paths) |

→ **Empfehlung:** `battery_control.json` als **Legacy** deklarieren. Alle aktiven
Parameter in `soc_param_matrix.json` konzentrieren. battery_control.json nur noch
für Tier-1 Schwellwerte und Hardware-Specs (Kapazität, SOH).

### 5.3 Entfernte Befehle noch in Param-Matrix

Die Param-Matrix enthält Regelkreise/Kommandos für entfernte Regeln:

- `abend_entladerate` → `set_discharge_rate`, `stop_discharge` (entfernt 2026-03-07)
- `temp_schutz` → `set_charge_rate` (entfernt 2026-03-07)
- `laderate_dynamisch` → `set_charge_rate` (entfernt 2026-03-07)
- `soc_schutz` → `stop_discharge`, `stop_charge` (entfernt 2026-03-07)

Diese Regelkreise sind in der Matrix noch `aktiv: true` und haben `score_gewicht`.
Die Engine registriert sie nicht, aber die Vorausschau-Anzeige und `param_matrix --validate`
können verwirrend sein.

→ **Aktion:** In soc_param_matrix.json `aktiv: false` setzen für entfernte Regelkreise.
   Optional Kommentar "Entfernt 2026-03-07: GEN24 HW-Limit" im `_kommentar`-Feld.

---

## 6. Code-Gesundheit

### 6.1 Metriken

| Metrik | Wert | Bewertung |
|---|---|---|
| Gesamt-LOC (Engine-Paket) | 7.334 | Angemessen |
| Größte Datei | geraete.py (903 LOC) | ⚠️ Refactoring-Kandidat |
| Zweitgrößte Datei | test_skeleton.py (777 LOC) | OK (Testcode) |
| Kompilierungsfehler | 0 | ✅ |
| Import-Zyklen | 0 | ✅ |
| Param-Matrix-Validierung | Alle Werte im Bereich | ✅ |
| Dead-Code-Referenzen | Nur in Kommentaren | ✅ Sauber entfernt |

### 6.2 Code Smells

1. **Duplizierung in RegelHeizpatrone**: `bewerte()` und `erzeuge_aktionen()` prüfen
   die gleichen Bedingungen. Geschätzt ~40% Code-Duplizierung innerhalb der Klasse.

2. **Class-Level Cache in DataCollector**: `_soc_config_cache_ts`, `_fritzdect_cache_ts`
   sind Class-Variablen (nicht `self.`). Funktioniert nur als Singleton.

3. **Magic Number in ForecastCollector**: `best_ghi * 37.59 * 0.15` — kWp und
   Wirkungsgrad hardcoded statt aus `config.py`.

4. **Collector importiert aus Aktor**: `data_collector.py` importiert
   `_load_fritz_config`, `_get_session_id`, `_aha_device_info` aus `aktor_fritzdect.py`.
   Verletzt den Datenfluss Collector→Engine→Aktor.

5. **`verifiziere()` in AktorBatterie effektiv leer**: Gibt immer `{'ok': True}`
   zurück nach Entfernung der Modbus-Readback-Logik.

6. **`engine_vorausschau()` fehlt `RegelSlsSchutz`**: 7 statt 8 aktive Regeln.

### 6.3 Thread-Safety

| Shared State | Schutz | Risiko |
|---|---|---|
| ObsState im Daemon | `_obs_lock` (threading.Lock) | ✅ Korrekt |
| RAM-DB Connection | `check_same_thread=False` + Lock | ✅ |
| `soc_extern_tracker` (Singleton) | Kein Lock | ⚠️ OK solange Engine single-threaded |
| RegelHeizpatrone._burst_* | Kein Lock | ⚠️ OK solange Engine single-threaded |
| Fritz!DECT SID-Cache | Globale Variable `_sid_cache` | ⚠️ Nur 1 Thread greift zu |

→ Bei Architekturänderung (Multi-Thread-Engine) müsste der Singleton-basierte
State umgebaut werden.

---

## 7. Sicherheits-Review

### 7.1 Schutz-Hierarchie (IST)

```
Prio 1: Hardware (GEN24 DC-DC ~22A, BMS LFP-Temp)
   └→ Nicht umgehbar, immer aktiv

Prio 2: Tier-1 (tier1_checker.py)
   └→ Batterie-Temp-Flags (Dashboard/Log)
   └→ SOC-kritisch-Flag (Dashboard/Log)
   └→ Netz-Überlast → Wattpilot dimmen

Prio 3: Engine-Schutzregeln ('schutz' im Namen)
   └→ SLS-Schutz (35A/Phase → HP aus, WP dimmen)

Prio 4: Engine-Optimierung (Score-basiert)
   └→ HP Notaus (immer aktiv, auch bei aktiv=False)
   └→ WP-Battschutz (SOC_MIN anheben)
```

### 7.2 Schutzlücken

| Lücke | Schwere | Mitigation |
|---|---|---|
| **WW-Temp-Sensor fehlt** | HOCH | HP-Übertemp-Schutz (≥78°C) komplett blind. Warmwasserspeicher-Schaden möglich bei Handbetrieb der HP. |
| **WattPilot-Aktor = Stub** | MITTEL | Tier-1 Netz-Überlast kann WP nicht wirklich dimmen. SLS-Schutz sendet Befehl, aber nichts passiert. |
| **RvrtTms=0 bei Modbus-Schreiben** | NIEDRIG | Aktuell nur für grid_charge relevant (SOC via HTTP-API). SOC_MODE=manual persistiert korrekt über den Fronius-eigenen Mechanismus. |
| **Kein Watchdog für HP-Dauerbetrieb** | MITTEL | Wenn Fritz!Box nicht erreichbar → HP-Status unbekannt → Engine kann HP nicht abschalten. Burst-Timer begrenzt auf 30 Min, aber: Was wenn die Fritz!Box während eines Bursts ausfällt? |

### 7.3 Empfehlung: HP-Hardware-Watchdog

Aktuell begrenzt nur der Burst-Timer (max 30 Min) die HP-Laufzeit. Wenn der
Daemon crasht WÄHREND die HP läuft, bleibt sie dauerhaft ein (Fritz!DECT-Steckdose
behält Zustand).

→ **Empfehlung (PRIORITÄT HOCH):** Beim Daemon-Start (und Restart) sollte als
  **erste Aktion** der HP-Status geprüft und ggf. abgeschaltet werden. Aktuell
  wird der HP-Zustand erst nach dem ersten Collector-Zyklus (10s) erkannt.

→ **Langfristig:** Fritz!DECT-Steckdose mit Timeout-Automatik konfigurieren
  (falls Fritz!OS das unterstützt) oder einen Software-Watchdog implementieren,
  der HP nach max. 45 Min ohne Heartbeat abschaltet.

---

## 8. Test-Abdeckung

### 8.1 Ist-Zustand

`test_skeleton.py` (777 LOC) testet:
- ObsState RAM-DB Read/Write ✅
- Tier-1 Schwellenprüfung ✅
- Engine-Zyklus (Score-Bewertung) ✅
- Actuator Dispatch (Dry-Run) ✅
- Persist-DB Logging ✅
- Parametermatrix-Validierung ✅
- 9 Regelkreise mit Matrix-Parametern ✅

**Fehlend:**
- Kein CI/CD — Tests müssen manuell ausgeführt werden
- Keine Integrationstests (volles Daemon-Lifecycle)
- Keine Edge-Case-Tests für HP-Phasen (z.B. Probe-Verlängerung nach Erfolg)
- Keine Timing-spezifischen Tests (Burst-Timer-Ablauf, Dedup-Sperre)
- Kein Test für ForecastCollector-Trigger-Logik
- Kein Test für SocExternTracker-Edge-Cases

### 8.2 Empfehlung: Prioritäre Tests

1. **HP Phase-Übergänge**: Test-Matrix mit allen 6 Phasen × Notaus-Gründen
2. **SocExternTracker**: registriere_aktion() vor vs. nach ausfuehren()
3. **Komfort-Reset Nachtlade-Vermeidung**: Forecast-Timing Edge Cases
4. **SLS-Schutz**: Phasenströme an der Grenze (34.9A, 35.0A, 35.1A)

---

## 9. Offene Architektur-Entscheidungen

### E1: WattPilot-Integration → Wann Stub ersetzen?

**Status:** Reiner Stub. SLS-Schutz und Tier-1 Netz-Überlast erzeugen Aktionen,
die ins Leere laufen.

**Optionen:**
- A) websocket-Steuerung via `wattpilot_api.py` (bestehende Lese-Library erweitern)
- B) Direkte REST-API (falls WattPilot v2 verfügbar)
- C) MQTT-Bridge (falls Fronius das plant)

**Empfehlung:** Option A ist am naheliegendsten (wattpilot_api.py existiert bereits
für Lesen). Schreibzugriffe (`amp=6`, `frc=0`) über WebSocket-API sollten in
~2h implementierbar sein.

### E2: WW-Temperatursensor → Wann installieren?

**Status:** `ww_temp_c` immer None. HP-Schutz funktionslos.

**Optionen:**
- A) Thermistor an MegaBas I2C-Board (IN1–IN4) → TODO Phase 1
- B) DS18B20 1-Wire direkt am Raspberry Pi GPIO
- C) Funk-Sensor (z.B. Fritz!DECT 440) → Kein Verkabelungsaufwand

**Empfehlung:** Option C für schnelle Lösung (Fritz!DECT 440 hat Temperatur-Sensor,
Integration über AHA-API analog zum bestehenden Steckdosen-Code).

### E3: Wie mit entfernten Regelkreisen in der Param-Matrix umgehen?

**Optionen:**
- A) `aktiv: false` setzen, als Dokumentation beibehalten
- B) Komplett entfernen (saubere Matrix, aber Verlust der historischen Parameter)
- C) In separate `_historisch`-Sektion verschieben

**Empfehlung:** Option A — minimaler Aufwand, maximale Nachvollziehbarkeit.

### E4: Config-Konsolidierung

**Optionen:**
- A) `battery_control.json` als Master, param_matrix nur für Engine-spezifische Parameter
- B) `soc_param_matrix.json` als Master, battery_control.json auf Legacy reduzieren
- C) Merge: Ein einziges Config-File

**Empfehlung:** Option B — die Param-Matrix hat bereits Validierung, Bereiche, Einheiten,
   Beschreibungen. `battery_control.json` auf Hardware-Specs + Tier-1 Grenzen reduzieren.

### E5: Vorausschau-Vervollständigung

Die `engine_vorausschau()` zeigt nur 7 von 8 Regeln. `RegelSlsSchutz` fehlt.
Einfacher Fix: Import + Instanziierung hinzufügen.

### E6: Algorithmus-Neudenk — Event-basiert statt Polling?

**Aktuell:** Engine pollt alle 60s/15min, bewertet den gesamten ObsState.

**Alternative:** Event-Driven — Regeln werden nur bewertet wenn sich relevante
ObsState-Felder ändern (z.B. SOC-Delta > 2%, PV-Sprung > 500W).

**Bewertung:** Für das aktuelle System (8 Regeln, Score-Berechnung < 1ms)
bringt Event-Driven keinen Vorteil. Der Polling-Ansatz ist einfacher zu debuggen,
da der Zustand zu festen Zeitpunkten bekannt ist. Bei Skalierung auf Echtzeit-
Steuerung (z.B. Sekundenbasiertes EV-Lademanagement) wäre ein Hybrid sinnvoll:
**Fast-Events** für Schutzregeln + **Polling** für Strategieregeln.

→ **Empfehlung: NICHT umbauen.** Polling ist für den Use Case richtig.

---

## 10. Empfehlungen (priorisiert)

### PRIORITÄT 1 — Sicherheit (vor nächstem Commit)

| # | Empfehlung | Aufwand | Impact | Status |
|---|---|---|---|---|
| S1 | HP-Status beim Daemon-Start prüfen + ggf. abschalten | 15 Min | Schützt vor Dauer-HP nach Crash | **DONE** |
| S2 | `soc_param_matrix.json` entfernte Regelkreise → `aktiv: false` | 5 Min | Verhindert Verwirrung | **DONE** |
| S3 | `soc_param_matrix.json` hardware.kapazitaet_kwh → 20.48 | 1 Min | Korrekte Datenbasis | **DONE** |

### PRIORITÄT 2 — Korrektheit (nächste Woche)

| # | Empfehlung | Aufwand | Impact | Status |
|---|---|---|---|---|
| K1 | `engine_vorausschau()` um `RegelSlsSchutz` ergänzen | 5 Min | Web-API zeigt vollständiges Bild | **DONE** |
| K2 | `soc_extern_tracker.registriere_aktion()` nach Actuator-Erfolg verschieben | 30 Min | Korrekte Extern-Erkennung | **DONE** |
| K3 | ForecastCollector: Tomorrow-Forecast auch bei startup-Trigger holen | 10 Min | Nachtlade-Entscheidung korrekt nach Daemon-Neustart | **N/A** (war bereits korrekt) |
| K4 | Hysterese für komfort_reset.erholung_schwelle_kwh | 15 Min | Kein Flickern bei Wolkendurchzügen | **DONE** |

### PRIORITÄT 3 — Wartbarkeit (nächster Sprint)

| # | Empfehlung | Aufwand | Impact | Status |
|---|---|---|---|---|
| W1 | RegelHeizpatrone → Phase-Objekt-Muster refactorn | 2–3 h | Von 903 LOC Monolith auf ~6×100 LOC | Separater Chat |
| W2 | Fritz!DECT-Utilities extrahieren (Collector→Aktor Import auflösen) | 30 Min | Saubere Schichtentrennung | → mit W1 |
| W3 | AktorBatterie.verifiziere() für HTTP-API SOC-Readback implementieren | 1 h | Echte Verifikation statt No-Op | **DONE** (Toter Code bereinigt, TODO hinterlegt) |
| W4 | DataCollector Class-Level Cache → Instance-Variablen | 15 Min | Singleton-Abhängigkeit entfernen | **DONE** |
| W5 | Magic Number `37.59 * 0.15` in ForecastCollector → `config.PV_KWP_TOTAL` | 5 Min | Wartbar | **DONE** |

### PRIORITÄT 4 — Funktionalität (Roadmap)

| # | Empfehlung | Aufwand | Impact | Status |
|---|---|---|---|---|
| F1 | WattPilot-Aktor implementieren (WebSocket-Steuerung) | 4–6 h | SLS-/Überlast-Schutz funktional | Freigabe ausstehend |
| F2 | WW-Temperatursensor anbinden (Fritz!DECT 440 oder DS18B20) | 2–4 h | HP-Übertemp-Schutz aktiviert | Zurückgestellt (HW fehlt) |
| F3 | Config-Konsolidierung (param_matrix als Master) | 2 h | Eine Wahrheitsquelle | Offen |
| F4 | CI-Pipeline für test_skeleton.py | 1 h | Automatische Regression | Offen |

### PRIORITÄT 5 — Dokumentation

| # | Empfehlung | Aufwand |
|---|---|---|
| D1 | AUTOMATION_ARCHITEKTUR.md aktualisieren: SLS-Schutz, Service-Name, Regelanzahl | 30 Min |
| D2 | STRATEGIEN.md: Duplikat in §2.3 bereinigen | 5 Min |
| D3 | automation/README.md auf Stand bringen (Fritz!DECT ist produktiv, kein "optional") | 15 Min |
| D4 | EventNotifier in Architektur-Doc dokumentieren | 15 Min |

---

## Fazit

Das System ist **architektonisch solide** und für den aktuellen Einsatzzweck gut
dimensioniert. Die Entscheidung, GEN24-HW-Limits zu respektieren und auf SOC_MIN/MAX
als primäres Steuerungsinstrument umzusteigen, war korrekt und hat die Code-Komplexität
deutlich reduziert.

**Die drei wichtigsten Handlungsfelder:**
1. **HP-Startup-Schutz** — einfach, kritisch, sofort umsetzbar (S1)
2. **Config-Bereinigung** — 3 Minuten, verhindert künftige Verwirrung (S2+S3)
3. **HP-Refactoring** — größter Wartbarkeitsgewinn, kann vorbereitet werden (W1)

Das Event-basierte vs. Polling-Paradigma sollte NICHT geändert werden — der aktuelle
Ansatz ist für 8 Regeln und 10s-Zyklen optimal. Ein Neudenken der Algorithmen ist
nur für die Heizpatrone sinnvoll (Phase-Objekt-Muster), nicht für die Gesamtarchitektur.
