## Plan: NQ PAC4200 Pi5 Szenario

Ziel ist eine belastbare Entscheidungsvorlage fuer NQ mit PAC4200 bei **maximaler Datendichte** (inkl. voller Harmonischer dauerhaft) auf dem Pi5. 

Dabei gelten folgende **Prämissen**:
- Intensive Nutzung von **CPU und 4 GB RAM**.
- **Expliziter Verzicht** auf Nutzdatenspeicherung auf der SD-Karte (RAM-Only / Ingest-Node).
- Der Plan liefert einen quantifizierten Nachweis über **Datenmengen und Transferzeiten** zum Pi5-Backup.
- Gleichwertiger Vergleich der Topologien (Direktverbindung vs. Switch).
- Definition klarer Betriebsgrenzen und einer Risikoampel (ohne sofortige Codeänderung).

---

### Steps

1. **Rahmen und Annahmen fixieren**
   - **Hardware:** Pi5 4 GB RAM. Die SD-Karte darf nur für OS/Resilienz genutzt werden, absolut nicht für NQ-Daten.
   - **Transport:** Modbus-TCP.
   - **Ziel:** Dauerhafte Vollnutzung aller PAC4200-Daten.
   - **Netzwerk:** Offener Architekturvergleich (Switch vs. LAN/WLAN-Direktverbindung).
   - **Status Quo:** Festhalten, dass derzeit noch keine produktive PAC4200-Implementierung existiert.
   - *(Referenz: [doc/netzqualitaet/MESSTECHNIK.md](doc/netzqualitaet/MESSTECHNIK.md), [config.py](config.py#L146), [modbus_v3.py](modbus_v3.py#L1055), [doc/netzqualitaet/TRADE_SWITCH_DETECTION.md](doc/netzqualitaet/TRADE_SWITCH_DETECTION.md#L80))*

2. **Datengruppen und Minimal-Polling definieren**
   - **Fast-Block** (RMS/Leistung/Frequenz): Startwert `500 ms`
   - **Medium-Block** (THD): Startwert `1 s`
   - **Slow-Block** (Harmonische 2..64 für U+I je Phase): Startwert `1 s`
   - **Sensitivitätsszenario:** Vergleich mit z.B. 500 ms / 1 s / 5 s für den Slow-Block.
   - *(Referenz: [doc/netzqualitaet/MESSTECHNIK.md](doc/netzqualitaet/MESSTECHNIK.md#L107))*

3. **Szenario-Rechnung aufziehen**
   - Werte pro Sekunde ermitteln.
   - Rohdatenvolumen pro Stunde / Tag / Monat berechnen.
   - Konservativen SQLite-Overhead und Write-IOPS einkalkulieren.
   - **RAM-Pufferbedarf** (Queue-Größe) für 1 h und 6 h berechnen.
   - *Output:* Übersichtliche Matrix je Datengruppe und Gesamtlast.

4. **Topologievergleich ausrechnen**
   - **Option A:** Direktverbindung PAC4200 ↔ Pi5 (Pi5 via WLAN im Hausnetz).
   - **Option B:** Beide Geräte regulär am Switch.
   - *Metriken:* Latenz, Jitter-Risiken, Ausfallmodi, Wartbarkeit, Monitoring und Recovery.

5. **Zielarchitektur für RAM-Entkopplung bewerten**
   - **Pi5 als reiner Datensammler:** Nutzung von `tmpfs` o.ä. für RAM-Cache und Queue.
   - Geordneter Weitertransport an das Pi5-Backup zum Schreiben.
   - Erneuter Abgleich: Zero-Write-Policy auf die lokale Pi5 SD-Karte.

6. **Nachweis Datenmengen und Transferzeit erbringen**
   - **Transfer-Footprint:** Bandbreitenbedarf im (W)LAN bei kontinuierlichem Forwarding.
   - **Batch-Dauer:** Minimale Transferzeit und Netzlast bei zyklischem Leeren des Puffers.
   - **RAM-Resilienz:** Wie viele Minuten/Stunden Netzausfall puffert der RAM, bevor Werte verworfen werden?

7. **Entscheidungsvorlage erstellen**
   Bewertung und Empfehlung für drei Betriebsprofile:
   - **Profil 1 (Maximal):** Maximale Dichte (Wunschprofil).
   - **Profil 2 (Balanciert):** Optimierter Kompromiss.
   - **Profil 3 (Konservativ):** Hohe Sicherheit, geringere Dichte.
   *(Inhalte je Profil: Polling-Takt, RAM-Bedarf, Transferzeiten, CPU-Risiko, Ausfallerwartung und empfohlene Topologie)*

8. **Verifikationsplan definieren**
   - Definition eines kurzen 48-Stunden-Feldtests mit einem "Read-Only Testcollector".
   - Ermitteln von Realwerten zu Register-Refresh-Zeiten und tatsächlichen Daten-Änderungsraten.
   - Kriterien für die endgültige Produktionsfreigabe festlegen.

---

### Relevant Files
- [doc/netzqualitaet/MESSTECHNIK.md](doc/netzqualitaet/MESSTECHNIK.md) — PAC4200-spezifische Polling- und Blocklogik
- [doc/netzqualitaet/TRADE_SWITCH_DETECTION.md](doc/netzqualitaet/TRADE_SWITCH_DETECTION.md) — Bestehende Laufzeit- und Ssizing-Werte
- [config.py](config.py#L146) — Standard-Policys für Polling & Flush
- [modbus_v3.py](modbus_v3.py#L1055) — Aktuelles Polling-Muster, Modbus-Zyklus-Grenzen
- [doc/collector/DB_SCHEMA.md](doc/collector/DB_SCHEMA.md) — Schema- und Retention-Referenz
- [netzqualitaet/nq_export.py](netzqualitaet/nq_export.py#L24) — NQ-Spalten und Pipeline als Referenz

---

### Verification
1. **Plausibilität:** Wertezahl pro Sekunde / Volumen gegen [MESSTECHNIK.md](doc/netzqualitaet/MESSTECHNIK.md#L145) prüfen.
2. **Konsistenz:** Summe (Fast + THD + Harmonische) muss exakt die Profil-Gesamtlast ergeben.
3. **Ressourcengrenzen:**
   - RAM-Berechnung hält das 4-GB-Limit ein (inkl. OS-Bedarf).
   - Transfermengen überschreiten nicht die realistische (W)LAN-Bandbreite.
   - SD-Karten-Verbot bleibt erhalten.
4. **Resilienz:** Failure-Mode-Checkliste (Link Down, WLAN-Drop, Switch tot, Backup offline).
5. **Freigabe:** Profil "MaxDichte" benötigt erst reale Testdaten (Verhinderung von Queue-Überläufen).

---

### Decisions
- **In Scope:** Reine Szenario-Rechnung, Entscheidungsvorlage, Fokus auf Maximaldatendichte inkl. Harmonischer. Topologievergleich (Direkt vs. Switch).
- **Out of Scope:** Code-Umbau am aktiven pv-system-Collector, lokale SD-Speicherung von Messwerten.

---

### Further Considerations
1. **Ausfallsicherheit bei RAM-Only:**
   - Strategie, wenn Link zum Pi5-Backup fällt: Da SD-Speicherung blockiert ist, verfallen bei vollem Puffer Daten. Muss entschieden werden: *Älteste* Daten überschreiben vs. *neueste* Daten ablehnen?
2. **Transfer-Zyklen (RAM -> Backup):**
   - Taktung definieren: Sekunden? Minuten? 5-Minuten-Blöcke?
   - *Abwägung:* Mikrobatches (wenig Latenz, ineffizient) vs. Makrobatches (Kompressionspotenzial, CPU-Spitzen beim Senden).
3. **Harmonische im Dauerbetrieb:**
   - **Option A:** Dauerhaft alles (2..64).
   - **Option B:** Dauerhaft nur THD + Kernordnungen, Vollspektrum nur bei Bedarf / Events.
   - *Status:* Empfehlung geht weiterhin zu Option A, sofern die Nachweise im RAM und WLAN halten.
