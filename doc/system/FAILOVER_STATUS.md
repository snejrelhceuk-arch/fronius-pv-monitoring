# Failover — Status (IST 2026-07-11, nach REFORMATION)

> Beschreibt den **IST-Zustand** des Failover-Hosts. Nach der REFORMATION ist der
> Failover **Pi5-FB** (`192.0.2.195`, admin, `.role=failover`) — **nicht** mehr der
> alte Pi4-Failover (der ist jetzt **Pi4-Küche**: Kiosk + Longterm-GFS).

## Einsatzbereitschaft — Kurzstatus

| Aspekt | Status | Details |
|---|---|---|
| Host | ✅ | Pi5-FB · `192.0.2.195` · admin · Pi 5 Rev 1.0 · 8 GB RAM · NVMe 512 GB · Debian 12 · Py 3.11 |
| Rolle | ✅ | `.role=failover` (read-only) — keine Writer (Collector/Automation/Aggregation) |
| **venv** | ✅ nativ | Pi5 mit Internet → native venv (kein Offline-Klon mehr nötig). Primary+Failover beide Py 3.11/aarch64 = Mirror-kompatibel |
| Code | ✅ | Gemeinsames Repo; Verteilung via `git push`/`pull` bzw. `scripts/sync_code_to_peer.sh` |
| DB-Mirror | ✅ funktional | `pv-mirror-sync` (Timer 10 min) zieht die Primary-`data.db` von `192.0.2.204` per rsync nach `/dev/shm/fronius_data.db` (tmpfs, atomarer `mv`). Sync-Marker `.state/last_mirror_sync.ok` frisch. SD/NVMe-`data.db` bleibt bewusst älter (Reboot-Fallback). |
| Ticker | ✅ | `pv-ticker.service` aktiv (inkl. 2. Zeile) |
| Backup | ✅ | Zentraler GFS-Empfänger (daily/weekly/monthly/yearly) auf NVMe. Großvater-Longterm-Offload (monthly/yearly) → Pi4-Küche via `scripts/install_longterm_offload.sh` |
| Web | ✅ | `pv-web.service` read-only auf `:8000` |
| Health/Badge | ✅ | Primary (`.204`) prüft `/api/failover_status` jetzt gegen `admin@192.0.2.195`; Flow-Badge **„Safe: Sync"** (grün) |

## Aktivierung (unverändert)

`scripts/failover_activate.sh` (+ `failover_set_mode.sh`, `routes/system/failover.py`).
Stufe 1 = Collector/Wattpilot starten; Stufe 2 = `.role=primary` (Aggregation + Automation).
Zurück: `.role=failover` + `scripts/failover_passive.sh`.

## Offene Punkte (siehe `doc/TODO.md`)

1. **SMTP-Passwort** auf Pi5-FB provisionieren (Secret, durch Betreiber), damit
   `pv-failover-health` Alarm-Mails senden kann.
2. **`data_stats.db`** in den Mirror-/Backup-Fluss aufnehmen (aktuell nur täglicher
   Direkt-Sync via `scripts/stats_archive_daily.sh`).
3. **Pi4-Küche-Zugang:** SSH-Key von `admin@Pi5-Primary` beim Pi4-Küche-User (jk)
   autorisieren, danach Kiosk-Autostart + Longterm-GFS-Offload deployen.
