# System-Architektur — PV-Monitoring

> **WICHTIG**: Dieses Dokument ist die zentrale Referenz für LLMs und Entwickler.
> Vor jeder Änderung am System DIESES DOKUMENT ZUERST LESEN.
> Stand: 2026-02-19

---

## 1. Hardware-Topologie

### PV-Anlage (37,59 kWp, 3 Wechselrichter)

                    ┌─────────────────────────────────────────────┐
                    │              DC-Seite (PV-Module)           │
                    │                                             │
    ┌───────────────┼─────────────────────────────────────────────┼───────────┐
    │               │                                             │           │
    │  MPPT1: String 1+2       MPPT2: String 3+4                 │           │
    │  (20+20)×345Wp=13,8kWp   (8+8)×345Wp=5,52kWp               │           │
    │        │                       │                            │           │
    │     │   F1: Gen24 12 kW    │◄──── BYD Battery 10,24 kWh    │           │
    │     │   (Hybrid-WR)        │      (DC-gekoppelt!)           │           │
    │     │   19,32 kWp          │                                │           │
    │     └─────────┬────────────┘                                │           │
    │               │ AC                                          │           │
    │               │                                             │           │
    │  ┌────────────┼──────────────────────────────────────────┐  │           │
    │  │         Hausnetz (AC)                                 │  │           │
    │  │            │                                          │  │           │
    │  │   ┌────────┤           ┌──────────────┐               │  │           │
    │  │   │        │           │  SM Netz (2)  │◄──── EVU     │  │           │
    │  │   │        │           └──────────────┘  Einspeisepkt │  │           │
    │  │   │        │                                          │  │           │
    │  │   │  ┌─────┴──────┐   ┌─────────────┐                │  │           │
    │  │   │        │                 │                        │  │           │
    │  │   │        ▼                 ▼                        │  │           │
    │  │   │  F2: Gen24 10kW    Wärmepumpe                    │  │           │
    │  │   │  12,42 kWp                                       │  │           │
    │  │   │                                                   │  │           │
    │  │   │  ┌─────────────┐                                  │  │           │
    │  │   │  │  SM F3 (6)  │                                  │  │           │
    │  │   │  └──────┬──────┘                                  │  │           │
    │  │   │         ▼                                         │  │           │
    │  │   │   F3: Symo 4,5kW                                 │  │           │
    │  │   │   5,85 kWp                                       │  │           │
    │  └───┼───────────────────────────────────────────────────┘  │           │
    └──────┼──────────────────────────────────────────────────────┘           │
           │                                                                  │
           ▼                                                                  │
    Monitoring: Pi4 (192.0.2.181) ◄── Modbus TCP ── Fronius (192.0.2.122)│
```

### Modbus Unit IDs

| Unit | Gerät | Modell | SunSpec Models |
|------|-------|--------|----------------|
| 1 | Inverter F1 | Gen24 12 kW (Hybrid) | 103, 120, 122, 123, 160 |
| 4 | SmartMeter WP | Fronius SM | 201/202/203 |

### Monitoring-Hardware

| System | IP | User | Speicher | RAM | Rolle | .role |
|--------|-----|------|---------|-----|-------|-------|
| **Pi4 Produktion** (primary-host) | 192.0.2.181 (eth0) | admin | 16 GB SD | 4 GB | **Produktion** (Collector + Web + Aggregation + Battery) | `primary` |
| **Pi4 Failover** (failover-host) | 192.0.2.105 (eth0) | jk | 128 GB SD | 8 GB | **Failover** (DB-Mirror + Web read-only + Küchen-Display) | `failover` |
| **Pi5 Backup** (backup-host) | 192.0.2.195 (eth0) | admin | 476 GB NVMe | — | Backup-Empfänger (alternierendes data.db + GFS-Dateikopien) | — |

> **Produktion und Failover teilen dasselbe Git-Repository.**  
> Rollenabhängiges Verhalten wird durch die lokale `.role`-Datei gesteuert (gitignored).  
> Details: [DUAL_HOST_ARCHITECTURE.md](DUAL_HOST_ARCHITECTURE.md)

---
## 2. Energiefluss-Modell (KRITISCH!)

### ⚠️ W_AC_Inv ≠ PV-Erzeugung!

```
                         DC-Bus (im Hybrid-Wechselrichter F1)
                         ════════════════════════════════════
                              │              │
                           MPPT1          MPPT2
                         (String 1+2)   (String 3+4)
                              │              │
                              ▼              ▼
        Batterie ◄──────► DC-Bus ────────────────────► AC-Ausgang F1
        (laden/           │                                  │
         entladen)        │                                  │
                          │                                  ▼
                          │                            W_AC_Inv (Counter)
                          │                            P_AC_Inv (Leistung)
                          │
                          ▼
                     W_DC1 + W_DC2 (MPPT Counter)
                     P_DC1 + P_DC2 (MPPT Leistung)
