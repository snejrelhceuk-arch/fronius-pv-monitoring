# A/B/C Trennungspolicy — Datenbank, Web-API, Automatisierung

**Stand:** 21. Februar 2026  
**Status:** Governance-Dokument (dokumentierend, ohne Laufzeitwirkung)  
**Geltungsbereich:** Architekturentscheidungen und künftige Änderungen im Repo `pv-system`

---

## 1. Ziel und Nicht-Ziel

### Ziel
Eine klare, sichere Aufgabentrennung zwischen:
- **A Datenbank**
- **B Web-API**
- **C Automatisierung**

damit bei weiterem Ausbau der Automatisierung keine ungewollten Querwirkungen,
Schreibkonflikte oder Sicherheitslücken entstehen.

### Nicht-Ziel
- Keine sofortige Umstrukturierung des produktiven Codes.
- Keine Änderungen an laufenden Services, Cron-Jobs oder Berechtigungen in diesem Schritt.

Diese Version hat **rein dokumentierende Funktion**.

---

## 2. Grundprinzipien

1. **Single Write Owner für Aktorik:**
   Schreibende Eingriffe in WR/Modbus erfolgen ausschließlich durch **C Automatisierung**.

2. **No Side Effects in Read APIs:**
   **B Web-API** dient primär der Darstellung/Abfrage. Lese-Endpoints sollen keine
   Nebenwirkungen (DB-Write, Gerätezugriff, Zustandsänderung) auslösen.

3. **Datenbank als Plattform, nicht als Entscheidungsort:**
   **A Datenbank** stellt Persistenz, Konsistenz, Backup und Replikation sicher,
   trifft aber keine fachlichen Steuerentscheidungen.

4. **Rollen- und Betriebsgrenzen bleiben bindend:**
   Die bestehende `primary`/`failover`-Logik bleibt Sicherheitsanker
   (siehe `host_role.py`, `scripts/role_guard.sh`, `doc/DUAL_HOST_ARCHITECTURE.md`).

---

## 3. Verantwortungsmatrix (A/B/C)

## A — Datenbank

**Verantwortet:**
- Schema, Migration, Datenintegrität
- tmpfs/Persist-Strategie, Backup, Mirror
- DB-Performance-Basisparameter

**Darf:**
- Tabellen anlegen/ändern (kontrolliert)
- Persistenz- und Restore-Prozesse bereitstellen
- Konsistenzprüfungen auf Datenebene durchführen

**Darf nicht:**
- Automatisierungsentscheidungen treffen
- Gerätezustände steuern
- UI-/API-Fachlogik enthalten

## B — Web-API

**Verantwortet:**
- Read-Model für Dashboards und externe Clients
- Aggregierte Ausgaben, Status-Ansichten, Diagnose-Ausgaben

**Darf:**
- DB lesen
- Caches für Antwortzeiten nutzen
- Berechnete Ansichten rendern

**Darf nicht (Zielbild):**
- Modbus/WR schreiben
- Scheduler-Entscheidungen ausführen
- Persistente Business-Writes in GET-Endpunkten durchführen

## C — Automatisierung

**Verantwortet:**
- Scheduler-Logik, Schutzregeln, Aktorik
- Modbus-/API-Schreibzugriffe Richtung Wechselrichter/Peripherie
- Operational Logs der Entscheidungen

**Darf:**
- explizite Writes in DB (Audit/State) und zu Aktoren
- Fail-safe, Retry, Konsistenzchecks

**Darf nicht:**
- API-Darstellungslogik übernehmen
- DB-Backup-/Mirror-Verantwortung übernehmen

---

## 4. Aktueller Ist-Befund (Kurz)

Die Trennung ist bereits teilweise umgesetzt:
- Rollen-Gating (`.role`) und Failover-Schutz sind etabliert.
- Web-API ist überwiegend read-orientiert.

