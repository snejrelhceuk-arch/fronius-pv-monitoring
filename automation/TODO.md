# TODO — Automation Projekt

> Stand: 2026-02-14

---

## Phase 0: Grundlagen (JETZT)

- [ ] **I2C aktivieren** auf Pi4 (`dtparam=i2c_arm=on` in /boot/config.txt)
- [ ] Pi4 Neustart nach I2C-Aktivierung
- [ ] `sudo pip3 install SMmegabas` — Python-Bibliothek installieren
- [ ] `megabas` CLI-Tool installieren (git clone + make install)
- [ ] Board-Erkennung testen: `megabas 0 board` / `python3 -c "import megabas; print(megabas.getVer(0))"`
- [ ] Firmware-Version prüfen (REV 3.3 ↔ Software-Version?)
- [ ] I2C-Adresse 0x48 auf Bus 1 bestätigen: `i2cdetect -y 1`

## Phase 1: Sensorik (Temperaturen)

- [ ] **Thermistoren beschaffen** (10K NTC, genauer Typ klären)
- [ ] Speichertemperatur oben (IN1) — verkabeln & kalibrieren
- [ ] Speichertemperatur mitte (IN2) — verkabeln & kalibrieren
- [ ] Speichertemperatur unten (IN3) — verkabeln & kalibrieren
- [ ] Außentemperatur (IN4) — verkabeln & kalibrieren
- [ ] Input-Typ per Software konfigurieren: `megabas 0 incfgwr <ch> 2` (10K Thermistor)
- [ ] Temperatur-Logging in Datenbank implementieren
- [ ] Temperatur-Anzeige im Web-Dashboard

## Phase 2: Heizpatrone (2 kW, 1-phasig)

> **Hinweis (2026-03-01):** Die HP-Steuerung wurde über **Fritz!DECT** realisiert
> (Software-Lösung, kein MEGA-BAS TRIAC erforderlich). Siehe `doc/TODO.md` §B5
> und `automation/STRATEGIEN.md` §2.6. Die Hardware-Phase (Schütz, TRIAC, Thermistoren)
> ist für spätere Erweiterungen (3-Phasen, Temperatur-Sensorik) weiterhin relevant.

- [ ] **Installationsschütz beschaffen** (24VAC-Spule, mind. 10A/250V für 2kW)
- [ ] 24VAC-Netzteil (bereits vorhanden durch MEGA-BAS Versorgung?)
- [ ] Optional: RC-Snubber über Schützspule (100Ω + 100nF für TRIAC-Langlebigkeit)
- [ ] Sicherheitstemperaturbegrenzer (STB) am Speicher prüfen/installieren
- [ ] Verkabelung: MEGA-BAS TRIAC AC1 → Schütz-Spule → Heizpatrone
- [ ] Software: `setTriac(0, 1, 1/0)` für Heizpatrone Ein/Aus
- [ ] Regellogik: PV-Überschuss + Temperatur < 80°C → EIN
- [ ] Hysterese implementieren (nicht ständig ein/aus schalten)
- [ ] Mindestlaufzeit / Mindestpausenzeit definieren

## Phase 2b: Klimaanlage (1,3 kW Split-Klima)

- [ ] **Installationsschütz beschaffen** (24VAC-Spule, mind. 10A/250V)
- [ ] Klären: Standby-Modus beibehalten oder Komplett-Trennung?
- [ ] Verkabelung: MEGA-BAS TRIAC AC2 → Klima-Schütz
- [ ] Regellogik: PV-Überschuss + Außentemperatur + Speicher-Temp → Klima EIN?
- [ ] Alternative: IR-Sender über Pi (feinere Steuerung möglich)

## Phase 3: Bypass-Ventil

- [ ] Stellantrieb für Bypass beschaffen/prüfen (24VAC?)
- [ ] Verkabelung: MEGA-BAS TRIAC AC2 → Bypass-Stellantrieb
- [ ] Logik: Bypass EIN (nur oben) vs. AUS (ganzer Speicher)
- [ ] Jahreszeitabhängige Strategie implementieren

## Phase 4: Lüftungsanlage & Brandschutzklappen

