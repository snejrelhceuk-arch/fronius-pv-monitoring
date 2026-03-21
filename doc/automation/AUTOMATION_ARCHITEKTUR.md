# Automation-Architektur — Schicht C

**Erstellt:** 2026-02-22  
**Letzte Überarbeitung:** 2026-03-01 (HP-Automation produktiv: Fritz!DECT, SOC-Notaus, flow_view)  
**Status:** Produktiv (Batterie + Heizpatrone laufen über pv-automation.service)  
**Referenz Rollenmodell:** [ABCD_ROLLENMODELL.md](../system/ABCD_ROLLENMODELL.md)

---

## 1. Zielsetzung

Ein **erweiterungsoffenes** Automationsframework für alle steuerbaren Aktoren
der PV-Anlage, das:

- das A/B/C/D-Rollenmodell strikt einhaelt (C schreibt Aktorik, B liest,
  A liefert Daten, D bewertet read-only)
- von jeder Instanz (Batterie, WP, EV, Heizpatrone, Klima, Lüftung, …)
  **nur das Interface kennen muss**, nicht die Implementierung
- über ein SSH-Terminal konfigurierbar ist (kein Web-Write-Pfad)
- jede Entscheidung dokumentiert, bevor sie ausgeführt wird
- jede Wirkung nach Ausführung verifiziert

### Entwicklungsprinzip: Strikte Isolation

Die Automation wurde **vollständig getrennt** vom laufenden System
entwickelt:

- ~~`battery_scheduler.py` + Cron~~ → **`pv-automation.service`** (seit 2026-02-28)
- Code in eigenem Verzeichnis (`automation/engine/`)
- Kein gemeinsamer State mit Legacy-Scheduler
- Umschaltung nach abgeschlossener Testphase (Phase 2, erledigt 2026-02-28)
- Jeder Meilenstein ist einzeln testbar und rückrollbar
- **Nicht alles auf einmal** — ein Aktor nach dem anderen

---

## 2. Gesamtübersicht — 4 Schichten innerhalb C

```
Mensch (SSH / VPN)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  S1  Config-Tool            pv-config.py (on-demand)     │
│      Menüstruktur (whiptail), Parameter lesen/schreiben  │
│      Schnittstelle: JSON-Dateien in config/              │
└──────────────────────┬───────────────────────────────────┘
                       │ config/*.json
                       ▼
┌──────────────────────────────────────────────────────────┐
│  S2  Observer                automation/engine/observer.py │
│      (eigenständiger Prozess, interrupt-fähig)           │
│                                                          │
│      TIER 1: Interrupt (< 1 s)  → Sofort-Schutzaktion   │
│      TIER 2: Daemon (5–30 s)    → ObsState aufbauen     │
│      TIER 3: Cron (1–15 min)    → träge Daten           │
│                                                          │
│      Schnittstelle: RAM-DB  /dev/shm/automation_obs.db   │
└──────────────┬───────────────────────┬───────────────────┘
               │ ObsState (RAM-DB)     │ ALARM (Bypass)
               ▼                       ▼
┌──────────────────────────────┐  ┌────────────────────────┐
│  S3  Decision Engine         │  │  Schutzregel direkt    │
│      (Thread im Observer)    │  │  → Actuator            │
│      Scores, Plausibilität,  │  │  (T>80°C, Überlast,   │
│      Dokumentation           │  │   Frost, …)            │
│                              │  └────────────────────────┘
│  Zyklen: 1 min / 15 min     │
│  Tier-1-Flags → Sofort-Score │
│  Schnittstelle: ActionPlan   │
└──────────────┬───────────────┘
               │ ActionPlan
               ▼
┌──────────────────────────────────────────────────────────┐
│  S4  Actuator  (Thread im Observer, on-demand)           │
│      Aktionsplan ausführen, Wirkung verifizieren,        │
│      Protokoll in Persist-DB (Schicht A: data.db)        │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Schicht S1 — Config-Tool (pv-config.py)

### Zweck
Interaktives Terminal-Menü für den Bediener. Läuft **on-demand** per SSH,
kein Daemon. Kein Web-Frontend (→ Rollenmodell: kein Write-Pfad in B).

### Menüstruktur (Entwurf)

```
PV-Anlage Erlau — Konfiguration
═══════════════════════════════
 1) Batterie-Parameter
 2) E-Auto / Wattpilot
 3) Wärmepumpe (SIK 11 TES)
 4) Heizpatrone
 5) Klimaanlage
 6) Lüftung / Brandschutzklappen
 ─────────────────────
 7) Globale Strategie (Prioritäten, Saisonprofile)
 8) Schutzregeln & Schwellwerte
 9) Status & Diagnose (read-only)
 0) Beenden
