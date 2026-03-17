# WP-Register (Herstellerdoku)

Stand: 2026-03-17  
Quelle: Dimplex NWPM Modbus TCP (Herstellerdokumentation)

## 1. Geltungsbereich

Diese Datei fasst Register aus der Herstellerdoku strukturiert zusammen.
Fokus: fuer die PV-Automation relevante Datenpunkte (Monitoring + Stellgroessen).

Wichtig:
- Die Herstellerdoku unterscheidet Adressen je nach WPM-Softwarestand.
- Spalten in den Tabellen:
  - Adresse J/L/M
  - Adresse H
- Wenn eine Adresse in einer Spalte fehlt, ist sie dort laut Doku nicht angegeben.

## 2. Protokoll und Funktionscodes

| Typ | Zugriff | Funktionscode | Modbus-Funktion |
|---|---|---|---|
| Digital | R | 01 (0x01) | Read Coils |
| Analog | R | 03 (0x03) | Read Holding Register |
| Digital | W | 05 (0x05) | Write Single Coil |
| Analog | W | 06 (0x06) | Write Single Register |
| Digital | W | 15 (0x0F) | Write Multiple Coils |
| Analog | W | 16 (0x10) | Write Multiple Registers |

## 3. Live-Betriebsdaten (5.1 Betriebsdaten)

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W | Einheit | Lokaler Status |
|---|---:|---:|---|---|---|---|
| Aussentemperatur (R1) | 1 | 27 | Float16 | R | degC | ungetestet |
| Ruecklauf (R2) | 2 | 29 | Float16 | R | degC | Lesen ok |
| Ruecklauf-Soll | 53 | 28 | Float16 | R | degC | Lesen ok, Schreiben nicht angenommen |
| Warmwasser-Ist (R3) | 3 | 30 | Float16 | R | degC | Lesen ok |
| Warmwasser-Soll (Betriebsdaten) | 58 | 40 | Float16 | R | degC | ungetestet |
| Vorlauf (R9) | 5 | 31 | Float16 | R | degC | Lesen ok |
| Waermequellen-Eintritt (R24) | 6 | - | Float16 | R | degC | Lesen ok |
| Waermequellen-Austritt (R6) | 7 | 41 | Float16 | R | degC | Lesen ok |
| Solltemperatur 2. Heizkreis | 54 | 32 | Float16 | R | degC | ungetestet |
| Solltemperatur 3. Heizkreis | 55 | 34 | Float16 | R | degC | ungetestet |

## 4. Status und Stoerungen (5.5 Displayanzeigen)

| Datenpunkt | Adresse L/M | Adresse J | Adresse H | Typ | R/W | Bereich |
|---|---:|---:|---:|---|---|---|
| Statusmeldungen | 103 | 43 | 14 | uint16 | R | 0..30 |
| Waermepumpe Sperre | 104 | 59 | 94 | uint16 | R | 1..42 |
| Stoermeldungen | 105 | 42 | 13 | uint16 | R | 1..31 |
| Sensorikcode | 106 | - | - | uint16 | R | 1..27 |

## 5. Historie und Laufzeiten (5.2 Historie)

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W | Einheit |
|---|---:|---:|---|---|---|
| Verdichter 1 Laufstunden | 72 | 64 | uint16 | R | h |
| Verdichter 2 Laufstunden | 73 | 65 | uint16 | R | h |
| Primaerpumpe/Ventilator | 74 | 66 | uint16 | R | h |
| 2. Waermeerzeuger (E10) | 75 | 67 | uint16 | R | h |
| Heizungspumpe (M13) | 76 | 68 | uint16 | R | h |
| Warmwasserpumpe (M18) | 77 | 69 | uint16 | R | h |
| Flanschheizung (E9) | 78 | 70 | uint16 | R | h |
| Schwimmbadpumpe (M19) | 79 | 71 | uint16 | R | h |
| Waermemenge Heizen 1-4 | 5096 | 5101 | uint16 | R | kWh |
| Waermemenge Heizen 5-8 | 5097 | 5102 | uint16 | R | kWh |
| Waermemenge Heizen 9-12 | 5098 | 5103 | uint16 | R | kWh |
| Waermemenge WW 1-4 | 5099 | 5104 | uint16 | R | kWh |
| Waermemenge WW 5-8 | 5100 | 5105 | uint16 | R | kWh |
| Waermemenge WW 9-12 | 5101 | 5106 | uint16 | R | kWh |

