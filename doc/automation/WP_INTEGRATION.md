# WP-Integration — Dimplex SIK 11 TES

**Stand:** 2026-03-17

---

## 1. Hydraulik: Schichtenspeicher mit Durchlauferhitzung

| Aspekt | Detail |
|--------|--------|
| **Speichertyp** | Schichtenspeicher mit totem Heizungswasser |
| **WW-Bereitung** | Durchlauferhitzung via Edelstahlwellrohr (von unten nach oben) |
| **Unterer Bereich** | Heizungswasser — Rücklauf-Solltemperatur (Standard 37 °C) |
| **Oberer Bereich** | WW-Zone — Solltemperatur am externen Sensor (Standard 55 °C) |

### Thermische Wechselwirkung

Das Wellrohr durchläuft den Speicher von unten nach oben:

1. Im unteren Bereich (Heizungszone) wird das aufsteigende Trinkwasser
   vorgewärmt durch das umgebende Heizungswasser.
2. Im oberen Bereich (WW-Zone) erfolgt die finale Erwärmung auf Soll.
3. **Konsequenz:** Wird die Heizungs-Rücklauftemperatur abgesenkt,
   sinkt die Vorwärmung unten → WW-Zone muss mehr Arbeit leisten
   → häufigere WP-Starts.

### Absenkpotential Heizungstemperatur

| Außentemperatur | Rücklauf-Soll | Effekt |
|-----------------|---------------|--------|
| < 5 °C | 37 °C (Standard) | Volle Heizleistung |
| > 5 °C | 35 °C möglich | Effizientere Wärmebereitstellung |
| > 15 °C | 30 °C möglich | Deutlich besserer COP, aber weniger WW-Vorwärmung |

**Trade-off:** Niedrigere Vorlauftemp. = besserer COP, aber häufigere
Kompressorstarts wegen WW-Nachheizung (Scroll-Verschleiß).

---

## 2. Verfügbare WP-Daten (Modbus RTU, produktiv)

Vollständiger, strukturierter Registerkatalog aus der Herstellerdoku:
`doc/automation/WP_REGISTER.md`

### 2.1 Verifizierte Register (`wp_modbus.py` + Schreibtest)

| Feldname | Register | Einheit | Auflösung | Lesen | Schreiben | Beschreibung |
|----------|----------|---------|-----------|-------|-----------|--------------|
| `vorlauf` | 5 | °C | 0.1 | ✅ | - | Vorlauftemperatur |
| `ruecklauf` | 2 | °C | 0.1 | ✅ | - | Rücklauftemperatur (≈ unterer Speicherbereich) |
| `ruecklauf_soll` | 53 | °C | 0.1 | ✅ | ❌ | Rücklauf-Sollwert (Heizkurve), Schreibtest nicht angenommen |
| `ww_ist` | 3 | °C | 0.1 | ✅ | - | WW-Isttemperatur (externer Sensor, oberer Speicher) |
| `quelle_ein` | 6 | °C | 0.1 | ✅ | - | Sole-Eintritt (Erdwärme rein) |
| `quelle_aus` | 7 | °C | 0.1 | ✅ | - | Sole-Austritt (nach WP) |
| `ww_soll` | 5047 | °C | 1 | ✅ | ✅ | WW-Solltemperatur (ganzzahlig), Schreibtest erfolgreich |

### 2.2 Abgeleitete Signale

| Signal | Berechnung | Nutzen |
|--------|------------|--------|
| **WW-Delta** | `ww_soll − ww_ist` | Indikator für bevorstehenden WP-Start (WW-Bereitung) |
| **Heiz-Delta** | `ruecklauf_soll − ruecklauf` | Indikator für Heizbedarf |
| **Spreizung** | `vorlauf − ruecklauf` | Wärmeabgabe-Indikator |
| **Sole-Delta** | `quelle_ein − quelle_aus` | Entzugsleistung der Erdsondenanlage |
| **COP-Näherung** | `(vorlauf + 273) / (vorlauf − quelle_ein)` | Carnot-Schätzung als Plausibilitätscheck |

### 2.3 WP-Leistungsdaten (SmartMeter, produktiv)

Unabhängig von Modbus RTU liefert der Fronius SmartMeter (Unit 4) bereits:

| ObsState-Feld | Quelle | Beschreibung |
|---|---|---|
| `wp_power_w` | `P_WP` (raw_data) | Aktuelle WP-Leistung [W] |
| `wp_active` | `P_WP > 200W` | WP läuft gerade (bool) |
| `wp_power_avg30_w` | `AVG(P_WP_avg)` 30 min | Gleitender Mittelwert |
| `wp_today_kwh` | `SUM(W_Imp_WP_delta)` | Tagesverbrauch [kWh] |

---

## 3. Verifizierte Stellgröße

| Stellgröße | Register | Wirkung |
|---|---|---|
| `heiz_soll` setzen | 5037 | Heizungs-Sollwert schreiben |
| `heiz_soll` aktiv anzeigen | 53 | Effektiver Betriebs-Sollwert (kann zeitverzögert folgen) |
| `ww_soll` ↑ (z.B. 55→58 °C) | 5047 | WP-Start triggern bei PV-Überschuss |
| `ww_soll` ↓ (z.B. 55→50 °C) | 5047 | WP-Start verzögern |

Hinweis: Weitere Stellgrößen (SG-Ready Coils, Betriebsmodus 5015) stehen im
`TODO.md`, bis die exakte Wirkung und Schreibbarkeit am System verifiziert ist.

**Kompressor-Schutz:** WPM schützt Scroll-Kompressor intern
(Mindest-Ein/Auszeiten, täglicher Pflichtlauf für Schmierung).
Automation darf nicht dagegen arbeiten.

---

## 4. Integrationsstatus

| Bereich | Status | Modul |
|---------|--------|-------|
| Modbus-RTU-Lesung | ✅ Produktiv | `wp_modbus.py` |
| Web-UI (Flow-View) | ✅ Anzeige läuft | `templates/flow_view.html` |
| API-Endpunkt | via `/api/battery_status` | `routes/system.py` |
| ObsState (SmartMeter) | ✅ 4 Felder | `data_collector.py` |
