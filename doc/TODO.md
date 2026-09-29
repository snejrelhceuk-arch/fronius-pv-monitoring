# Zentrale TODO-Liste — PV-System

**Stand:** 2026-09-29  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories. Ausschliesslich offene `- [ ]` ToDos — keine Audit-/Entwicklungsnotizen.

---

## Sicherheit & Haertung

- [ ] API-Authentifizierung evaluieren (bei Remote-Zugriff)
- [ ] Rate Limiting (`flask-limiter`, 60 req/min/IP)
- [ ] CORS auf Frontend einschraenken (bei Oeffnung)
- [ ] TLS via nginx-Proxy (bei Bedarf)
- [ ] Fehlermeldungen entschaerfen (`str(e)` → generische Antworten)

---

### Hardware: MEGA-BAS HAT

- [ ] Phase 0: I2C aktivieren, SMmegabas installieren, Board-Erkennung
- [ ] Phase 1: Thermistoren (WW oben/mitte/unten + Aussen) verkabeln & kalibrieren
- [ ] Phase 2: Installationsschuetz fuer 3-Phasen-HP (Zukunft)
- [ ] Phase 2b: Klimaanlage-Steuerung klaeren (Schuetz vs. IR-Sender)
- [ ] Phase 3: Bypass-Ventil (Stellantrieb 24VAC?)
- [ ] Phase 4: Lueftungsanlage & Brandschutzklappen
- [ ] Phase 7: 3-Phasen-Heizpatrone (Zukunft)

### Offene Hardware-Fragen

- [ ] F2: Externer WW-Temperatursensor der WP — Typ? NTC 10K? PT1000?
- [ ] F3: WPM-Reglerversion am Geraet pruefen (LCD=WPM_L/H, Touch=WPM_M)
- [ ] F5: Brandschutzklappen-Stellantriebe — Hersteller, Spannung, Rueckmeldekontakt?
- [ ] F5b: Klimaanlage — Schuetz oder IR-Sender?
- [ ] F6: Lueftungsgeraet — Steuerungsmoeglichkeiten (0-10V? Modbus?)
- [ ] F7: Bypass-Ventil — Motor- oder Magnetventil? Spannung?

---

## Automation / Steuerbox

- [ ] HP-Dauerbetrieb-Schalter in der Steuerbox (Cockpit) mit Sicherheits-Rueckfrage:
      dauerhafter HP-Betrieb als Ersatzheizung bei WP-Defekt. Soll die weichen
      WP-Koordinations-Caps (drain/abend) UND — nach expliziter Bestaetigung — die
      Nacht-/Niedrig-SOC-Abschaltung ueberstimmen (nur die harte 78-Grad-Schwelle
      und BYD-BMS/Tier-1-Schutz bleiben zwingend). Kette analog `hp_toggle`:
      `config.py` (STEUERBOX_ALLOWED_ACTIONS) + `steuerbox/validators.py`
      + `automation/engine/operator_overrides.py` + Reader in
      `automation/engine/operator_intents.py` + Respekt in
      `automation/engine/regeln/geraete_heizpatrone.py` + Cockpit-Schalter
      (`steuerbox/static/js/cockpit.js`).
  - [ ] Bleibt der 5-Prozent-SOC-Hartschutz (stop_entladung_unter) auch im Dauerbetrieb zwingend? (Empfehlung: ja)
  - [ ] Zeitliche Begrenzung (max. Laufzeit / taegliche Rueckfrage) statt echt "permanent"?
  - [ ] Netzbezug im Dauerbetrieb bewusst zulassen (WP-Defekt) — Integral-Guard nur warnen statt abschalten?