```

### Regeln
- Liest und schreibt **ausschließlich** JSON-Dateien in `config/`
- **Kein** Direktzugriff auf Modbus, HTTP-API, DB oder Hardware
- Validierung: Wertebereich, Typprüfung, Plausibilität **beim Schreiben**
- Jede Änderung wird mit Timestamp und Bediener-Info im JSON gespeichert
- Auch über VPN/App nutzbar (SSH-Tunnel), aber immer dasselbe Config-Tool
- **Windows-Zugang:** Fertige Scripts in `scripts/windows/` — Setup-Script richtet
  SSH-Key, SSH-Config (`pv-pi4`) und Windows Terminal Profil automatisch ein.
  Siehe `scripts/windows/README.md` für Details.

### Technologie-Entscheidung (E3 — entschieden)

Verfügbar auf dem Pi **ohne Installation**:

| Bibliothek | Stärke | Schwäche |
|------------|--------|----------|
| `whiptail` (newt 0.52) | Dialog-Boxen, Radio/Check/Input, intuitiv | Kein Python nativ, Subprozess |
| `curses` (2.2, built-in) | Volle Kontrolle, stabile Plattform-API | Viel Boilerplate für Menüs |
| `prompt_toolkit` (3.0.14) | Bereits installiert, Autocomplete, modern | Eher CLI als Menü |

**Entscheidung:** `whiptail` als primäres UI-Backend.

**Begründung:** Menügeführt, intuitiv, Dialog-Boxen für Eingabe/Bestätigung,
Radio-Buttons für Auswahl, Checklisten für Multi-Select. Auf jedem
Debian/Raspbian vorinstalliert. Aufruf aus Python via `subprocess`.
Fallback auf `curses` bei Bedarf (z.B. für Live-Status-Ansichten).

Beispiel-Aufruf:
```python
import subprocess
def whiptail_menu(title, items):
    """items = [('tag', 'beschreibung'), ...]"""
    args = ['whiptail', '--title', title, '--menu', '', '20', '70', '10']
    for tag, desc in items:
        args.extend([tag, desc])
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, result.stderr.strip()  # whiptail gibt auf stderr aus
```

### Config-Dateien (Erweiterung)

| Datei | Inhalt | Existiert |
|-------|--------|-----------|
| `config/battery_control.json` | Batterie SOC-Grenzen, Algorithmen | ✅ ja |
| `config/fritz_config.json` | Fritz!Box-IP, AIN, HP-Leistung | ✅ ja |
| `config/soc_param_matrix.json` | Regelkreis-Parameter (12 Kreise) | ✅ ja |
| `.secrets` | Credentials (FRITZ_USER/PASS, FRONIUS_PASS, etc.) | ✅ ja |

### Config-Schema (Beispiel für ein Device)

```json
{
  "_meta": {
    "device": "heizpatrone",
    "version": 1,
    "changed_at": "2026-02-22T14:30:00",
    "changed_by": "user@ssh"
  },
  "enabled": true,
  "leistung_kw": 2.0,
  "steuerungskanal": "relay",
  "relay_nr": 1,
  "schwellen": {
    "min_ueberschuss_kw": 2.0,
    "temp_max_c": 80,
    "temp_hysterese_aus_c": 78,
    "temp_hysterese_ein_c": 70,
    "temp_ziel_sommer_c": 65,
    "temp_ziel_winter_c": 55,
    "min_pausenzeit_s": 300,
    "min_laufzeit_s": 300
  }
}
```

---

## 4. Schicht S2 — Observer (observer.py)

### Zweck
Ein **eigenständiger Prozess**, der alle Datenquellen nach abgestuften
Prioritäten beobachtet und daraus ein einheitliches `ObsState`-Objekt
aufbaut. Definiert in [BEOBACHTUNGSKONZEPT.md](BEOBACHTUNGSKONZEPT.md).

### 3-Tier-Beobachtungsprioritäten

Nicht alle Daten sind gleich dringend. Der Observer arbeitet auf **drei
Prioritätsebenen**, die unterschiedliche Reaktionszeiten erfordern:

```
┌─────────────────────────────────────────────────────────────────┐
│  Observer-Prozess (eigenständig, interrupt-fähig)               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TIER 1 — INTERRUPT  (< 1 s Reaktionszeit)              │   │
│  │  Sicherheitskritisch, nicht aufschiebbar                │   │
│  │                                                          │   │
│  │  • Übertemperatur (I2C Thermistor, GPIO Edge-Trigger)    │   │
│  │  • Netz-Überlast (Modbus TCP, Schwellenerkennung)        │   │
│  │  • Batterie-Alarm (BMS Flags via Modbus)                 │   │
│  │  • Fenster-offen-Kontakt (Dry Contact → GPIO Interrupt)  │   │
│  │  • Luftqualität außen (wenn Sensor vorhanden)            │   │
│  │                                                          │   │
│  │  → Sofort-Aktion: Bypass direkt zu S4 Actuator           │   │
│  │  → Sofort: Engine-Score beeinflusst (Flag im ObsState)   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TIER 2 — DAEMON  (5–30 s Polling)                      │   │
│  │  Steuerungsrelevant, zeitnah benötigt                   │   │
│  │                                                          │   │
│  │  • PV-Gesamtleistung (Modbus TCP, 5 s)                   │   │
│  │  • Batterie SOC + Leistung (Modbus M124, 5 s)            │   │
│  │  • Netz-Leistung (Modbus, 5 s)                           │   │
│  │  • Wattpilot Status + Leistung (WebSocket, 2 s Push)     │   │
│  │  • Speicher-Temperaturen (I2C, 10 s)                     │   │
│  │  • WP Betriebsstatus (Modbus RTU, 30 s)                  │   │
│  │                                                          │   │
│  │  → ObsState aktualisieren → Engine kann reagieren         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TIER 3 — CRON  (1–15 min Polling)                      │   │
│  │  Träge Daten, Planungshorizont                           │   │
│  │                                                          │   │
│  │  • Fronius HTTP API: SOC_MODE/MIN/MAX Settings (1 min)   │   │
│  │  • Solar-Prognose: Open-Meteo Wolken/GHI (15 min)        │   │
│  │  • Sonnengeometrie: Auf-/Untergang (1× täglich)          │   │
│  │  • WW-Solltemperatur via WP-Modbus (5 min)               │   │
│  │  • SOH, Firmware-Version (1× täglich)                    │   │
│  │                                                          │   │
│  │  → ObsState aktualisieren → Engine nächster Zyklus        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│                       ▼                                         │
│              ┌─────────────────┐                                │
│              │  ObsState        │                               │
│              │  → RAM-DB        │                               │
│              │  (obs.db tmpfs)  │                               │
│              └─────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

