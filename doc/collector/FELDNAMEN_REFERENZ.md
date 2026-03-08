# Feldnamen-Referenz

> **Energiefluss-Modell**: Siehe [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) Abschnitt 2.

## ⚠️ KRITISCH: W_AC_Inv ≠ PV-Erzeugung!

W_AC_Inv misst den AC-Ausgang des Hybrid-Wechselrichters F1. Da die Batterie
DC-seitig am selben Inverter hängt, **inkludiert W_AC_Inv Batterie-Entladung
und exkludiert Batterie-Ladung**:

```
W_AC_Inv = W_DC1 + W_DC2 + Batt_Entladung - Batt_Ladung
```

**Reine PV-Erzeugung = W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3**

## Wichtig: Namenskonventionen

### Datenbank (data.db)
- **Tabelle**: `data_1min`
- **Zeitstempel**: `ts` (REAL, Unix-Timestamp)
- **Konvention**: Großbuchstaben mit Unterstrichen (z.B. `P_Direct`, `W_Ertrag`)

### API/JSON Output
- **Zeitstempel**: `timestamp` (Unix-Timestamp im JSON)
- **Konvention**: Kleinbuchstaben mit Unterstrichen (z.B. `p_direct`, `w_ertrag`)

---

## Feldnamen-Mapping: Datenbank → API/JSON

### Zeitstempel
| Datenbank | API/JSON | Beschreibung |
|-----------|----------|--------------|
| `ts` | `timestamp` | Unix-Timestamp (Sekunden seit 1970) |

### Leistungswerte (Momentanwerte)
| Datenbank | API/JSON | Einheit | Beschreibung |
|-----------|----------|---------|--------------|
| `P_AC_Inv_avg` | - | W | WR Ausgangsleistung F1 (Durchschnitt) |
| `P_DC_Inv_avg` | - | W | WR DC-Eingangsleistung F1 |
| `P_DC1_avg` | - | W | String 1 Leistung |
| `P_DC2_avg` | - | W | String 2 Leistung |
| `P_Netz_avg` | - | W | SmartMeter Netz (+ Bezug, - Einspeisung) |
| `P_F2_avg` | - | W | WR F2 Ausgangsleistung |
| `P_F3_avg` | - | W | WR F3 Ausgangsleistung |
| `P_WP_avg` | - | W | Wärmepumpe Leistung |
| `SOC_Batt_avg` | `soc` | % | Batterie-Ladezustand |

### Berechnete Leistungswerte (aus aggregate_1min.py)
| Datenbank | API/JSON (Ertrag) | API/JSON (Verbrauch) | Einheit | Beschreibung |
|-----------|-------------------|----------------------|---------|--------------|
| `P_Direct` | `p_direct_ertrag` | `p_direct_verbrauch` | W | Direktverbrauch PV |
| `P_inBatt_PV` | `p_inbatt_pv` | - | W | Batterieladung aus PV |
| `P_inBatt_Grid` | - | - | W | Batterieladung aus Netz |
| `P_Exp` | `p_exp` | - | W | Einspeisung ins Netz |
| `P_Imp` | - | `p_imp` | W | Netzbezug |
| `P_outBatt` | - | `p_outbatt` | W | Batterieentladung |
| - | `p_produktion` | - | W | **Berechnet**: P_DC1 + P_DC2 + P_F2 + P_F3 |
| - | - | `p_haushalt` | W | **Berechnet**: P_Direct + P_outBatt + P_Imp |

### Energiewerte (Delta-Werte pro Minute / data_1min)
| Datenbank | Einheit | Beschreibung |
|-----------|---------|---------------|
| `W_AC_Inv_delta` | Wh | WR F1 AC-Energie (inkl. Batterie-AC) |
| `W_DC1_delta` | Wh | String 1 Energie (aus P_DC1 integriert) |
| `W_DC2_delta` | Wh | String 2 Energie (aus P_DC2 integriert) |

### Energiewerte (Delta-Werte pro 15min / data_15min, hourly_data, data_monthly)
| Datenbank | Einheit | Beschreibung |
|-----------|---------|---------------|
| `W_PV_total_delta` | Wh | **Gesamt-PV** = DC1+DC2+F2+F3 (reine PV-Erzeugung) |
| `W_DC1_delta` | Wh | String 1 Energie (Counter-Delta) |
| `W_DC2_delta` | Wh | String 2 Energie (Counter-Delta) |
| `W_Exp_Netz_delta` | Wh | Einspeisung (aus P_Exp integriert) |
| `W_Imp_Netz_delta` | Wh | Netzbezug (aus P_Imp integriert) |
| `W_Exp_F2_delta` | Wh | F2 Energie (aus P_F2 integriert) |
| `W_Exp_F3_delta` | Wh | F3 Energie (aus P_F3 integriert) |

### Energiewerte (Kumulative Werte)
| Datenbank | Einheit | Beschreibung |
|-----------|---------|--------------|
| `W_Ertrag` | Wh | **Summe**: W_DC1 + W_DC2 + W_F2 + W_F3 |
| `W_Einspeis` | Wh | Einspeisung ins Netz |
| `W_Bezug` | Wh | Netzbezug |
| `W_Direct` | Wh | Direktverbrauch PV |
| `W_inBatt` | Wh | Batterieladung gesamt |
| `W_inBatt_PV` | Wh | Batterieladung aus PV |
| `W_inBatt_Grid` | Wh | Batterieladung aus Netz |
| `W_outBatt` | Wh | Batterieentladung |
| `W_Verbrauch` | Wh | **Berechnet**: W_Ertrag - W_Einspeis + W_Bezug |

---

## ⚠️ KRITISCH: Solarweb-Wattpilot ≠ Unser Wattpilot