Hinweis zur Berechnung laut Doku:
Waermemenge = (9-12 * 100000000) + (5-8 * 10000) + (1-4)

## 6. Einstellungen (5.3)

### 6.1 Modus

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W | Bereich |
|---|---:|---:|---|---|---|
| Betriebsmodus | 5015 | 5007 | uint16 | R/W | 0..5 |
| Anzahl Partystunden | 5016 | 5008 | uint16 | R/W | 0..72 h |
| Anzahl Urlaubstage | 5017 | 5009 | uint16 | R/W | 0..150 d |

Betriebsmodus-Codierung:
- 0 Sommer
- 1 Auto
- 2 Urlaub
- 3 Party
- 4 2. Waermeerzeuger
- 5 Kuehlen

### 6.2 Warmwasser

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W | Bereich | Lokaler Status |
|---|---:|---:|---|---|---|---|
| WW-Hysterese | 5045 | 5004 | uint16 | R/W | 2..15 K | ungetestet |
| WW-Solltemperatur | 5047 | 5022 | uint16 | R/W | Solltemp.Min..85 degC | Lesen/Schreiben ok |
| WW-Solltemperatur Minimal | 5145 | - | uint16 | R/W | 10..Solltemp | ungetestet |
| WW-Solltemperatur Maximal | 5048 | - | uint16 | R/W | Solltemp..85 degC | ungetestet |

### 6.3 1. Heizkreis (Auszug)

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W | Bereich |
|---|---:|---:|---|---|---|
| Parallelverschiebung | 5036 | 5002 | uint16 | R/W | 0..38 |
| Raumtemperatur | 46 | 21 | uint16 | R/W | 15.0..30.0 degC |
| Festwertsolltemperatur | 5037 | 5003 | uint16 | R/W | 18..60 degC |
| Heizkurvenendpunkt | 5038 | 5015 | uint16 | R/W | 20..70 degC |
| Hysterese | 47 | 22 | uint16 | R/W | 0.5..5.0 K |
| Solltemp. dyn. Kuehlung | 5043 | 5024 | uint16 | R/W | 10..35 degC |

## 7. Smart Grid / SG Ready (6.2)

### 7.1 WPM_L20.2 bis WPM_L23.7 (Coils)

| Datenpunkt | Adresse | Typ | R/W |
|---|---:|---|---|
| Smart Grid 1 | 3 | Coil | R/W |
| Smart Grid 2 | 4 | Coil | R/W |

Zustandsmatrix:

| Zustand | SG1 | SG2 |
|---|---:|---:|
| rot | 0 | 1 |
| gelb | 0 | 0 |
| gruen | 1 | 0 |
| dunkelgruen | 1 | 1 |

Wirkung laut Herstellerdoku:
- rot: abgesenkter Betrieb
- gelb: Normalbetrieb
- gruen: verstaerkter Betrieb
- dunkelgruen: Leistungsstufe 3, inkl. elektrischer Waermeerzeuger

### 7.2 ab WPM_M1.3 (Register)

| Datenpunkt | Adresse | Typ | R/W | Bereich |
|---|---:|---|---|---|
| Smart_Grid_extern | 5167 | uint16 | R/W | 0..13 |

Codierung laut Herstellerdoku:
- 0 Hardwareeingang
- 10 gelb
- 11 gruen
- 12 rot
- 13 dunkelgruen

## 8. Zeitfunktionen (5.4, Multiplexer)

| Datenpunkt | Adresse | Typ | R/W | Hinweis |
|---|---:|---|---|---|
| Zeitfunktionsauswahl (Multiplexer) | 5065 | uint16 | R/W | Schaltet Ziel-Funktion um |
| Zeitfenster Start/Ende | 5066..5073 | uint16 | R/W | Stunden/Minuten |
| Wochenprogramm | 5074..5080 | uint16 | R/W | So..Sa |
| Wert/Funktion | 5081 | uint16 | R/W | Abhaengig vom Modus |

## 9. Eingaenge und Ausgaenge

### 9.1 Eingaenge (5.6)

| Datenpunkt | Adresse J/L/M | Adresse H | Typ | R/W |
|---|---:|---:|---|---|
| Warmwasserthermostat | 3 | 57 | Coil | R |
| Schwimmbadthermostat | 4 | 58 | Coil | R |
| EVU-Sperre | 5 | 56 | Coil | R |
| Sperre Extern | 6 | 63 | Coil | R |