### Tier-Zuordnung pro Datenquelle

| Datenquelle | Tier | Intervall | Trigger-Typ | Begründung |
|-------------|------|-----------|-------------|------------|
| I2C Übertemp (MEGA-BAS) | 1 | < 1 s | GPIO Edge / Polling | Schutzregel, Sofort-Aus |
| Netz-Überlast (Modbus) | 1 | 5 s* | Schwellenerkennung | Hauptsicherung 3×40A |
| Batterie BMS Alarm | 1 | 5 s* | Schwellenerkennung | Zellschutz |
| Fenster-Kontakt (Dry Contact) | 1 | < 1 s | GPIO Interrupt | Lüftung sofort anpassen |
| PV-Erzeugung (Modbus M103/M160) | 2 | 5 s | Daemon-Poll | Überschuss-Berechnung |
| Batterie SOC (Modbus M124) | 2 | 5 s | Daemon-Poll | Lade-Algorithmus |
| Netz-Leistung (Modbus M103) | 2 | 5 s | Daemon-Poll | Bezug/Einspeisung |
| Wattpilot (WebSocket) | 2 | 2 s | WebSocket-Push | EV-Laststeuerung |
| Speicher-Temps (I2C) | 2 | 10 s | Daemon-Poll | Heizpatronen-Regelung |
| WP Status (Modbus RTU) | 2 | 30 s | Daemon-Poll | SG-Ready Steuerung |
| Fronius SOC-Settings (HTTP) | 3 | 1 min | Cron-Poll | Konsistenzcheck |
| Solar-Prognose (Open-Meteo) | 3 | 15 min | Cron-Poll | Tagesplanung |
| Sonnengeometrie | 3 | 1× Tag | Cron-Poll | Auf-/Untergangszeiten |
| SOH / Firmware | 3 | 1× Tag | Cron-Poll | Langzeit-Monitoring |

\* Tier 1 nutzt die Tier-2-Daten mit, aber prüft **bei jedem Tier-2-Lauf**
die Schwellen. Zusätzlich: echte GPIO-Interrupts für Kontakte.

### ObsState-Objekt

Das Objekt ist bereits in BEOBACHTUNGSKONZEPT.md §5 definiert. Es wird
**nicht verändert** durch den Observer, sondern als **Snapshot** pro Zyklus
an die RAM-DB geschrieben. Erweiterung um neue Felder jederzeit möglich,
Regeln müssen `None`-sicher sein.

### Wirkung auf Engine-Scores

Tier-1-Ereignisse setzen **Flags** im ObsState, die Engine-Scores sofort
beeinflussen können:

```python
# ObsState-Erweiterung für Tier-1-Flags
'alarm_uebertemp':    bool,   # True → Heizpatrone-Score = 0
'alarm_ueberlast':    bool,   # True → EV-Score auf Drosselung
'alarm_batt_kritisch': bool,  # True → Entladung-Score = 0
'alarm_frost':        bool,   # True → Lüftung-Score = Minimum
'fenster_offen':      bool,   # True → Lüftung-Score anpassen
```

Die Engine liest diese Flags im nächsten Zyklus und passt Scores an —
aber Tier-1-Sofort-Aktionen warten **nicht** auf die Engine.

### Determinierende Schwellenprüfungen (Observer-Bypass zu S4)

Diese Prüfungen überspringen die Decision Engine — sie sind **nicht
verhandelbar**, **nicht score-basiert** und dürfen **nie deaktiviert** werden:

| Schwelle | Bedingung | Sofort-Aktion |
|----------|-----------|---------------|
| Übertemperatur Speicher | `ww_temp_c ≥ 80` | Heizpatrone AUS |
| Überlast Netz | `grid_bezug_w > 26000` | Wattpilot auf 1.4 kW |
| Überlast Warnung | `grid_bezug_w > 24000` | Wattpilot drosseln |
| Frost | `aussen_temp_c < -5` | Lüftung Minimum, Klappen ZU |
| Batterie kritisch | `batt_soc_pct < 5` | Stop Entladung |
| Batterie Übertemp | `batt_temp_c > 45` | Stop Ladung |
| WP Kompressor | `wp_laufzeit_heute == 0 && uhrzeit > 12` | Pflichtlauf |

### Recycling aus bestehendem Code

