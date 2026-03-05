# Batterie-Steuer-Algorithmus

## 1. Systemübersicht

| Parameter | Wert | Quelle |
|-----------|------|--------|
| Batterie | 2× BYD HVS 20.48 kWh (LFP, parallel, SOH ~96%) | battery_control.json |
| Nutzbar 20→5% | **3.07 kWh** | (15% × 20.48) |
| Nutzbar 70→100% | **6.14 kWh** | (30% × 20.48) |
| Nacht-Grundlast | ~1000 W (00–06 Uhr) | DB Mittelwert 7d |
| Morgen-Last | ~2500 W (07–09 Uhr) | DB Mittelwert 7d |
| PV-Start (Feb) | ~08:00 (spürbar ab 09:00) | Forecast |
| PV-Start (Jun) | ~05:30 (spürbar ab 06:30) | Forecast |
| Sunset (Feb) | ~17:15 | Forecast |
| Sunset (Jun) | ~21:30 | Forecast |

### Aktuelles SOC-Profil (Februar, 7-Tage-Mittel)
```
00-06:  SOC = 20% (am Minimum, 100% Netzbezug)
07-08:  SOC = 20% (noch kein PV)
09:     SOC = 24% (PV startet)
10-15:  SOC steigt auf ~59% (PV lädt Batterie)
16-20:  SOC fällt auf 20% (Abendverbrauch)
21-00:  SOC = 20% (Minimum)
```

---

## 2. Grundidee

Zwei Entscheidungen pro Tag, **jeweils einmal, nicht rückgängig:**

| # | Entscheidung | Standard | Aktion | Wirkung |
|---|-------------|----------|--------|---------|
| ① | **Morgens: SOC_MIN öffnen** | 20% | → 5% | +1.53 kWh aus Batterie statt Netz |
| ② | **Nachmittags: SOC_MAX erhöhen** | 80% | → 100% | +2.04 kWh Speicherkapazität |

### Grundphilosophie: Sanft optimieren

> **Nicht zu radikal.** Der Algorithmus soll die Eigenverbrauchsquote
> verbessern, ohne die Batterie übermäßig zu beanspruchen. LFP ist
> robust, aber unnötige Grenzbereichszyklen kosten trotzdem Lebensdauer.

- Kein starrer Mitternacht-Reset — Einstellungen bleiben erhalten
- Konfigurierbarer Komfort-Bereich (20%–80%) — darunter/darüber = Stress
- Der Algorithmus gilt immer gleich — keine Saisons, die Prognose steuert alles
- 1× monatlich Vollzyklus für BYD-Zellausgleich (→ Abschnitt 5a)

### Komfort-Bereich vs. Stress
```
SOC:  5% ──── 20% ═══════════════════ 80% ──── 100%
      │ Stress │     Komfort-Bereich     │ Stress │
      │ (nur bei│   (Normalzustand)       │(nur bei│
      │  guter  │                         │ wenig  │
      │Prognose)│                         │  PV)   │
```
- Im Winter: 20→5% wird häufiger nötig (viel PV-Ertrag zum Nachladen)
  und 100% fast immer (wenig PV → alle Kapazität nutzen)
- Im Sommer: 5% fast immer (viel PV → nächsten Tag sicher geladen),
  80→100% nur wenn PV-Fenster sich schliesst

### Tagesstart (kein fester Reset!)
```
Flags werden morgens bei erster Prüfung zurückgesetzt:
  morning_done = False, afternoon_done = False
  manual_override bleibt bis manuell aufgehoben

SOC-Grenzen bleiben auf dem aktuellen Wert (Komfort-Defaults oder
vom Vortag), bis der Algorithmus aktiv eine Änderung vornimmt.
```

---

## 3. Morgen-Algorithmus: SOC_MIN Öffnung

### Kernidee
> *"Die Batterie soll gerade noch geleert werden können, bevor PV übernimmt."*

Nicht feste Zeiten, sondern **Rückwärtsrechnung** vom PV-Übernahmezeitpunkt:

```
                        drain_time
                    ◄──────────────►
    ─────────┬──────────────────────┬─────────────
             │   Batterie-Entleerung │  PV übernimmt
             │   20% → 5%           │
        open_time               takeover_time
```

### Berechnung

