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

- [ ] **`automation/engine/regeln/geraete_heizpatrone.py`: `bewerte()`/`erzeuge_aktionen()` entduplizieren.**
      Beide Methoden leiten die Phasen-Entscheidung (AUS-Pfad, Drain P0, Burst P1/1b/2/3/4)
      unabhaengig voneinander ab (~1000 Z. Duplikat). Dadurch bereits stille Drift:
      WW-Temp-AUS nutzt in `bewerte()` `_dynamic_temp_max_c`, im AUS-Pfad von
      `erzeuge_aktionen()` aber den Roh-Cap `speicher_temp_max_c` (78 C); der Phase-0-
      Haushaltscheck rechnet in `bewerte()` HP+WP heraus, in `erzeuge_aktionen()` nicht;
      analog `RegelWattpilotBattSchutz` (bewerte hardcodet `soc<25`, erzeuge nutzt
      `soc_min_netz_pct`). Ziel: gemeinsame Kern-Entscheidung, aus der Score UND Aktion
      abgeleitet werden (Schnitt nach Schaltgrund statt Duplikat).
      RISIKO: safety-critical Rolle C, **zustandsbehaftet** (Burst-Timer/Probe/Kurz-Burst-
      Sperre) — **isoliert** umsetzen, gegen `tests/test_heizpatrone_characterization.py`
      und `tests/test_geraete_characterization.py` (Golden) verifizieren; vorher um
      Zustandssequenz-Szenarien (mehrere Ticks) erweitern, da die Golden je Szenario aktuell
      eine frische Regel nutzen.
- [ ] Weitere Gross-Module fuer Zerlegung pruefen (nach gleichem Muster, je nach Bedarf):
      `routes/pac4200.py` (~1850 Z.), `pv-config.py` (~1550 Z.), `routes/verbraucher.py` (~1420 Z.),
      `automation/engine/regeln/waermepumpe.py` (~1130 Z.), `routes/realtime.py` (~1080 Z.),
      `automation/engine/regeln/soc_steuerung.py` (~1060 Z.). `solar_geometry.py` bleibt bewusst
      ein Block (Teilung nicht gerechtfertigt).
