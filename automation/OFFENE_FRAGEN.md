# Offene Fragen — Automation

> Stand: 2026-02-14
> Diese Fragen müssen für die weitere Planung geklärt werden.

---

## Dringende Fragen (Phase 0–2)

### F1: Wärmepumpen-Modell? — ✅ GEKLÄRT
**Modell: Dimplex SIK 11 TES** (Sole/Wasser, 11 kW th., 2,1 kW el., max. 4,3 kW)

(Quelle: [doc/PV_REFERENZSYSTEM_DOKUMENTATION.md](../doc/PV_REFERENZSYSTEM_DOKUMENTATION.md))

**🔥 Modbus RTU via LWPM 410 (Art.Nr. 339410, ~155€) — ✅ BESTELLT (2026-02-14)**
- SG-Ready steuerbar per Modbus (Coil 3 + Coil 4, ab WPM_L20.2)
- Alle Temperaturen lesbar (Warmwasser, Vorlauf, Rücklauf, Sole, Außen)
- Betriebsmodus schreibbar (Sommer/Auto/Heizen/Kühlen)
- Warmwasser-Solltemperatur schreibbar (Register 5047, 10–85°C)
- Doku: https://dimplex.atlassian.net/wiki/spaces/DW/pages/2873393288/NWPM+Modbus+TCP

**Noch zu prüfen am Gerät (KRITISCH für Kompatibilität):**
- **WPM-Reglerversion?** LCD-Display = WPM L/H, Touch = WPM M
- **Softwarestand?** Im Menü ablesen (z.B. `WPM_L23.7` oder `WPM_H60`)
- **Steckplatz "Serial Card / BMS Card"** im WPM vorhanden?
- Kompatibel lt. Doku: WPM 2004/2006/2007/EconPlus, ab Software H_H50
- **HA-Community:** SIW 8TES (gleiche SI-Familie) erfolgreich angebunden

### F2: Externer Warmwasser-Temperatursensor der WP
- Welcher Typ? (NTC 10K? PT1000? Herstellerspezifisch?)
- Wo sitzt er? (Tauchhülse? Anlegefühler?)
- Widerstandskurve bekannt?
- Ist eine Manipulation realistisch und sicher?

### F3: Heizpatrone — ✅ GEKLÄRT
**Leistung: 2 kW, 1-phasig 230V**

(Quelle: [doc/PV_REFERENZSYSTEM_DOKUMENTATION.md](../doc/PV_REFERENZSYSTEM_DOKUMENTATION.md) — Verbrauch 2025: 2.614 kWh)

**Aktuelle Schaltung (bestätigt):**
- 230V-Versorgung über **Fritz!DECT Steckdose** (Primärschaltung)
- Steuerung über **24V-Relais** mit **2 Temperatursensoren**
- **NICHT am WPM-Ausgang E9** (Flanschheizung) angeschlossen!

**Noch offen:**
- 24V-Relais: AC oder DC? (→ mit 24VDC-Bus vermutlich DC-Relais!)
- Typ/Modell der 2 Temperatursensoren?
- Fritz!DECT Steckdose: Welches Modell? (Fritz!DECT 200/210?)
- Soll Fritz!DECT langfristig ersetzt werden oder als Sicherheits-Backup bleiben?
- **Kann das Eight Relays HAT das 24V-Relais direkt ansteuern?** (Ja, wenn DC-Relais)

### F4: 24VAC-Versorgung — ✅ GEKLÄRT (nicht vorhanden!)

**Im Haus gibt es einen 24VDC-Bus.** Kein 24VAC-Trafo vorhanden.

**Konsequenz für MEGA-BAS TRIACs:**
- TRIACs sind AC-Halbleiterschalter (benötigen Nulldurchgang zum Abschalten)
- **TRIACs sind KEINE potentialfreien Kontakte** — sie schalten inline in der AC-Leitung
- Ohne AC-Quelle im Lastkreis → **TRIACs sind nicht nutzbar**
- Max. TRIAC-Spannung laut User's Guide v4.2: **120V** (nicht nur 24V!)
- Aber 230V europäische Netzspannung → trotzdem zu hoch

**Lösung: Sequent Microsystems Eight Relays HAT (~$45)**
- 8 potentialfreie Relais-Kontakte, 4A/120VAC, schaltbar AC und DC
- Stackbar auf demselben Pi
- Siehe README.md §4 für I/O-Zuordnung

### F5: Brandschutzklappen — Stellantriebe
- Hersteller / Modell?
- Betriebsspannung? (24VAC? 230VAC?)
- Stromaufnahme?
- Federzug-Rückstellung (Sicherheitsposition bei Stromausfall)?
- Rückmeldekontakt vorhanden?
### F5b: Klimaanlage (Split-Klima, 1,3 kW)
- Hersteller / Modell?
- Kann das Gerät per Schütz nur den Leistungsteil geschaltet werden?
  (Standby-Modus beibehalten, damit Einstellungen nicht verloren gehen)
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
