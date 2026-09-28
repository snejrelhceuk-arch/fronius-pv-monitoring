# Zentrale TODO-Liste — PV-System

**Stand:** 2026-09-28  
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

## Code-Architektur

- [ ] **`automation/engine/regeln/geraete_heizpatrone.py`: EIN-Phasen-Entscheidung (Phase 0/1/1b/2/3/4) entduplizieren.**
      Der **AUS-Pfad ist bereits Single-Source** (`_ww_temp_aus_pruefen`, `_phase4_aus_pruefen`,
      `_aus_kontext_pruefen`, `_phase0_haushalt_netto` — von `bewerte()` UND `erzeuge_aktionen()`
      genutzt); damit sind die WW-Temp-Drift (dyn. Cap jetzt in beiden Pfaden) und die
      Phase-0-Haushalt-Drift (HP+WP-Herausrechnung in beiden) behoben. **Offen:** die
      Burst-EIN-Phasen sind weiterhin doppelt abgeleitet (Score in `bewerte()`, Burst/Aktion in
      `erzeuge_aktionen()`). Vor dem Teilen zu KLAEREN — dabei aufgefallene latente Divergenz:
      `bewerte()` Phase 2 feuert zusaetzlich bei `rest_kwh > min_rest_kwh` (12), `erzeuge_aktionen()`
      NICHT → Score will EIN ohne dass eine Aktion folgt. Ziel: gemeinsame Phasen-Kern-Entscheidung
      (Schnitt nach Phase/Burst statt Duplikat).
      RISIKO: safety-critical Rolle C, **zustandsbehaftet** (Burst-Timer/Probe/Kurz-Burst-Sperre,
      Phase-1b-Probe) — **isoliert** umsetzen, gegen die (um Multi-Tick-Zustandssequenzen
      erweiterten) Golden `tests/test_heizpatrone_characterization.py` und
      `tests/test_geraete_characterization.py` verifizieren.
- [ ] **`RegelWattpilotBattSchutz` (`automation/engine/regeln/geraete_wattpilot_schutz.py`): `bewerte()`/`erzeuge_aktionen()` entduplizieren** (analog HP-AUS-Pfad).
      `bewerte()` hardcodet `soc<25`, `erzeuge_aktionen()` nutzt `soc_min_netz_pct` — stille Drift.
      Gemeinsamer SOC-Schwellen-Helfer; gegen `tests/test_geraete_characterization.py` (Golden) verifizieren.
- [ ] Weitere Gross-Module fuer Zerlegung pruefen (nach gleichem Muster, je nach Bedarf):
      `routes/pac4200.py` (~1850 Z.), `pv-config.py` (~1550 Z.), `routes/verbraucher.py` (~1420 Z.),
      `automation/engine/regeln/waermepumpe.py` (~1130 Z.), `routes/realtime.py` (~1080 Z.),
      `automation/engine/regeln/soc_steuerung.py` (~1060 Z.). `solar_geometry.py` bleibt bewusst
      ein Block (Teilung nicht gerechtfertigt).
