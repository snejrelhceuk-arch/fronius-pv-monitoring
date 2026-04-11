# Steuerbox — TODO

**Stand:** 2026-04-11
**Status:** Priorisierte Umsetzungsliste

---

## Phase 0: Sicherheitsbaseline (Blocker fuer alles Weitere)

- [ ] **UFW auf Primary (.181) aktivieren** — `scripts/safe_ufw_apply.sh` mit Rollback-Timer ausfuehren
  - Akzeptanz: `sudo ufw status` zeigt deny incoming + allow 22+8000 aus LAN
- [ ] **SSH StrictHostKeyChecking haerten** — `no` → `accept-new` in sync_code_to_peer.sh, backup_db_gfs.sh, routes/system.py
  - Akzeptanz: grep zeigt kein `StrictHostKeyChecking=no` mehr

---

## Phase 1: Steuerbox-API Grundgeruest

- [ ] **config.py erweitern** — STEUERBOX_PORT, STEUERBOX_HOST, STEUERBOX_ALLOWLIST, STEUERBOX_ALLOWED_ACTIONS, Hard-Guard-Konstanten
  - Akzeptanz: config.STEUERBOX_PORT liefert Wert != 8000
- [ ] **steuerbox/steuerbox_api.py** — Flask-App auf separatem Port, Blueprint-Registrierung
  - Akzeptanz: `curl http://localhost:8001/api/ops/status` liefert JSON
- [ ] **steuerbox/validators.py** — IP-Allowlist-Check, Auth-Token-Check, Hard-Guard-Validator
  - Akzeptanz: Anfrage von nicht-erlaubter IP → 403; SOC=3% → 422
- [ ] **steuerbox/intent_handler.py** — Intent-Verarbeitung: validieren, operator_overrides schreiben, an C weiterleiten
  - Akzeptanz: POST hp_toggle → Eintrag in operator_overrides mit expires_at
- [ ] **pv-steuerbox.service** — systemd Unit fuer separaten Dienst
  - Akzeptanz: `systemctl status pv-steuerbox` zeigt active (running)
- [ ] **UFW-Regel fuer Steuerbox-Port** — nur explizite Endgeraete-IPs
  - Akzeptanz: `ufw status | grep 8001` zeigt nur freigegebene IPs

---

## Phase 2: Release-1 Schalter

- [ ] **HP AN/AUS** — Intent mit Respekt-Verfahren, Automation pausiert weiche Regeln
  - Akzeptanz: HP schaltet, nach extern_respekt_s uebernimmt Automation wieder
- [ ] **WP Komfort/Auto** — Offset-Modus (Hz/WW -10K), Respekt-Verfahren
  - Akzeptanz: WP-Sollwert aendert sich, nach Respekt-Zeit Automation uebernimmt
- [ ] **Batterie Komfort/Auto** — SOC 25-75% Komfort bzw. 5-100% Auto plus manuelle SOC-Override
  - Akzeptanz: SOC-Grenzen aendern sich, Hard Guard blockiert SOC < 5%
- [ ] **Wattpilot Start/Pause/Laden starten** — frc-Steuerung, Respekt-Verfahren
  - Akzeptanz: Wattpilot reagiert, nach Respekt-Zeit zurueck auf Normalbetrieb
- [ ] **Regelkreis EIN/AUS** — pro Bereich, Respekt-Verfahren
  - Akzeptanz: Regelkreis deaktiviert sich, nach Respekt-Zeit automatische Reaktivierung

---

## Phase 3: Safety Enforcer + D/E-Integration

- [ ] **steuerbox/enforcer.py** — Respekt-Zeitueberwachung, Parametermatrix-Reset, Audit
  - Akzeptanz: Wenn Automation nach Respekt-Ablauf nicht reagiert hat → Warnung; nach 6h → Matrix-Reset
- [ ] **Diagnos-Integration** — Enforcer nutzt `diagnos.health` und `diagnos.integrity` als Entscheidungsdaten
  - Akzeptanz: Enforcer liest D-Health-JSON, beschleunigt Eskalation bei Service-Ausfall
- [ ] **Diagnos auf beliebigem Pi deploybar machen** — Remote-Monitoring-Modus fuer D
  - Akzeptanz: `python3 -m diagnos.health --remote <PRIMARY_HOST>` liefert JSON
- [ ] **Heartbeat-Pruefung** — Automation-Heartbeat auswerten, Stale-Erkennung, D-Daten einbeziehen
  - Akzeptanz: Automation 15 min stale + D meldet Service inactive → Enforcer setzt Normparameter
- [ ] **6h-Parametermatrix-Reset** — kompletter Reset auf konservative Defaults
  - Akzeptanz: Nach 6h ohne Automation-Reaktion → SOC Komfort, HP AUS, WP Auto, Overrides weg
- [ ] **Power-Restore-Erkennung** — Boot-Timestamp vs. letzter Heartbeat
  - Akzeptanz: Nach Stromausfall: Audit-Log „Power-Restore", Normparameter gesetzt
- [ ] **Enforcer-Resilienz** — systemd Restart=always, SD-Persistenz, Deadman-Check
  - Akzeptanz: `kill enforcer` → systemd startet neu innerhalb 30s
- [ ] **Enforcer auf Failover/Pi5 deployen** — role-unabhaengiger Betrieb mit lokaler D-Instanz
  - Akzeptanz: Enforcer + Diagnos laufen auf zweitem Pi, erkennen Primary-Ausfall

---

## Phase 4: pv-config Integration

- [ ] **Regelkreis-Abschaltung in pv-config mit Respekt-Verfahren** — gleiche Mechanik wie Steuerbox
  - Akzeptanz: pv-config zeigt Respekt-Restlaufzeit, nach Ablauf Automation uebernimmt
- [ ] **Override-Status in pv-config anzeigen** — aktive Overrides mit Respekt-Countdown
  - Akzeptanz: pv-config Menue zeigt „HP EIN (Respekt noch 22 min)"

---

## Phase 5: Cockpit-UI (optional, spaeter)

- [ ] **Web-Schaltpult-Startseite** — Hauptschalter mit Status
- [ ] **Untermenues** — Spezialfunktionen je Aktor
- [ ] **Live-Countdown** — Override-Restlaufzeit in der UI
- [ ] **Audit-Ansicht** — Letzte Aktionen mit Ergebnis

---

## Querschnitt-Aufgaben

- [ ] **Audit-Logging** — jeder Override-Start, Reset, Timeout in steuerbox_audit
- [ ] **Rate-Limiting** — pro Aktion, HTTP 429 bei Ueberschreitung
- [ ] **Failover-Verhalten** — Steuerbox read-only auf Failover, role_guard
- [ ] **SYSTEM_BRIEFING.md aktuell halten** — Steuerbox-Abschnitt einpflegen
- [ ] **Testmatrix** — Security, Timeout, Failover, Power-Restore End-to-End

---

## Aufwandsschaetzung

| Phase | Aufwand |
|---|---|
| Phase 0 (Sicherheitsbaseline) | 1-2h |
| Phase 1 (API-Grundgeruest) | 2-4 Tage |
| Phase 2 (Release-1 Schalter) | 2-3 Tage |
| Phase 3 (Safety Enforcer) | 3-5 Tage |
| Phase 4 (pv-config Integration) | 1 Tag |
| Phase 5 (Cockpit-UI) | 2-3 Tage |
| **Gesamt bis produktionsreif** | **~2 Wochen** |