- `collector.py` → Modbus-TCP-Polling (F1/F2/F3) — **direkt nutzbar**
- `wattpilot_collector.py` → WebSocket-Anbindung — **direkt nutzbar**
- `solar_forecast.py` → Prognose-Aufbau — **direkt nutzbar**
- `fronius_api.py` → HTTP-API lesend — **direkt nutzbar**

Diese bleiben als eigenständige Module bestehen. Der Observer **importiert**
sie, anstatt die Logik zu duplizieren.

---

## 5. Schicht S3 — Decision Engine (engine.py)

### Zweck
Aus dem ObsState und den Parameter-Matrizen einen **begründeten Aktionsplan**
erzeugen. Score-basiert, plausibilisiert, dokumentiert.

### Entscheidungszyklen (E4 — adaptiv nach Priorität)

Die Engine läuft **nicht in festem Takt**, sondern adaptiv nach Priorität:

| Auslöser | Engine-Reaktion | Typische Latenz |
|----------|----------------|-----------------|
| Tier-1-Alarm (Flag in RAM-DB) | Sofort-Score-Override, nächster Engine-Lauf | < 5 s |
| Tier-2-Update (ObsState geändert) | Engine prüft Scores im 1-min-Takt | 1 min |
| Tier-3-Update (Prognose, Settings) | Engine nutzt nächsten turnusmäßigen Lauf | 15 min |

Konkret:
- **Schneller Zyklus** (1 min): Score-Berechnung für alle Aktoren,
  Kapazitätsverteilung, Plausibilitätsprüfung. Nutzt Tier-2-Daten.
- **Langsamer Zyklus** (15 min): Strategische Entscheidungen
  (SOC-Tagesplanung, Prognose-basiert). Nutzt Tier-3-Daten.
- **Sofort** (< 5 s): Wenn Observer ein Tier-1-Flag setzt, prüft die
  Engine beim nächsten Durchlauf ob Score-Anpassungen nötig sind
  (z.B. EV-Score → 0 bei Überlast).

Die Tier-1-Sofort-Aktionen (EV drosseln) laufen
**unabhängig** von der Engine direkt im Observer → Actuator Bypass.

> **HP-Notaus — Architekturentscheidung (2026-03-01):**
> Der HP-Entladeschutz läuft bewusst im **Engine fast-cycle (60 s)**,
> nicht im Observer (Tier-1, 10 s). Begründung: Die HP ist ein thermischer
> Verbraucher — 1–5 Minuten Reaktionszeit sind akzeptabel. Der Notaus ist
> **immer aktiv** (auch bei `aktiv: false`) und nutzt SOC-abhängige
> Schwellen: SOC ≥ 90% toleriert bis −1000 W, SOC < 90% → sofort AUS.
> Konfigurierbar via `notaus_soc_schwelle_pct` und `notaus_entladung_hochsoc_w`
> in `config/soc_param_matrix.json`.

### Entscheidungsablauf pro Zyklus

```
Für jeden registrierten Aktor:
│
├── 1. Relevanzprüfung
│      Ist der Aktor enabled? Ist die Vorbedingung erfüllt?
│
├── 2. Score-Berechnung (0.0 – 1.0)
│      Eingaben: ObsState-Felder + Parameter-Matrix des Aktors
│      Ergebnis: Dringlichkeitsscore
│
├── 3. Prioritäts-Ranking
│      Alle Aktoren nach Score sortieren
│      Kapazitätsgrenze beachten (Netz-Budget, PV-Überschuss)
│
├── 4. Plausibilitätsprüfung
│      Ist die geplante Aktion konsistent?
│      Widerspricht sie einer Schutzregel?
│      Ist die Abweichung zum Ist-Zustand sinnvoll?
│
├── 5. Dokumentation
│      Warum diese Entscheidung? (Score, Eingabewerte, Regel)
│      → ActionPlan-Eintrag mit Begründung
│
└── 6. Ausgabe: ActionPlan
```

### ActionPlan-Datenstruktur

```python
@dataclass
class Action:
    aktor: str          # z.B. 'batterie', 'wattpilot', 'heizpatrone'
    kommando: str       # z.B. 'set_soc_min', 'set_power', 'relay_on'
    wert: any           # z.B. 5, 2000, True
    score: float        # 0.0 – 1.0
    grund: str          # Menschenlesbarer Entscheidungsgrund
    prioritaet: int     # 1 = höchste
    vorher: any         # Aktueller Ist-Wert (aus ObsState)

ActionPlan = list[Action]
```

### Aktor-Basis-Interface (AktorBase)

Jeder Aktor implementiert das `AktorBase`-Interface. Die Engine kennt nur
das Interface, nicht die Hardware:

```python
class AktorBase:
    """Basis-Interface für alle steuerbaren Geräte."""

    name: str

    def ausfuehren(self, kommando: str, wert: any) -> dict:
        """Kommando ausführen. Return: Ergebnis-Dict."""
        ...

    def verifiziere(self, kommando: str, wert: any) -> bool:
        """Nach Ausführung: Hat die Aktion gewirkt?"""
        ...
```

Die Score-Berechnung (`bewerte()`) und Aktionserzeugung (`erzeuge_aktionen()`)
sind Methoden der **Regeln** (`Regel`-Basisklasse in `regeln/basis.py`),
nicht der Aktoren.

### Aktor-Plugins (Ist-Stand)

