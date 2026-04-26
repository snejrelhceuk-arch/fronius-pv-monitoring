# Entscheidungsvorlage: Netzqualität PAC4200 auf Pi5 (RAM-Only)

**Stand:** 2026-04-19
**Ursprung:** `.github/prompts/plan-NQPac4200Pi5Szenario.prompt.md`

## 1. Rahmenbedingungen & Prämissen
- **Hardware:** Pi5 (4 GB RAM), bewusste Ausreizung von CPU & RAM-Bandbreite.
- **Speicher-Policy:** **STRIKTES SD-KARTEN-VERBOT** für Nutzdaten. Datenerfassung erfolgt 100% flüchtig im RAM (`tmpfs`), Pi5 dient als reiner Ingest-/Caching-Node.
- **Transport:** Modbus TCP vom Siemens PAC4200 am PCC (Netzanschlusspunkt).
- **Ziel:** Dauerhafte Vollerfassung (inkl. Harmonische 2..64) bei maximaler Dichte, kontinuierliche oder gebatchte Weiterleitung an Pi5-Backup zur finalen Speicherung.

## 2. Szenario-Rechnung: Datenmengen & RAM-Last

### Datengruppen, Register & Modbus-Datenformate (nach Herstellerdoku PAC4200)
Der Siemens PAC4200 überträgt kontinuierliche Messwerte über Modbus TCP konsequent als **`FLOAT32` (32-Bit IEEE 754 Gleitkommazahlen, 4 Byte pro Wert, verteilt auf 2 Modbus-Register)**. Zählerstände verwenden `FLOAT64` (8 Byte, 4 Register), sind für das Netzqualitäts-Sampling jedoch irrelevant. Stati und Diagnosen kommen als `UINT16` oder `UINT32` (2 oder 4 Byte). Für die NQ-Analyse kalkulieren wir ausschließlich mit `FLOAT32`.

- **Fast-Block** (RMS U/I, P, Q, S, PF, f): ca. 20 Werte
  - *Datentyp:* 20 × `FLOAT32`
  - *Nutzdaten (Payload) pro Abfrage:* 80 Byte
- **Medium-Block** (THD U/I): 6 Werte (3 Phasen)
  - *Datentyp:* 6 × `FLOAT32`
  - *Nutzdaten (Payload) pro Abfrage:* 24 Byte
- **Slow-Block** (Harmonische 2..64 U/I): 378 Werte (63 Ordnungen × 2 Typen × 3 Phasen)
  - *Datentyp:* 378 × `FLOAT32`
  - *Nutzdaten (Payload) pro Abfrage:* 1.512 Byte

### Profil 1: Maximale Dichte (Wunschprofil)
*Polling: Fast 500 ms / Medium 1 s / Slow 1 s*
- Werte pro Sekunde: Fast (40) + Medium (6) + Slow (378) = **424 Werte/Sekunde**
- RAM-Write-Bandbreite: ~4 KB/s
- **Datenvolumen pro Stunde:** ca. 14,4 MB
- **Datenvolumen pro Tag:** ca. 345 MB (brutto inkl. SQLite-File-Overhead ca. **550 MB/Tag**)

### Profil 2: Balanciert
*Polling: Fast 500 ms / Medium 1 s / Slow 5 s*
- Werte pro Sekunde: Fast (40) + Medium (6) + Slow (75,6) = **122 Werte/Sekunde**
- **Datenvolumen pro Tag:** ca. **180 MB/Tag** (inkl. Overhead)

### Profil 3: Konservativ
*Polling: Fast 1 s / Medium 5 s / Slow 10 s*
- Werte pro Sekunde: Fast (20) + Medium (1,2) + Slow (37,8) = **59 Werte/Sekunde**
- **Datenvolumen pro Tag:** ca. **90 MB/Tag** (inkl. Overhead)

---

## 3. Nachweis: Topologie, Bandbreite & Transferzeiten

### Topologie-Vergleich
1. **Option A: Pi5 + PAC4200 gemeinsam am Switch (Empfohlen)**
   - *Aufbau:* Beide Geräte per Ethernet an Gigabit-Switch.
   - *Vorteile:* Modbus-TCP läuft kabellosfrei (Latenz < 1 ms, kein Jitter). Transfer zum Pi5-Backup hat im Hausnetz maximalen und konstanten Durchsatz.
   - *Ausfallsicherheit:* Switch als SPoF, jedoch im industriellen/stationären Einsatz etabliert und zuverlässig.
2. **Option B: Direktverbindung PAC4200 ↔ Pi5, Pi5 Uplink via WLAN**
   - *Aufbau:* Pi5 Eth-Port direkt am PAC4200 angeschlossen (Crossover/Auto-MDIX). Netzwerk-/Backup-Erreichbarkeit via Pi5 WLAN.
   - *Vorteile:* Modbus-Layer ist physisch komplett isoliert, keine Fremdpakete.
   - *Nachteil:* WLAN als Flaschenhals für regelmäßigen Datentransfer zum Backup. Ein Drop im WLAN verzögert die Übertragung, der RAM-Puffer füllt sich, Jitter der WLAN-Cores könnte (theoretisch) CPU-Zeit klauen.

