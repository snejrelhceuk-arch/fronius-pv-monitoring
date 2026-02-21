# Dual-Host Architektur — Ein Repo, Drei Hosts, Zwei Rollen

> **PFLICHTLEKTÜRE für jedes LLM und jeden Entwickler.**  
> Dieses System läuft auf DREI Raspberry Pis mit EINEM Git-Repository.  
> Stand: 2026-02-20

---

## 1. Überblick

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│  Pi4 — PRIMÄR (Produktion)      │     │  Pi4 — FAILOVER (fronipi)       │
│  192.168.2.181 (eth0)           │     │  192.168.2.105 (eth0)           │
│  User: admin                    │     │  User: jk                       │
│  Hostname: raspberrypi          │     │  Hostname: fronipi              │
│  .role = "primary"              │     │  .role = "failover"             │
│  SD: 16 GB, RAM: 4 GB           │     │  SD: 128 GB, RAM: 8 GB          │
│                                 │     │  (+ Küchen-Display mit GUI)     │
│  ✓ Collector (Modbus → raw_data)│     │  ✗ Collector (gestoppt)         │
│  ✓ Wattpilot Collector          │     │  ✗ Wattpilot (gestoppt)         │
│  ✓ Web-API (3 Gunicorn Worker)  │     │  ✓ Web-API (1 Worker, read-only)│
│  ✓ Aggregation (Cron, 5 Jobs)   │     │  ✗ Aggregation (role_guard)     │
│  ✓ Battery Scheduler (Modbus!)  │     │  ✗ Battery Scheduler (role_guard)│
│  ✓ Monitor-Scripts (Cron)       │     │  ✗ Monitor-Scripts (role_guard)  │
│  ✓ DB in tmpfs (/dev/shm)      │     │  ✓ DB in tmpfs (Mirror → tmpfs) │
│  ✓ Persist: tmpfs → SD (stündlich)│   │  ✓ Mirror-Sync (alle 10 Min)    │
│  WLAN/BT: deaktiviert           │     │  ✓ Backup SD (1×/2d)            │
│                                 │rsync│                                 │
│  SD-Card: 16 GB                 │────►│  SD-Card: 128 GB                │
└──────────┬──────────────────────┘     └─────────────────────────────────┘
           │ Alternierend 1×/2 Tage
           ▼
┌─────────────────────────────────┐
│  Pi5 — BACKUP-Empfänger         │
│  192.168.2.195 (eth0)           │
│  192.168.2.196 (wlan0)          │
│  User: admin                    │
│  Hostname: PI5-5                │
│  476 GB NVMe                    │
│                                 │
│  Empfängt alternierende data.db │
│  + GFS-Dateikopien von Pi4      │
│  (Sohn 3-tägig, sonst unveränd.)│
│  KEIN eigenes pv-system aktiv.  │
└─────────────────────────────────┘
```

### Datenbankfluss (KRITISCH)

```
Pi4 Primär (181)                    Pi4 Failover fronipi (105)
═══════════════                     ══════════════════════════
Collector → raw_data
         ↓
    /dev/shm/fronius_data.db        /dev/shm/fronius_data.db
    (tmpfs, Live-DB)                (tmpfs, Mirror)
         │                                ▲
         │ rsync alle 10 Min              │
         └────────────────────────────────┘
         │                                    Kein SD-Write!
         │ SQLite .backup stündlich       SD nur via backup_db_every2d (1×/2d)
         ▼
    data.db (SD-Card)               data.db (SD-Card, Fallback nach Reboot)
         │
         │ rsync alle 6 Persist-Zyklen
         ▼
    Pi5 (195): data.db (NVMe)