| Plugin | Aktor | Steuerungskanal | Status |
|--------|-------|-----------------|--------|
| `aktor_batterie.py` | 2× BYD HVS 20.48 kWh | Modbus TCP + HTTP API | ✅ Produktiv |
| `aktor_fritzdect.py` | Fritz!DECT Smart-Plug (Heizpatrone 2 kW) | Fritz!Box AHA-HTTP-API | ✅ Produktiv |
| `aktor_wattpilot.py` | E-Auto Wallbox | WebSocket CMD | ⚠️ Stub (nur Logging) |

### Kapazitätsverteilung (Budget-Algorithmus)

Die Engine verteilt den verfügbaren PV-Überschuss nach Priorität:

```
verfuegbar_w = pv_total_w - house_load_w

Prioritätsreihenfolge (konfigurierbar in automation_global.json):
  1. Schutzregeln          (nicht verhandelbar, bereits in S2)
  2. Batterie-Laden        (Score aus Prognose + SOC + Tageszeit)
  3. E-Auto                (Score aus Urgency + Überschuss)
  4. Wärmepumpe SG-Ready   (Score aus WW-Temp + Überschuss)
  5. Heizpatrone            (Score aus WW-Temp + Überschuss)
  6. Klimaanlage            (Score aus Heizhaus-Temperatur + Tageszeit/Fallback)

Jeder Aktor bekommt nur soviel Budget wie bei seinem Rang noch übrig ist.
```

---

## 6. Schicht S4 — Actuator (actuator.py)

### Zweck
Aktionsplan **ausführen**, Wirkung **verifizieren**, Ergebnis **protokollieren**.

### Ablauf pro Aktion

```
Für jede Aktion im ActionPlan (nach Priorität sortiert):
│
├── 1. Pre-Check
│      Ist der Aktor erreichbar? Ist die Aktion noch gültig?
│      (ObsState kann sich seit Engine-Lauf geändert haben)
│
├── 2. Ausführen
│      Dispatch an richtigen Kanal (Modbus, WS, Relay, …)
│      Retry-Logik (2× mit 1.5s Delay — bewährt aus InverterControl)
│
├── 3. Wirkungsprüfung (Read-Back)
│      Nach 2–5 s: Hat sich der Ist-Wert geändert?
│      Erwarteter Wert vs. tatsächlicher Wert
│
├── 4. Ergebnis bewerten
│      ✅ Erfolg → Log
│      ⚠️ Teilweise → Log + Warnung
│      ❌ Fehlgeschlagen → Log + Alarm + ggf. Rollback
│
└── 5. Protokoll → DB (Schicht A)
│      Tabelle: automation_log
│      Felder: ts, aktor, kommando, wert_vorher, wert_nachher,
│              score, grund, ergebnis, dauer_ms
```

### Steuerungskanal-Dispatcher

| Kanal | Zielsystem | Tool |
|-------|-----------|------|
| `modbus_tcp` | Fronius Gen24 (F1/F2/F3) | `battery_control.py` → `ModbusClient` |
| `http_api` | Fronius SOC/Mode Settings | `fronius_api.py` → `BatteryConfig` |
| `websocket` | Wattpilot E-Auto | `wattpilot_api.py` (Stub) |
| `fritzdect` | Fritz!Box AHA-HTTP-API | `aktor_fritzdect.py` (Heizpatrone) |

---

## 7. Rollenmodell — Wer darf was?

```
┌─────────┬────────────────────────────────────────────────────┐
│ Bereich           │ Rollenmodell                            │
├─────────┼────────────────────────────────────────────────────┤
│ S1-S4             │ C — Regeln, Logik, Aktorik, Audit-Log   │
├─────────┼────────────────────────────────────────────────────┤
│ Collector-Pipeline│ A — liefert Rohdaten und Aggregationen  │
├─────────┼────────────────────────────────────────────────────┤
│ Web-API          │ B — liest ObsState, ActionPlan, Logs     │
│                  │     aus DB/shared State. Kein Write-Pfad │
├─────────┼────────────────────────────────────────────────────┤
│ Diagnos          │ D — liest Health, Integritaet und Parity │
│                  │     und meldet ohne technische Writes     │
├─────────┼────────────────────────────────────────────────────┤
│ Datenlayer       │ gemeinsame SQLite-Plattform unter A/B/C/D│
└─────────┴────────────────────────────────────────────────────┘
```

**Leserichtung B → C (Dashboard + API):**
Die Web-API (Schicht B) zeigt Automations-Daten an, indem sie **echte Daten**
aus der DB liest:

| API-Endpunkt | Quelle | Daten |
|--------------|--------|-------|
| `/api/battery_status` → `soc_switches` | `automation_log` | Vergangene SOC-Umschaltungen (letzte 24 h) |
| `/api/battery_status` → `last_engine_action` | `automation_log` | Letzte Engine-Aktion (Kommando, Grund, Ergebnis) |
| `/api/battery_status` → `last_soc_switch` | `automation_log` / Fallback `battery_control_log` | Letzte SOC_MIN/MAX-Änderung |
| `/api/battery_status` → `scheduler` | `battery_scheduler_state.json` | Phasen-Flags (Legacy-Kompatibilität) |

Alle angezeigten Umschaltungen sind **echte
Aktionen** aus dem `automation_log` mit Zeitstempel, Kommando, Wert und
menschenlesbarer Begründung.

