# Steuerbox — Architektur

**Stand:** 2026-04-11
**Status:** Planungsdokument

---

## 1. Einordnung im ABCD-Rollenmodell

Die Steuerbox ist eine **neue Schicht E** (Operator-Intent-API), die neben den
bestehenden Schichten A–D operiert:

| Rolle | Aufgabe | Schreibzugriff |
|---|---|---|
| **A** Collector | Daten sammeln | DB (INSERT) |
| **B** Web-API | Anzeige, Read-only | KEINER |
| **C** Automation | Regeln, Aktorik | DB + Hardware (Single Write Owner) |
| **D** Diagnos | Health, Integritaet | geplant: read-only |
| **E** Steuerbox | Operator-Intents | **NUR via C** (kein direkter Hardware-Zugriff) |

**Kernprinzip:** E darf Intents formulieren. C entscheidet und fuehrt aus.
E hat keinen direkten Zugriff auf Aktoren, Modbus oder Fritz!DECT.

---

## 2. Systemuebersicht

```
┌───────────────┐     ┌───────────────────────┐     ┌──────────────┐
│ E) Steuerbox  │     │  B) Web-API (Flask)    │     │ C) Automation│
│ steuerbox/    │     │  web_api.py + routes/  │     │ engine/      │
│ Port != 8000  │     │  Port 8000             │     │ 4 Schichten  │
│ IP-Allowlist  │     │  READ-ONLY             │     │ S1→S2→S3→S4 │
│ Auth + Guards │     │                        │     │ Write Owner  │
└──────┬────────┘     └───────────┬────────────┘     └──────┬───────┘
       │ Intent                   │ Read                     │ Execute
       │ (validiert)              │                          │
  ┌────┴──────────────────────────┴──────────────────────────┴────┐
  │         operator_overrides (SQLite, automation_obs.db)        │
  │         + automation_log (Audit)                              │
  └───────────────────────────────────────────────────────────────┘
```

---

## 3. API-Design

### Port und Binding

- Nicht-Standard-Port (z.B. 8001, konfigurierbar via `config.py`)
- UFW erlaubt diesen Port **nur** fuer freigegebene Endgeraete (IP-Allowlist)
- Binding: `0.0.0.0` oder `127.0.0.1` + Reverse-Proxy (entscheidbar)

### Authentifizierung

- **Einheitlich** fuer alle Endpunkte (kein Step-up, kein mTLS)
- Zentrale Auth (z.B. API-Key oder Session-Token) plus IP-Allowlist
- Kein Internet-Zugriff, nur LAN

### Endpunkte (Release-1)

| Endpunkt | Methode | Funktion |
|---|---|---|
| `POST /api/ops/hp_toggle` | POST | Heizpatrone EIN/AUS |
| `POST /api/ops/wp_offset` | POST | WP Komfort/Auto (Hz/WW Offset) |
| `POST /api/ops/battery_mode` | POST | Batterie Komfort/Auto + SOC Override |
| `POST /api/ops/wattpilot_ctrl` | POST | Wattpilot Start/Pause/Laden |
| `POST /api/ops/regelkreis_toggle` | POST | Regelkreis EIN/AUS pro Bereich |
| `GET  /api/ops/status` | GET | Aktueller Override-Status + Respekt-Restlaufzeiten |
| `GET  /api/ops/audit` | GET | Letzte Aktionen mit Ergebnis |

**Timeout-Modell:** Alle Schalter nutzen das bestehende Respekt-Verfahren (siehe §5).
Kein fester Timer pro Endpunkt.

---

## 4. Hard Guards (unueberwindbar)

Diese Grenzen kann der Operator **nicht** ueberschreiben:

| Parameter | Grenze | Grund |
|---|---|---|
| SOC_MIN | >= 5% | BYD Notaus-Schutz |
| SOC_MAX | <= 100% | Physikalisch |
| WP Temp-Offset | >= -15K | Frostschutz |
| HP bei SOC <= extern_notaus_soc_pct (15%) | SOFORT AUS | Entladeschutz |
| HP bei Uebertemperatur (>= 78°C) | SOFORT AUS | Speicherschutz |

