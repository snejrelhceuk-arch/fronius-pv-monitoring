# Steuerbox — LLM-Ausfuehrungsanweisung

**Zweck:** Kompakte, effiziente Anweisung fuer ein ausfuehrendes LLM (Copilot, Ollama, etc.),
das die Steuerbox implementiert. Dieses Dokument ersetzt nicht die detaillierte Doku,
sondern gibt die kuerzeste Wegbeschreibung mit allen No-Go-Grenzen.

**Stand:** 2026-04-11

---

## Was ist die Steuerbox?

Eigener Flask-Dienst auf Port != 8000 (z.B. 8001). Nimmt Operator-Intents entgegen,
validiert gegen Hard Guards, schreibt in `operator_overrides`-Tabelle, Automation (Schicht C)
liest und fuehrt aus. Steuerbox hat **keinen direkten Hardware-Zugriff**.

---

## Architektur-Regeln (MUSS eingehalten werden)

1. **Kein direkter Aktor-Aufruf aus Steuerbox.** Alle Writes gehen ueber Schicht C.
2. **Hard Guards sind absolut.** SOC nie < 5%, Temp-Offset nie < -15K, HP-Notaus bei SOC<=15% oder Uebertemp>=78°C.
3. **Respekt-Verfahren statt fester Timer.** Alle Intents nutzen das bestehende `extern_respekt_s`-Muster (default 30 min, 15–120 min konfigurierbar). Automation pausiert weiche Regeln waehrend Respekt-Zeit. KEIN fester Timer pro Schaltertyp.
4. **6h = Sicherheitsnetz, nicht Normalbetrieb.** 6h-Reset greift nur bei Automation-Versagen oder Fehler → Reset der GESAMTEN Parametermatrix auf konservative Defaults.
5. **IP-Allowlist vor Auth-Check.** Erst IP pruefen, dann Token.
6. **Failover = read-only.** role_guard aus host_role.py nutzen. Keine Intents auf Failover.
7. **Audit-Log fuer jede Aktion.** Kein stiller Fehlschlag.
8. **Enforcer nutzt Diagnos-Daten.** Vor Eskalation immer `diagnos.health` auswerten.

---

## Dateien und Reihenfolge

### Schritt 1: Config erweitern
- **Datei:** `config.py`
- **Aktion:** Neue Konstanten STEUERBOX_PORT, STEUERBOX_HOST, STEUERBOX_ALLOWLIST,
  STEUERBOX_ALLOWED_ACTIONS, Hard-Guard-Werte (SOC_MIN=5, etc.)
- **Muster:** Folge dem bestehenden `load_local_setting()`-Pattern

### Schritt 2: Validator
- **Datei:** `steuerbox/validators.py`
- **Aktion:** `check_allowlist()` (request.remote_addr gegen CIDR), `check_auth()` (Bearer-Token),
  `validate_action(name, params)` (Whitelist + Hard Guards: nur physikalische Grenzen)
- **Verhalten:** abort(403) bei IP/Auth-Fehler, abort(422) bei Guard-Verletzung
- **NICHT im Validator:** Zeitbasierte Limits (die kommen aus dem Respekt-Verfahren in C)

### Schritt 3: Intent-Handler
- **Datei:** `steuerbox/intent_handler.py`
- **Aktion:** `handle_intent(action, params)` → validieren → operator_overrides INSERT
  → JSON-Response mit override_id und Respekt-Countdown
- **DB:** `/dev/shm/automation_obs.db`, neue Tabelle `operator_overrides`
- **Kein expires_at im klassischen Sinn:** Der Eintrag hat `created_at` und `respekt_s`.
  Die Automation entscheidet nach Respekt-Ablauf selbst, was sie tut.

### Schritt 4: Flask-App
- **Datei:** `steuerbox/steuerbox_api.py`
- **Aktion:** Flask-App mit Blueprints, Endpoints wie in ARCHITEKTUR.md §3
- **Start:** Eigener gunicorn oder direkt `python3 steuerbox_api.py`

### Schritt 5: systemd Service
- **Datei:** `pv-steuerbox.service`
- **Muster:** Kopiere pv-automation.service, aendere ExecStart + Port