```python
# 1. PV-Übernahmezeitpunkt bestimmen
#    = erste Stunde, in der PV-Prognose > aktueller Verbrauchsdurchschnitt
takeover_hour = erste_stunde(p_produktion > base_load_w)

# 2. Entleerungszeit berechnen
drain_energy_kwh = (SOC_MIN_DEFAULT - SOC_MIN_OPEN) / 100 * BATT_CAPACITY
                 = (20 - 5) / 100 * 10.2
                 = 1.53 kWh

drain_rate_kw    = avg_consumption_night_kw  # aus DB, ~1.0 kW nachts, ~2.5 kW morgens
drain_hours      = drain_energy_kwh / drain_rate_kw

# 3. Optimaler Öffnungszeitpunkt
open_time = takeover_hour - drain_hours
```

### Entscheidungsbaum

```
Alle 15 min prüfen (05:00 bis sunrise + 3h):

┌─ morning_done oder manual_override?
│  └─ JA → nichts tun
│
├─ expected_kwh < 5.0 kWh?
│  └─ JA → NICHT öffnen (schlechter Tag, Reserve behalten)  [REGEL A]
│     └─ morning_done = True
│        Log: "Nicht geöffnet: Prognose {expected_kwh} kWh < 5 kWh"
│
├─ Aktueller SOC < SOC_MIN_DEFAULT + 2?
│  └─ JA → NICHT öffnen (Batterie schon leer genug)  [REGEL B]
│
├─ current_time >= open_time?
│  └─ JA → SOC_MIN → 5%  [ÖFFNEN]
│     └─ morning_done = True
│        Log: "Geöffnet um {time}, Prognose {expected_kwh} kWh,
│              PV-Übernahme {takeover_hour}, Drain {drain_hours:.1f}h"
│
└─ WARTEN (nächste Prüfung in 15 min)
```

### Beispiele

| Szenario | Prognose | Takeover | Drain | Open-Time | Ergebnis |
|----------|----------|----------|-------|-----------|----------|
| Sonniger Sommertag | 80 kWh | 06:30 | 1.5h | 05:00 | Öffnen um 05:00 |
| Normaler Frühlingstag | 25 kWh | 09:00 | 1.0h | 08:00 | Öffnen um 08:00 |
| Bewölkter Wintertag | 8 kWh | 10:30 | 0.6h | 09:54 | Öffnen um 09:54 |
| Dunkler Wintertag | 3 kWh | nie | - | - | NICHT öffnen |
| Regen ganzer Tag | 1 kWh | nie | - | - | NICHT öffnen |

### Takeover-Stunde Berechnung (Detail)

```python
def find_takeover_hour(hourly_forecast, base_load_w):
    """
    Finde die erste Stunde, in der PV-Produktion den Grundverbrauch deckt.
    Nimmt cloud-gewichtete PV-Prognose.
    
    base_load_w: gleitender Mittelwert der letzten 2h aus DB
    """
    for h in hourly_forecast:
        cloud_factor = 1.0 - 0.7 * (h['cloud_cover'] / 100.0)
        effective_pv = h['ghi'] * ANLAGE_FACTOR * cloud_factor  # W
        if effective_pv > base_load_w * 0.8:  # 80%-Schwelle (konservativ)
            return h['hour']
    return None  # PV erreicht nie den Verbrauch → nicht öffnen
```

### Drain-Rate Berechnung (adaptiv)

```python
def get_drain_rate_kw():
    """
    Aktuellen Verbrauch aus DB abschätzen.
    Nimmt den Durchschnitt der letzten 30 min oder
    den historischen Wert für die aktuelle Stunde.
    """
    # Variante 1: Live (besser)
    recent_30min = db.query("""
        SELECT AVG(P_Imp + P_outBatt + P_Direct) / 1000 
        FROM data_1min 
        WHERE ts > ? - 1800
    """, time.time())
    
    # Variante 2: Historisch (Fallback)
    hour = datetime.now().hour
    historical = db.query("""
        SELECT AVG(P_Imp + P_outBatt + P_Direct) / 1000
        FROM data_1min 
        WHERE ts > ? - 7*86400
          AND CAST(strftime('%H', datetime(ts, 'unixepoch', 'localtime')) AS INT) = ?
    """, time.time(), hour)
    
    return recent_30min or historical or 1.5  # Fallback 1.5 kW
```

---

## 4. Nachmittag-Algorithmus: SOC_MAX Erhöhung