**Hinweis:** Timeouts sind KEINE Hard Guards, sondern Teil des Respekt-Verfahrens (§5).
Hard Guards pruefen physikalische Grenzen — sie werden vom Validator **vor** der Aktion
blockiert (abort 422), nicht erst bei der Ausfuehrung.

---

## 5. Respekt-Verfahren und Sicherheitsnetz

### Grundprinzip

Alle Steuerbox-Intents nutzen dasselbe **Respekt-Verfahren**, das die Automation
bereits fuer externe Schaltvorgaenge implementiert hat (vgl. `extern_respekt_s`,
`SocExternTracker`). Steuerbox-Intents werden von der Automation behandelt wie
manuelle Aenderungen ueber die Fronius-App oder Fritz!DECT.

### Ablauf

1. **Operator setzt Intent** via Steuerbox-API
2. **Intent wird als externer Schaltvorgang registriert** in `operator_overrides`
3. **Automation erkennt den externen Wert** und startet Respekt-Periode
4. **Waehrend der Respekt-Zeit** (default `extern_respekt_s` = 1800s / 30 min,
   konfigurierbar 15–120 min): Automation pausiert alle weichen Regeln fuer
   diesen Aktor. Nur Hard Guards (SOC <= 5%, Uebertemperatur >= 78°C,
   SOC <= extern_notaus_soc_pct) ueberstimmen sofort.
5. **Nach Ablauf der Respekt-Zeit:** Automation uebernimmt wieder die volle
   Regelhoheit. Der Override ist „abgearbeitet".
6. **Operator kann erneut setzen** (neuer Respekt-Zyklus).

### 6h-Sicherheitsnetz (Safety Enforcer)

Das 6h-Sicherheitsnetz ist **kein regulaerer Timeout pro Schalter**, sondern
ein Notfall-Reset der **gesamten Parametermatrix** auf konservative Standardwerte.
Es greift nur in zwei Situationen:

- **Respekt-Zeiten werden wiederholt ueberschritten** (Automation reagiert nicht)
- **Schwere Fehlersituation** (Primary-Ausfall, Automation-Heartbeat stale)

Resetumfang: SOC auf Komfortwerte, HP AUS, WP auf Auto, alle offenen
Overrides geloescht, Regelkreise reaktiviert. Audit-Eintrag „Parametermatrix-Reset".

### Notfallbetrieb (Automation/Primary defekt)

- Safety Enforcer (beliebiger Pi) ueberwacht Heartbeat der Automation
- Heartbeat stale (>5 min): Enforcer warnt + Diagnos-Daten auswerten (§6)
- Heartbeat stale (>15 min) + Primary nicht erreichbar: Enforcer darf Normparameter setzen
- Dauerhaft (>6h): zwingender Parametermatrix-Reset

### Stromwiederkehr nach Stromausfall

1. **Erkennen:** Boot-Timestamp vs. letzter bekannter Heartbeat
2. **Loggen:** Audit-Eintrag „Power-Restore erkannt"
3. **Normparameter setzen:** SOC auf Komfortwerte, HP AUS, WP auf Auto, alle Overrides loeschen
4. **Verifizieren:** Read-Back der gesetzten Werte

---

## 6. Safety Enforcer

Kleine, unabhaengige Instanz auf beliebigem Pi (Primary, Failover oder Pi5).

### Strikt begrenzte Aufgaben

1. **Respekt-Zeitueberschreitungen erkennen** — Automation sollte nach Respekt-Ablauf
   reagiert haben. Wenn nicht: Warnung, nach 6h Matrix-Reset.
2. **Bei Fehler/Ausfall: Parametermatrix auf konservative Standardwerte setzen**
   (ueber Aktorik in C, falls erreichbar; sonst direkt Modbus-Notfall-Pfad)
3. **Verifikation und Audit schreiben**

### Diagnos-Daten als Entscheidungsgrundlage (D/E-Kooperation)

Der Enforcer trifft Entscheidungen nicht blind, sondern wertet **Diagnos-Daten
(Schicht D)** aus, bevor er eingreift:

- **Health-Checks:** Service-Status, Daten-Frische, CPU/RAM/Disk (via `diagnos.health`)
- **Integritaet:** Energiebilanz-Plausibilitaet, Luecken-Klassifikation (via `diagnos.integrity`)
- **Erreichbarkeit:** Fronius Modbus/HTTP, Fritz!Box (geplant: Phase 3 Diagnos)