### Schritt 6: Automation-Integration
- **Datei:** `automation/engine/engine.py` oder `actuator.py`
- **Aktion:** Steuerbox-Intents werden wie externe Schaltvorgaenge behandelt.
  Bestehenden `extern_respekt_s`-Mechanismus nutzen (SocExternTracker-Muster).
  Override aus `operator_overrides` lesen → als extern erkannten Wert einspeisen →
  Respekt-Timer laeuft → nach Ablauf Automation uebernimmt wieder.

### Schritt 7: Safety Enforcer
- **Datei:** `steuerbox/enforcer.py`
- **Aktion:** Endlosschleife (60s Takt):
  1. Diagnos-Health-Daten lesen (`diagnos.health.run_checks()` oder Remote-JSON)
  2. Automation-Heartbeat + D-Health auswerten → Eskalationsstufe bestimmen
  3. Wenn Respekt-Zeiten wiederholt ueberschritten ODER Automation-Ausfall:
     Warnung → nach 6h Parametermatrix-Reset auf konservative Defaults
  4. Power-Restore erkennen → Normparameter setzen
  5. Audit schreiben

---

## No-Go (DARF nicht passieren)

- ❌ Steuerbox importiert direkt aus `automation/engine/aktoren/`
- ❌ Steuerbox oeffnet Modbus/WebSocket/Fritz!DECT-Verbindung
- ❌ Fester Timeout pro Schaltertyp (KEIN „HP 30 min, WP 6h" — alles via Respekt-Verfahren)
- ❌ Override ohne `created_at` und `respekt_s` in DB
- ❌ Steuerbox akzeptiert Intents auf Failover-Host
- ❌ SOC-Wert < 5% wird gesetzt
- ❌ Aktion ohne Audit-Log-Eintrag
- ❌ Enforcer eskaliert ohne vorherige Diagnos-Daten-Auswertung

---

## Tests (Pflicht vor Produktivnahme)

1. **IP-Block:** Anfrage von nicht-erlaubter IP → 403
2. **Auth-Block:** Anfrage ohne Token → 401
3. **Guard-Block:** SOC=3% → 422
4. **Respekt-Test:** Override setzen, Respekt-Zeit ablaufen lassen → Automation uebernimmt
5. **HP-Notaus:** HP EIN bei SOC<=15% → SOFORT AUS (Engine fast-cycle)
6. **Failover-Block:** Steuerbox auf Failover → nur GET erlaubt
7. **Power-Restore:** Reboot simulieren → Normparameter gesetzt, Audit geschrieben
8. **Audit-Vollstaendigkeit:** Jede Aktion hat Eintrag in steuerbox_audit
9. **6h-Matrix-Reset:** Automation 6h stale → Enforcer setzt gesamte Parametermatrix zurueck
10. **D/E-Integration:** Enforcer liest Diagnos-Health, beschleunigt Eskalation bei Service-Ausfall

---

## Referenzdateien (lesen vor Implementierung)

| Datei | Warum |
|---|---|
| `config.py` | Pattern fuer Konstanten, load_secret(), load_local_setting() |
| `host_role.py` | is_primary(), role_guard |
| `automation/engine/actuator.py` | Wie Aktorik ausgefuehrt wird |
| `automation/engine/obs_state.py` | RAM-DB Schema, Heartbeat |
| `automation/engine/regeln/soc_extern.py` | SocExternTracker — Referenzmuster fuer Respekt-Verfahren |
| `automation/engine/regeln/geraete.py` | extern_respekt_s Implementation fuer HP |
| `diagnos/health.py` | Health-Checks, run_checks() — Datenquelle fuer Enforcer |
| `diagnos/integrity.py` | Integritaets-Checks — Datenquelle fuer Enforcer |
| `gunicorn_config.py` | Service-Start-Muster inkl. INVOCATION_ID Guard |
| `web_api.py` | Flask Blueprint-Registration, CORS-Muster |
| `doc/steuerbox/ARCHITEKTUR.md` | Volle Architektur-Doku |
| `doc/steuerbox/SICHERHEIT.md` | Auth, Guards, Rate-Limiting |
| `doc/automation/STRATEGIEN.md` | Autoritaetsschaltung, extern_respekt_s Doku |