**Solarweb** zeigt unter `wattpilot_kwh` ausschließlich den **PV-Direkt-Anteil** der
E-Auto-Ladung — also nur den Strom, der direkt von der PV-Anlage zum Wattpilot fließt.
Der vom Netz bezogene Anteil der EV-Ladung erscheint in Solarweb **NICHT** als
`wattpilot_kwh`, sondern geht unsichtbar im allgemeinen Netzbezug unter.

**Unser System** zählt schlicht den **Gesamtverbrauch des Wattpilot** — also alles,
was der Wattpilot verbraucht, egal ob aus PV oder Netz. Gemessen wird am
dedizierten SmartMeter (`wattpilot_daily.energy_wh`). Keine Aufteilung nach Quelle.

### Konsequenzen für den Solarweb-Abgleich

| Feld | Solarweb-Bedeutung | Unser System |
|------|-------------------|--------------|
| `wattpilot_kwh` | Nur PV→EV (Solar-Direktanteil) | Gesamtverbrauch des Wattpilot (egal ob PV oder Netz) |
| `direkt_kwh` | PV→Haus **ohne** Wattpilot | PV→Alles **inkl.** Wattpilot (`W_PV_Direct`) |
| `netzbezug_kwh` | Inkl. Netz→EV (aber nicht separat) | Gesamter Netzbezug (inkl. Netz→EV) |

### Richtige Vergleichsformeln

```
# Solarweb → Unser System: Direktverbrauch
solarweb.direkt + solarweb.wattpilot  ≈  unser.W_PV_Direct / 1000

# Solarweb-Wattpilot hat keinen eigenständigen Vergleichswert!
# Unser wattpilot_daily enthält MEHR (den Netz-Anteil zusätzlich).
# Deshalb: Solarweb-WP nur als Bestandteil von Direktverbrauch verwenden.
```

### Beim Import (import_solarweb_daily.py)

Das Script rechnet korrekt: `W_PV_Direct = (direkt + wattpilot) × 1000`
Damit geht der Solarweb-WP-Anteil im Direktverbrauch auf. Ein separater
Vergleich von `wattpilot_kwh` zwischen Solarweb und unserem System ist
**sinnlos**, da die Messbasis verschieden ist.

---

## Häufige Fehlerquellen

### ❌ Falsch: SQL mit "timestamp"
```sql
SELECT timestamp FROM data_1min WHERE timestamp > 1234567890
```

### ✅ Richtig: SQL mit "ts"
```sql
SELECT ts FROM data_1min WHERE ts > 1234567890
```

### ❌ Falsch: JSON-Feldnamen in SQL
```python
cursor.execute("SELECT p_direct FROM data_1min")  # Feld existiert nicht!
```

### ✅ Richtig: DB-Feldnamen in SQL, umbenennen für JSON
```python
cursor.execute("SELECT P_Direct FROM data_1min")
return {'p_direct': row[0]}  # Lowercase für JSON
```

---

## Power-Integration (seit 6.2.2026)

**Problem**: SmartMeter-Zähler haben unregelmäßige Updates (5-20 Min)

**Lösung**: Alle Delta-Energiewerte aus Leistung berechnen:

```python
W_delta = (P_avg * 60) / 3600  # Wh pro Minute
```

**Betrifft** (in aggregate_1min.py):
- Zeile 150-151: `W_DC1_delta`, `W_DC2_delta` → IMMER aus Power
- Zeile 157-159: `W_Exp_Netz_delta`, `W_Imp_Netz_delta` → aus `P_Exp`, `P_Imp`
- Zeile 163-165: `W_Exp_F2_delta`, `W_Exp_F3_delta` → aus `P_F2`, `P_F3`

---

## Automation-Felder (ObsState)

Die Automation-Engine verwendet `ObsState` als zentrales Beobachtungsobjekt.
Folgende Felder werden aus `raw_data` gelesen und in ObsState abgebildet:

### Netz-Phasenströme (ab 2026-03-08)

| raw_data-Feld | ObsState-Feld | Einheit | Quelle | Beschreibung |
|---------------|---------------|---------|--------|--------------|
| `I_L1_Netz` | `i_l1_netz_a` | A | SmartMeter Netz (F1) | Phasenstrom L1 (positiv=Bezug) |
| `I_L2_Netz` | `i_l2_netz_a` | A | SmartMeter Netz (F1) | Phasenstrom L2 |
| `I_L3_Netz` | `i_l3_netz_a` | A | SmartMeter Netz (F1) | Phasenstrom L3 |
| — | `i_max_netz_a` | A | berechnet | `max(I_L1, I_L2, I_L3)` — für SLS-Schutz (35A/Phase) |

**Verwendung:** `RegelSlsSchutz` prüft `i_max_netz_a >= 35A` als primäre
Überlastbedingung. Fallback bei fehlenden Phasenströmen: `grid_power_w > 24000W`.

> **Hinweis:** Die Felder `I_L1_Netz`, `I_L2_Netz`, `I_L3_Netz` werden von
> `modbus_v3.py` über Modbus TCP vom SmartMeter gelesen und in `raw_data`
> gespeichert. Die Werte sind vorzeichenbehaftet (positiv=Bezug, negativ=Einspeisung).

---

## Änderungshistorie

- **8. Mär 2026**: Netz-Phasenströme (I_L1/L2/L3_Netz) und Automation-ObsState-Felder dokumentiert
- **8. Feb 2026**: Dokument erstellt nach Systemcheck
- **6. Feb 2026**: Power-Integration für F2/F3 und Netz implementiert
- **5. Feb 2026**: Power-Integration für W_DC1/W_DC2 implementiert
