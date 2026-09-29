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

## Architektur-Haertung

- [ ] P2: Wattpilot-Lesepfad trennen: read-only Client fuer Collector/Web einfuehren; schreibfaehiges `set_value` ausschliesslich im C-Aktor belassen.
- [ ] P2: Web-DB-Zugriff standardmaessig read-only machen: `get_db_connection_ro` einfuehren, normale Routen darauf umstellen und Forecast-Schreibzugriffe explizit kapseln.
- [ ] P2: `Actuator.ausfuehren` als harte Exception-/Audit-Grenze ausbauen: Aktor-Exceptions in Fehlerergebnisse wandeln und immer `automation_log` schreiben.
- [ ] P2: Systemd-Installation gegen nicht existente `WorkingDirectory` absichern und Diagnos-Check fuer installierte PV-Units ergaenzen.
- [ ] P2: NQ-Diagnose vervollstaendigen: `diagnos/config.py:NQ_TIMERS` mit installierten Primary-NQ-Timern synchronisieren und Kritikalitaeten fuer Core/Analyse/Backup/Rollup staffeln.
- [ ] P2: Config-Reload-Vertrag dokumentieren und technisch vereinheitlichen: Hot-reload, Safe-reload und Restart-only trennen; optionale Aktor-`reload_config`-Schnittstelle pruefen.
- [ ] P3: Architekturgrenzen weiter mit Tests absichern: Actuator-Exception-Test und statische Web-DB-Write-Tests ergaenzen.
- [ ] P3: Hotspot-Dateien nur risikogetrieben zerlegen; vor Aenderungen an grossen Regel-/Routenmodulen passende Charakterisierungstests ergaenzen.

### User
- [ ] Peak-Leistung: Anzeige in Monitoring/Verbraucher stimmt nicht mit dem Marker überein (29.09.2026)
- [ ] "P-Max WP" Button und Grafik im Button überarbeiten: "§14a-WP"? Grafik entfernen! oder "WP§14a"? Oder "WP §14a"? Was ist professioneller?
- [ ] Pi4 Küche war 29.09.26 down (ich hatte ihn am 28. mal heruntergefahren.) Warum habe ich keine Fehlermeldung erhalten? Der gehört zum pv-system und hat eine Backup-Funktion, die ggf. nicht auffiel, weil dort nur Langfrist-Backups abgelegt werden. Diagnos hätte aber reagieren müssen.