- [ ] Brandschutzklappe 1 — elektr. Spezifikation prüfen
- [ ] Brandschutzklappe 2 — elektr. Spezifikation prüfen
- [ ] Klären: 24VAC Stellantriebe oder andere Spannung?
- [ ] Rückmeldekontakte verkabeln (Dry Contact IN6, IN7)
- [ ] Lüftungsgerät — Steuerungsmöglichkeiten prüfen (0-10V? Relais?)
- [ ] Frostschutzlogik implementieren
- [ ] Luftqualitätssensor evaluieren

## Phase 5: WP-Integration (Dimplex SIK 11 TES)

- [x] **WP-Modell identifiziert:** Dimplex SIK 11 TES (Sole/Wasser, 11kW th., 2,1kW el.)
- [x] **🔥 LWPM 410 Modbus-RTU-Modul (Art.Nr. 339410, ~155€) — ✅ BESTELLT (2026-02-14)**
- [ ] **WPM-Reglerversion am Gerät prüfen!** (LCD=WPM_L/H, Touch=WPM_M)
- [ ] **Softwarestand ablesen** (kompatibel ab H_H50, SG-Ready ab L20.2)
- [ ] **Steckplatz "Serial Card / BMS Card" prüfen** (vorhanden?)
- [ ] LWPM 410 in WPM einbauen (spannungsfrei!)
- [ ] RS485-Kabel MEGA-BAS ↔ LWPM 410 verlegen (A→A, B→B, 120Ω Term.)
- [ ] `pymodbus` installieren + Modbus-RTU-Test-Script schreiben
- [ ] Register-Scan: Alle Temperaturen auslesen (R1-R9, R24)
- [ ] SG-Ready via Modbus testen (Coil 3 + Coil 4 schreiben)
- [ ] WW-Solltemperatur via Modbus setzen (Register 5047)
- [ ] Betriebsmodus via Modbus umschalten (Register 5015)
- [ ] Täglichen Pflichtlauf absichern (Kompressor-Schmierung)
- [ ] Modbus-Daten in SQLite-DB loggen (neue Tabelle `wp_modbus`)

## Phase 6: Software-Integration

- [ ] `automation_control.py` als zentraler Steuerungsdaemon
- [ ] Anbindung an bestehende DB (Automation-Tabellen in data.db)
- [ ] Dashboard-Erweiterung: Automation-Tab in Web-UI
- [ ] Logging & Alerting (Temperatur-Alarms, Fehler)
- [ ] Watchdog konfigurieren (Hardware-WDT der MEGA-BAS)

## Phase 7: 3-Phasen-Heizpatrone (Zukunft)

- [ ] 3-Phasen-Schütz (24VAC-Spule)
- [ ] Eventuell stufenweises Zuschalten (1→2→3 Phasen) je nach Überschuss
- [ ] Dafür reicht 1 TRIAC wenn alle 3 Phasen über 1 Schütz geschaltet werden
- [ ] Oder: 3 Schütze + 3 TRIACs für stufenweise Leistungsregelung

---

## Offene Entscheidungen

| # | Frage | Optionen | Status |
|---|-------|----------|--------|
| 1 | Thermistor-Typ | 10K NTC B3950? Oder 1K? | Offen |
| 2 | Schütz-Typ für Heizpatrone | Finder? Schneider? Leistung? | Offen |
| 3 | WPM-Version der SIK 11 TES | **Am Gerät prüfen!** LCD=L/H, Touch=M | **🚨 DRINGEND** |
| 4 | Brandschutzklappen-Antriebe | Spannung? Strom? Typ? | Offen |
| 5 | Lüftungsgerät-Steuerung | 0-10V? Relais? Modbus? | Offen |
| 6 | Fritz!DECT in Übergangsphase? | Sofort nutzbar, aber Einschränkungen | ✅ **Produktiv seit 2026-03-01** |
| 7 | 24V**AC**-Versorgung für TRIACs | Trafo nötig, oder besser Eight Relays HAT? | **Eight Relays HAT!** |
| 8 | LWPM 410 vs. NWPM | ✅ **LWPM 410 bestellt!** RS485 via MEGA-BAS |
| 9 | TRIACs nutzbar? | 24VDC-Bus → TRIACs funktionieren NICHT ohne AC-Quelle | **Eight Relays HAT bevorzugt** |
