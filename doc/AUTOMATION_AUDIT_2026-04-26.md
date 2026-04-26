# Automation-Audit — Tiefenprüfung 2026-04-26

> **Auftrag:** Tiefenprüfung der Automation. Architektur, Bedingungsgefüge,
> pv-config-Parametermatrix, Namenskonsistenz, Doku-Realitätsbezug,
> SOC-Grenzen-Steuerbox, generelle Respekt-Logik.
> **Stand:** 26. April 2026 · **Branch:** `main` · **Working Tree:**
> uncommitted Änderungen in `automation/engine/operator_overrides.py`,
> `automation/engine/regeln/geraete.py` (= „Korrektur von gestern"),
> neue, unversionierte Datei `HP_TOGGLE_OVERRIDE_FLOW.md`.

---

## 0 · Executive Summary

Das System ist **funktional robust und produktiv stabil**, leidet aber an
*struktureller Inkonsistenz*, die jede Erweiterung riskant macht. Drei
Wurzelursachen erklären das Bauchgefühl des Users:

1. **Drei parallele Respekt-Mechanismen** für externe Schaltungen — nur
   einer (HP/Klima) ist wirklich aktiv. Wattpilot und Batterie-Modi haben
   gar keine Erkennung. Die Korrektur von gestern hat **einen Spezialfall**
   geheilt, aber das Asymmetrie-Problem nicht angefasst.
2. **Drei Quellen von Default-Werten** (Code-Default, Matrix-Wert,
   Doku-Wert) — bei mindestens drei Parametern divergieren sie.
3. **Hartcodierte Registrierung** von Regeln/Aktoren plus dezentralisierte
   Modbus-Register-Adressen — jede neue Regel berührt 3–5 Dateien.

Zusätzlich: Die SOC-Grenzen-Steuerbox-Korrektur wirkt nicht, weil der
Fehler in einem `LOG.debug()` verschluckt wird *und* weil im Fronius-
`SOC_MODE=auto` die HTTP-API stillschweigend unwirksam ist.

| Kategorie                              | Status | Bemerkung                              |
|----------------------------------------|--------|----------------------------------------|
| Architektur Daten-/Kontrollfluss       | 🟢 ok   | Schichten sauber, aber Plugin-Punkte fehlen |
| Bedingungsgefüge HP/SOC/WP             | 🟡 fragil | Phasen-If-Kette, Score-Mehrdeutigkeit |
| Respekt-Logik (extern)                 | 🔴 inkonsistent | Asymmetrie EIN↔AUS, fehlt für WP/Batt |
| pv-config Parametermatrix              | 🟡 lückenhaft | ~40 Parameter nur via JSON edit |
| Namenskonsistenz                       | 🟡 mittel | `hp_*` vs `heizpatrone_*`, `_a` vs `_w` |
| Doku ↔ Realität                        | 🟡 mittel | 19 Mismatches, davon 4 kritisch        |
| SOC-Grenzen Steuerbox                  | 🔴 defekt | Silent Failure + Mode-Trap            |

Der Bericht endet mit einer **priorisierten Roadmap** und einer
Entscheidungsmatrix für das weitere Vorgehen (§9).

---

## 1 · Architektur (Code-Schichten & Datenfluss)

### 1.1 Schichten-Modell (Soll-Zustand)

```
S1  pv-config.py            (CLI/whiptail, on-demand)
       └─→ config/*.json    (atomic write-temp+rename, SIGHUP an Daemon)
S2  observer.py + collectors/   (Tier-1 Bypass + Tier-2/3 ObsState)
       └─→ /dev/shm/automation_obs.db    (RAM-DB, WAL)
S3  engine.py + regeln/     (Score-basierte Auswertung)
       └─→ ActionPlan (list[dict])
S4  actuator.py + aktoren/  (Ausführung + Verifikation + Dedup)
       └─→ automation_log (data.db, persistent)
```

Der Daemon ([automation/engine/automation_daemon.py](automation/engine/automation_daemon.py))
orchestriert S2–S4 in einem Prozess (systemd: `pv-automation.service`).
S1 ist separate on-demand CLI mit SIGHUP-Reload.

**Bewertung:** Sauber. Tier-1-Bypass ([automation/engine/observer.py](automation/engine/observer.py))
greift an der Engine vorbei direkt zum Actuator — das ist eine
Architektur-Sicherheit, kein Bug.

### 1.2 Schwachstellen der Schicht-Grenzen

| # | Stelle | Problem |
|---|--------|---------|
| A1 | [engine.py#L153-L172](automation/engine/engine.py) `_register_default_regeln()` | 17 Regeln hartcodiert importiert/instanziiert. Neue Regel = `engine.py` ändern. |
| A2 | [actuator.py#L120-L127](automation/engine/actuator.py) `_register_default_aktoren()` | 4 Aktoren hartcodiert. Plugin-Hook `registriere_aktor()` existiert, aber Defaults nicht aus Konfig. |
| A3 | [collectors/data_collector.py](automation/engine/collectors/data_collector.py) | Modbus-Register-Adressen verteilt. Keine zentrale Register-Map. |
| A4 | [actuator.py#L47-L50](automation/engine/actuator.py) `DEDUP_INTERVALL_S=45`, `OSCILLATION_WINDOW_S=20*60` | Dedup-Schwellen hartcodiert, nicht in Matrix. |
| A5 | [automation_daemon.py#L48-L50](automation/engine/automation_daemon.py) `FAST_INTERVAL=60`, `STRATEGIC_INTERVAL=900` | Zyklus-Intervalle hartcodiert. |

→ **Erweiterungs-Kosten heute:** Eine neue Regel braucht typisch **3–5
Datei-Änderungen** (Regel-Klasse + `engine.py` + ggf. `aktor_*.py`-Kommando
+ pv-config-UI + Doku). Mit Plugin-Pattern könnten es **2** sein
(Regel-Klasse + Matrix-JSON).

---

## 2 · Bedingungsgefüge — wo die Logik fragil wird

### 2.1 Die 6-Phasen-Kette der Heizpatrone

[automation/engine/regeln/geraete.py#L137-L330](automation/engine/regeln/geraete.py)
implementiert den HP-Schaltbetrieb als **6 Phasen** (Morgen-Drain,
Vormittag, Nulleinspeiser, Mittag-Burst, Nachmittag, Abend-Nachtlade).
Diese Phasen sind als **lineare if/elif-Kette** mit teilweise
überlappenden Zeitfenstern modelliert (`sunrise±1h` vs. `06:00–12:00`).

**Risiken:**
- Bei früher Sonnenaufgangszeit (Sommer) überlappen Phase 0 und 1.
- Notaus-Bedingungen (`ww_temp_c >= 78` ODER `soc <= 7`) sind **nicht** als
  separate Schutz-Regel gekennzeichnet — der Engine-Code unterscheidet
  Schutz/Optimierung über den Namens-Substring `'schutz'`. `RegelHeizpatrone`
  erfüllt das nicht und könnte gegen eine andere Optimierungs-Regel
  „verlieren".
- `_warte_auf_engine_aus`-Flag ist State, der über Zyklen leben muss —
  aber das Objekt ist **Singleton in der Engine** und überlebt
  Daemon-Neustarts nicht. Nach Restart gilt jeder externe Schaltvorgang
  bis zum ersten Engine-Eingriff potentiell als „extern".

**Empfehlung:** State-Machine statt If-Kette; Notaus als separate Klasse
`RegelHeizpatroneSchutz`; Persistenz des Phasen-State in der RAM-DB.

### 2.2 SOC-Steuerung: Score-Multiplikatoren kollidieren

| Regel | Multiplikator | Trigger |
|-------|---------------|---------|
| `RegelMorgenSocMin` | × 1.3 bei SOC nahe MIN ([soc_steuerung.py#L244-L390](automation/engine/regeln/soc_steuerung.py)) |
| `RegelNachmittagSocMax` | × 1.5 bei schlechtem Forecast ([soc_steuerung.py#L393-L585](automation/engine/regeln/soc_steuerung.py)) |
| `RegelKomfortReset` | × 1.0 nachts ([soc_steuerung.py#L585-L900](automation/engine/regeln/soc_steuerung.py)) |

Bei früher Sonne kann Morgen-Min und Komfort-Reset zeitlich überlappen.
Es gibt **keine explizite Priorisierungs-Doku**, nur den emergenten
Score-Vergleich.

### 2.3 Hartcodierte vs. matrix-basierte Schwellen

| Datei | Konstante | Wert | Sollte in Matrix |
|-------|-----------|------|------------------|
| [regeln/geraete.py#L84](automation/engine/regeln/geraete.py) | `ev_leistung_schwelle_w` Default | `2000` (Code) vs. `5000` (Matrix) | ⚠️ Mismatch |
| [regeln/geraete.py#L557, L761, L966](automation/engine/regeln/geraete.py) | `extern_respekt_s` Default | `3600` (Code) vs. `1800` (Doku) | ⚠️ Mismatch |
| [regeln/geraete.py#L1455, L1502](automation/engine/regeln/geraete.py) | `extern_respekt_s` (Klima) Default | `1800` | ⚠️ Asymmetrie zu HP |
| [regeln/waermepumpe.py#L211](automation/engine/regeln/waermepumpe.py) | `start_h` (ww_absenkung) | `23` (Code) vs. `22` (Matrix) | ⚠️ Mismatch |
| [regeln/waermepumpe.py#L39-L42](automation/engine/regeln/waermepumpe.py) | `WP_HEIZ_STD_C=37`, `WP_WW_STD_C=57`, `_MAX_C=42/62` | hartcodiert | empfohlen |

→ **Diagnose:** Code-Defaults sind selten kritisch (Matrix überschreibt
sie in Produktion), aber sie zeigen **Drift** und sind die Quelle der
„jede Korrektur stört" Wahrnehmung: Eine Doku-Konvention wird gepflegt,
ein Code-Default vergessen, ein Matrix-Wert geändert.

---

## 3 · Die Respekt-Logik — Kernbefund

### 3.1 Drei Mechanismen, kein gemeinsames Konzept

```
┌──────────────────────────────────────────────────────────────────┐
│ Ebene 1: Regel-Veto (geraete.py)                                  │
│ • _extern_aus_ts / _extern_ein_ts pro Geräte-Regel               │
│ • bewerte() liefert Score = 0 bei aktivem Respekt                 │
│ • implementiert: HP, Klima                                        │
│ • NICHT implementiert: Wattpilot, Batterie-Modus                  │
├──────────────────────────────────────────────────────────────────┤
│ Ebene 2: SOC-Tracker (soc_extern.py)                              │
│ • SocExternTracker (Klasse) für SOC_MIN/MAX-Werte                │
│ • Wert-Vergleich + Grace-Period 300s                              │
│ • implementiert: nur Batterie SOC-Grenzen                         │
├──────────────────────────────────────────────────────────────────┤
│ Ebene 3: Operator-Overrides (operator_overrides.py)               │
│ • DB-getriebene Hold-Verwaltung von Steuerbox-Intents             │
│ • Reapply bei Drift                                               │
│ • implementiert: alle Aktoren — aber: kennt Ebene 1 nicht!        │
└──────────────────────────────────────────────────────────────────┘
```

**Diese drei sprechen nicht miteinander.** Wenn Ebene 1 `_extern_aus_ts`
setzt, weiß Ebene 3 davon nichts und könnte einen alten DB-Override
re-applien (genau das war das Race der „Korrektur von gestern").

### 3.2 Was die uncommittete Korrektur tut — und was sie übersieht

**Geänderte Stellen** (working tree, noch nicht committet):

1. [geraete.py#L240-L276](automation/engine/regeln/geraete.py) — neue Methode
   `_cancel_conflicting_overrides(desired_state, geraet)`. Setzt im SQL
   `status='released'` für DB-Overrides mit konfligierendem `state`.
2. [geraete.py#L598](automation/engine/regeln/geraete.py) — Aufruf
   `_cancel_conflicting_overrides('off')` *nur bei extern-AUS-Erkennung*.
3. [geraete.py#L1490](automation/engine/regeln/geraete.py) — analoger Aufruf
   für Klimaanlage.
4. [operator_overrides.py#L194-L232](automation/engine/operator_overrides.py)
   `_active_hold_needs_reapply()` neu geschrieben mit defensiverer Logik
   (kein Reapply bei Soll≠Ist).

**Das löst** den Spezialfall: User klickt „HP OFF" in Steuerbox, dann
schaltet jemand HP intern (z.B. Engine) ein → DB-Override würde reapplied
und gegen die externe Aktion arbeiten. Die Cancellation verhindert das.

**Das löst nicht:**
- **B1 — Asymmetrie EIN↔AUS:** [geraete.py#L573-L580](automation/engine/regeln/geraete.py)
  erkennt extern-EIN, ruft aber **kein** `_cancel_conflicting_overrides('on')`.
  Wenn jemand die HP physisch einschaltet, bleibt eine offene OFF-Override
  aktiv und kann die User-Aktion stören.
- **B2 — `_active_hold_needs_reapply` spekuliert:** Der Kommentar
  „respektiere potenzielle externe AUS" prüft nicht den tatsächlichen
  `_extern_aus_ts`-State der Regel. Das ist defensives Raten, kein
  Engineering.
- **B3 — Wattpilot:** Keine Erkennung, wenn der User in der Wattpilot-App
  pausiert. Kein `_extern_*_ts` in [aktoren/aktor_wattpilot.py](automation/engine/aktoren/aktor_wattpilot.py).
- **B4 — Batterie-Modus:** SOC-Grenzen sind getrackt, aber Modus-Wechsel
  (`auto`/`manual`/`hold`/`grid_charge`) nicht.
- **B5 — Audit-Trail fehlt:** `_cancel_conflicting_overrides` loggt nur
  via `LOG.info`, schreibt keinen Eintrag in `steuerbox_audit`. Forensik
  ist erschwert.
- **B6 — Spezifisch HP/Klima:** Die SQL ist hardcoded auf `hp_toggle` /
  `klima_toggle`. Keine generelle Methode.

### 3.3 Vorschlag: ein zentraler `ExternalRespectManager`

Ein Singleton-Modul, das **Ereignis-getrieben** beide Richtungen
abhandelt:

```python
# automation/engine/external_respect.py  (neu)
class ExternalRespectManager:
    def melde_extern(self, geraet: str, aktion: str,    # 'ein'|'aus'|'pause'|'mode_changed'
                     grund: str, respekt_s: int): ...
    def ist_geholdet(self, geraet: str) -> bool: ...
    def verbleibend_s(self, geraet: str) -> int: ...
    # synchronisiert in einem Schritt:
    #   - In-Memory-State (für Regel-Veto)
    #   - operator_overrides DB (für Audit + Reapply-Block)
    #   - steuerbox_audit (für Forensik)
```

Alle Quellen melden hierhin (Regel-Detection, soc_extern, Aktor-Verify,
Tier-1-Checker). Alle Konsumenten lesen hier (Regel-Veto, Override-Reapply,
UI-Anzeige). **Eine Wahrheit, eine API.** Damit verschwindet die
Asymmetrie zwischen EIN/AUS und zwischen Geräten.

---

## 4 · Parametermatrix & pv-config

### 4.1 Reife-Bewertung

- **Stark:** Atomare Speicherung (write-tmp + rename), Bereichs-
  Validierung vor Persist, SIGHUP-Hot-Reload, einheitliches
  Schema-Skelett (`wert/bereich/einheit/beschreibung`).
- **Schwach:**
  - **~40 Parameter** sind im Code via `get_param()` adressiert, aber
    nicht im pv-config-Whiptail-Menü editierbar. Der User muss JSON
    direkt anfassen.
  - **3 Code-Defaults divergieren** von Matrix-Werten (siehe §2.3).
  - **`battery_control.json`, `efficiency_table.json`, `geometry_config.json`,
    `solar_calibration.json`, `statistics_corrections.json`** werden von
    pv-config nicht editiert — sind aber teils kritisch für die
    Automation.
  - **Score-Gewichte** (`score_gewicht` pro Regelkreis) sind in der
    Matrix, aber nicht in der UI editierbar.

### 4.2 Konkrete Lücken-Liste

Top-Kandidaten für UI-Aufnahme (nach Auswirkung):

| Regelkreis | Parameter | Aufrufe | Heute |
|------------|-----------|---------|-------|
| `nachmittag_soc_max` | `nacht_soc_dynamik_aktiv` (bool) | 1 | nur JSON |
| `nachmittag_soc_max` | `nacht_last_lookback_tage` | 1 | nur JSON |
| `nachmittag_soc_max` | `nacht_soc_usable_kwh` | 1 | nur JSON |
| `morgen_soc_min` | `morgen_vorlauf_min` | 2 | nur JSON |
| `wattpilot_battschutz` | `ev_leistung_schwelle_w` | 1 | nur JSON, **divergent** |
| `klimaanlage` | `initial_temp_c`, `temp_hysterese_k` | 2 | nur JSON |
| `heizpatrone` | 12× `drain_*` Parameter | 30+ | nur JSON |
| `ww_absenkung` / `heiz_absenkung` | `start_h`, `ende_h`, `absenkung_k` | je 5 | nur JSON, **divergent** |

→ ~40 verborgene Parameter, der HP-Drain-Block am dichtesten.

### 4.3 Doku-↔-Code-Drift

- `extern_respekt_s` Doku 1800 vs. Code 3600 (HP) vs. Code 1800 (Klima).
- `start_h` (ww_absenkung) Doku 22 vs. Code 23.
- `ev_leistung_schwelle_w` Matrix 5000 vs. Code 2000.
- [PV_CONFIG_HANDBUCH.md](doc/automation/PV_CONFIG_HANDBUCH.md) listet 18
  Regelkreise, Matrix hat 31. **Über die Hälfte fehlt in der Doku.**

---

## 5 · Namenskonsistenz

| Bereich | Status |
|---------|--------|
| Regel-Klassennamen `Regel*` | ✅ einheitlich |
| Aktor-Klassennamen `Aktor*` | ✅ einheitlich |
| Parameter-Suffixe (`_pct`, `_s`, `_h`, `_w`, `_kwh`, `_c`, `_k`) | ✅ ~95% einheitlich |
| Kommando-Präfixe `hp_*` vs. `heizpatrone_*` | ⚠️ Dual-Aliasing in [aktor_fritzdect.py#L35-L40](automation/engine/aktoren/aktor_fritzdect.py) — funktional, aber Drift-Risiko |
| `regelkreis` vs. `regel` vs. `kontext` | ⚠️ Begriff „Kontext" undefiniert, taucht in Doku auf, im Code nicht |
| `_extern_*_ts` vs. `_engine_*_ts` (SocExternTracker) | ⚠️ analog, aber andere Implementierung |

---

## 6 · Doku-↔-Realitäts-Konsistenz

19 Mismatches im Detail im Anhang A. Die vier kritischen:

1. **`RegelTempSchutz` / `RegelSocSchutz`** sind in
   [AUTOMATION_ARCHITEKTUR.md](doc/automation/AUTOMATION_ARCHITEKTUR.md)
   als aktiv beschrieben, wurden aber 2026-03-07 entfernt
   ([engine.py#L35-L36](automation/engine/engine.py)). GEN24-Hardware
   übernimmt den Schutz.
2. **`SR-EV-01` (NMC-Überladeschutz)** in
   [SCHUTZREGELN.md](doc/automation/SCHUTZREGELN.md) ist nicht implementiert
   und kann es auch nicht sein (E-Auto-SOC nicht verfügbar laut
   [BEOBACHTUNGSKONZEPT.md#L42](doc/automation/BEOBACHTUNGSKONZEPT.md)).
3. **`K-04 Matrix-Auto-Reload`** in [CHANGELOG.md](CHANGELOG.md) (v1.3.1)
   ist als „prüft `os.path.getmtime()` in jedem Zyklus" beschrieben — im
   `engine.py` existiert das nicht. Reload geht nur per SIGHUP.
4. **`HP_TOGGLE_OVERRIDE_FLOW.md`** beschreibt ein Two-Layer-System.
   Layer 1 (Regel-Tracking) ist aktiv, Layer 2 (operator_overrides) wird
   vom HP-Respekt-Code nicht gelesen — die Layer koordinieren nicht.

---

## 7 · SOC-Grenzen Steuerbox — Wurzeldiagnose

### 7.1 Pfad und Bruchstelle

```
Steuerbox-UI  →  intent_handler.handle_intent
              →  operator_overrides DB
              →  OverrideProcessor → actuator → AktorBatterie
              →  fronius_api.BatteryConfig.set_soc_min
              →  Fronius GEN24 HTTP-API
                                 ↓
                  Read-Back via data_collector._collect_battery_soc_config
                                 ↓
                       Fehler →  LOG.debug(...)   ← VERSCHLUCKT
```

### 7.2 Drei sich überlagernde Defekte

1. **D1 — Silent Failure in Collector**
   [data_collector.py#L294-L295](automation/engine/collectors/data_collector.py):
   ```python
   except Exception as e:
       LOG.debug(f"SOC-Config API: {e}")
   ```
   Daemon läuft mit `--log-level INFO` ([automation_daemon.py#L635](automation/engine/automation_daemon.py)).
   Jeder Fronius-API-Fehler verschwindet ungehört. `obs.soc_min` bleibt
   `None` oder veraltet.
2. **D2 — Fronius `SOC_MODE=auto`-Trap**
   Bei `BAT_M0_SOC_MODE=auto` ignoriert die GEN24-Firmware schreibende
   `BAT_M0_SOC_MIN/MAX` **ohne HTTP-Fehler** (siehe
   [FRONIUS_SOC_MODUS.md](doc/automation/FRONIUS_SOC_MODUS.md)). Die
   Werte wirken nicht, der Aktor merkt es erst in der Verifikation.
3. **D3 — Verifikation eskaliert nicht**
   `aktor_batterie.verifiziere()` (v1.3.1, K-01) liefert bei IST≠SOLL
   `{'ok': False}` plus `LOG.warning`. Die Engine-/Actuator-Schicht
   muss daraus aber die User-Intent-Weiterverarbeitung blockieren —
   sonst sieht der User „erfolgreich gespeichert" und nichts ändert sich.

**Was die Korrektur von gestern getan hat:** Die K-01-Korrektur (vom
19. April, Commit `0663cac`) hat *die Verifikation überhaupt erst
implementiert*. Sie funktioniert technisch, aber der Pfad **darüber
hinaus** (Fehler nach oben tragen, UI rückmelden, SOC_MODE-Wechsel
voranstellen) wurde nicht angefasst. Daher der Eindruck „Korrektur hat
nicht funktioniert".

### 7.3 Empfohlene Fix-Reihenfolge

1. **Sofort (5 Min):** [data_collector.py#L295](automation/engine/collectors/data_collector.py)
   `LOG.debug` → `LOG.warning`. Damit wird sichtbar, was wirklich passiert.
2. **Kurz (30 Min):** In `RegelMorgenSocMin`/`RegelNachmittagSocMax`
   einen Mode-Guard voranstellen — wenn `obs.soc_mode == 'auto'`, zuerst
   `set_soc_mode='manual'` als Aktion erzeugen und nur bei verifiziertem
   Erfolg die SOC-Grenzen folgen lassen.
3. **Mittel:** Im Actuator (`ausfuehren_plan`) bei `verifiziere().ok=False`
   das Ergebnis-`ok` auf `False` propagieren und im
   `OperatorOverrideProcessor` reflect:
   `_active_hold_needs_reapply` muss bei wiederholt fehlgeschlagener
   Verifikation den Hold ablaufen lassen, statt endlos zu re-applien.
4. **Mittel:** UI-Feedback in Steuerbox (`steuerbox_audit`-Eintrag mit
   `verify_failed=true`) sichtbar machen.

---

## 8 · Empfohlene Roadmap

### Phase 1 — *„Sichtbarkeit + Sofortbremse"* (kein Risiko)

- [x] `LOG.debug` → `LOG.warning` in data_collector.py (D1). *(2026-04-26)*
- [x] Code-Defaults `extern_respekt_s` (3 Stellen → `1800`) und
      `start_h` (→ `22`) und `ev_leistung_schwelle_w` (→ `5000`) an
      Matrix-Werte angleichen. *(2026-04-26)*
- [x] [HP_TOGGLE_OVERRIDE_FLOW.md](automation/HP_TOGGLE_OVERRIDE_FLOW.md) nach
      `doc/automation/` verschoben und Two-Layer-Beschreibung an die
      Realität angepasst. *(2026-04-26)*

### Phase 2 — *„Asymmetrie heilen"* (mittleres Risiko)

- [x] Symmetrischer Aufruf `_cancel_conflicting_overrides('on')` bei
      extern-EIN-Erkennung (HP & Klima). *(2026-04-26)*
- [x] `_cancel_conflicting_overrides` schreibt einen Audit-Eintrag. *(2026-04-26)*
- [x] `_active_hold_needs_reapply` ohne Spekulation; Soll==Ist-Idempotenz,
      Drift → Reapply. *(2026-04-26)*
- [x] SOC-Mode-Guard vor SOC-Grenzen-Aktionen. *(2026-04-26)*

### Phase 3 — *„Ein Respekt für alle"* (Architektur-Schritt)

- [ ] `ExternalRespectManager` einführen (siehe §3.3).
- [ ] HP/Klima/SOC migrieren — alle drei melden in *einen* Manager.
- [ ] Wattpilot-Aktor: externe Pause-Erkennung in `verifiziere()`.
- [ ] Batterie-Aktor: Modus-Wechsel-Erkennung (auto/manual/hold).

### Phase 4 — *„Plugin-fähige Engine"* (große Investition)

- [ ] Dynamisches Regel-Laden (Plugin-Pattern statt Hardcode).
- [ ] Aktoren-Registry aus Konfig.
- [ ] Zentrale Modbus-Register-Map.
- [ ] State-Machine für HP-Phasen statt If-Kette.

### Phase 5 — *„Doku als Wahrheit"*

- [ ] PV_CONFIG_HANDBUCH alle 31 Regelkreise.
- [ ] AUTOMATION_ARCHITEKTUR: archivierte Regeln dokumentieren.
- [ ] SCHUTZREGELN: SR-EV-01 als „GEPLANT" markieren.
- [ ] CHANGELOG K-04 entfernen oder Feature implementieren.

---

## 9 · Frage an den User: weiteres Vorgehen

Es gibt mehrere mögliche Wege. Ich empfehle die folgenden zur
Entscheidung:

| Pfad | Was passiert | Aufwand | Risiko |
|------|-------------|---------|--------|
| **A — Sofort-Hotfix SOC-Grenzen** | Phase-1-Sichtbarkeit + Mode-Guard + Verifikations-Eskalation. SOC-Grenzen-Steuerbox wieder nutzbar. | klein | gering |
| **B — Respekt-Symmetrie** | Phase 2: extern-EIN cancelt OFF-Overrides, Audit-Trail, kein Spekulieren. | klein–mittel | gering |
| **C — `ExternalRespectManager`** | Phase 3: ein Mechanismus für alle Geräte inkl. Wattpilot. | mittel | mittel (Refactor) |
| **D — Plugin-Engine** | Phase 4: jede neue Regel = 1 Datei + Matrix-Eintrag. | groß | mittel–hoch |
| **E — Doku auf Realität** | Phase 5: nur Doku-Updates, kein Code. | klein | keins |
| **F — Erst stoppen, Test-Suite** | Vor weiterem Refactor automatisierte Tests rund um Respekt-Logik und SOC-Pfad. | mittel | gering, hohe Hebelwirkung |

### Konkrete Frage

> Soll ich mit **A + B + E** als „stabilisierender Sprint" beginnen
> (begrenzter Scope, geringes Risiko, sichtbarer Nutzen), oder bevorzugst
> du **F** voranzustellen (Tests zuerst, dann Refactor) — oder direkt
> **C** als architektonischer Big Step?
>
> Außerdem: soll der bestehende uncommittete Stand (Korrektur von gestern)
> erst committet werden (mit klarer Beschreibung des Spezialfall-Fixes),
> bevor weitere Änderungen kommen?

---

## Anhang A · Doku-Mismatch-Tabelle (gekürzt)

Vollständige Tabelle siehe Subagent-Bericht (Session-Memory). Top 6:

| # | Datei | Soll | Ist | Severity |
|---|-------|------|-----|----------|
| 1 | AUTOMATION_ARCHITEKTUR.md §3 | RegelTempSchutz/SocSchutz aktiv | entfernt 2026-03-07 | 🔴 |
| 2 | SCHUTZREGELN.md SR-EV-01 | NMC-Überladeschutz aktiv | nicht implementierbar | 🔴 |
| 3 | CHANGELOG.md v1.3.1 K-04 | Matrix-Auto-Reload via mtime | nicht implementiert | 🔴 |
| 4 | HP_TOGGLE_OVERRIDE_FLOW.md §3 | extern_respekt 1800s | HP=3600, Klima=1800 | 🔴 |
| 5 | HP_TOGGLE_OVERRIDE_FLOW.md §4 | Two-Layer kohärent | Layer 2 nicht gelesen | 🔴 |
| 6 | PV_CONFIG_HANDBUCH.md §4 | 18 Regelkreise | 31 in Matrix | 🟠 |

## Anhang B · Verifikations-Spuren

- `git status --short`: M `automation/engine/operator_overrides.py`,
  M `automation/engine/regeln/geraete.py`, ?? `HP_TOGGLE_OVERRIDE_FLOW.md`.
- `grep extern_respekt_s automation/engine/regeln/geraete.py` → 6 Treffer,
  Defaults inkonsistent (3× 3600, 2× 1800).
- `grep _cancel_conflicting_overrides automation/engine/regeln/geraete.py` →
  3 Treffer, alle nur mit Argument `'off'`.
- `grep "LOG.debug.*SOC-Config" automation/engine/collectors/data_collector.py` →
  Zeile 295 bestätigt.

---

*Bericht erstellt von Audit-Lauf 2026-04-26. Quellen: 4 parallele
Codebase-Explorationen + Direkt-Verifikation. ~870 Zeilen Detail-Output
in Session-Resources gespeichert.*
