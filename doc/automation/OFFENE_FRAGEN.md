# Offene Fragen — Automation

> Stand: 2026-04-04

Geklärte Fragen (F1: WP-Modell, F3: Heizpatrone, F4: 24VAC/DC) sind abgeschlossen
und in der jeweiligen Fachdokumentation dokumentiert. Siehe:
- WP-Modell → automation/README.md §2.3 + doc/meta/PV_REFERENZSYSTEM_DOKUMENTATION.md
- Heizpatrone → automation/README.md §2.1
- 24VDC-Bus / TRIAC-Problem → automation/README.md §1.2

---

## Noch offen

### F2: Externer Warmwasser-Temperatursensor der WP
- Welcher Typ? (NTC 10K? PT1000? Herstellerspezifisch?)
- Wo sitzt er? (Tauchhülse? Anlegefühler?)
- Widerstandskurve bekannt?

### F5: Brandschutzklappen — Stellantriebe
- Hersteller / Modell?
- Betriebsspannung? (24VAC? 230VAC?)
- Stromaufnahme?
- Federzug-Rückstellung (Sicherheitsposition bei Stromausfall)?
- Rückmeldekontakt vorhanden?

### F5b: Klimaanlage (Split-Klima, 1,3 kW)
- Hersteller / Modell?
- Kann das Gerät per Schütz nur den Leistungsteil geschaltet werden?
- Oder muss komplett getrennt werden?
- Infrarot-Fernbedienung → IR-Sender über Pi als Alternative?
---

## Mittelfristige Fragen (Phase 3–5)

### F6: Lüftungsanlage
- Hersteller / Modell des Lüftungsgeräts?
- Steuerungsmöglichkeiten? (Stufenschalter? 0-10V? Modbus?)
- Aktuell manuelle Steuerung oder bereits automatisch?

### F7: Bypass-Ventil am Speicher
- Motorventil oder Magnetventil?
- Betriebsspannung?
- Federzug-Rückstellung? (Welche Position bei Stromausfall?)

### F8: Luftqualitätssensor
- Schon vorhanden? Oder geplant?
- Typ? (CO2? VOC? Feinstaub?)
- Ausgang? (0-10V? 4-20mA? Digital?)

### F9: E-Auto-Batterie Verfügbarkeit
- Wie wird der E-Auto-SOC aktuell erkannt?
- Wattpilot meldet Ladestatus? Oder anderer Datenpunkt?
- Wann ist "leere E-Auto-Batterie zur Verfügung"?

---

## Strategische Fragen (Phase 6+)

### F10: Prioritäten bei PV-Überschuss
Wie soll die Reihenfolge sein? Vorschlag:
1. Batterie laden (bis SOC-Schwelle?)
2. E-Auto laden (wenn verfügbar und SOC niedrig)
3. Heizpatrone (wenn Speicher < 80°C)
4. Netz-Einspeisung (= 0 bei Nulleinspeiser)

Oder lieber dynamisch je nach Jahreszeit?

### F11: Nacht-Strategie
- Batterie-Entladung für Haushalt (bestehend via battery_control.py)
- WP-Pflichtlauf wann nachts? (Günstigster Zeitpunkt?)
- Lüftung nachts reduzieren?

### F12: Alarme & Benachrichtigungen
- Bei Übertemperatur (>80°C) — wie benachrichtigen?
- Bei MEGA-BAS-Ausfall — wie erkennen?
- Push-Notification? E-Mail? Web-Dashboard?