Aktuell erkennbare Vermischung (architektonisch relevant):
- Forecast-API triggert Persistierung in DB (Write-Side-Effect im API-Pfad).
- Einzelne Initialisierungen in der Web-Schicht übernehmen DB-nahe Aufgaben.

**Bewusste Code-Duplikation (ABC-konform):**
- `RawModbusClient` (modbus_v3.py, Schicht A) — **nur Lesen**, kein `write`-Capability.
- `ModbusClient` (battery_control.py, Schicht C) — Lesen + Schreiben für Aktorik.
- Die Duplikation des Socket-Codes ist gewollt: Der Collector (A) soll keine
  Schreibfähigkeit besitzen. Eine gemeinsame Klasse würde dem Collector unnötige
  Write-Capability geben — Verstoß gegen Prinzip 1 (Single Write Owner).

Das ist **kein akuter Betriebsfehler**, aber ein wichtiger Ansatzpunkt für
saubere zukünftige Entkopplung.

---

## 5. Sicherheitsrationale

Warum diese Trennung bei wachsender Automatisierung wichtig ist:

- **Begrenzte Blast-Radius pro Schicht:**
  Ein Problem in B führt nicht direkt zu Aktorik-Writes.

- **Nachvollziehbarkeit:**
  Steuerentscheidungen sind eindeutig C zugeordnet und auditierbar.

- **Failover-Stabilität:**
  Passive Hosts bleiben wirklich passiv, wenn Write-Pfade klar zentralisiert sind.

- **Wartbarkeit:**
  Änderungen an Visualisierung gefährden nicht unbeabsichtigt Schutz- und Steuerlogik.

---

## 6. Entscheidungskriterien für künftige Änderungen

Bei jeder neuen Funktion zuerst prüfen:

1. **Wo liegt der Write-Owner?**
   - Wenn Geräte-/Steuer-Writes: immer C.

2. **Hat ein Read-Endpunkt Side-Effects?**
   - Wenn ja: in C-Job oder expliziten Write-Pfad verschieben.

3. **Ist Failover-Verhalten eindeutig?**
   - Muss auf `failover` sicher no-op sein, wenn es aktorisch ist.

4. **Ist die Änderung auditierbar?**
   - Aktionen und Gründe müssen in C-Logs nachvollziehbar bleiben.

---

## 7. Doku-Only Einführungsmodus (jetzt)

Aktueller Schritt ist bewusst ohne Produktionswirkung:

- Keine Service-Neustarts
- Keine Codepfad-Änderungen
- Keine Rechte-/User-Änderungen
- Keine Cron-Anpassungen

Nutzen jetzt:
- Gemeinsame Entscheidungsgrundlage für kommende PRs/Änderungen
- Konsistente Architekturbegriffe (A/B/C) im Team und mit LLM-Unterstützung

---

## 8. Nächste sinnvolle Folge-Schritte (später, optional)

1. **Policy-Checkliste in PR-Reviews nutzen**
2. **Write-Side-Effects aus B schrittweise nach C verlagern**
3. **A/B/C-Kontrakt als kurzes Kapitel in `SYSTEM_ARCHITECTURE.md` pflegen**
4. **Automation-Engine gemäß 4-Schichten-Architektur aufbauen**
   → Siehe [AUTOMATION_ARCHITEKTUR.md](AUTOMATION_ARCHITEKTUR.md)

Diese Folge-Schritte sind absichtlich **nicht Teil** dieser dokumentierenden Änderung.

---

## 9. Abgrenzung zu Veröffentlichung/Compliance

Diese A/B/C-Policy ist **rein technisch-architektonisch**. Regeln zu
Veröffentlichung, Urheberrecht, Nutzungsrechten, Kommunikation nach außen und
Compliance-Prozessen stehen zentral in:

- `doc/VEROEFFENTLICHUNGSRICHTLINIE.md`

Damit bleibt die Trennung sauber:
- **Technische Systemgrenzen** in dieser Datei
- **Recht/Veröffentlichung/Compliance** in der separaten Richtlinie