### Kernidee
> *"SOC_MAX von 70% auf 100% erhöhen, wenn die verbleibende PV
> gerade noch reicht, um die zusätzliche Kapazität zu füllen."*

```
           remaining_pv_kwh
    ◄────────────────────────────►
    ├───┐              ┌──────────┤
    │PV │              │ Sunset   │
    └───┘              └──────────┘
    │                              
    │  fill_needed = 3.06 kWh     
    │  (70% → 100%)               
    │                              
    ▼ Wenn remaining_pv > consumption + fill_needed
      → NOCH WARTEN
      Wenn remaining_pv ≈ fill_needed
      → JETZT UMSCHALTEN
```

### Berechnung

```python
# Verbleibende PV-Energie bis Sonnenuntergang (cloud-gewichtet)
remaining_pv_kwh = Summe(p_produktion[jetzt:sunset]) / 1000

# Verbleibender Verbrauch bis Sonnenuntergang (aus Tagesprofil)
remaining_consumption_kwh = Summe(base_load[jetzt:sunset]) / 1000

# Zusätzlich benötigte Energie für 70→100%
fill_needed_kwh = (SOC_MAX_FULL - SOC_MAX_LOW) / 100 * BATT_CAPACITY
                = (100 - 70) / 100 * 10.2 = 3.06 kWh

# PV-Überschuss (was für die Batterie übrig bleibt)
surplus_kwh = remaining_pv_kwh - remaining_consumption_kwh

# Spätester Umschaltzeitpunkt = wenn Surplus ≈ fill_needed
```

### Entscheidungsbaum

```
Alle 15 min prüfen (12:00 bis sunset):

┌─ afternoon_done oder manual_override?
│  └─ JA → nichts tun
│
├─ hours_to_sunset ≤ 1.5?
│  └─ JA → SOC_MAX → 100% [SPÄTESTENS JETZT]  [REGEL C]
│     └─ Log: "Deadline-Umschaltung, {hours_to_sunset:.1f}h bis Sunset"
│
├─ remaining_pv_kwh < 1.0?
│  └─ JA → SOC_MAX → 100% [WENIG PV ÜBRIG]  [REGEL D]
│     └─ Log: "Umschaltung: Nur noch {remaining_pv_kwh:.1f} kWh PV übrig"
│
├─ remaining_cloud_avg > 85%?
│  └─ JA → SOC_MAX → 100% [WOLKEN]  [REGEL E]
│     └─ Log: "Umschaltung: Bewölkung {remaining_cloud_avg:.0f}%"
│
├─ surplus_kwh ≤ fill_needed_kwh * 1.3?
│  └─ JA → SOC_MAX → 100% [PV-FENSTER SCHLIESST SICH]  [REGEL F]
│     └─ Log: "Umschaltung: Surplus {surplus_kwh:.1f} kWh ≈ Fill {fill_needed_kwh:.1f} kWh"
│
└─ WARTEN (noch genug PV-Überschuss, nächste Prüfung in 15 min)
    Log (debug): "Warte: Surplus {surplus_kwh:.1f} kWh > Fill {fill_needed_kwh:.1f} kWh"
```

### Beispiele

| Szenario | Uhrzeit | Remaining PV | Surplus | Aktion |
|----------|---------|-------------|---------|--------|
| Klarer Sommertag | 12:00 | 45 kWh | 30 kWh | Warten |
| Klarer Sommertag | 17:00 | 8 kWh | 4 kWh | → 100% (≈ Fill) |
| Klarer Sommertag | 18:00 | 3 kWh | 1 kWh | → 100% (Deadline) |
| Bewölkter Tag | 12:00 | 3 kWh | 0.5 kWh | → 100% (wenig PV) |
| Wechselhaft | 14:00 | 6 kWh | 3 kWh | → 100% (Surplus ≈ Fill) |
| Dunkler Wintertag | 12:00 | 0.5 kWh | -5 kWh | → 100% (sofort) |

---

## 5. Konfiguration: `config/battery_control.json`

Alle Parameter sind zentral in `config/battery_control.json` konfigurierbar.
Die Datei ist bewusst auf Deutsch und selbstdokumentierend (`_doc`-Felder).

### Struktur-Übersicht