Pi4 Primary zusätzlich:
  backup_db_gfs.sh (03:00 täglich via systemd)
    - Sohn alle 3 Tage aus /dev/shm → backup/db/daily
    - Vater/Großvater/Urgroßvater wie bisher
    - jede neu erzeugte GFS-Datei zusätzlich per rsync nach Pi5 backup/db/*
```

---

## 2. Die .role-Datei (KRITISCH)

Jeder Host hat eine lokale Datei `.role` im Repo-Root:

| Host | IP | User | Inhalt | Bedeutung |
|------|-----|------|--------|----------|
| Pi4 Produktion (raspberrypi) | 192.168.2.181 | admin | `primary`  | Volle Produktion: Collector, Aggregation, Battery-Steuerung |
| Pi4 Failover (fronipi)       | 192.168.2.105 | jk    | `failover` | Nur DB-Mirror (→tmpfs) + Web read-only. Kein Modbus, keine Writes |
| Pi5 Backup (PI5-5)           | 192.168.2.195 | admin | —          | Kein pv-system aktiv, nur Backup-Empfänger |

**Die Datei ist gitignored** — sie gehört zum Host, nicht zum Repo.  
Fehlt sie, gilt der Default `primary` (sicherer Rückfall).

### Ersteinrichtung .role
```bash
# Auf dem Failover-Pi4 fronipi (105):
echo "failover" > /home/jk/Dokumente/PVAnlage/pv-system/.role

# Auf dem Produktions-Pi4 (181):
echo "primary" > /home/admin/Dokumente/PVAnlage/pv-system/.role
# (oder weglassen — Default ist primary)
```

### Prüfung in Python-Scripts
```python
from host_role import is_failover
if is_failover():
    sys.exit(0)  # Dieses Script hat auf dem Failover nichts zu tun
```

### Prüfung in Shell-Scripts
```bash
source "$(dirname "$0")/scripts/role_guard.sh" 2>/dev/null || exit 0
# Ab hier: nur primary-Code
```

---

## 3. Was auf dem Failover LAUFEN darf

| Dienst | Warum |
|--------|-------|
| `pv-web.service` (1 Worker) | Read-only Dashboard, zeigt gespiegelte Daten |
| `pv-mirror-sync.timer` (10 Min) | Holt DB vom Primär per rsync |
| `pv-failover-health.timer` (1 Min) | Prüft Primär-Erreichbarkeit |
| `pv-backup-2d.timer` | Lokales DB-Backup alle 2 Tage |

## 4. Was auf dem Failover NICHT laufen darf

| Dienst/Job | Warum nicht |
|------------|-------------|
| `pv-collector.service` | Doppelte Modbus-Abfragen → Datendurcheinander |
| `pv-wattpilot.service` | WebSocket-Konflikt (nur 1 Verbindung), 17% CPU |
| `aggregate_*.py` (Cron) | Sinnlos — DB wird alle 10 Min überschrieben |
| `battery_scheduler.py` | **GEFÄHRLICH** — schreibt Modbus-Register zum WR! |
| `monitor_wattpilot.sh` | Startet Wattpilot neu → sabotiert passive mode |
| `monitor_collector.sh` | Collector ist bewusst aus |
| `capture_energy_checkpoints.py` | Schreibt Checkpoints, die beim Sync verloren gehen |
| `check_energy_counters.py` | Prüft Counter die nicht lokal gepflegt werden |

---

## 5. Git-Workflow mit zwei Hosts

### Goldene Regel
> **Alles was rollenabhängig ist, wird per `host_role.py` / `role_guard.sh` gesteuert —  
> NICHT per unterschiedlichem Code auf den beiden Pis.**

### Änderungen am Code
```
1. Entwickle auf EINEM Pi (egal welchem)
2. git commit + git push
3. Auf dem ANDEREN Pi: git pull
4. → Code ist identisch, Verhalten wird durch .role gesteuert
```

### Nach git pull auf dem Produktions-Pi4 (181)
```bash
cd /home/admin/Dokumente/PVAnlage/pv-system
git pull

# .role anlegen (einmalig, danach permanent):
echo "primary" > .role

# Keine Services neustarten nötig — die role_guards in den
# Python-Scripts erkennen "primary" und laufen normal weiter.
# Gunicorn-Restart nur nötig wenn gunicorn_config.py geändert wurde:
# sudo systemctl restart pv-web.service
```

### Nach git pull auf dem Failover-Pi4 fronipi (105)
```bash
cd /home/jk/Dokumente/PVAnlage/pv-system
git pull
# .role ist bereits "failover" (einmalig angelegt)
# Kein Restart nötig — neue Guards wirken beim nächsten Cron-Lauf
```

### Was NICHT ins Repo gehört (gitignored)
- `.role` — Host-Identität
- `.state/` — Laufzeit-Status (Sync-Marker, Empfehlungen)
- `data.db` — Datenbank
- `.secrets` — Zugangsdaten
- `*.log` — Logfiles

### Was ins Repo gehört
- `host_role.py` — Python Role-Check
- `scripts/role_guard.sh` — Shell Role-Check
- `scripts/failover_*.sh` — Failover-Steuerung
- `scripts/install_failover_services.sh` — Failover-Setup
- `gunicorn_config.py` — Worker-Anzahl passt sich automatisch an
- Diese Dokumentation

---

## 6. Failover-Aktivierung

### Automatisch? Nein.
Der Health-Check (`pv-failover-health.timer`) gibt nur eine **Empfehlung**.  
Kein automatischer Failover — zu riskant für Modbus-Steuerung.

### Manuell aktivieren (Stufe 1: Collector)
```bash
# Auf dem Failover-Pi4 fronipi (105):
/home/jk/Dokumente/PVAnlage/pv-system/scripts/failover_activate.sh
```
Das macht:
1. `PV_MIRROR_MODE=0` in Gunicorn-Override
2. Startet `pv-collector.service` + `pv-wattpilot.service`
3. Stoppt `pv-mirror-sync.timer`

**Achtung**: Die `.role`-Datei ändert sich dabei NICHT.  
Cron-Jobs (Aggregation, Battery-Scheduler) laufen erst,  
wenn `.role` manuell auf `primary` geändert wird.  
→ Zweistufige Sicherheit gegen versehentliche Doppelsteuerung.

### Manuell aktivieren (Stufe 2: Volle Übernahme)
Nur bei längerem Ausfall (> 2 Tage):
```bash
echo "primary" > /home/jk/Dokumente/PVAnlage/pv-system/.role
# → Aggregation + Battery-Scheduler laufen jetzt auch
```

### Zurück in Passive-Modus
```bash
echo "failover" > /home/jk/Dokumente/PVAnlage/pv-system/.role
/home/jk/Dokumente/PVAnlage/pv-system/scripts/failover_passive.sh
```

---

## 7. Checkliste für LLMs

Wenn du auf einem dieser Pis arbeitest:

1. **Lies `.role`** — weißt du ob du auf Primary oder Failover bist?
2. **Schreibe nie Code der nur auf einem Pi funktioniert** — nutze `host_role.py`
3. **Neue Cron-Jobs?** → `from host_role import is_failover` am Anfang
4. **Neues Shell-Script?** → `source scripts/role_guard.sh || exit 0`
5. **Modbus-Writes?** → Nur auf Primary! Prüfe `is_primary()`
6. **Diese Doku aktualisieren** wenn sich die Architektur ändert
7. **Commit + Push** damit der andere Pi die Änderung sieht

---

## 8. Ressourcen-Budget Failover (Pi4, fronipi 105)

| Ressource | Budget | Aktuell |
|-----------|--------|---------|
| CPU | < 5% idle | ~2% (nur Web + Sync) |
| RAM | < 500 MB für PV-System | ~200 MB (1 Worker + tmpfs-DB) |
| SD-I/O Writes | **~0** im Normalbetrieb | Nur 1×/2 Tage Backup (~130 MB) |
| tmpfs (RAM) | ~150 MB | Mirror-DB in /dev/shm |
| Netzwerk | rsync alle 10 Min | ~130 MB × 6/h = ~780 MB/h max |
| GUI/Browser | fronipi dient als Küchen-Display | Unberührt, kein Konflikt |

### Warum kaum SD-Writes?
Der Mirror-Sync (`failover_sync_db.sh`) schreibt **direkt nach /dev/shm** (tmpfs = RAM).  
Die SD-Card-Kopie (`data.db`) wird **nur** vom 2-Tage-Backup (`backup_db_every2d`) aktualisiert.  
Damit schont der Failover-Betrieb die SD-Karte maximal.

### Reboot-Verhalten
Nach Reboot ist `/dev/shm` leer. Der Gunicorn-Start (`ensure_tmpfs_db`) lädt einmalig  
die letzte `data.db` von der SD-Karte ins tmpfs als Fallback.  
Der nächste Mirror-Sync (≤10 Min) überschreibt sie mit aktuellen Daten.
---

## 9. Entwicklung & Code-Sync

> **Stand: 2026-02-21** — Commit-Sperre + Code-Sync implementiert.

### Goldene Regeln

1. **Entwickelt wird NUR auf dem Primary (181).**
2. **Committet wird NUR auf dem Primary (181).**
3. **Code-Sync zum Failover (105) per rsync** — ohne host-spezifische Dateien.
4. **Auf dem Failover NIEMALS committen** — Pre-Commit-Hook blockiert das.

### Schutzmechanismus: Pre-Commit-Hook

Datei: `scripts/pre-commit` → wird nach `.git/hooks/pre-commit` installiert.

```
┌─────────────────────────────────────────────────────────┐
│  git commit auf Host mit .role ≠ "primary"              │
│  → BLOCKIERT mit Fehlermeldung                          │
│                                                          │
│  Notfall-Override:                                       │
│    GIT_ALLOW_COMMIT=1 git commit -m "emergency fix"     │
└─────────────────────────────────────────────────────────┘
```

Installation (einmalig pro Host, nach `git clone` oder `sync_code_to_peer.sh`):
```bash
./scripts/install_hooks.sh
```

### Workflow: Entwickeln → Committen → Syncen

```
  Primary (181)                    Failover/fronipi (105)
  ═════════════                    ═══════════════════════

  1. Code ändern (VSCode/LLM)
  2. git add + git commit
  3. git push origin main
  4. ./scripts/sync_code_to_peer.sh
         │
         │  rsync (Code, Templates, Doku, .git/)
         │  OHNE: .role, *.db, *.log, *.pid, __pycache__,
         │        backup/, .secrets, Laufzeit-State
         │
         └──────────────────────────►  Code aktualisiert
                                       .role bleibt "failover"
                                       Hook blockiert Commits
                                       Services unverändert
```

### Scripts

| Script | Zweck | Aufruf |
|--------|-------|--------|
| `scripts/pre-commit` | Git-Hook: blockiert Commits auf Nicht-Primary | automatisch bei `git commit` |
| `scripts/install_hooks.sh` | Installiert Hook in `.git/hooks/` | einmalig: `./scripts/install_hooks.sh` |
| `scripts/sync_code_to_peer.sh` | rsync Code 181→105 (ohne host-spezifische Dateien) | `./scripts/sync_code_to_peer.sh [--dry-run] [--force]` |
| `scripts/check_repo_parity.sh` | Prüft Commit-Gleichstand Primary↔Failover | `./scripts/check_repo_parity.sh [/mnt/failover-pv]` |

### Was wird NICHT gesynct (host-spezifisch)

| Muster | Grund |
|--------|-------|
| `.role` | Host-Identität (primary vs failover) |
| `.state/` | Laufzeit-Status (Sync-Marker, Empfehlungen) |
| `*.db`, `*.db-shm`, `*.db-wal` | Datenbank (eigener Mirror-Sync alle 10 Min) |
| `*.log` | Logfiles (host-lokal) |
| `*.pid` | Prozess-IDs |
| `__pycache__/` | Python-Bytecode |
| `backup/` | Lokale Backups |
| `.secrets` | Zugangsdaten |
| `config/battery_scheduler_state.json` | Laufzeitstatus Battery-Scheduler |
| `config/battery_bms_checkpoints.json` | BMS-Checkpoints |

### Ersteinrichtung auf neuem Host

```bash
# 1. Repo klonen
git clone https://github.com/snejrelhceuk-arch/fronius-pv-monitoring.git pv-system
cd pv-system

# 2. Rolle setzen
echo "failover" > .role    # oder "primary"

# 3. Hook installieren
./scripts/install_hooks.sh

# 4. Fertig — auf Failover sind Commits blockiert
```