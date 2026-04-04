# Umsetzungsplan — Diagnos D

**Stand:** April 2026  
**Status:** Roadmap (In Planung)  
**Aktueller Stand:** Phase 0 abgeschlossen (Begriffe, Rollenmodell), Phase 1 teilweise umgesetzt (health.py).

---

## Phase 0 — Begriffe und Grenzen

**Ziel:** Doku konsolidieren, Rollenmodell freigeben.

Ergebnisse:
- `ABCD_ROLLENMODELL.md`
- `doc/diagnos/` als eigener Planungsbereich
- klare Regel: keine Kalender-Restarts des Collectors

---

## Phase 1 — Leichte Read-only Checks

**Ziel:** Basis-Health ohne Betriebsrisiko.

Umfang:
- Prozess- und Freshness-Checks
- CPU-/Unterspannungs-Checks
- Datentraegerbelegung lokal
- Mirror-/Backup-Alter

Ausgabe:
- RAM-Logs
- Mail-Warnungen
- einfacher Statusreport

---

## Phase 2 — Integritaet und Parity

**Ziel:** Daten- und Systemkonsistenz regelmaessig beweisen.

Umfang:
- SQL-Invarianten
- Config-Parse und Checksummen
- systemd-/Cron-/Git-Parity
- Gap-Klassifikation

Ausgabe:
- taeglicher Diagnos-Bericht
- Eskalationshistorie

---

## Phase 3 — Infrastruktur und I/O

**Ziel:** Aussenkanten des Systems gezielt beobachten.

Umfang:
- Fronius Modbus / HTTP Reachability
- Fritz!Box-API Reachability
- Wattpilot-Status pruefbar, aber kollisionsarm
- SSH / LAN / Remote-Backup Host
- MEGA-BAS / RS485 sobald aktiv

---

## Phase 4 — Gezielte Schutzaktionen

**Ziel:** begrenzte, nachvollziehbare Reaktionen auf klar definierte Fehler.

Umfang:
- Cooldown-gesicherter Neustart einzelner Hilfsdienste
- Incident-Reports mit Handlungsempfehlung
- optional spaeter: Reboot-Freigabelogik fuer eng definierte Hard-Faults

Bedingung:
- erst nach laengerer Beobachtung und dokumentierter Fehlklassifikation

---

## Phase 5 — Langzeitspeicher auf Pi5

**Ziel:** SD-Schreiblast klein halten, Historie auf SSD verlagern.

Umfang:
- verdichtete Diagnos-Berichte nach Pi5
- Trenddaten, Alarmhistorie, Parity-Snapshots
- keine lauten Dauerwrites auf dem Primary

---

## Abnahmefrage je Phase

Vor dem Weitergehen immer klaeren:

1. Was wird nur gelesen?
2. Was wird geschrieben?
3. Was passiert bei Fehlalarm?
4. Ist die Massnahme auf dem Failover identisch nachvollziehbar?