```

### Was die Hardware-Counter WIRKLICH messen

| Counter | Messpunkt | Was es misst | Was es NICHT misst |
|---------|-----------|-------------|-------------------|
| **W_AC_Inv** | AC-Ausgang F1 | PV-Erzeugung F1 **PLUS** Batterie-Entladung **MINUS** Batterie-Ladung | Kein reiner PV-Wert! |
| **W_DC1** | MPPT1 Eingang | Reine PV-Erzeugung String 1+2 | Keine Batterie |
| **W_DC2** | MPPT2 Eingang | Reine PV-Erzeugung String 3+4 | Keine Batterie |
| **W_Exp_Netz** | Einspeisepunkt | Ins Netz eingespeiste Energie | — |
| **W_Imp_Netz** | Einspeisepunkt | Aus Netz bezogene Energie | — |
| **W_Exp_F2** | SM F2 | Von F2 ins Hausnetz eingespeist | — |
| **W_Imp_F2** | SM F2 | Aus Hausnetz durch F2 bezogen (Standby) | — |
| **W_Exp_F3** | SM F3 | Von F3 ins Hausnetz eingespeist | — |
| **W_Imp_F3** | SM F3 | Aus Hausnetz durch F3 bezogen (Standby) | — |
| **W_Imp_WP** | SM WP | Wärmepumpe Bezug aus Hausnetz | — |

### Energiefluss-Gleichungen

```
PV-Erzeugung total   = W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3
PV-Erzeugung F1      = W_DC1 + W_DC2    (≠ W_AC_Inv!)
PV-Erzeugung F2      = W_Exp_F2 - W_Imp_F2  (netto)
PV-Erzeugung F3      = W_Exp_F3 - W_Imp_F3  (netto)

Batterie-Leistung    = P_DC_Inv - (P_DC1 + P_DC2)
                       positiv = Laden, negativ = Entladen

W_AC_Inv             = W_DC1 + W_DC2 + Batterie_Entladung - Batterie_Ladung
                       (daher W_AC_Inv ≠ PV und NICHT als PV-Counter nutzbar!)

Netz-Bilanz          = W_Imp_Netz - W_Exp_Netz
Eigenverbrauch       = PV_total - W_Exp_Netz
Gesamtverbrauch      = PV_total + W_Imp_Netz - W_Exp_Netz
```

### Namenkonvention in Aggregationstabellen

| Spaltenname | In Tabelle | Bedeutung |
|-------------|-----------|-----------|
| `W_AC_Inv_delta` | data_1min | Counter-Delta W_AC_Inv (inkl. Batterie!) |
| `W_PV_total_delta` | data_15min, hourly, monthly | **Gesamt-PV** = DC1+DC2+F2+F3 (REIN PV, keine Batterie) |
| `W_PV_total` | daily_data | Tages-PV-Erzeugung in Wh |
| `W_*_start` / `W_*_end` | data_1min, data_15min, hourly, daily | Absolute Zählerstände am Intervall-Anfang/-Ende |

**⚠️ SEMANTIK-KOLLISION (behoben 2026-02-11):**
- `data_1min.W_AC_Inv_delta` = AC-Counter-Delta (inkl. Batterie)
- `data_15min.W_PV_total_delta` = Gesamt-PV (OHNE Batterie) — wurde von W_AC_Inv_delta UMBENANNT!

---

## 3. Datenbank-Architektur

### tmpfs + Persistierung (laufender Betrieb)

```
/dev/shm/fronius_data.db  (RAM, ~132 MB)
     │
     │  SQLite .backup() stündlich
     ▼
  data.db (SD-Card lokal)
  ~/Dokumente/.../data.db
     │
     │  rsync alle 6 Persist-Zyklen
     ▼
  data.db (Pi5 via rsync)
  admin@192.0.2.195:~/Documents/.../data.db
