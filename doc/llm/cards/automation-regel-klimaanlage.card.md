---
title: "Automation: RegelKlimaanlage (Klima-Thermoschutz)"
domain: automation
role: C
last_review: 2026-05-04
status: stable
code_anchor: automation/engine/regeln/geraete.py#L1577
invariants:
  - "Tier-2 Aktor: Fritz!DECT-Steckdose (nur Klima-SD via AHA-API)"
  - "Schaltfrequenz-Cooldown: Bei 2×AUS im 30-Min-Fenster → 60 Min EIN-Sperre + sofortiges AUS"
  - "Extern-Erkennung: Lastflanke (Kompressor ON/OFF) + SD-Schaltflanke (ON/OFF)"
  - "Hold-Hierarchie: Sunset+SOC > Steuerbox-Override > Extern-Respekt > Cooldown > Normallogik"
  - "Daemon-Restart-Sicherung: lade_cooldown_aus_db() wird Engine.__init__ aufgerufen"
---

# RegelKlimaanlage — Klima-Thermoschutz

**Domäne:** Automation (Rolle C) | **Zyklus:** `fast` (1 min) | **Tier:** 2  
**Hardware:** Fritz!DECT-Steckdose (nur Schalter, kein Modbus)

## Funktion

Temperaturgeführter Thermoschutz für Heizhaus-Klimaanlage mit Schaltfrequenz-Schutz:

- **Vor Sunrise:** Nur wenn Forecast='gut' und Temp ≥ `initial_temp_c` (standard: 15°C)
- **Nach Sunrise:** Start abhängig von Forecast-Qualität (`initial_temp_c_gut_nach_sunrise` vs. `initial_temp_c_maessig`)
- **Laufend:** Hysterese-Betrieb (temp ≥ start - hysterese_k)
- **Sunset+SOC-Stop:** Harte Sicherheit bleibt IMMER aktiv (auch bei Extern/Override)
- **Schaltfrequenz-Schutz:** Erkennt Kompressor-Kurzzyklen → 60-Min-Cooldown nach 2×AUS im 30-Min-Fenster

## Schaltfrequenz-Schutz (Wichtig!)

### Erkennung (Lastflanke)

Kompressor läuft intern im Takt; Fritz!DECT-SD bleibt EIN, Last springt ~1 kW ↔ ~30 W.
Wird erfasst durch **Lastflanke** (nicht SD-OFF):

```python
_KOMP_ON_THR_W = 600.0   # HIGH-Schwelle
_KOMP_OFF_THR_W = 200.0  # LOW-Schwelle
_AUS_EVENT_DEDUP_S = 60.0  # min. Abstand zwischen gezählten Events
```

→ **HIGH→LOW Übergang** = Kompressor-AUS erkannt
→ Mit Dedup: max. 1 Event pro Minute zählen

### Cooldown-Aktivierung

- 2× AUS im `schaltintervall_s`-Fenster (default: 30 Min) → Cooldown startet
- Cooldown-Dauer: `cooldown_s` (default: 60 Min)
- **Aktion: `klima_aus` sofort + RAM-DB persistiert (für Web-API + Post-Restart)**
- Neue EIN-Anforderungen blockiert während Cooldown aktiv

## Extern-Erkennung (Hold-Respekt)

Symmetrisch für ON/OFF (ähnlich `RegelHeizpatrone`):

| Event | Trigger | Respekt-Dauer |
|-------|---------|---|
| Extern EIN | SD-OFF→ON ohne Engine | `extern_respekt_s` (default: 30 Min) |
| Extern AUS | SD-ON→OFF ohne Engine | `extern_respekt_s` (default: 30 Min) |
| Kompressor-AUS | Lastflanke HIGH→LOW | sofort → Cooldown |

Während Respekt-Phase: Tempatur-Abschaltlogik unterdrückt, nur Sunset+SOC aktiv.

## Hold-Hierarchie (bewerte/erzeuge_aktionen)

```
1. Sunset+SOC-Stop        (IMMER — auch bei Extern/Override) → AUS
2. Steuerbox-Hold (ON/OFF) (respekt_s von Steuerbox)          → ON/AUS
3. Extern-Hold (ON/OFF)    (respekt_s = extern_respekt_s)     → ON/AUS
4. Cooldown-AUS-Sperre    (nach 2×AUS erkannt)               → AUS
5. Temperatur-Hysterese    (normale Regelung)                 → ON/AUS
```

## Pre-Commit-Guard

Code in `automation/engine/regeln/geraete.py` erfordert **diese Card-Aktualisierung** (last_review).

## Häufige Aufgaben

| Aufgabe | Ort | Beispiel |
|---------|-----|---------|
| Cooldown-Schwelle ändern | `config/soc_param_matrix.json` > `klimaanlage.schaltintervall_s` | 900–2700 s |
| Cooldown-Dauer ändern | `config/soc_param_matrix.json` > `klimaanlage.cooldown_s` | 1800–5400 s |
| Extern-Respekt-Zeit ändern | `config/soc_param_matrix.json` > `klimaanlage.extern_respekt_s` | 300–7200 s |
| Starttemperatur ändern | `config/soc_param_matrix.json` > `klimaanlage.initial_temp_c` | z.B. 15°C |
| Hysterese anpassen | `config/soc_param_matrix.json` > `klimaanlage.temp_hysterese_k` | z.B. 1.0 K |
| Loggen prüfen (Cooldown erkannt) | Terminal | `grep "Schaltfrequenz-Cooldown" automation_daemon.log` |

## Verwandte Cards

- [`automation-regel-heizpatrone.card.md`](automation-regel-heizpatrone.card.md) — HP-Regelung (analog)
- [`automation-steuerungsphilosophie.card.md`](automation-steuerungsphilosophie.card.md) — Hold-Hierarchie, Prioritäten
- [`automation-state.card.md`](automation-state.card.md) — RAM-DB (engine_flags Persist)

## Human-Dokumentation

- [`doc/automation/STEUERUNGSPHILOSOPHIE.md`](../../automation/STEUERUNGSPHILOSOPHIE.md) — Hold-Hierarchie, Prioritäten, Regelkonzept
