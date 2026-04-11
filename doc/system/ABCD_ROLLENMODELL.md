# A/B/C/D/E Rollenmodell — Collector, Web, Automation, Diagnos, Steuerbox

**Stand:** 11. April 2026  
**Status:** Governance-Dokument (dokumentierend, ohne Laufzeitwirkung)  
**Geltungsbereich:** Architekturentscheidungen und künftige Änderungen im Repo `pv-system`

---

## 1. Zweck

Das Rollenmodell beschreibt die fünf Systembereiche mit ihren klaren Grenzen:

- **A Collector-Pipeline** — Erfassung, Aggregation, Datenfluss
- **B Web-API** — Darstellung, API, Read-Model
- **C Automation** — Regeln, Entscheidungen, Aktorik
- **D Diagnos** — Health, Integritaet, Parity, Alarmierung
- **E Steuerbox** — Operator-Intent-API, eingeschraenkte Aktorik nur via C

Die gemeinsame SQLite-Landschaft ist dabei **Plattform unterhalb** der Rollen,
kein eigener Buchstabe.

---

## 2. Grundsaetze

1. **Single Write Owner fuer Aktorik:** Schreibende Eingriffe an WR, Batterie,
   Wattpilot, Fritz!DECT oder kuenftigen Aktoren erfolgen ausschliesslich durch **C**.
2. **Read-only fuer B und D:** Web-API und Diagnos lesen, bewerten und melden,
   fuehren aber standardmaessig keine fachlichen Writes aus.
3. **Keine Rekonstruktion technischer Zeitreihen:** Luecken in `raw_data`,
   `data_1min`, `data_15min` und `hourly_data` bleiben als echte Luecken sichtbar.
4. **Statistik darf counter-basiert korrigieren:** Tages-, Monats- und Jahreswerte
   duerfen auf Zaehlerdifferenzen beruhen, wenn die technische Datenbasis zeitweise fehlt.
5. **Config bleibt ausserhalb des Webs:** Konfigurationsaenderungen erfolgen via SSH
   und `pv-config.py` oder ueber die **Steuerbox** (zeitlich begrenzte Overrides).
   Web-UI bleibt read-only.
6. **Failover-Grenzen bleiben bindend:** Die bestehende `primary`/`failover`-Logik
   ist fuer alle vier Rollen Sicherheitsanker.

---

## 3. Verantwortungen

| Rolle | Verantwortet | Darf | Darf nicht |
|---|---|---|---|
| **A Collector-Pipeline** | Rohdaten, Aggregationen, laufende Datenversorgung | DB schreiben, Zeitreihen erzeugen, Persistierung anstossen | Aktorik entscheiden oder Web-Side-Effects ausloesen |
| **B Web-API** | Dashboards, Read-Endpoints, Diagnose-Ausgaben | DB lesen, Caches nutzen, Visualisierung erzeugen | Geraete steuern oder Automation schreiben |
| **C Automation** | Regeln, Schutzlogik, Aktorik, Audit-Log | Sensoren lesen, Aktoren schreiben, Entscheidungen protokollieren | Web-Logik oder generelle Diagnos-Orchestrierung uebernehmen |
| **D Diagnos** | Health, Integritaet, Parity, Kapazitaet, Alarmierung | lesen, vergleichen, klassifizieren, melden | technische Messwerte interpolieren oder kalenderbasiert den Collector neu starten |
| **E Steuerbox** | Operator-Intents, zeitlich begrenzte Overrides, Safety Enforcer | Intents validieren, operator_overrides schreiben, Audit fuehren, Normparameter-Reset bei Timeout | Aktoren direkt ansprechen, Overrides ohne Timeout setzen, Hardware-Zugriff |

---

## 4. D als eigene Schicht

**D Diagnos** ist absichtlich getrennt von A, B und C.

Ziel:
- Probleme frueh erkennen
- Drift, Ressourcenengpaesse und Inkonsistenzen sichtbar machen
- Entscheidungen fuer Restart, Failover oder Hardwaretausch vorbereiten

Nicht-Ziel:
- A/B/C verdeckt reparieren
- Messdaten glätten oder nachtragen
- ungepruefte automatische Neustarts nach Kalender

Die Planungsdokumente fuer D liegen gesammelt in `doc/diagnos/`.

---

## 5. E als Operator-Kanal

**E Steuerbox** ist der einzige Weg, ueber den ein Endgeraet schreibende
Eingriffe ins PV-System ausloesen kann (abgesehen von SSH/pv-config).

Ziel:
- Intuitive Bedienung ohne SSH-Kenntnisse
- Zeitlich begrenzte Overrides (max. 6h, HP max. 30 min)
- Hard Guards gegen Parameterueberschreitungen (SOC >= 5%, Temp im Safe-Bereich)
- Safety Enforcer fuer automatischen Normparameter-Reset bei Timeout/Fehler/Stromwiederkehr

Nicht-Ziel:
- Zweite Automation aufbauen
- Dauerhafte Parametersetzungen ohne Timeout
- Internet-exponierten Zugriff ermoeglichen

Die Planungsdokumente fuer E liegen gesammelt in `doc/steuerbox/`.

---

## 6. Entscheidungsregeln fuer Aenderungen

Bei jeder neuen Funktion zuerst pruefen:

1. **Welcher Bereich ist Owner?**
2. **Entsteht ein Write-Pfad ausserhalb von C?**
3. **Bleibt das Verhalten auf `failover` eindeutig?**
4. **Ist die Entscheidung auditierbar?**
5. **Gehoert das Thema fachlich zu Diagnos statt in Collector/Web/Automation?**
6. **Geht ein Operator-Eingriff ueber E (Steuerbox) statt ueber direkten Code-Zugriff?**

---

## 7. Verweise

| Dokument | Zweck |
|---|---|
| `doc/SYSTEM_BRIEFING.md` | Kurzuebersicht des Gesamtsystems |
| `doc/system/SYSTEM_ARCHITECTURE.md` | Gesamtarchitektur, Datenfluesse, Modulrollen |
| `doc/automation/AUTOMATION_ARCHITEKTUR.md` | Schicht C im Detail |
| `doc/diagnos/DIAGNOS_KONZEPT.md` | Zielbild fuer D Diagnos |
| `doc/steuerbox/ARCHITEKTUR.md` | Architektur der E-Schicht (Operator-Intent-API) |
| `doc/steuerbox/SICHERHEIT.md` | Sicherheitskonzept Steuerbox |
| `doc/steuerbox/TODO.md` | Umsetzungsplan Steuerbox |
| `doc/diagnos/CHECKKATALOG.md` | Check-Domaenen und Methoden |
| `doc/diagnos/TAKTUNG_UND_ESKALATION.md` | Intervalle und Schutzreaktionen |
| `doc/diagnos/UMSETZUNGSPLAN.md` | Schrittweise Realisierung |