### Transfer-Dauer & Netzlast (Basis: Profil 1 - Max Dichte)
Angenommen, der Pi5 Ingest-Node sammelt und schickt Blöcke über LAN (`Option A`) zum Pi5-Backup:
- **5-Minuten-Batch:** Volumen beträgt ca. **1,2 bis 1,9 MB**.
- **Transferzeit (LAN 1 Gbit):** **< 0,1 Sekunden**.
- **Netzwerk-Footprint:** Völlig vernachlässigbar. Ein 5-Minuten-Sync von 2 MB ist im lokalen Netzwerk ein Wimpernschlag und verursacht keine Staus oder Latenz-Peaks für andere Systeme.

### RAM-Resilienz (Offline-Puffer)
Von den 4 GB RAM des Pi5 können sehr sicher **1,5 GB** als dediziertes `tmpfs` (RAM-Disk) für NQ-Daten gemountet werden. Das OS und der Ingest-Agent benötigen max. ~700 MB.
- **Pufferdauer bei Netzausfall (Profil 1):** 1.500 MB Kapazität / 550 MB pro Tag = **~65 Stunden (> 2,5 Tage)**.
- **Fallback Strategie ("Ringpuffer"):** Wenn der Transfer zum Backup-Pi5 (z.B. wegen Switch-Arbeiten oder Wartung) > 2,5 Tage ausfällt, beginnt die SQLite-Queue alte Rows zu bereinigen (`DELETE FROM raw_data WHERE ts < ...`).
- **Ergebnis:** Die SD-Karte bekommt absolut **NULL Bytes** Nutzdaten zu sehen, der Node bleibt durchgängig ansprechbar.

---

## 4. Übersicht & Ampelbewertung

| Metrik | Profil 1 (Maximal) | Profil 2 (Balanciert) | Profil 3 (Konservativ) |
|---|---|---|---|
| **Datendichte** | 500ms / 1s / 1s | 500ms / 1s / 5s | 1s / 5s / 10s |
| **RAM Footprint / Tag** | ~ 550 MB | ~ 180 MB | ~ 90 MB |
| **Offline-Puffer (1.5GB RAM)**| ~ 65 Stunden (🟢) | ~ 8 Tage (🟢) | ~ 16 Tage (🟢) |
| **Transfer Batch (5 Min)** | ~ 1,9 MB | ~ 0,7 MB | ~ 0,3 MB |
| **Machbarkeit ohne SD** | **Uneingeschränkt Ja** | Ja | Ja |
| **CPU Limit Risk (Pi5)** | Sehr gering | Keines | Keines |

### Gesamtbewertung
🟢 **Fazit: GRÜN für Profil 1 (Maximale Datendichte).**
Durch die kluge Entscheidung, Datenspeicherung komplett in den 4 GB RAM (`tmpfs`) zu verlagern, löst sich das Volumenproblem für den Pi5 vollständig in Luft auf. Die Netzwerktransferlast liegt im Promillebereich eines Gigabit-LANs. Solange das Pi5-Backup den Datenstrom am Ende wegspeichern kann, steht einer Vollerfassung der Harmonischen bis zur 64. Ordnung (U+I) im Sekundentakt auf dem Ingest-Pi5 nichts im Weg.

**Zielarchitektur:**
- Start mit **Topologie A (Switch)** für konstante Modbus- und Netzwerklatenz.
- `tmpfs`-Mount mit 1,5 GB in `/dev/shm/nq_cache/`.
- Ein Daemon pollt den PAC4200, schreibt in den RAM.
- Ein parallel laufender, asynchroner Sync-Prozess schickt die Daten z.B. über eine REST-Schnittstelle oder per rsync/SQLite-Dump alle 5 Minuten ans Backup. Löschung aus dem RAM erfolgt strikt *nach* Transfer-Quittierung.

---

## 5. Freigabekriterium: Der 48-h Feldtest
Vor dem Schreiben des finalen Production-Codes muss *eine* technische Unbekannte des PAC4200 evaluiert werden:
* **Der Read-Only Test:** Es wird initial ein kleines Python-Skript gebaut, das Profil 1 (500ms/1s/1s) anwendet. Es *druckt* nur die Deltas aus und speichert nichts. 
* **Erkenntnisziel:** Aktualisiert der PAC4200 die FFT der *64. Harmonischen* geräteintern wirklich sekündlich? Oder refreshen sich die Spektral-Register intern nur alle N Sekunden? 
* Sollte der PAC4200 intern die Harmonik-Werte z.B. nur alle 3 Sekunden neu berechnen, wird das Polling auf exakt diesen Intervall gedrosselt, da dichteres Abfragen nur redundante Werte auf den Bus zwingt.