**Datenfluss für SOC-Anzeige im Dashboard:**
```
┌─────────────────┐   liest    ┌────────────┐   scored    ┌──────────┐
│ soc_param_matrix│ ─────────> │   Engine   │ ─────────> │ Actuator │
│ (.json Config)  │            │  6 Regeln  │            │ Dispatch │
└─────────────────┘            └────────────┘            └────┬─────┘
                                                              │ loggt
                                                              v
                                                     ┌──────────────┐
                                                     │automation_log│
                                                     │  (data.db)   │
                                                     └──────┬───────┘
                                                            │ liest
                                                            v
                                                    ┌───────────────┐
                                                    │ Web-API (B)   │
                                                    │ /api/battery_ │
                                                    │ status        │
                                                    └───────────────┘
```

Kein Write-Pfad von B nach C. Keine Steuerung über das Web-Dashboard.

**Strikte Trennung (E6 — entschieden):**
- B darf **keinen** Override-Request an C stellen
- Manuelle Eingriffe erfolgen **ausschließlich** über das Config-Tool (S1)
- Auch mobil: SSH-Tunnel über VPN → Config-Tool → gleicher Pfad
- B zeigt an, C entscheidet, A speichert — keine Ausnahmen

---

## 8. Prozess-Modell (E1 — entschieden)

### Architektur: Ein Observer-Hauptprozess mit Ableger-Threads

Der Observer ist ein **eigenständiger Prozess** (kein Thread in einem
Sammel-Daemon), weil er interrupt-fähig sein muss (Tier-1-Alarme).
Engine und Actuator sind **Ableger** (Threads/Callbacks) des Observer-Prozesses:

```
automation_daemon.py  (pv-automation.service, systemd)
  │
  ├── Tier 1: Interrupt-Handler  (GPIO-Callbacks, < 1 s)
  │     └── Alarm erkannt → Sofort-Aktion via Actuator
  │
  ├── Tier 2: Daemon-Loop  (5–30 s Polling-Threads)
  │     ├── Modbus-TCP-Thread (5 s)
  │     ├── WebSocket-Listener (Wattpilot, permanent)
  │     ├── I2C-Polling-Thread (10 s)
  │     └── Modbus-RTU-Thread (30 s, WP)
  │     └── → ObsState-Update in RAM-DB
  │
  ├── Engine-Loop  (adaptiv: 1 min normal / 15 min träge Daten)
  │     ├── Liest ObsState aus RAM-DB
  │     ├── Liest Parameter-Matrizen aus config/*.json
  │     ├── Score-Berechnung → ActionPlan
  │     └── Tier-1-Flags → Score-Override (sofortige Beeinflussung)
  │
  ├── Actuator  (on-demand, getriggert durch Engine oder Tier-1)
  │     └── Ausführung → Read-Back → Protokoll in Persist-DB
  │
  ├── Sunset-Erkennung  (is_day True→False Transition)
  │     └── EventNotifier.sende_sunset_bericht() → E-Mail (1×/Tag)
  │
  └── Tier 3: Cron-Ableger  (1 min / 15 min Timer-Threads)
        ├── Fronius-HTTP-API (1 min)
        ├── Solar-Prognose (15 min)
        └── Tägliche Routinen (SOH, Geometrie)
```

### Begründung

- **Ein Prozess** (nicht drei): Einfachere IPC, gemeinsamer Speicher,
  ein PID-File, ein systemd-Service, ein Watchdog
- **Interrupt-fähig**: GPIO-Callbacks laufen im Hauptprozess-Kontext
  und können den Actuator direkt ansprechen (kein IPC-Umweg)
- **Ableger-Threads** statt Cron-Jobs: Vermeidet Cron-Startoverhead,
  ermöglicht sauberes Shutdown-Handling via Signale
- **Shared RAM-DB**: Alle Threads schreiben/lesen über SQLite im tmpfs
  (obs.db) — thread-safe über WAL-Modus

### Watchdog & Überwachung

```
systemd → automation_observer.service
            ├── WatchdogSec=60  (systemd native)
            ├── Restart=on-failure
            └── monitor.sh prüft PID + Heartbeat in RAM-DB
```

---

## 9. Regelkreise — Übersicht

### 8 aktive Regeln in `automation/engine/regeln/` (Stand: 2026-03-08)

| # | Klasse | Modul | Zyklus | Priorität | Funktion |
|---|--------|-------|--------|-----------|----------|
| 1 | `RegelSlsSchutz` | schutz.py | fast | P1 Sicherheit | SLS-Überstromschutz: 3×35A/Phase Überwachung |
| 2 | `RegelKomfortReset` | soc_steuerung.py | mixed | P2 Steuerung | Täglicher Reset auf 25–75% SOC-Bereich, Früh-Reset mit Hysterese (K4) |
| 3 | `RegelMorgenSocMin` | soc_steuerung.py | mixed | P2 Steuerung | SOC_MIN-Öffnung basierend auf Sunrise+1h PV-Prognose, Hold-Mode, konfigurierbarer Vorlauf |
| 4 | `RegelNachmittagSocMax` | soc_steuerung.py | mixed | P2 Steuerung | SOC_MAX→100% via Clear-Sky-Peak + Power-Threshold |
| 5 | `RegelZellausgleich` | optimierung.py | strategic | P3 Wartung | Monatlicher BYD-Zellausgleich (Vollzyklus) |
| 6 | `RegelForecastPlausi` | optimierung.py | strategic | P3 Optimierung | IST/SOLL-Abweichung >30% → SOC-Strategie anpassen |
| 7 | `RegelWattpilotBattSchutz` | geraete.py | fast | P1 Sicherheit | 3-stufiger Batterieschutz während EV-Ladung |
| 8 | `RegelHeizpatrone` | geraete.py | fast | P2 Steuerung | 6-Phasen Forecast-gesteuerte Burst-Strategie für 2 kW HP via Fritz!DECT |