D liefert read-only Zustandsdaten → E (Enforcer) nutzt diese fuer Eskalationsentscheidungen.
Beispiel: Heartbeat stale + D meldet `pv-automation.service inactive` → Enforcer
eskaliert sofort statt 15 min zu warten.

**Voraussetzung:** D muss auf demselben Pi laufen wie der Enforcer, oder
ueber einen leichten HTTP-Endpunkt erreichbar sein (geplant).

### Kein zweites Automationssystem

Der Enforcer fuehrt **keine Regellogik** aus. Er hat nur Normparameter und
darf nur bei klaren Triggern (Respekt-Ueberschreitung, Primary-Ausfall,
Power-Restore) aktiv werden.

### Resilienz

- systemd `Restart=always`, `RestartSec=30`
- Lokaler Heartbeat (eigene Liveness-Pruefung)
- Override-State auf SD persistiert (nicht nur /dev/shm)
- Idempotente Recovery-Aktionen (mehrfach ausfuehrbar ohne Schaden)

---

## 6a. D/E-Architektur: Diagnos als Datenquelle fuer Enforcer

### Warum D auf beliebigem Pi?

Wenn der Enforcer auf Failover (.105) oder Pi5 (.195) laeuft, braucht er
eine lokale Diagnos-Instanz, die den Primary ueberwacht. D ist bereits als
leichtgewichtiges Lese-Tool konzipiert (< 1% CPU).

### Deployment-Modell

| Pi | D (Diagnos) | E (Enforcer) | Bemerkung |
|---|---|---|---|
| Primary (.181) | Health + Integrity (lokal) | Optional | Beides lokal, schnellster Pfad |
| Failover (.105) | Health (remote-Monitoring) | Empfohlen | D prueft Primary per Netz |
| Pi5 (.195) | Health (remote-Monitoring) | Alternative | D prueft Primary per Netz |

### Datenfluss

```
  D (diagnos)         E (enforcer)
  ┌──────────┐        ┌────────────┐
  │ health() │──JSON──▶│ bewerten() │
  │ integr() │        │ eskalieren │
  └──────────┘        └─────┬──────┘
                            │ Trigger?
                            ▼
                    Normparameter setzen
                    (via C oder Notfall)
```

### Zugriffsmuster

- **Gleicher Pi:** Enforcer importiert `diagnos.health.run_checks()` direkt
- **Remote Pi:** D bietet leichten JSON-Endpunkt `/diagnos/health` (geplant),
  oder Enforcer ruft `ssh pi@primary python3 -m diagnos.health --json` auf

---

## 7. Failover-Verhalten

| Host | Steuerbox-Rolle | Aktorik |
|---|---|---|
| **Primary** (.181) | Volle API aktiv | Intents → C (lokal) |
| **Failover** (.105) | Read-only Status | Keine Intents annehmen |
| **Beliebiger Pi** | Safety Enforcer | Nur Notfall-Normreset |

role_guard prueft `.role`-Datei. Auf Failover wird Steuerbox-API
im Read-only-Modus gestartet (nur GET /status und /audit).

---

## 8. Verwandte Dokumente

| Dokument | Zweck |
|---|---|
| [SICHERHEIT.md](SICHERHEIT.md) | Auth, Allowlist, UFW, Haertung |
| [TODO.md](TODO.md) | Umsetzungsschritte mit Akzeptanzkriterien |
| [LLM_AUSFUEHRUNG.md](LLM_AUSFUEHRUNG.md) | Kompakte Implementierungsanweisung fuer ausfuehrendes LLM |
| [doc/SYSTEM_BRIEFING.md](../SYSTEM_BRIEFING.md) | Gesamtsystem-Kontext |
| [doc/system/ABCD_ROLLENMODELL.md](../system/ABCD_ROLLENMODELL.md) | Rollenmodell (jetzt ABCDE) |
| [doc/automation/STEUERUNGSPHILOSOPHIE.md](../automation/STEUERUNGSPHILOSOPHIE.md) | Schutzgrenzen und Prioritaeten |
