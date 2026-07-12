# Netzqualität — Offene Aufgaben & Gedanken

**Stand:** 2026-04-02

---

## TODO: Datenreduktion für Visualisierung

**Problem:** Die API liefert aktuell 5min-Mittelwerte aus raw_data (~288 Punkte/Tag).
Mittelwerte sind für Netzqualität oft kontraproduktiv:

- Frequenz-Nadirs an 15min-Grenzen dauern 5–15 Sekunden → im 5min-AVG unsichtbar
- Spannungssprünge (3V in 3s bei Lastsprung) → verwässert auf ~0,02V im Mittel
- Die drei L-L-Spannungen liegen eng beieinander (Spread ~3V bei ~414V) → noch flacher

**Lösung:** Pro 5min-Bucket nicht nur AVG, sondern:

| Kennwert | Zweck |
|----------|-------|
| `avg` | Grundniveau |
| `min` / `max` | Fängt Nadirs und Spikes — die interessanten Events |
| `spread` (max−min) | Volatilität: ruhiger Block ~0,02 Hz, wilder Block ~0,08 Hz |
| `std` | Unterscheidet "flach bei 49,95" von "zappelig um 50,00" |
| Letzter Wert vor Blockgrenze | Entscheidend für DFD-Erkennung |

**Visualisierung:** Bänder (min/max als Fläche) + Mittelwert als Linie.
→ 28.000 Samples → ~288 Datenpunkte, ohne Extrema zu verlieren.

---

## ERLEDIGT: Schleifenimpedanz-Bestimmung ✓

**Ziel:** Netz-Schleifenwiderstand bestimmen, um lokale Spannungseffekte
(eigener Strombezug) von netzseitigen Spannungsänderungen zu trennen.

**Methode:**
1. HP-Schaltvorgänge (Heizpatrone) aus `schaltlog.txt` mit raw_data korreliert
2. HP = rein ohmisch (cos φ = 1) → ΔU/ΔI liefert direkt **R**
3. WP-Events (Wattpilot, 3-phasig, induktiv) liefern **Z_eff = R cos φ + X sin φ**
4. Aus R (HP) und Z_eff (WP) → X aufgelöst

**HP-Identifikation:**
- Phase: **L1** (72 von 73 Events, 1 Ausreißer auf L3)
- Ø |ΔI| = 7,9 A (typisch für 2kW-Heizpatrone)

**Ergebnisse (2026-04-02, 7 Tage Daten):**

| Größe | Wert | Methode |
|-------|------|---------|
| **R** | 163 mΩ | Median aus 71 HP-Events (IQR 130–211 mΩ) |
| **X** | 251 mΩ | Abgeleitet aus WP-Events (Z_eff=296 mΩ, PF_WP=0,43) |
| **\|Z\|** | 299 mΩ | √(R² + X²) |
| **R/X** | 0,6 | Typisch für Niederspannung mit längerer Kabelstrecke |

**Kompensationsbeispiele:**

| Lastsprung | ΔI | ΔU (berechnet) |
|------------|-----|----------------|
| HP ein/aus | 8,7 A | 1,41 V |
| WP Start | 5 A | 1,48 V |
| Wallbox 10A | 10 A | 1,96 V |

**Physik (Kompensationsformel):**
```
U_netz_bereinigt = U_gemessen − I_lokal × (R cos φ + X sin φ)
```
- Ohmische Lasten (HP): U_korr = U_mess − I × R (nur R relevant, X×sin0=0)
- Induktive Lasten (WP): U_korr = U_mess − I × Z_eff (R und X relevant)

**Status:** ✅ Abgeschlossen 2026-04-02. Werte bereit für Kompensation in API.

---

## TODO: Erweiterte API (Phase 2)

- API um min/max/std pro Bucket erweitern
- Chart mit Bändern (ECharts areaStyle)
- Bereinigte Spannungswerte (nach Schleifenimpedanz-Kompensation)
- 15min-Blockgrenzen als vertikale Marker im Chart