| Abschnitt | Zweck | Beispiel-Parameter |
|-----------|-------|---------------------|
| `batterie` | Hardware-Konstanten | Kapazität, Chemie, Max-Leistung |
| `soc_grenzen` | SOC-Bereiche | komfort_min=20%, komfort_max=80%, stress_min=5% |
| `morgen_algorithmus` | SOC_MIN-Öffnung | PV-Mindestprognose, Übernahme-Schwelle |
| `nachmittag_algorithmus` | SOC_MAX-Erhöhung | Surplus-Faktor, Wolken-Schwelle |
| `zellausgleich` | Monatl. Vollzyklus | Tag im Monat, Modus |
| `leistungsbegrenzung` | Lade-/Entladeraten | Sommer-Laderate, Temperatur-Limits |
| `zeitsteuerung` | Intervalle & Fenster | Prüfintervall, Nacht-/Abendgrenzen |
| `sicherheit` | Fail-Safe-Werte | Watchdog, Netzladung |
| `logging` | Protokollierung | Level, DB-Logging |

### Philosophie

> **Nicht zu radikal.** Die Batterielebensdauer ist wichtiger als die letzten
> 2% Autarkie. LFP-Chemie ist robust, aber unnötige Zyklen im oberen und
> unteren Grenzbereich verkürzen die Lebensdauer trotzdem. Der Algorithmus
> soll *sanft optimieren*, nicht *aggressiv ausreizen*.

Konkret bedeutet das:
- **Kein täglicher Mitternacht-Reset** — Einstellungen bleiben, bis der
  Algorithmus aktiv ändert (kann auch tagelang gleich bleiben)
- **Konfigurierbarer Komfort-Bereich** (20%–80%, einstellbar Richtung 30/70)
- **Keine Saisons** — der Algorithmus gilt immer gleich, die Prognose bestimmt
- **Fail-Safe auf unkritische Werte** (20%/100% bei Ausfall)

---

## 5a. Monatlicher Zellausgleich (BYD Cell Balancing)

### Hintergrund

Das BYD-BMS (Battery Management System) benötigt gelegentlich einen
**vollständigen Lade-/Entladezyklus**, um die Zellspannungen auszugleichen.
Ohne Balancing driften die Zellen auseinander → nutzbare Kapazität sinkt.

BYD empfiehlt: **mindestens 1× pro Monat einen Vollzyklus** durchführen.

### Problem: Fixer Tag ist sinnlos

Ein Vollzyklus braucht genug PV, um die Batterie auch wirklich von 5%
auf 100% laden zu können. An einem dunklen Wintertag mit 3 kWh Ertrag
wird das nichts. Deshalb:

> **Kein fixer Monatstag.** Stattdessen: Prognose befragen und den
> ersten sonnigen Tag im Monat nutzen.

### Ablauf (prognosegesteuert)

```
Täglich bei der ersten Morgen-Prüfung:

┌─ Zellausgleich diesen Monat schon durchgeführt?
│  └─ JA → nichts tun
│
├─ Letzter Ausgleich > 45 Tage her? (Notfall)
│  └─ JA → Schwelle senken auf 15 kWh
│
├─ PV-Prognose heute >= 25 kWh? (bzw. 15 kWh bei Notfall)
│  └─ NEIN → warten auf besseren Tag
│     └─ Log: "Zellausgleich: Prognose {x} kWh < Schwelle, warte"
│
└─ JA → ZELLAUSGLEICH AUSLÖSEN:
       SOC_MODE → "auto"
       SOC_MIN  → 5%
       SOC_MAX  → 100%
       StorCtl_Mod → 0 (keine Begrenzung)
       morning_done = True  (kein Morgen-Algorithmus heute)
       afternoon_done = True  (kein Nachmittag-Algorithmus heute)
       Log: "Zellausgleich gestartet — Prognose {x} kWh"

Folgetag 06:00:
       SOC_MODE → "manual"
       SOC_MIN  → Komfort-Minimum (20%)
       SOC_MAX  → Komfort-Maximum (80%)
       letzter_ausgleich → heute
       Log: "Zellausgleich beendet — zurück auf Komfort-Defaults"
```

### Schwellen-Staffelung

| Situation | PV-Schwelle | Begründung |
|-----------|-------------|------------|
| Normal (Tag 1–28) | **25 kWh** | Genug für Vollzyklus 5%→100% + Verbrauch |
| Spät (Tag 29+, oder >35 Tage) | **15 kWh** | Lieber Teilzyklus als gar keiner |
| Notfall (>45 Tage) | **15 kWh** | Nächster Tag >15 kWh wird genommen |