**Entfernt (2026-03-07, GEN24 DC-DC HW-Limit):**
`RegelSocSchutz`, `RegelTempSchutz`, `RegelAbendEntladerate`, `RegelLaderateDynamisch`
→ Software-Ratenlimits (InWRte/OutWRte/StorCtl_Mod) waren wirkungslos. Steuerung
erfolgt jetzt ausschließlich über SOC_MIN/SOC_MAX via Fronius HTTP-API.

### Collector-Subsystem in `automation/engine/collectors/`

| Klasse | Modul | Funktion |
|--------|-------|----------|
| `DataCollector` | data_collector.py | Liest Collector-DB + Modbus + HTTP API → ObsState |
| `BatteryCollector` | battery_collector.py | Direktes Modbus/HTTP-Polling (für Observer standalone) |
| `ForecastCollector` | forecast_collector.py | Trigger-basierte Solarprognose |
| `Tier1Checker` | tier1_checker.py | Deterministische Schwellenprüfungen (Safety-Bypass) |

### Querschnitts-Module in `automation/engine/`

| Modul | Funktion |
|-------|----------|
| `regeln/soc_extern.py` | SOC-Extern-Toleranz: Erkennt manuell geänderte SOC-Werte (Fronius App) und stellt 30-min Toleranzperiode bereit. Registrierung erfolgt nach Actuator-Erfolg (K2). |
| `event_notifier.py` | Täglicher Sunset-Bericht per E-Mail, Alarm-Benachrichtigungen. Integriert in `automation_daemon.py` als Observer-Callback. |
| `schaltlog.py` | Einheitliches Schalt-/Extern-Logging für alle Regeln → `automation_log` in Persist-DB. |

---

## 10. Datenhaltung — 2 Datenbanken (E2, E5 — entschieden)

Die Automation nutzt **zwei getrennte SQLite-Datenbanken** mit
unterschiedlichem Lebenszyklus:

### 10.1 RAM-DB: Beobachtung + Parameter (schnell, flüchtig)

**Pfad:** `/dev/shm/automation_obs.db` (tmpfs, wie bestehende `fronius_data.db`)

**Zweck:** Observer schreibt, Engine liest — schnelle Schreib-/Lesezyklen
ohne SD-Karten-Verschleiß. Enthält den **aktuellen Zustand** des Systems.

```sql
-- Aktueller ObsState (immer nur 1 Zeile, wird überschrieben)
CREATE TABLE obs_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    ts          TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    tier1_flags TEXT DEFAULT '{}'
);

-- ObsState-History (Ring-Puffer, z.B. letzte 1000 Snapshots)
CREATE TABLE obs_history (
    ts          TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL
);

-- Parameter-Matrix-Spiegel (Config-Tool schreibt JSON, Observer lädt hier)
CREATE TABLE param_matrix (
    device      TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    loaded_at   TEXT NOT NULL
);

-- Engine-AktionsPlan (letzter Zyklus, für Actuator und Dashboard)
CREATE TABLE action_plan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zyklus_id   TEXT NOT NULL,
    ts          TEXT NOT NULL,
    plan_json   TEXT NOT NULL
);

-- Heartbeat (Watchdog-Prüfung)
CREATE TABLE heartbeat (
    component   TEXT PRIMARY KEY,
    ts          TEXT NOT NULL
);
```

**WAL-Modus** für parallelen Lese-/Schreibzugriff (Observer-Threads +
Engine-Thread + Web-API lesend).

### 10.2 Persist-DB: Protokoll + Audit (langlebig, SD-Karte)

**Pfad:** `data.db` (bestehende Datenbank, neue Tabellen)

**Zweck:** Alles, was einen Stromausfall überleben muss. Für Analyse,
Dashboard-Historien und Audit.

```sql
-- Automations-Protokoll (alle Aktoren, alle Entscheidungen)
CREATE TABLE automation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,           -- ISO-8601
    aktor       TEXT NOT NULL,           -- 'batterie', 'wattpilot', ...
    kommando    TEXT NOT NULL,           -- 'set_soc_min', 'relay_on', ...
    wert_vorher TEXT,                    -- JSON-enkodierter Vorher-Wert
    wert_nachher TEXT,                   -- JSON-enkodierter Nachher-Wert
    score       REAL,                    -- 0.0–1.0
    grund       TEXT,                    -- Menschenlesbar
    ergebnis    TEXT DEFAULT 'pending',  -- 'ok', 'failed', 'partial', 'pending'
    dauer_ms    INTEGER,                 -- Ausführungsdauer
    zyklus_id   TEXT                     -- UUID pro Engine-Zyklus
);

-- ObsState-Snapshots (komprimiert, für langfristige Analyse)
CREATE TABLE obs_state_snapshot (
    ts          TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL
);
```

