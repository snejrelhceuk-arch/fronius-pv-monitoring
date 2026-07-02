# Pi4-Failover — Status (IST 2026-07-02)

> Beschreibt den **IST-Zustand** des Failover-Hosts (`Pi4-failover`, Rolle `failover`).

## Einsatzbereitschaft — Kurzstatus

| Aspekt | Status | Details |
|---|---|---|
| Erreichbarkeit | ✅ | passwortloses SSH; up (12+ Tage) |
| Hardware/Python | ✅ | aarch64 / Python 3.13.5 — **identisch** zum Primary |
| **venv** | ✅ **provisioniert** | vom Primary geklont (offline, Failover hat **kein** Internet), Pfade gepatcht, 32 Pakete = Primary; `web_api` importiert sauber |
| Code | ✅ | via `sync_code_to_peer.sh` auf Primary-Stand (git HEAD identisch) |
| STATS-DB | ✅ | `data_stats.db` (51 692 Zeilen) vorhanden; `tag_table()` liefert `stats.data_5min_permanent` → Tag-Charts nach Aktivierung verfügbar |
| DB-Mirror | ✅ funktional | `pv-mirror-sync` (oneshot, Timer 10 min) zieht die Primary-`data.db` per rsync **nach `/dev/shm/fronius_data.db`** (tmpfs, = die bei Aktivierung genutzte DB), atomarer `mv`. Sync-Marker `.state/last_mirror_sync.ok` frisch (≈ 9 s). RAM-Mirror aktuell bis ~20:59 (Lag ≈ Primary-Persist-Kadenz + rsync-Dauer). Die **SD-`data.db` bleibt bewusst alt** (nur 2-Tage-Backup schreibt sie). |
| `pv-failover-health.service` | ⚠️ zeitweise „failed" | Script `exit 1`, wenn es einen Failover **empfiehlt** (Marker „veraltet" > `MAX_SYNC_AGE_SEC=660`). Trat transient auf, als ein Sync-Lauf um 20:57 fehlschlug; bei frischem Marker meldet der Check OK. Zusätzlich fehlt auf dem Failover das **SMTP-Passwort** (Alarm-Mail). |

## Warum „no internet" relevant ist

Der Failover hat **keinen Internet-Zugang** → `pip install` scheidet aus. Die venv wurde
deshalb **direkt vom Primary geklont** (rsync `.venv/`) und die einprogrammierten Pfade
(Primary-Home → Failover-Home) in `.venv/bin/*` + `.venv/pyvenv.cfg` per `sed`
gepatcht. Da HW-Arch (aarch64) und Python (3.13.5) identisch sind, ist der Klon binär
kompatibel. Verifiziert: `import flask, gunicorn, pymodbus, requests, numpy, wattpilot,
paho.mqtt.client` OK; `import web_api` OK. (`astral`/`pandas` sind auf **beiden** Hosts
nicht installiert = keine Laufzeit-Abhängigkeit.)

## Offene Punkte (in `doc/TODO.md`)

1. **SMTP-Passwort** auf dem Failover provisionieren (`/etc/pv-system/smtp_pass.key`,
   gleiches Verfahren wie Primary — **Secret, durch den Betreiber**), damit
   `pv-failover-health` Alarm-Mails senden kann und nicht mehr auf SMTP fehlschlägt.
2. **Mirror-Sync entschlacken (optional):** Der rsync-Vollpull der Primary-`data.db`
   (~285 MB) nach `/dev/shm` dauert je Lauf einige Minuten und schlägt gelegentlich fehl
   (→ transiente `pv-failover-health`-„failed"). Optionen: rsync `--inplace`/Delta,
   `MAX_SYNC_AGE_SEC` an die reale Pull-Dauer anpassen, oder zusätzlich die kleinere
   `data_stats.db` spiegeln.
3. **`data_stats.db` in den Mirror-/Backup-Fluss** aufnehmen (aktuell nur täglicher
   Direkt-Sync durch `scripts/stats_archive_daily.sh`).

## Aktivierung (unverändert)

`scripts/failover_activate.sh` (+ `failover_set_mode.sh`, `routes/system/failover.py`).
Nach der venv-Provisionierung ist der Failover startfähig (Web/Collector/Automation via
`.venv/bin/python`).