Die 25-kWh-Schwelle ist bewusst konservativ: 3 kWh Batterie (5→100%) +
~15 kWh Tagesverbrauch + Verluste = man braucht ordentlich Sonne.

### Konfiguration

```json
"zellausgleich": {
    "aktiv": true,
    "modus": "auto",
    "soc_min_waehrend": 5,
    "soc_max_waehrend": 100,
    "min_prognose_kwh": 25.0,
    "fruehester_tag": 1,
    "spaetester_tag": 28,
    "max_tage_ohne_ausgleich": 45,
    "notfall_min_prognose_kwh": 15.0,
    "letzter_ausgleich": null
}
```

| Parameter | Wirkung |
|-----------|--------|
| `min_prognose_kwh` | Mindest-PV-Prognose für normalen Ausgleich |
| `notfall_min_prognose_kwh` | Abgesenkte Schwelle nach `spaetester_tag` |
| `max_tage_ohne_ausgleich` | Absolute Obergrenze — danach wird die nächste Gelegenheit genommen |
| `letzter_ausgleich` | ISO-Datum, wird automatisch gesetzt |
| `modus` | `"auto"` = Inverter steuert frei, `"manual"` = nur SOC-Grenzen öffnen |

### Warum "auto"?

Im Auto-Modus überlässt man dem Fronius-Inverter die Entscheidung über
Lade-/Entladezeitpunkte. Das BYD-BMS hat dann die Freiheit, den Balancing-
Algorithmus optimal auszuführen. An einem sonnigen Tag wird die Batterie
entladen → voll aufgeladen → BMS gleicht Zellen aus.

### Jahreszeiten-Erwartung (natürlich, ohne Konfiguration)

| Jahreszeit | Typischer Ausgleich-Tag | Anmerkung |
|--------|------------------------|----------|
| Sommer | 1.–5. des Monats | Viele Tage >25 kWh, schnell erledigt |
| Frühling/Herbst | 5.–15. des Monats | Muss evtl. etwas warten |
| Winter | 15.–28. (oder Notfall) | Kann in die Notfall-Schwelle rutschen |

Im tiefsten Winter (Dez/Jan) sind Tage mit 25 kWh selten — dann greift
die abgesenkte Schwelle (15 kWh) ab Tag 29, und der Teilzyklus reicht
für einen groben Zellausgleich

---

## 5b. Abend-/Nacht-Algorithmus (Entladerate begrenzen)

### Kernidee
> *"Abends die Batterie vor schnellem Entladen durch Hochlastgeräte schützen.
> Grid übernimmt Spitzenlasten, Batterie liefert nur Grundlast."*

Ohne Begrenzung entlädt die BYD HVS mit bis zu 10,2 kW — ein Backofen
(3,5 kW) + Trockner (2,5 kW) allein reichen, um die Batterie in 1,5 Stunden
von 80% auf 20% zu leeren. Danach: voller Netzbezug die ganze Nacht.

### Phasen

```
Stunde:  00──── 06 ──────────── 15 ──────────── 24
         │ NACHT │      TAG      │     ABEND     │
         │ 10%   │  AUTOMATIK    │     29%       │
         │~1.0 kW│  (keine       │   ~3.0 kW     │
         │       │   Limits)     │               │
```

| Phase | Zeitfenster | Entladerate | Max. Leistung | Zweck |
|-------|-------------|-------------|---------------|-------|
| **Nacht** | 00:00–06:00 | 10% | ~1,0 kW | Nur Standby (Kühlschrank, Server, etc.) |
| **Tag** | 06:00–15:00 | AUTOMATIK | 10,2 kW | PV-Betrieb, keine Einschränkung |
| **Abend** | 15:00–24:00 | 29% | ~3,0 kW | Grundlast OK, Spitzenlasten → Grid |

### SOC-Notbremse

| SOC-Level | Aktion | Grund |
|-----------|--------|-------|
| < 10% (kritisch_soc) | Entladerate → **0%** (HOLD) | Tiefentladeschutz |
| 10–20% (unter komfort_min) | Normaler Abend/Nacht-Betrieb | SOCmin fängt ab |

### Entscheidungsbaum