### 10.3 Backup-Strategie gegen Ausfälle

| Datenbank | Medium | Verlust bei Stromausfall | Backup |
|-----------|--------|--------------------------|--------|
| `automation_obs.db` | tmpfs (RAM) | Letzte Sekunden. Kein Problem — Observer baut innerhalb von 30 s neu auf | Snapshot in Persist-DB (alle 5 min) |
| `data.db` (automation_log) | SD-Karte | Keine (persistent) | Bestehende `backup_db_gfs.sh` |
| `config/*.json` | SD-Karte | Keine (persistent) | Git-versioniert |

**Wiederanlauf nach Stromausfall:**
1. systemd startet `automation_observer.service`
2. Observer prüft: RAM-DB existiert? → Nein → `CREATE` + Schema-Init
3. Tier-2-Loop füllt ObsState innerhalb von 30 s auf
4. Engine wartet auf erstes vollständiges ObsState → dann erster Zyklus
5. Actuator setzt Komfort-Defaults (wie bisher `_apply_comfort_defaults()`)

Die bestehende Tabelle `battery_control_log` ist Legacy und wird nicht mehr aktiv befüllt.

---

## 11. Offene Punkte

| Thema | Status | Detail |
|-------|--------|--------|
| AktorWattpilot | Stub | Nur Logging, keine echte EV-Steuerung |
| WW-Temperatur-Sensor | Nicht vorhanden | `ww_temp_c` in ObsState immer `None` — HP-Übertemperaturschutz inaktiv |
| Batterie-Temperaturen | Teilweise | `batt_temp_c` wird nur im Observer-Pfad (BatteryCollector) befüllt, nicht im Daemon-Pfad (DataCollector) |
| `ev_eco_mode` | Nicht befüllt | ObsState-Feld vorhanden, aber DataCollector setzt es nicht |

---

## 12. Architektur-Entscheidungen (abgeschlossen)

| Nr. | Frage | Entscheidung | Begründung |
|-----|-------|--------------|------------|
| E1 | Observer als Thread oder eigener Prozess? | **Eigener Prozess** mit Ableger-Threads | Interrupt-fähig (GPIO), sauberer Signal-Handling, ein systemd-Service. Engine + Actuator als Threads darin. Siehe §8 |
| E2 | ObsState-Transport? | **RAM-DB** (SQLite tmpfs) | Eigene `automation_obs.db` in `/dev/shm/`. Thread-safe via WAL. Persist-Snapshots alle 5 min. Siehe §10 |
| E3 | Config-Tool Technologie? | **whiptail** (+ curses Fallback) | Intuitiv, menügeführt, Dialog-Boxen, auf Pi vorinstalliert. Kein pip-Install. Siehe §3 |
| E4 | Engine-Zyklus? | **Adaptiv nach Tier** | Tier-1: Interrupt (< 1 s). Tier-2: Daemon 5–30 s → Engine reagiert im nächsten 1-min-Zyklus. Tier-3: Cron 1–15 min. Siehe §4 |
| E5 | automation_log Speicherort? | **Persist-DB** (data.db) | Muss Stromausfall überleben. RAM-DB nur für flüchtigen Zustand. Siehe §10 |
| E6 | Darf B Override-Requests an C senden? | **Nein — strikt getrennt** | B = Monitoring/Analyse. Steuerung nur über Config-Tool (S1) per SSH, auch mobil über VPN. Siehe §7 |

---

## 13. Verwandte Dokumente

| Dokument | Relevanz |
|----------|----------|
| [ABCD_ROLLENMODELL.md](../system/ABCD_ROLLENMODELL.md) | Rollen A/B/C/D, Grenzen und Verantwortungen |
| [DIAGNOS_KONZEPT.md](../diagnos/DIAGNOS_KONZEPT.md) | Zielbild fuer Health, Integritaet und Parity |
| [BEOBACHTUNGSKONZEPT.md](BEOBACHTUNGSKONZEPT.md) | ObsState-Definition, Datenkanäle, Prioritäten |
| [PARAMETER_MATRIZEN.md](PARAMETER_MATRIZEN.md) | Erzeuger/Speicher/Verbraucher/Netz-Matrizen |
| [BATTERIE_STRATEGIEN.md](BATTERIE_STRATEGIEN.md) | Strategien A–F, Kontroll-Matrix |
| [BATTERY_ALGORITHM.md](BATTERY_ALGORITHM.md) | Algorithmus-Details (Morgen/Nachmittag/Nacht) |
| [SCHUTZREGELN.md](SCHUTZREGELN.md) | Determinierende Schutzregeln |
| [automation/STRATEGIEN.md](../automation/STRATEGIEN.md) | Saisonale Strategien (WP, Heizpatrone, Klima) |
| [automation/TODO.md](../automation/TODO.md) | Hardware-Phasen (0–5) |

---

*Letzte Aktualisierung: 2026-03-06 (12 Regelkreise, Tier-1 SOC-Recovery mit Hardware-Sync, BMS-Live-SOH, E-Mail-Benachrichtigungen, Sunset-Tagesbericht, Schaltlog-Zusammenfassung)*