Hinweis: Laut Hersteller nicht beschreibbar (nur Zustand lesen).

### 9.2 Ausgaenge (5.7, Auszug)

| Datenpunkt | Adresse J/L | Adresse H | Typ | R/W |
|---|---:|---:|---|---|
| Verdichter 1 | 41 | 80 | Coil | R |
| Verdichter 2 | 42 | 81 | Coil | R |
| Primaerpumpe/Ventilator | 43 | 82 | Coil | R |
| Flanschheizung (E9) | 50 | 89 | Coil | R |
| Heizungspumpe (M14) | 59 | 94 | Coil | R |
| Kuehlpumpe (M17) | 60 | 99 | Coil | R |

Hinweis: Laut Hersteller nicht beschreibbar (nur Zustand lesen).

## 10. Lokale Verifikation (PV-System)

Sicher verifiziert am System:
- Lesen: 2, 3, 5, 6, 7, 53, 5047
- Lesen/Schreiben: 5037 erfolgreich (37 -> 38 -> 37)
- Schreiben: 5047 erfolgreich
- Schreiben: 53 nicht angenommen
- Reset-Test erfolgreich: 5037=37 und 5047=55 wiederhergestellt

Beobachtung aus Test:
- Schreiben auf 5037 aendert Register 5037, aber nicht den Live-Lesewert in 53.
- 53 ist damit im Betrieb mindestens als Anzeige-/Betriebswert zu betrachten,
  nicht als direktes Spiegelregister von 5037.
- Bei Sollwertwechsel kann die Uebernahme in API/Anzeige verzoegert erscheinen.

Empfehlung fuer Integration:
- Setting Heizung: Register 5037 schreiben.
- Anzeige Heizung (effektiver Betriebs-Sollwert): Register 53 lesen.
- Optional UI: beide Werte anzeigen ("Heiz-Soll gesetzt"=5037, "Heiz-Soll aktiv"=53).

Noch offen im Systemtest:
- 5015 (Betriebsmodus)
- SG-Ready (Coil 3/4 bzw. 5167 je nach WPM-Stand)
- WW-Hysterese 5045

## 11. WW-Nachtabsenkung (Automation)

Seit 2026-03-17 steuert die Regel `ww_absenkung` das Register **5047** (WW-Soll)
zeitgesteuert ueber den Automation-Engine Fast-Zyklus (1 min).

### 11.1 Parameter (soc_param_matrix.json)

| Parameter | Default | Bereich | Beschreibung |
|---|---:|---|---|
| standard_temp_c | 57 | 55–62 degC | WW-Soll Tageswert |
| absenkung_k | 5 | 1–10 K | Absenkung gegenueber Standard |
| start_h | 23 | 20–23 Uhr | Beginn Nachtmodus |
| ende_h | 3 | 0–5 Uhr | Ende Nachtmodus |

### 11.2 Ablauf

- **Ab start_h**: Engine erkennt Ist-Soll ≠ Nacht-Soll, Score=45 →  
  Aktor `waermepumpe` setzt Register 5047 auf `standard_temp_c - absenkung_k`  
  (Default: 57 - 5 = **52 degC**)
- **Ab ende_h**: Engine erkennt Ist-Soll ≠ Tag-Soll, Score=45 →  
  Aktor `waermepumpe` setzt Register 5047 auf `standard_temp_c`  
  (Default: **57 degC**)
- Toleranz ±1 degC verhindert Pendeln bei Modbus-Rundung

### 11.3 Dateien

| Datei | Rolle |
|---|---|
| automation/engine/regeln/waermepumpe.py | RegelWwAbsenkung (Bewertung + Aktionen) |
| automation/engine/aktoren/aktor_waermepumpe.py | AktorWaermepumpe (Modbus-Schreiber) |
| wp_modbus.py | write_register() mit Whitelist (5047, 5037) |
| config/soc_param_matrix.json | Regelkreis ww_absenkung (Parameter) |

## 12. Quellen

- Herstellerdoku: NWPM Modbus TCP (Dimplex Atlassian)
- Projektbezug:
  - doc/automation/WP_INTEGRATION.md
  - doc/automation/TODO.md
  - wp_modbus.py
  - tools/wp_test_sollwerte.py