```
Alle 15 min prüfen (immer, nicht nur Abend):

┌─ balancing_active?
│  └─ JA → nichts tun (Zellausgleich braucht vollen Zyklus)
│
├─ SOC < kritisch_soc (10%)?
│  └─ JA → HOLD (Entladerate = 0%)  [SOC-SCHUTZ]
│
├─ Uhrzeit im Fenster abend_ab...24:00?
│  └─ JA → Entladerate = abend_rate (29%)  [ABEND-PHASE]
│
├─ Uhrzeit im Fenster nacht_ab...nacht_bis (0:00–6:00)?
│  └─ JA → Entladerate = nacht_rate (10%)  [NACHT-PHASE]
│
├─ Uhrzeit 6:00–15:00 UND evening_rate_active?
│  └─ JA → StorCtl_Mod = 0 (alle Limits aufheben)  [TAG-PHASE]
│
└─ KEIN HANDLUNGSBEDARF
```

### Modbus-Umsetzung

```
Entladerate begrenzen:
  OutWRte  = Prozent × 100  (Register 40355, SF=-2)
  StorCtl_Mod |= 0x02       (Register 40348, Bit 1 = Discharge-Limit aktiv)

Aufheben (Tag-Phase):
  StorCtl_Mod = 0            (alle Limits deaktiviert)
```

### Konfiguration (battery_control.json)

```json
"leistungsbegrenzung": {
    "entladerate_abend_prozent": 29,    ← 29% × 20480W = ~5,9 kW (⚠️ Regel deaktiviert seit März 2026)
    "entladerate_nacht_prozent": 10,    ← 10% × 20480W = ~2,0 kW (⚠️ Regel deaktiviert seit März 2026)
},
"zeitsteuerung": {
    "abend_entladelimit_ab": 15,        ← Beginn Abend-Phase
    "abend_entladelimit_bis": 0,        ← Ende (0 = Mitternacht)
    "nacht_entladelimit_ab": 0,         ← Beginn Nacht-Phase
    "nacht_entladelimit_bis": 6          ← Ende Nacht-Phase
}
```

### Warum 29% Abend?

- 29% × 20.480 W = **5.939 W** (≈ 5,9 kW) — ⚠️ *Regel deaktiviert seit März 2026*
- Deckt ab: Küche (800W), TV/Licht (300W), Kühlschrank (150W), Standby (200W) = ~1.450 W
- Deckt NICHT ab: Backofen (3.500W), Waschmaschine (2.200W), Trockner (2.500W)
- Spitzenlasten → Grid bezieht automatisch den Rest (Nulleinspeiser-Setup)
- Bei 3 kW Entladerate und 7,8 kWh nutzbarer Energie (80%→20%): **~2,6 Stunden** Volllast

### Zusammenspiel mit Zellausgleich

- Während `balancing_active = True`: Abend-Algo pausiert
- Sobald Sunset + 30 Min vorbei: Balancing wird beendet → Komfort-Defaults → Abend-Algo greift

---

## 6. Tagesablauf-Beispiel (bewölkter Februartag)

```
00:05  RESET → SOC_MIN=20%, SOC_MAX=80%, Flags=False
       Prognose geladen: expected_kwh=8.2, sunrise=07:31, sunset=17:13
       Cloud 08-12: 65%, Takeover-Hour: 10:00
       Drain: 1.53 kWh / 1.2 kW = 1.28h → Open-Time: 08:43

05:00  Morgen-Check: current_time < open_time → WARTEN
05:15  Morgen-Check: WARTEN
...
08:45  Morgen-Check: current_time >= 08:43 → SOC_MIN → 5% ✓
       Log: "Geöffnet 08:45, Pr. 8.2 kWh, Takeover 10:00, Drain 1.28h"
       morning_done = True

08:45-09:30  Batterie entlädt von 20% → ~12%
09:30-10:00  Batterie entlädt von 12% → 5%, PV startet
10:00+       PV übernimmt Versorgung, Batterie beginnt zu laden

12:00  Nachmittag-Check: remaining_pv=4.2 kWh, consumption=3.5 kWh
       surplus=0.7 kWh < 3.06*1.3=3.98 → SOC_MAX → 100% ✓
       Log: "Umschaltung 12:00, Surplus 0.7 kWh < Fill 3.06 kWh"
       afternoon_done = True

12:00-17:00  Batterie lädt bis sunset (schafft ~45% bei 8.2 kWh Tag)

15:00  Abend-Algo: ABEND-PHASE → Entladerate auf 29% (~3 kW)
       StorCtl_Mod=2, OutWRte=29%
       Log: "Entladerate: auto→29% (ABEND 15:00–24:00)"

17:00+       PV endet, Batterie entlädt für Abendverbrauch (max 3 kW)
             Spitzenlasten (Backofen etc.) → Grid übernimmt Rest

00:00  Abend-Algo: NACHT-PHASE → Entladerate auf 10% (~1 kW)
       Nur Standby-Verbrauch aus Batterie
```

