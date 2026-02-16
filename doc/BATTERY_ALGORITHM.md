# Batterie-Steuer-Algorithmus — Entwurf zur Diskussion

## 1. Systemübersicht

| Parameter | Wert | Quelle |
|-----------|------|--------|
| Batterie | BYD HVS 10.2 kWh (LFP, SOH 92%) | Fixwert |
| Nutzbar 20→5% | **1.53 kWh** | (15% × 10.2) |
| Nutzbar 70→100% | **3.06 kWh** | (30% × 10.2) |
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
    "entladerate_abend_prozent": 29,    ← 29% × 10240W = ~3,0 kW
    "entladerate_nacht_prozent": 10,    ← 10% × 10240W = ~1,0 kW
},
"zeitsteuerung": {
    "abend_entladelimit_ab": 15,        ← Beginn Abend-Phase
    "abend_entladelimit_bis": 0,        ← Ende (0 = Mitternacht)
    "nacht_entladelimit_ab": 0,         ← Beginn Nacht-Phase
    "nacht_entladelimit_bis": 6          ← Ende Nacht-Phase
}
```

### Warum 29% Abend?

- 29% × 10.240 W = **2.970 W** (≈ 3 kW)
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

## 9. Logging & Datenbank

```sql
CREATE TABLE battery_control_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,           -- Timestamp
    action TEXT NOT NULL,       -- 'morning_open', 'morning_skip', 'afternoon_raise',
                                -- 'afternoon_wait', 'midnight_reset', 'manual_override'
    param TEXT,                 -- 'soc_min' oder 'soc_max'
    old_value INTEGER,
    new_value INTEGER,
    reason TEXT,                -- Begründung (lesbar)
    forecast_kwh REAL,          -- Tagesprognose
    cloud_avg REAL,             -- Bewölkung zum Zeitpunkt
    soc_at_decision REAL,       -- SOC bei Entscheidung
    takeover_hour INTEGER,      -- Berechnete PV-Übernahmestunde
    manual BOOLEAN DEFAULT 0
);
```

---

## 10. Implementierungsplan

| Schritt | Beschreibung | Aufwand |
|---------|-------------|---------|
| 1 | ✅ Config-Datei `config/battery_control.json` | erledigt |
| 2 | `battery_scheduler.py` erstellen (Algorithmus-Kern) | ~300 Zeilen |
| 3 | DB-Tabelle `battery_control_log` anlegen | 1 SQL |
| 4 | Cron-Job: alle 15 min `battery_scheduler.py` aufrufen | 1 Zeile |
| 5 | Zellausgleich-Logik (1× monatlich) | ~50 Zeilen |
| 6 | API-Endpunkt `/api/battery_control` in web_api.py | ~50 Zeilen |
| 7 | UI-Buttons in tag_view.html Batterie-Bar | ~40 Zeilen |
| 8 | Status-Anzeige: nächste geplante Aktion | ~30 Zeilen |
| 9 | Systemd-Service (optional, statt Cron) | 1 Unit-File |

---

## 11. Offene Fragen zur Diskussion

1. **SOC_MAX = 70% als Standard?**
   Aktuell steht SOC_MAX auf 100%. Soll 70% wirklich der Tages-Standard werden?
   → Batterieschonung vs. maximale Speichernutzung
   → Im Winter erreicht die Batterie ohnehin nur ~60%

2. **Drain-Rate**: Live-Verbrauch (letzte 30 min) oder historischer Stundenwert?
   → Live ist genauer, aber evtl. untypisch (z.B. Waschmaschine gerade an)
   → Vorschlag: Gewichteter Mix (70% historisch, 30% live)

3. **Wärmepumpe-Spitzen**: Die WP zieht intermittierend 3-5 kW.
   Soll der Algorithmus WP-Zyklen berücksichtigen?
   → Oder reicht der 80%-Threshold bei der Takeover-Berechnung?

4. **Wattpilot (EV-Ladung)**: Bei EV-Ladung steigt der Verbrauch auf 10+ kW.
   Separate Behandlung oder ignorieren?

5. **Sicherheits-SOC**: Sollte 5% wirklich das absolute Minimum sein?
   → LFP verträgt tiefe Entladung, aber 5% lässt noch Puffer
   → Alternative: 10% als Kompromiss?

6. **Netzladung**: `GRID_CHARGE=True` ist aktuell gesetzt.
   Soll der Algorithmus auch steuern, ob Netzladung erlaubt ist?
   → Z.B. bei günstigem Nachtstrom gezielt laden?

7. **Mehrere Tage voraus**: Soll die Entscheidung auch den Folgetag berücksichtigen?
   → Z.B. morgen Regen → heute auf 100% laden
   → Komplexität vs. Nutzen?

---

*Erstellt: 2026-02-09 — Aktualisiert: 2026-02-10*
*Algorithmus v1.1 — Zellausgleich + Config-Datei + pragmatische Philosophie*

---

## 12. Nutzerfeedback (09.02.2026 Abend)

### Saisonale Logik — Grundsätzliche Korrektur

> **Winter / Übergangszeit (WP-dominiert):**
> - Batterie reicht NICHT über Nacht (WP allein ~20 kWh/Tag, PV evtl. nur 10 kWh)
> - SOC_MAX-Einschränkung (70%) meist **nicht nötig** — nur bei wirklich hohen Erträgen
> - SOC_MIN-Öffnung auf 5% ist quasi **Standard-Aktion** im Winter
> - **Zusatzeffekt**: Öffnung auf 5% kann die PV-Aktivierung vorziehen, weil der
>   Inverter erst bei Mindestleistung startet — Batterie-Entladung erhöht den
>   Eigenverbrauchsanteil und zieht den PV-Start vor → mehr Dunkelertrag
> - **ABER**: Wenn den ganzen Tag nur 10 kWh PV kommen, aber die WP alleine 20 kWh
>   braucht, bringt die Öffnung nichts — die Batterie wird ohnehin nicht voll

> **Sommer:**
> - Batterie kann über Nacht reichen und >20% bleiben
> - Standard unten = 5%, Fokus muss auf der **oberen Begrenzung** (SOC_MAX) liegen!
> - SOC_MAX 70→100% ist die Hauptentscheidung

> **Allgemein:**
> - Es ist durchaus denkbar, dass über Nacht oder gar **tagelang** eine Einstellung
>   konstant bleibt (kein täglicher Reset nötig!)
> - Täglicher Mitternacht-Reset auf 20%/70% ist zu aggressiv

### Auswirkungen auf den Algorithmus

1. **Mitternacht-Reset streichen** — Einstellungen bleiben, bis Algorithmus aktiv ändert
2. **Saisonale Grundkonfiguration** statt starrer Defaults:
   - Winter (Nov-Feb): SOC_MIN=20% (Schutz Tiefentladung), SOC_MAX=100% (oben egal)
   - Übergang (Mär-Apr, Sep-Okt): SOC_MIN=10%, SOC_MAX=90%
   - Sommer (Mai-Aug): SOC_MIN=5% (unten egal), SOC_MAX=80% (Schutz Dauer-Voll)
3. **Inverter-Aktivierungs-Effekt** berücksichtigen (SOC_MIN 5% → PV startet früher)
4. **WP-Verbrauchsprognose** einbeziehen (nicht nur PV-Prognose)

→ *Überarbeitung des Algorithmus erfolgt am 10.02.2026*

---

## 6. LFP-Batterie-Lebensdauer — Analyse & Prognose

### 6.1 Batterie-Hardware

| Parameter | Wert |
|-----------|------|
| Modell | BYD HVS 10.2 |
| Chemie | **LiFePO₄ (LFP)** |
| Nennkapazität | 10,2 kWh (5 Module à 2,56 kWh) |
| Nennspannung | 204,8 V (5 × 40,96 V) |
| Zellspannung | 3,2 V nominal, 3,65 V max, 2,5 V min |
| Max. Lade-/Entladeleistung | 10.240 W |
| Inbetriebnahme | November 2021 |
| SOH (Stand Feb 2026) | **92 %** |

### 6.2 Bisherige Zyklenbelastung (gemessen)

Berechnung: **Gesamte Batterieladung [kWh] ÷ 10 kWh ≈ Äquivalente Vollzyklen**

| Jahr | Ladung [kWh] | Entladung [kWh] | Effizienz | Äq. Vollzyklen |
|------|-------------:|----------------:|----------:|---------------:|
| 2021 (ab Nov) | 198 | 182 | 92,0 % | **20** |
| 2022 | 2.519 | 2.359 | 93,6 % | **252** |
| 2023 | 2.380 | 2.236 | 93,9 % | **238** |
| 2024 | 3.119 | 2.946 | 94,5 % | **312** |
| 2025 | 3.568 | 3.390 | 95,0 % | **357** |
| 2026 (bis 10.02.) | 228 | 215 | 94,4 % | **23** |
| **Gesamt** | **12.012** | **11.328** | **94,3 %** | **~1.201** |

**Durchschnitt (volle Jahre 2022–2025): ~290 Zyklen/Jahr**

Trend: Die jährliche Zyklenbelastung steigt (252 → 312 → 357), bedingt durch
den Wattpilot (ab 2024) und zunehmende Optimierung des Eigenverbrauchs.

### 6.3 SOH-Verlauf

| Datum | SOH | Verlust | Zyklen kumuliert | Betriebsjahre |
|-------|----:|--------:|-----------------:|---------------:|
| Nov 2021 | 100 % | — | 0 | 0 |
| Feb 2026 | **92 %** | **8 %** | **~1.200** | **4,3** |

→ **8 % Kapazitätsverlust in 4,3 Jahren und ~1.200 Zyklen**
→ Das entspricht ~1,9 % SOH-Verlust pro Jahr (kalendarisch)
→ Oder ~0,67 % SOH-Verlust pro 100 Zyklen

### 6.4 LFP-Lebensdauer — Wissenschaftliche Quellen

#### Quelle 1: BatteryUniversity — Zyklenlebensdauer nach Entladetiefe

> Tabelle 2 aus [BU-808: How to Prolong Lithium-based Batteries](https://batteryuniversity.com/article/bu-808-how-to-prolong-lithium-based-batteries)

| Entladetiefe (DoD) | NMC Zyklen | **LFP Zyklen** |
|--------------------:|-----------:|---------------:|
| 100 % | ~300 | **~600** |
| 80 % | ~400 | **~900** |
| 60 % | ~600 | **~1.500** |
| 40 % | ~1.000 | **~3.000** |
| 20 % | ~2.000 | **~9.000** |
| 10 % | ~6.000 | **~15.000** |

*„A partial discharge reduces stress and prolongs battery life, so does a
partial charge."* — BatteryUniversity

#### Quelle 2: BatteryUniversity — Optimales SOC-Fenster (DST-Test)

> Figure 6 aus [BU-808](https://batteryuniversity.com/article/bu-808-how-to-prolong-lithium-based-batteries), Dynamic Stress Test

| SOC-Bereich | Zyklen (bis 90 % Kapazität) | Energieausbeute | Nutzungsgrad |
|-------------|----------------------------:|----------------:|-------------:|
| 75–65 % | sehr viele | 90.000 EU | 10 % |
| **75–25 %** | **~3.000** | **150.000 EU** | **50 %** |
| 85–25 % | ~2.000 | 120.000 EU | 60 % |
| 100–25 % | kurz | hoch | 75 % |

**Fazit: 75–25 % SOC ist das Optimum** — beste Balance aus Lebensdauer und
Energieausbeute. Genau unser Einsatzbereich.

> *„Chalmers University of Technology, Sweden, reports that using a reduced
> charge level of 50% SOC increases the lifetime expectancy of the vehicle
> Li-ion battery by 44–130%."* — BatteryUniversity BU-808

#### Quelle 3: BatteryUniversity — Extrapolation bei 75–25 % SOC

> Figure 8 aus [BU-808](https://batteryuniversity.com/article/bu-808-how-to-prolong-lithium-based-batteries)

- Bei **75–25 % SOC**: Kapazität fällt erst nach **14.000 Zyklen** auf 74 %
- Bei 85–25 % SOC: 64 % nach 14.000 Zyklen
- Bei 100–25 % SOC: 48 % nach 14.000 Zyklen

#### Quelle 4: Wikipedia — LFP-spezifische Lebensdauer

> [Lithium iron phosphate battery — Wikipedia](https://en.wikipedia.org/wiki/Lithium_iron_phosphate_battery)

- Zyklenlebensdauer: **2.500–9.000+ Zyklen** (normale Bedingungen)
- Unter optimalen Bedingungen: **>10.000 Zyklen**
- Kalendarische Alterung (A123-Daten): *„17 % impedance growth and 23 %
  capacity loss in 15 years at 100 % SOC, 60 °C"*
- Thermische Stabilität: Thermal Runaway erst bei 270 °C (vs. 150 °C bei LiCoO₂)

#### Quelle 5: BatteryUniversity — Zusammenfassungstabelle LFP

> [BU-216: Summary Table of Lithium-based Batteries](https://batteryuniversity.com/article/bu-216-summary-table-of-lithium-based-batteries)

- LFP Zyklenlebensdauer: 1.000–2.000 (konservativ)
- Wartungshinweis: *„Keep cool; store partially charged; prevent full charge
  cycles, use moderate charge and discharge currents"*
- Anwendung: *„Stationary with high currents and endurance"*

### 6.5 Prognose: Verbleibende Lebensdauer

#### Realistische Betriebsweise — kein starres 50 % DoD

Die SOC-Grenzen 25–75 % sind **Komfortgrenzen**, nicht starr. In der Praxis:

- **Sommertage mit viel PV**: Batterie bleibt bei 75 %, weil die Ladung bis
  zum nächsten Morgen reicht — kein Grund tiefer zu entladen
- **Wintertage ohne PV**: Batterie bleibt bei 25 %, weil tagsüber zu wenig PV
  kommt, um sie nennenswert aufzuladen
- **Zellausgleich** (1×/Monat): Voller Zyklus 5–100 % = 100 % DoD
- **Übergangsmonate**: Algorithmus öffnet bei Bedarf auf 5 % bzw. 100 %

Saisonale Batterie-Nutzung (Durchschnitt 2024/2025):

| Monat | Ladung/Monat | Ø kWh/Tag | Ø DoD | Zyklen/Monat |
|-------|-------------:|----------:|------:|-------------:|
| Jan | 166 kWh | 5,5 | 54 % | 17 |
| Feb | 229 kWh | 7,6 | 75 % | 23 |
| Mär | 311 kWh | 10,4 | 102 % | 31 |
| Apr | 330 kWh | 11,0 | 108 % | 33 |
| Mai | 346 kWh | 11,5 | 113 % | 35 |
| Jun | 287 kWh | 9,6 | 94 % | 29 |
| Jul | 303 kWh | 10,1 | 99 % | 30 |
| Aug | 372 kWh | 12,4 | 122 % | 37 |
| Sep | 339 kWh | 11,3 | 111 % | 34 |
| Okt | 306 kWh | 10,2 | 100 % | 31 |
| Nov | 201 kWh | 6,7 | 66 % | 20 |
| Dez | 153 kWh | 5,1 | 50 % | 15 |

**Trend: ~300 Zyklen/Jahr** (2022: 252, 2023: 238, 2024: 312, 2025: 357).
Das 25/75-Fenster wird den Anstieg bremsen, aber der Wattpilot und steigende
Optimierung treiben die Nutzung nach oben. **300 Zyklen/Jahr als Prognose.**

#### Wieviele Zyklen hält die Batterie insgesamt?

Unser gemessener SOH-Verlauf: **8 % Verlust in ~1.200 Zyklen / 4,3 Jahren**.

> **Wichtiger Hinweis:** Die reale Entladetiefe schwankt zwischen 20 % (trüber
> Wintertag) und >120 % (Sommertag mit mehrfachem Laden/Entladen). Das
> entspricht NICHT dem Labor-Idealszenario „konstant 50 % DoD". Die
> BatteryUniversity-Tabellen gelten für gleichmäßige Zyklen — unsere gemischte
> Nutzung liegt zwischen den Laborszenarien.

Realistischste Schätzung aus **eigenen Messdaten**:

- Von 92 % auf 70 % = 22 % Verlust nötig
- Bisheriger Verlust: 0,67 % pro 100 Zyklen
- **22 % ÷ 0,067 %/Zyklus ≈ 3.300 verbleibende Zyklen**
- **3.300 ÷ 300 Zyklen/Jahr ≈ 11 Jahre**

| Meilenstein | SOH | Zyklen kumuliert | Geschätztes Datum |
|-------------|----:|-------------------:|-------------------|
| Heute | 92 % | ~1.200 | Feb 2026 |
| 85 % | 85 % | ~2.250 | ~2029 |
| 80 % | 80 % | ~3.000 | ~2032 |
| 75 % | 75 % | ~3.750 | ~2035 |
| **70 % (EOL)** | **70 %** | **~4.500** | **~2037** |

> ⚠️ **Achtung:** Der SOH-Verlauf ist typischerweise NICHT linear. LFP verliert
> anfangs schneller (Formierung, SEI-Schicht), dann folgt ein langes Plateau.
> Die 92 % nach 4 Jahren könnten bedeuten, dass das Plateau bereits erreicht
> ist und die Batterie die nächsten 10 Jahre nur noch langsam altert.
> Das spricht eher für **2036–2040** als EOL-Fenster.

#### Effekt der SOC-Umstellung 20/80 → 25/75

| Aspekt | Vorher (20–80) | Nachher (25–75) |
|--------|--------:|--------:|
| Komfort-DoD | 60 % | 50 % |
| LFP-Laborzyklenzahl bei konstantem DoD | ~1.500 | ~3.000 |
| Reale Wirkung | — | *gemischt* |

**Was bringt 25/75 wirklich?** Nicht die theoretische Verdopplung, weil:
1. An vielen Sommertagen wird die Batterie ohnehin nicht unter 75 % entladen
2. An vielen Wintertagen wird sie ohnehin nicht über 25 % geladen
3. Der Zellausgleich (1×/Monat, 5–100 %) bleibt
4. Der Algorithmus öffnet bei Bedarf auf 5 %/100 %

**Aber:** Die Komfortgrenzen vermeiden, dass die Batterie **dauerhaft** im
Stressbereich (<20 % oder >80 %) verweilt. Genau das ist der Hauptschaden-
faktor laut BatteryUniversity: *„Keeping a cell at a high charge voltage for
an extended time can be more stressful than cycling."* (BU-808, Tabelle 3)

**→ Realistisches Ziel: 15 Jahre Nutzungsdauer (bis ~2036), EOL bei ~70 % SOH.**

### 6.6 Wirtschaftlichkeit — Was die Batterie spart

#### Bisherige Ersparnis (gemessen)

| Jahr | Batterie-Entladung | Vermiedener Netzbezug | Ersparnis (0,30 €/kWh) |
|------|-------------------:|----------------------:|------------------------:|
| 2021 (ab Nov) | 182 kWh | 182 kWh | **55 €** |
| 2022 | 2.359 kWh | 2.359 kWh | **708 €** |
| 2023 | 2.236 kWh | 2.236 kWh | **671 €** |
| 2024 | 2.946 kWh | 2.946 kWh | **884 €** |
| 2025 | 3.390 kWh | 3.390 kWh | **1.017 €** |
| 2026 (bis Feb) | 215 kWh | 215 kWh | **64 €** |
| **Gesamt** | **11.328 kWh** | | **3.398 €** |

**Ø Ersparnis (volle Jahre 2022–2025): ~820 €/Jahr** bei 0,30 €/kWh.

> **Nulleinspeiser-Effekt:** Als Anlage ohne Einspeisevergütung geht jede kWh
> PV-Strom, die nicht verbraucht oder gespeichert wird, verloren. Ohne Batterie
> wären ~3.000 kWh/Jahr einfach abgeregelt worden. Die Batterie nutzt diese
> Energie statt sie zu verschwenden.

#### Hochrechnung: Wann hat sich die Batterie bezahlt?

Annahme: Anschaffungskosten BYD HVS 10.2 mit Installation ca. **8.000 €** (2021).

| Zeitraum | Kumulierte Ersparnis | Status |
|----------|---------------------:|--------|
| Ende 2022 | ~760 € | |
| Ende 2023 | ~1.430 € | |
| Ende 2024 | ~2.310 € | |
| Ende 2025 | ~3.330 € | |
| **Ende 2026** (Prognose) | **~4.150 €** | |
| Ende 2028 (Prognose) | ~5.800 € | |
| **Ende 2030** (Prognose) | **~7.400 €** | |
| **Ende 2031** (Prognose) | **~8.200 €** | **≈ Amortisation** |

**→ Amortisation nach ~10 Jahren (ca. 2031)**, danach Reingewinn.

Bei steigenden Strompreisen (0,35–0,40 €/kWh) verkürzt sich das auf 8–9 Jahre.

#### Argument für eine zweite Batterie (Erweiterung)

**Kosten:** BYD HVS 10.2 (identisch, an F1 anschließbar) ≈ **3.000 €**

**Aktuelles Problem:** Trotz Batterie kaufen wir noch **~3.700 kWh/Jahr** aus
dem Netz (Ø 2023–2025). Das sind **~1.100 €/Jahr** Stromkosten.

| Szenario | Netzbezug/Jahr | Kosten/Jahr | Ersparnis vs. heute |
|----------|---------------:|------------:|--------------------:|
| Heute (10,2 kWh) | ~3.700 kWh | ~1.110 € | — |
| Mit 2. Batterie (20,4 kWh) | ~2.000–2.500 kWh | ~600–750 € | **~400–500 €/Jahr** |

**Warum spart die 2. Batterie weniger als die 1.?** Die erste deckt bereits den
Hauptteil des Abendverbrauchs. Die zweite verlängert die Nachtüberbrückung,
aber in der langen Winternacht (17:00–08:00 = 15h × ~1 kW = 15 kWh) reichen
auch 20 kWh nicht immer.

**Amortisation zweite Batterie:**

| Strompreis | Ersparnis/Jahr | Amortisation 3.000 € |
|-----------:|---------------:|---------------------:|
| 0,30 €/kWh | ~400 €/Jahr | **~7,5 Jahre** |
| 0,35 €/kWh | ~500 €/Jahr | **~6 Jahre** |
| 0,40 €/kWh | ~600 €/Jahr | **~5 Jahre** |

#### Fazit: Lohnt sich die Erweiterung?

**Pro:**
- Gesamte Kapazität 20,4 kWh → Nachtverbrauch besser überbrücken
- Halbierung der Zyklenbelastung pro Batterie → längere Lebensdauer beider
- Netzbezug sinkt um ~1.200–1.700 kWh/Jahr
- Bei steigenden Strompreisen schnellere Amortisation
- Als Nulleinspeiser: Jede gespeicherte kWh, die sonst abgeregelt würde, spart
  direkt den vollen Strompreis (0,30+ €/kWh)

**Contra:**
- Amortisation erst nach 5–7 Jahren
- Im Sommer ist die 1. Batterie oft schon ausreichend
- Hauptnutzen nur in der Übergangszeit (Mär–Apr, Sep–Okt)

**Empfehlung:** Die Erweiterung auf 20,4 kWh ist wirtschaftlich vertretbar,
besonders wenn Strompreise weiter steigen. **Optimaler Zeitpunkt: Wenn der
Strompreis über 0,35 €/kWh steigt** oder wenn die erste Batterie unter
80 % SOH fällt (~2032). Dann lohnt sich die Investition am deutlichsten.

### 6.7 Empfehlungen

1. **SOC-Fenster 25–75 % beibehalten** — vermeidet Dauerstress, nicht starre DoD
2. **Zellausgleich 1× monatlich** weiterführen (5–100 %, nur bei >50 kWh Prognose)
3. **SOH jährlich dokumentieren** — Abweichung vom linearen Trend überwachen
4. **Temperatur beachten** — LFP altert bei >40 °C schneller (BYD HVS hat Kühlung)
5. **Batterie-Erweiterung bei ~80 % SOH evaluieren** (~2032) — zweite BYD HVS 10.2
   an F1, Kosten ~3.000 €, Amortisation 5–7 Jahre
6. **Strompreis beobachten** — bei >0,35 €/kWh wird die 2. Batterie attraktiver

### 6.8 Quellenverzeichnis

1. BatteryUniversity: [BU-808: How to Prolong Lithium-based Batteries](https://batteryuniversity.com/article/bu-808-how-to-prolong-lithium-based-batteries) — Tabellen 2, 3, 4; Figuren 6, 8. Quelle: Xu et al. (2016), Choi et al. (2002), TU München, Chalmers University. Stand: Oct 2023.
2. BatteryUniversity: [BU-216: Summary Table of Lithium-based Batteries](https://batteryuniversity.com/article/bu-216-summary-table-of-lithium-based-batteries) — Übersichtstabelle LFP-Eigenschaften.
3. Wikipedia: [Lithium iron phosphate battery](https://en.wikipedia.org/wiki/Lithium_iron_phosphate_battery) — Zyklenlebensdauer, kalendarische Alterung (A123-Daten).
4. BYD Battery-Box HVS Datenblatt — Nennkapazität, Spannungen, Lade-/Entladeleistung.
5. Eigene Messungen: PV-Anlage Erlau, Datenbank `data.db`, Tabelle `monthly_statistics` und `yearly_statistics`, Nov 2021 – Feb 2026.
