# Diagnos-Konzept — Schicht D

**Stand:** 16. Maerz 2026  
**Status:** Planungsdokument

---

## 1. Zielbild

**D Diagnos** ist die read-only Schicht fuer:

- Host-Gesundheit
- Datenintegritaet
- Freshness und Gap-Erkennung
- Parity zwischen Hosts, Configs und Services
- Kapazitaet von RAM, SD und SSD
- Alarmierung und Berichtswesen

Diagnos soll das Produktionssystem **nicht ersetzen**, sondern dessen Zustand
beweisen und begruendet eskalieren.

---

## 2. Grenzen

Diagnos darf standardmaessig:

- lesen
- vergleichen
- klassifizieren
- loggen
- melden

Diagnos darf standardmaessig nicht:

- technische Messwerte rekonstruieren
- Zeitreihen interpolieren
- kalenderbasiert Collector oder Host neu starten
- fachliche Entscheidungen der Automation ersetzen

---

## 3. Beobachtungsfelder

1. **Host** — Temperatur, Unterspannung, Throttling, RAM, Load, Kernel-Fehler
2. **Datentraeger** — Belegung, Schreibfehler, Backup-Alter, Wachstum
3. **Services** — systemd-Status, Crash-Loops, Timer, Cron, Single-Instance
4. **Datenfluss** — Freshness von `raw_data`, `data_1min`, `data_15min`, Mirror, Backup
5. **Integritaet** — Counter-Konsistenz, Aggregations-Invarianten, Gap-Scan
6. **Parity** — Configs, systemd-Units, Cron, Git-Stand, Rollenstatus
7. **I/O und Netz** — LAN, SSH, API, Modbus, RS485, Fritz!Box, Wattpilot, MEGA-BAS
8. **Berichte** — Tagesstatus, Trends, Eskalationshistorie, Mail-Versand

---

## 4. Betriebsprinzip

Diagnos arbeitet in drei Ebenen:

1. **leichte Dauerpruefungen** — sehr haeufig, rein lesend
2. **tiefe Integritaetspruefungen** — periodisch, SQL- und Parity-basiert
3. **Eskalationspruefungen** — nur bei Auffaelligkeit, gezielt erweitert

---

## 5. Ziel fuer die Realisierung

Die Schicht D soll so umgesetzt werden, dass sie:

- auf Pi4 und spaeter Pi5 identisch funktioniert
- moeglichst wenig auf SD schreibt
- Langzeithistorie bevorzugt auf Pi5/SSD ablegt
- schrittweise eingefuehrt werden kann, ohne A/B/C umzubauen

Details stehen in den Begleitdokumenten dieses Ordners.