---

## 7. Tagesablauf-Beispiel (sonniger Sommertag)

```
00:05  RESET → SOC_MIN=20%, SOC_MAX=80%
       Prognose: expected_kwh=85, sunrise=05:15, sunset=21:25
       Cloud 06-10: 15%, Takeover-Hour: 06:00
       Drain: 1.53 kWh / 0.8 kW = 1.91h → Open-Time: 04:05

04:15  Morgen-Check: current_time >= 04:05 → SOC_MIN → 5% ✓
       (Batterie hat die ganze Nacht entladen, jetzt letzte 15%)

05:00  Batterie bei ~8%, PV startet langsam
06:00  Batterie bei 5% (leer), PV übernimmt komplett ✓

12:00  Nachmittag-Check: remaining_pv=55 kWh, surplus=40 kWh → WARTEN
14:00  Nachmittag-Check: remaining_pv=30 kWh, surplus=22 kWh → WARTEN
16:00  Nachmittag-Check: remaining_pv=15 kWh, surplus=10 kWh → WARTEN
17:30  Nachmittag-Check: remaining_pv=6 kWh, surplus=3.5 kWh
       surplus ≤ 3.06 * 1.3 → SOC_MAX → 100% ✓
       Log: "Umschaltung 17:30, Surplus 3.5 kWh ≈ Fill 3.06 kWh"

17:30-21:00  Batterie lädt von 70% auf ~95-100%
```

---

## 8. Manueller Override (UI-Buttons)

### API-Endpunkte
```
POST /api/battery_control   {action: "set_soc_min", value: 5}
POST /api/battery_control   {action: "set_soc_max", value: 100}
POST /api/battery_control   {action: "reset"}  → zurück auf Defaults
```

### UI (tag_view.html Batterie-Info-Bar)
```
┌─────────────────────────────────────────────────────┐
│ 🔋 SOC: 45%  │ Min: 20%  │ Max: 70%  │ Modus: auto │
│ ──────────────────────────────────────────────────── │
│ [📤 SOC_MIN → 5%]  [📥 SOC_MAX → 100%]  [↺ Reset]  │
│ Status: ⏳ Morgen-Öffnung um 08:43 geplant          │
└─────────────────────────────────────────────────────┘
```

**Manueller Override:**
- Button-Klick setzt den Wert sofort
- `manual_override = True` → Algorithmus überspringt automatische Umschaltung
- Reset am nächsten Tag um 00:05

---

## 9. Logging

Alle Batterie-Entscheidungen werden in der Tabelle `automation_log` (in `data.db`)
protokolliert. Felder: `ts`, `aktor`, `kommando`, `wert_vorher`, `wert_nachher`,
`score`, `grund`, `ergebnis`, `dauer_ms`, `zyklus_id`.

---

## 10. Implementierungsstand

| Schritt | Beschreibung | Status |
|---------|-------------|--------|
| 1 | Config-Datei `config/battery_control.json` | ✅ |
| 2 | Batterie-Algorithmus (jetzt in 11 Regelkreisen der Engine) | ✅ |
| 3 | DB-Tabelle `automation_log` (ersetzt `battery_control_log`) | ✅ |
| 4 | `pv-automation.service` (systemd, Score-basiert) | ✅ |
| 5 | Zellausgleich-Logik (1× monatlich, prognosegesteuert) | ✅ |
| 6 | Parametrierung über `pv-config.py` (SSH-Terminal) | ✅ |

---

> Die Batterie-Steuerung läuft seit 2026-02-28 über `pv-automation.service`.
> Alle Regelkreise sind in `automation/engine/regeln/` implementiert.
> Parametrierung: `config/soc_param_matrix.json` via `pv-config.py`.
