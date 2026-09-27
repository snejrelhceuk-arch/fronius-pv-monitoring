# Zentrale TODO-Liste — PV-System

**Stand:** 2026-09-27  
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

## Netzqualität (Rolle N)

- [ ] **Tech-Code-Sync automatisieren:** Tech (`.181`) hat KEINEN automatischen Code-Abgleich und driftete ~1 Tag (Poller lief ohne Harmonik-Thread). Sync-Mechanismus Primary→Tech (analog `sync_code_to_peer.sh`, nur git-tracked, ohne Daten) + Poller-Restart-Hook etablieren.
- [ ] **tmpfs-Schema-Migration robuster:** `open_db` nutzt `CREATE TABLE IF NOT EXISTS` → geaenderte tmpfs-Tabellen (z. B. `nq_raw_medium` `ts`→`ts_ms`) werden bei Poller-Neustart NICHT migriert (Insert-Fehler bis manuellem Drop). Versions-/Migrations-Check beim Poller-Start ergaenzen.
- [ ] **NQ-Units in Standard-Deployment aufnehmen:** `install_nq_services.sh` in `install_services.sh` bzw. Provisionierung referenzieren, damit NQ nach Reinstall/Reboot nicht manuell vergessen wird.


## Solarweb-Abgleich

- [ ] Maerz-Abgleich durchfuehren
- [ ] 2022–2025 CSV-Import pruefen
- [ ] Langfristig: Abweichung beobachten (Zaehlerstand-Delta = korrekt seit Feb 6)

---

## Code-Architektur

- [ ] **`automation/engine/regeln/geraete.py` (~2300 Z.) zerlegen.** Enthaelt 4 Regel-Klassen:
      `RegelWattpilotBattSchutz` (~110 Z.), `RegelHeizpatrone` (~1450 Z., Monster),
      `RegelKlimaanlage(RegelHeizpatrone)` (~580 Z.), `RegelFussbodenheizungNacht` (~90 Z.)
      plus Modul-Helfer `registriere_klima_engine_ein`/`klima_engine_ein_kuerzlich`.
      Zielschnitt: je Geraet ein Modul (`geraete_wattpilot_schutz.py`, `geraete_heizpatrone.py`,
      `geraete_klimaanlage.py`, `geraete_fbh_nacht.py`); `geraete.py` bleibt duenner Aggregator
      (Re-Export aller Klassen + Helfer), damit die String-Importpfade in `registry.py`
      (`automation.engine.regeln.geraete.RegelX`), `regeln/__init__.py` und `operator_overrides.py`
      unveraendert bleiben.
      RISIKO: safety-critical Rolle C (Batterie/HP/Klima/Wattpilot) — **nur isoliert +
      test-verifiziert** umsetzen, **nicht** mit Feature-/UI-Aenderungen buendeln.
      Vorbedingung: `tests/test_heizpatrone_characterization.py` deckt bisher nur die Heizpatrone
      ab → vor der Zerlegung Characterization-Tests fuer Wattpilot-Schutz, Klima und FBH-Nacht
      ergaenzen (Verhalten einfrieren), dann mechanisch verschieben, Tests gruen halten.
- [ ] Weitere Gross-Module fuer Zerlegung pruefen (nach gleichem Muster, je nach Bedarf):
      `routes/pac4200.py` (~1850 Z.), `pv-config.py` (~1550 Z.), `routes/verbraucher.py` (~1420 Z.),
      `automation/engine/regeln/waermepumpe.py` (~1130 Z.), `routes/realtime.py` (~1080 Z.),
      `automation/engine/regeln/soc_steuerung.py` (~1060 Z.). `solar_geometry.py` bleibt bewusst
      ein Block (Teilung nicht gerechtfertigt).
