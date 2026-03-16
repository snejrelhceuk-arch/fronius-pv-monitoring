# MEGA-BAS Modbus-Referenz — Projektkurzfassung

**Stand:** 16. Maerz 2026  
**Status:** Projektinterne Kurzreferenz

---

## 1. Zweck

Die MEGA-BAS-Platine kann ueber ihren RS485-Port als Modbus-RTU-Geraet betrieben
werden. Fuer das PV-System ist das derzeit **nur vorbereitete Option**, noch kein
produktiver Pfad.

---

## 2. Relevanz fuer dieses Projekt

Moegliche kuenftige Einsaetze:

- lokale Sensorik (Temperaturen, Kontakte)
- Feldbus-Anbindung fuer Zusatzhardware
- saubere Trennung zwischen Pi-seitiger Logik und externer Peripherie

Nicht vorgesehen:

- generische Modbus-Dokumentation fuer das ganze Projekt
- duplizierte Vollabschrift der Hersteller-Registertabellen

---

## 3. Operative Merkpunkte

- RS485-Konfiguration erfolgt ueber das `megabas`-CLI
- Adressierung haengt von der Stack-Konfiguration ab
- Register-Details sollen im Betrieb nur fuer die tatsaechlich genutzten Kanaele
  ins Projekt uebernommen werden

---

## 4. Projektregel

Wenn MEGA-BAS spaeter produktiv genutzt wird, dann werden nur folgende Inhalte
projektspezifisch dokumentiert:

1. benoetigte Kanaele
2. konkrete Register oder Kommandos
3. Polling-/Timing-Regeln
4. Schutz- und Fail-Safe-Verhalten

Die vollstaendige Herstellerreferenz bleibt extern.

---

## 5. Externe Quelle

Offizielle Herstellerdokumentation und CLI-/Library-Details bitte direkt bei
Sequent Microsystems bzw. im offiziellen `megabas-rpi`-Repository nachsehen.