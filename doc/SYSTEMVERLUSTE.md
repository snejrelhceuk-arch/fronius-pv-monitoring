# Systemverluste: DC-Generator vs. AC-Zähler

## Problemstellung

Solarweb zeigt für `gesamt_prod_kwh` (Jahresübersicht) systematisch **höhere** PV-Erträge
als unser System (`solar_erzeugung_kwh`). Die Differenz beträgt 2–4 % pro Jahr.

**Ursache:** Solarweb misst die DC-Generator-Leistung (vor Inverter), unser System misst
die AC-Leistung (nach Inverter). Die Differenz sind die **Systemverluste** im Inverter.

## Energiefluss-Kette

```
PV-Module (DC)
    │
    ├─► MPP-Tracker 1 (DC1)  ─┐
    └─► MPP-Tracker 2 (DC2)  ─┤
                               │
                      DC-Bus ◄─┤◄── Batterie (BHM) ──►
                               │
                      Inverter (DC→AC Wandlung, η ≈ 96%)
                               │
                      AC-Sammelschiene
                               │
    ┌──────────────────────────┤
    │           │              │             │
SmartMeter   F2(AC)         F3(AC)    Wattpilot(AC)
(Netz)    Generator2     Generator3   E-Auto
```

### Messpunkte

| Messpunkt | Quelle | Zähler | Einheit |
|-----------|--------|--------|---------|
| ① DC Generator (F1) | Fronius GEN24 intern | `W_DC1` + `W_DC2` | Wh (Lifetime) |
| ② AC Inverter (F1) | Fronius GEN24 intern | `W_AC_Inv` | Wh (Lifetime) |
| ③ F2 Generator | SmartMeter Kanal F2 | `W_Exp_F2` | Wh (Lifetime) |
| ④ F3 Generator | SmartMeter Kanal F3 | `W_Exp_F3` | Wh (Lifetime) |
| ⑤ Netz (Import/Export) | SmartMeter Netz | `W_Imp_Netz` / `W_Exp_Netz` | Wh (Lifetime) |

### Was Solarweb zeigt

- **gesamt_prod (Jahres-CSV)** = DC-Ertrag aller Generatoren (vor Inverter)
- **gesamt_prod (Tages-CSV)** = AC-Ertrag (gleiche Basis wie unser System!)
- Die Diskrepanz entsteht nur in der **Jahresübersicht**.

## Quantifizierung

### Methode 1: Solarweb Jahres-DC vs. Archiv-AC (alle Generatoren)

| Jahr | DC (Solarweb) | AC (Archiv) | Verlust | η System |
|------|---------------|-------------|---------|----------|
| 2022 | 9.470 kWh | 9.267 kWh | 203 kWh | 97,9 % |
| 2023 | 10.100 kWh | 9.798 kWh | 302 kWh | 97,0 % |
| 2024 | 12.440 kWh | 11.986 kWh | 454 kWh | 96,3 % |
| 2025 | 16.330 kWh | 15.940 kWh | 390 kWh | 97,6 % |
| **Σ** | **48.340 kWh** | **46.991 kWh** | **1.349 kWh** | **97,2 %** |

**Quelle DC:** `imports/solarweb/solarweb_yearly_2021-26_working.csv` (Feld `gesamt_prod_kwh`)
**Quelle AC:** `backup/data_{YYYY}.csv` (Feld `solar_erzeugung_kwh`), identisch mit `monthly_statistics`

### Methode 2: Fronius Lifetime-Zähler (nur F1 = GEN24 Hybrid)

Stand 2026-02-22:
- W_DC1 (MPP1): 12.563 kWh
- W_DC2 (MPP2):  5.204 kWh
- **DC F1 total: 17.767 kWh**
- W_AC_Inv:     17.067 kWh
- **Verlust F1: 700 kWh**
- **η F1 = 96,1 %**

**⚠ Einschränkung:** W_AC_Inv enthält auch Batterie-Durchsatz (DC-Bus ist shared).
Bei Batterie-Entladung fließt Batt→DC→AC, was den AC-Zähler erhöht.
Der wahre Solar-η liegt daher etwas **unter** 96,1 % (geschätzt ~95 %).

### Methode 3: Archiv-interne Bilanzkontrolle

```
solar_AC = einspeisung + batt_ladung + direktverbrauch + wattpilot
```

Da Solarweb die Postenaufschlüsselung DC-basiert berechnet (direkt = prod − einsp − batt),
ist die Summe der Posten > solar_AC:

| Jahr | solar_AC | Σ(Posten) | Δ | ≈ Verlust |
|------|----------|-----------|---|-----------|
| 2022 | 9.267 | 9.428 | −161 | 203 |
| 2023 | 9.798 | 10.109 | −311 | 302 |
| 2024 | 11.986 | 12.438 | −452 | 455 |
| 2025 | 15.940 | 16.318 | −378 | 390 |

Die Bilanz-Differenz (Δ) approximiert die Systemverluste unabhängig!

## Verlust-Quellen

1. **Inverter DC→AC Wandlung** (Hauptursache): η ≈ 95–97 %
   - Schaltungsverluste (MOSFETs/IGBTs)
   - Transformator-Verluste
   - Eigenverbrauch der Steuerelektronik
2. **MPP-Tracker Verluste**: Bereits im DC-Zähler enthalten (vor W_DC1/W_DC2)
3. **DC-Kabelverluste**: Minimal (kurze Wege, Module → Inverter)
4. **F2/F3 Generatoren**: Eigene Inverter-Verluste, aber kein DC-Zähler verfügbar
5. **Batterie-Durchsatz**: Entladung geht nochmals durch den Inverter (Doppel-Verlust)
6. **Standby-Verbrauch**: Inverter nachts ≈ 5 W × 12h = 60 Wh/Tag ≈ 22 kWh/Jahr

## Verfügbare Datenquellen

| Quelle | Granularität | Abdeckung | DC-seitig? |
|--------|-------------|-----------|------------|
| Solarweb Jahres-CSV | Jährlich | Alle Generatoren | ✅ `gesamt_prod_kwh` = DC |
| Solarweb Tages-CSV | Täglich | Alle Generatoren | ❌ `gesamt_prod_kwh` = AC |
| `solarweb_referenz.json` | Monatlich | Alle Generatoren | ❌ Archiv-AC Kopie |
| Fronius W_DC1 + W_DC2 | Momentaufnahme | Nur F1 | ✅ DC-Zähler (Lifetime) |
| data_1min W_DC_delta | 1 Minute | Nur F1 | ✅ Aber Batt-Durchsatz verzerrt |

## Bewertung und Entscheidung

### Solarweb: Generator-orientierte Zählung (DC)

Fronius Solarweb zählt die **DC-Generator-Leistung** – also das, was die PV-Module
theoretisch erzeugen, bevor Inverter-Wandlung, Kabel- und Betriebsverluste abgezogen werden.
Diese Darstellung überhöht den tatsächlich nutzbaren Ertrag systematisch um 2–4 %.

### Unser System: Verbraucher-orientierte Zählung (AC)

Unser System misst am **AC-Sammelschiene** – also das, was tatsächlich beim Verbraucher
ankommt. Diese Zählung ist **ehrlich und nachprüfbar**: Sie entspricht den SmartMeter-Werten
und damit der physikalischen Realität am Einspeisepunkt.

### Warum wir bewusst bei AC bleiben

Die Differenz zwischen DC-Generator und AC-Verbraucher hat viele Ursachen:
- Inverter DC→AC Wandlungsverluste (η ≈ 96–98 %)
- Kabel- und Standby-Verluste
- Wolken, Verschattung, Degradation, Neigung, Ausrichtung

**Die Sonne stellt keine Rechnung.** Was die Generatoren liefern, ist irrelevant –
entscheidend ist, was beim Verbraucher ankommt. Ob nun 203 kWh oder 454 kWh im Inverter
„verloren" gehen: Diese Verluste zu beziffern hat keinen wirtschaftlichen oder praktischen
Nutzen. Die PV-Module liefern was sie liefern – wir nehmen, was wir bekommen, und stellen
es wahrheitsgemäß dar.

> **Entscheidung (2026-02-22):** Keine Anpassung der Statistiken. Unsere AC-basierte
> Zählung ist korrekt, ehrlich und konsistent. Die Solarweb-DC-Überhöhung wird als
> bekannte Abweichung dokumentiert, aber nicht in unsere Darstellung übernommen.

## Fazit

- Die Solarweb-Jahresübersicht zeigt DC-Werte → systematisch 2–4 % höher als unser AC
- Unsere `solar_erzeugung_kwh` = AC-Wert = SmartMeter-Realität → **korrekt**
- Systemverluste betragen **2,1–3,7 %** pro Jahr (η = 96,3–97,9 %)
- 4-Jahres-Durchschnitt: **η = 97,2 %** (1.349 kWh von 48.340 kWh verloren)
- Fronius Lifetime-Zähler bestätigen: **η_F1 = 96,1 %**
- Archiv-Bilanzkontrolle bestätigt den Verlust unabhängig (−161 bis −452 kWh/Jahr)
- **Kein Handlungsbedarf:** Verluste sind physikalisch unvermeidbar und wirtschaftlich irrelevant