```

- **DB im RAM**: Schnell, kein SD-Card-Verschleiß für Lese-/Schreiboperationen
- **Persist lokal**: stündlich tmpfs → SD (`SQLite .backup()`)
- **Pi5-Transfer**: alle 6 Persist-Zyklen per rsync
- **Wiederherstellung**: Fallback-Kette SD → Pi5 → `backup/db/daily/*.db.gz`
- **Fixpunkte**: daily_data._start/_end sichern Tages-/Monats-/Jahres-/Gesamt-Werte
- **SD-Card Writes**: stark reduziert gegenüber Dauerpersist (tmpfs als Primär-DB)
- **SQLite**: Version 3.45.1 (kompiliert, wg. HAVING-Clause Kompatibilität)

### GFS-Backup auf Pi4 Primary + Pi5-Spiegel (Sohn-Vater-Großvater)

Nur **eine** Datenbank (`data.db`, ~127 MB) wird gesichert — sie enthält alle Tabellen.
Andere Dateien (solar_cache.db, config/*.json) sind regenerierbar bzw. im Git.

```
Pi4 Primary systemd Timer 03:00 → backup_db_gfs.sh

Sohn        (3-tägig) : data_YYYY-MM-DD.db.gz       → 7 Dateien behalten
Vater       (weekly)  : data_YYYY-WNN.db.gz (So)     → 5 Wochen
Großvater   (monthly) : data_YYYY-MM.db.gz (1.)      → 12 Monate
Urgroßvater (yearly)  : data_YYYY.db.gz (1. Jan)     → permanent

Quelle Sohn: /dev/shm/fronius_data.db (RAM → SD via SQLite .backup)
Nach jeder neu erzeugten GFS-Datei: zusätzliche Kopie nach Pi5 (NVMe)

Speicher: ~38 MB × (7+5+12+N) < 1 GB
Verzeichnis: ~/Documents/PVAnlage/pv-system/backup/db/{daily,weekly,monthly,yearly}
```

### Pi5 Neustart-Verhalten

Pi5 ist reiner Backup-Empfänger (kein Collector, kein Web, kein tmpfs).
Nach Reboot automatisch bereit:
- `data.db` auf NVMe → überlebt Reboot
- SSH (enabled) → Pi4 kann rsync senden
- Empfang der GFS-Dateikopien (`backup/db/{daily,weekly,monthly,yearly}`) vom Pi4 Primary

### Aggregations-Pipeline

```
raw_data (3s)  ──1min──►  data_1min  ──15min──►  data_15min  ──1h──►  hourly_data
                                                                           │
                                                                     ──1d──►  daily_data
                                                                                  │
                                                              ──1M──►  data_monthly (technisch)
                                                              ──1M──►  monthly_statistics (finanziell)
                                                                           │
                                                                     ──1Y──►  yearly_statistics
```

| Script | Cron | Quelle → Ziel |
|--------|------|---------------|
| aggregate_1min.py | jede Minute | raw_data → data_1min |
| aggregate.py | 0,15,30,45 | raw_data → data_15min → hourly_data |
| aggregate_daily.py | 2,17,32,47 | hourly_data → daily_data |
| aggregate_monthly.py | 6,21,36,51 | data_15min → data_monthly |
| aggregate_statistics.py | 8,23,38,53 | daily_data → monthly_statistics → yearly_statistics |

### Zählerstand-Propagation (_start/_end)

Absolute Zählerstände fließen durch die Kette:

| Tabelle | _start/_end vorhanden | Befüllt seit | Quelle |
|---------|----------------------|--------------|--------|
| raw_data | W_AC_Inv etc. direkt | immer | Modbus |
| data_1min | W_AC_Inv_start/end + 4 Paare | 7. Feb 2026 | aggregate_1min.py: MIN/MAX aus raw |
| data_15min | W_AC_Inv_start/end + 14 Paare | 4. Feb 2026 | aggregate.py: MIN(start)/MAX(end) aus raw |
| hourly_data | W_AC_Inv_start/end + 4 Paare | 4. Feb 2026 | aggregate.py: MIN(start)/MAX(end) aus 15min |
| daily_data | W_AC_Inv_start/end + 12 Paare | 4. Feb 2026 | aggregate_daily.py: MIN(start)/MAX(end) aus hourly |
| data_monthly | Spalten existieren (56-75) | 4. Feb 2026 | aggregate_monthly.py: MIN(start)/MAX(end) aus 15min, NULLIF(0) |

**Konsistenzgarantie**: `daily_data[Tag N].W_*_end == daily_data[Tag N+1].W_*_start` (verifiziert OK)

### Fixpunkt-Strategie (Datensicherheit)

Die **absoluten Zählerstände** an Tagesgrenzen (`daily_data._start/_end`) sind die
unfehlbaren Fixpunkte für die Langzeit-Bilanz. Aus den Differenzen zwischen zwei
Fixpunkten lässt sich jeder Energiewert exakt rekonstruieren:

```
PV-Erzeugung Monat = W_DC1_end[letzter Tag] - W_DC1_start[erster Tag]
                    + W_DC2_end[letzter Tag] - W_DC2_start[erster Tag]
                    + W_Exp_F2_end - W_Exp_F2_start
                    + W_Exp_F3_end - W_Exp_F3_start
```

**Tabelle `energy_checkpoints`**: 33 rekonstruierte Einträge (Jan-Feb), wird NICHT aktiv befüllt.
Redundant zu `daily_data._start` — gleiche Information, andere Struktur.

**Tabelle `energy_state`**: Laufende Energie-Akkumulatoren des Collectors (P×t-Integration).
KEIN Checkpoint-Mechanismus. Wird bei jedem Collector-Start aus DB geladen.

---

## 4. Collector (modbus_v3.py)

### Polling-Loop

```
Alle 3s:
  1. Modbus TCP → 5 Geräte lesen (Inv, SM Netz, SM F2, SM WP, SM F3)
  2. Batterie-API lesen (U, I)
  3. Batterieleistung berechnen: P_Batt = P_DC_Inv - (P_DC1 + P_DC2)
  4. Energie-Integration: W += P × dt (für energy_state Akkumulatoren)
  5. Record → RAM-Buffer (deque)

Alle 60s:
  - RAM-Buffer → raw_data (Batch INSERT, timeout=1s)
  - energy_state → DB speichern

Persist (Persist-Thread):
  - SQLite .backup() → data.db auf SD-Card
```

### Batterie-Berechnung

Die Batterie hat KEINEN eigenen Modbus-Zähler. Berechnung:

```python
P_Batt = P_DC_Inv - (P_DC1 + P_DC2)   # DC-Leistungsdifferenz
# positiv = Laden, negativ = Entladen
```

Seit Feb 2026: BYD BMS Component-API liefert Lifetime-Zähler (Ws).
Endpunkt: `http://192.0.2.122/components/BatteryManagementSystem/readable`
(Fronius Gen24 interne API auf F1-IP, BYD am internen Modbus RTU /dev/rtu0 Addr 21).

**Verfügbare BMS-Counter (Hardware-Zähler, NICHT P×t!):**
```
BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64      Laden gesamt (Ws → /3600 = Wh)
BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64   Entladen gesamt (Ws → /3600 = Wh)
BAT_VALUE_STATE_OF_HEALTH_RELATIVE_U16     SoH (%)
BAT_TEMPERATURE_CELL_MIN/MAX_F64           Zelltemperatur (°C)
```

⚠️ API-Header warnt: "this internal API may be changed any time".
Bei Firmware-Update können sich Register-Namen ändern → dann neu suchen.
Die Daten selbst sind echte Zähler und genauer als P×t (~99% vs ~90%).
Siehe `doc/BATTERY_COUNTER_DISCOVERY.md` für vollständige Analyse.

---

## 5. Systemdienste (nach Host)

### Pi4 Primary — primary-host (192.0.2.181, admin)

Volle Produktion: Collector, Aggregation, Battery-Steuerung, Web.

| Service | Typ | Beschreibung |
|---------|-----|-------------|
| pv-collector | systemd (enabled) | modbus_v3.py (Poller + Persist-Thread) |
| pv-wattpilot | systemd (enabled) | wattpilot_collector.py (WebSocket → raw_wattpilot) |
| pv-web | systemd (enabled) | web_api.py (gunicorn, 3 Worker, Port 8000), After=pv-collector |
| pv-backup-gfs.timer | systemd (enabled) | backup_db_gfs.sh täglich 03:00 (Sohn intern alle 3 Tage) |
| Cron (5 Aggregations-Jobs) | crontab (admin) | aggregate_1min, aggregate, aggregate_daily, monthly, statistics |
| Cron (Monitor-Scripts) | crontab (admin) | monitor_collector.sh, monitor_wattpilot.sh, monitor_web_service.sh |
| battery_scheduler.py | Cron | Batterie-Steuerung (Modbus-Writes zum WR!) |
| capture_energy_checkpoints.py | Cron | Energie-Fixpunkte sichern |

**Persistierung**: tmpfs → SD stündlich, zusätzlicher Pi5-rsync alle 6 Persist-Zyklen.
**GFS**: Sohn 3-tägig aus RAM→SD; Vater/Großvater/Urgroßvater unverändert; neue Dateien zusätzlich auf Pi5 gespiegelt.

### Pi4 Failover — failover-host (192.0.2.105, jk)

Passiv-Modus: Nur DB-Mirror, Read-Only-Web, Health-Check. **Kein Modbus, keine Writes.**

| Service | Typ | Status | Beschreibung |
|---------|-----|--------|-------------|
| pv-web | systemd (enabled) | ✅ aktiv | web_api.py (gunicorn, 1 Worker, read-only) |
| pv-mirror-sync | systemd timer (10 Min) | ✅ aktiv | rsync DB von Primary (181) → tmpfs |
| pv-failover-health | systemd timer (1 Min) | ✅ aktiv | Prüft Erreichbarkeit Primary |
| pv-backup-2d | systemd timer (1×/2 Tage) | ✅ aktiv | Lokales DB-Backup (SD) |
| ~~pv-collector~~ | — | ❌ gestoppt | Doppelte Modbus-Abfragen verboten |
| ~~pv-wattpilot~~ | — | ❌ gestoppt | WebSocket-Konflikt (nur 1 Verbindung) |
| ~~Aggregation (Cron)~~ | — | ❌ role_guard | Sinnlos — DB wird alle 10 Min überschrieben |
| ~~battery_scheduler~~ | — | ❌ role_guard | **GEFÄHRLICH** — schreibt Modbus-Register! |
| ~~Monitor-Scripts~~ | — | ❌ role_guard | Collector/Wattpilot bewusst aus |

**Wichtig**: Die `.role`-Datei (`failover`) steuert alle Guards.  
Kein Collector, keine Aggregation, keine Batterie-Steuerung auf diesem Host.

### Pi5 Backup — backup-host (192.0.2.195, admin)

Reiner Backup-Empfänger. Kein Collector, kein Web, kein tmpfs.

| Service | Status | Beschreibung |
|---------|--------|-------------|
| SSH | ✅ enabled | Empfang rsync von Pi4 Primary |
| ~~pv-db-restore~~ | disabled (2026-02-14) | Nicht nötig (data.db auf NVMe, kein tmpfs) |
| ~~pv-collector~~ | disabled | Nicht aktiv auf Pi5 |
| ~~pv-web~~ | disabled | Nicht aktiv auf Pi5 |

**data.db liegt direkt auf NVMe** — überlebt Reboot, kein tmpfs nötig.

### Hinweise

- DB-Restore auf Pi4 Primary läuft über `db_init.ensure_tmpfs_db()` im Collector selbst
- ~~pv-wattpilot Service-File~~ existiert als `pv-wattpilot.service` (nur auf Primary enabled)
- **Entwicklung und Git-Commits nur auf Pi4 Primary (181)**  
  → Pre-Commit-Hook blockt Commits auf Failover (siehe `scripts/pre-commit`)
- **Code-Sync** von 181 → 105 per `scripts/sync_code_to_peer.sh` (rsync, ohne host-spezifische Dateien)

### Boot-Sequenz nach Reboot/Stromausfall

#### Pi4 Primary (181) — Volle Wiederherstellung

```
1. systemd multi-user.target (CLI, kein GUI, WLAN/BT deaktiviert)
2. tmpfs /dev/shm ist LEER (RAM war weg)
3. pv-collector startet → db_init.ensure_tmpfs_db():
   a) data.db (SD-Card) → SQLite .backup() → /dev/shm/fronius_data.db
   b) Falls SD fehlt/korrupt → Fallback: rsync von Pi5 (192.0.2.195)
   c) Falls Pi5 nicht erreichbar → Fallback: backup/db/daily/*.db.gz
   d) Falls alles fehlt → leere DB (Collector befüllt sie)
4. pv-collector: start_persist_thread() + poller_loop()
5. pv-web startet (After=pv-collector): eigenes ensure_tmpfs_db() (idempotent)
6. pv-wattpilot startet: WebSocket → Wallbox
7. Cron-Jobs: db_utils-Import → ensure_tmpfs_db() (idempotent, no-op)
```

**Maximaler Datenverlust: ~1 Tag** (dank alternierender Sicherung).  
Fixpunkte (daily_data._start/_end) sichern Langzeit-Bilanzen.

#### Pi4 Failover/failover-host (105) — Schneller Mirror-Start

```
1. systemd multi-user.target (GUI für Küchen-Display)
2. tmpfs /dev/shm ist LEER (RAM war weg)
3. pv-web startet → ensure_tmpfs_db():
   a) data.db (SD-Card, letztes lokales Backup) → /dev/shm/fronius_data.db
   b) Dashboard zeigt Daten vom letzten Backup (≤2 Tage alt)
4. pv-mirror-sync.timer (≤10 Min): rsync von Primary (181)
   → /dev/shm/fronius_data.db wird mit Live-Daten überschrieben
5. Ab jetzt: Dashboard zeigt aktuelle Daten (max. 10 Min Verzögerung)
```

**Kein Datenverlust** — Failover hat nur gespiegelte Daten, keine eigenen.

#### Pi5 Backup (195) — Sofort bereit

```
1. data.db liegt auf NVMe → überlebt Reboot, kein tmpfs
2. SSH enabled → Pi4 kann rsync senden
3. Pi4 überträgt zusätzlich GFS-Dateien nach backup/db/{daily,weekly,monthly,yearly}
```

---

## 6. Bekannte Einschränkungen

| Thema | Status | Detail |
|-------|--------|--------|
| Jan 2026 _start/_end NULL | Nicht behebbar | raw_data für Jan bereits rotiert (7d Retention) |
| data_monthly _start/_end | ✅ Behoben | aggregate_monthly.py propagiert seit 2026-02-14 |
| energy_checkpoints | Inaktiv | 33 rekonstruierte Altdaten, kein aktiver Schreiber |
| W_AC_Inv als PV-Counter | FALSCH | Inkludiert Batterie! PV = DC1+DC2+F2+F3 |
| Pi4 SD-Card Verschleiß | Minimiert | Alternierend: ~24 GB/Jahr (1×/2 Tage à 132 MB) |
| Batterie P×t vs Hardware | Offen | BMS-Counter via Component-API verfügbar, noch nicht im Hauptpfad |
| Daten-Lücke 14.2. 03-12h | Akzeptiert | Pi4-Reboot, nicht rekonstruierbar |
| SQLite 3.45.1 | Manuell | System-Lib ersetzt (/lib/arm-linux-gnueabihf/) |
| System-Updates | Bewusst deaktiviert | Siehe Abschnitt "Update-Strategie" |

---

## 7. Update-Strategie

> **Stand: 2026-02-19** — Bewusste Entscheidung: KEINE automatischen Updates.

### Warum keine automatischen Updates?

Dieses System ist ein **headless Produktivsystem** auf einer 14,8 GB SD-Card,
das 24/7 Messdaten sammelt. Automatische Updates (apt, pip) sind hier **riskant**:

| Risiko | Auswirkung |
|--------|-----------|
| `apt upgrade` überschreibt SQLite 3.45.1 | DB-Operationen mit HAVING-Clause brechen |
| Kernel-Update erzwingt Reboot | tmpfs-DB verloren, Datenlücke bis nächster Persist |
| pip-Upgrade von Flask 1.1.2 → 2.x/3.x | Breaking API-Changes (Werkzeug, Jinja2) |
| numpy 1.19.5 → 2.x | Massiv inkompatible API (deprecated Funktionen entfernt) |
| SD-Card-Platz (14,8 GB, 1302 Pakete) | apt-Cache kann SD füllen → System unbenutzbar |
| Kein Monitor/Tastatur am Pi4 | Fehlgeschlagenes Update → SSH evtl. auch kaputt |

### Versions-Freeze (aktueller Stand)

| Komponente | Version | Quelle |
|-----------|---------|--------|
| Raspbian | Bullseye 11 (EOL ~Juni 2026) | System |
| Kernel | 6.1.21-v8+ | System |
| Python | 3.9.2 | System |
| SQLite | 3.45.1 | Manuell kompiliert |
| Flask | 1.1.2 | pip |
| gunicorn | 23.0.0 | pip |
| numpy | 1.19.5 | pip |
| requests | 2.25.1 | pip |
| websockets | 15.0.1 | pip |

Python-Dependencies sind in `requirements.txt` exakt gepinnt (`==`).

### Empfohlene Wartungs-Routine (manuell, ~2×/Jahr)

```
1. VORHER: Backup sicherstellen (Pi5 GFS aktuell?)
   ssh admin@192.0.2.195 "ls -la ~/Documents/PVAnlage/pv-system/backup/db/daily/"

2. Security-Check (nur schauen, NICHT installieren):
   sudo apt update && apt list --upgradable 2>/dev/null | head -20

3. Nur bei kritischen Sicherheitslücken (SSH, OpenSSL, Kernel):
   sudo apt install --only-upgrade <paket>   # gezielt, NICHT apt upgrade!

4. Python-Pakete: NICHT upgraden solange System funktioniert
   pip3 list --outdated   # nur zur Info

5. Nach jedem manuellen Eingriff:
   systemctl status pv-collector pv-web
   sqlite3 /dev/shm/fronius_data.db "SELECT COUNT(*) FROM raw_data WHERE ts > strftime('%s','now') - 300;"
```

### Wann wird ein OS-Upgrade nötig?

Raspbian Bullseye erreicht EOL ca. Juni 2026. Ein Upgrade auf Bookworm
erfordert eine **Neuinstallation** (kein In-Place-Upgrade empfohlen):

- SD-Card-Image frisch flashen (Bookworm)
- Python 3.11 → alle pip-Pakete neu installieren & testen
- SQLite manuell neu kompilieren
- data.db von Pi5-Backup wiederherstellen
- Services + Cron neu einrichten (`scripts/install_services.sh`)
- **Zeitfenster**: ~2-4 Stunden, am besten abends (keine Solar-Daten verloren)

---

## 8. Dateien-Übersicht

### Kern-Scripts

| Datei | Funktion |
|-------|----------|
| modbus_v3.py | Collector: Modbus-Polling, RAM-Buffer, DB-Write, Energie-Integration |
| collector.py | Thin Wrapper, importiert modbus_v3.poller_loop() |
| web_api.py | Flask/Gunicorn Web-API + Frontend |
| restart_webserver.sh | Sichere Gunicorn-Neustart (ohne Collector) |
| db_init.py | tmpfs-DB Init, Persist-Thread, Schema-Migration |
| db_utils.py | get_db_connection() mit WAL-Modus |
| config.py | Alle Konfiguration (Pfade, Intervalle, Retention) |
| modbus_quellen.py | SunSpec Register-Definitionen, Unit IDs |

### Aggregation

| Datei | Pipeline-Stufe |
|-------|----------------|
| aggregate_1min.py | raw_data → data_1min (P×t-Integration, Batterieaufteilung) |
| aggregate.py | raw_data → data_15min → hourly_data (Counter-Deltas) |
| aggregate_daily.py | hourly_data → daily_data (Tages-Summen + Zählerstände) |
| aggregate_monthly.py | data_15min → data_monthly (technisches Monitoring) |
| aggregate_statistics.py | daily_data → monthly_statistics → yearly_statistics |

### Konfiguration

| Datei | Inhalt |
|-------|--------|
| config/battery_control.json | Batterie-Steuerungsregeln |
| config/color_config.json | Chart-Farbschema |
| config/geometry_config.json | String-Geometrie, Optimierer-Gain, Verschattung |
| config/solar_calibration.json | Kalibrationsfaktoren Clear-Sky |
| config/efficiency_table.json | WR-Wirkungsgrad-Kurve |

### Governance / Architektur-Regeln

| Dokument | Zweck |
|----------|-------|
| [ABC_TRENNUNGSPOLICY.md](ABC_TRENNUNGSPOLICY.md) | Trennung A Datenbank / B Web-API / C Automatisierung (dokumentierend, ohne Laufzeitwirkung) |
| [VEROEFFENTLICHUNGSRICHTLINIE.md](VEROEFFENTLICHUNGSRICHTLINIE.md) | Regeln für externe Veröffentlichung, Urheberrecht/Nutzungsrechte und Compliance-Prozess |
| [SCHUTZREGELN.md](SCHUTZREGELN.md) | Schutzregeln und Prioritäten für automatisierte Eingriffe |
| [DUAL_HOST_ARCHITECTURE.md](DUAL_HOST_ARCHITECTURE.md) | Rollenmodell `primary`/`failover`, Betriebsgrenzen, Failover-Abläufe |
| [AUTOMATION_ARCHITEKTUR.md](AUTOMATION_ARCHITEKTUR.md) | 4-Schichten-Architektur Schicht C (Observer → Engine → Actuator), Plugin-System, Migration |

Hinweis: Die Verschattungsmaske kann als globale Lookup-Tabelle oder pro String
in config/geometry_config.json gepflegt werden. Das erlaubt schrittweise
Ergaenzung ueber das Jahr (Azimut/Elevation -> Faktor 0..1). Optimierer werden
als per-String Optimierer-Gain modelliert und in der Leistungskette
beruecksichtigt.

### Web-UI (Templates)

| Template | Seite | Beschreibung |
|----------|-------|-------------|
| flow_view.html | /flow | Echtzeit-Energiefluss (SVG-Knoten, animierte Partikel, Batterie-Detail) |
| tag_view.html | /monitoring | Monitoring Tag/Monat/Jahr/Gesamt (Ertrag/Verbrauch-Charts) |
| echtzeit_view.html | /echtzeit | Echtzeit-Leistungskurven (3s-Auflösung) |
| erzeuger_view.html | /erzeuger | Erzeuger-Analyse (F1/F2/F3 Tag/Monat/Jahr/Gesamt) |
| verbraucher_view.html | /verbraucher | Verbraucher-Analyse (WP/E-Auto/Sonstige) |
| analyse_pv_view.html | /analyse/pv | PV-Übersicht (Jahresvergleich) |
| analyse_haushalt_view.html | /analyse/haushalt | Haushalt-Analyse |
| analyse_amortisation_view.html | /analyse/amortisation | Amortisationsrechnung |
| info_overlay.html | (alle Seiten) | Info-Button: Anlage, Verbraucher, Hardware, Software, System-Live |

**Design-System**: Minimalistisch grau (rgba(15,23,42,0.95)), container-basiert, ECharts 5.4.3  
**Navigation**: 3-Stufen — Hauptnav (Flow/Monitoring/Analyse) → Sub-Nav → Zeitraum-Buttons
