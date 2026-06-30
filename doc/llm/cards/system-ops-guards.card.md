---
title: System Ops-Guards (Rollen, Sync, Backup, Publish)
domain: system
role: meta
applyTo: "scripts/**"
tags: [role-guard, failover, backup, publish-guard, sync]
status: stable
last_review: 2026-06-30
---

# System Ops-Guards

## Zweck
Systemweite Betriebsleitplanken fuer Multi-Host-Betrieb: `.role`-basiertes Verhalten, sichere Code-Synchronisation, Backup-Rhythmus und Publish-Guard vor oeffentlichen Pushes.

## Code-Anchor
- **Python-Rollencheck:** `host_role.py:get_role`, `is_primary`, `is_failover`
- **Shell-Rollencheck:** `scripts/role_guard.sh`
- **Cron-Monitore:** `scripts/monitor_collector.sh`, `scripts/monitor_wattpilot.sh`, `scripts/monitor_steuerbox.sh`
- **Terminal-Safe-Runner:** `scripts/terminal_safe_run.sh`
- **Code-Sync Primary->Failover:** `scripts/sync_code_to_peer.sh`
- **Failover-Quickstart (64bit-Rebuild):** `scripts/failover_postswap_quickstart.sh`, `scripts/install_failover_services.sh`, `scripts/failover_sync_db.sh`
- **Browser-Autostart (Display-Host):** `scripts/pv_kiosk_browser.sh`, `scripts/install_kiosk_autostart.sh`
- **GFS-Backup:** `scripts/backup_db_gfs.sh`
- **Publish-Audit:** `scripts/publish_audit.sh`
- **Service-Definitionen:** `config/systemd/pv-automation.service`, `config/systemd/pv-observer.service`, `config/systemd/pv-wattpilot.service`, `config/systemd/pv-steuerbox.service`
- **Optionaler HA-Adapter-Service:** `config/systemd/pv-ha-bridge.service`

## Inputs / Outputs
- **Inputs:** `.role`, `.infra.local`/ENV, `.publish-guard`, `/dev/shm/fronius_data.db`, Backup-Verzeichnisse unter `backup/db/*`.
- **Outputs:** Rollenbasiertes Enable/Skip von Jobs, rsync-Codeabgleich, GFS-Backups, Publish-Freigabe/Blockade.

## Invarianten
- Ein gemeinsamer Code-Stand auf den Hosts; Verhalten wird ueber `.role` gesteuert, nicht ueber divergenten Code.
- Failover darf keine Writer-Pfade fuer Collector/Aggregation/Automation aktiv betreiben.
- Publish-Pipeline muss vor Push sensible Muster blocken (`.publish-guard` + `publish_audit.sh`).
- GFS-Backups werden aus der RAM-DB per `sqlite3 .backup` erzeugt, nicht per blindem Datei-Copy im Laufbetrieb.
- `.venv` ist erforderlich (nicht entfernen): Unter Debian 13 ist System-Python PEP-668-`EXTERNALLY-MANAGED`, und `gunicorn`/`pymodbus`/`minimalmodbus`/`paho-mqtt`/`websocket-client`/`websockets`/`wattpilot` fehlen systemweit. Writer/Protokoll-Services (`pv-web`/`pv-collector`/`pv-wattpilot`/`pv-steuerbox`) laufen aus `.venv`; reine Engine-/Aggregations-Jobs nutzen System-`/usr/bin/python3`. `.venv` ist lokal reproduzierbar (`requirements.txt`) und aus Git/Code-Sync ausgeschlossen.
- Terminal-Schutzlogik lebt nur in `scripts/terminal_safe_run.sh`; VS-Code-Tasks nutzen dieses Script unveraendert weiter.
- Cron-Monitore werden aus `scripts/` gestartet, berechnen aber den Repo-Root als Basis und sourcen `scripts/role_guard.sh` von dort.

## No-Gos
- Keine Umgehung der Rollenpruefung bei neuen Cron-/Shell-Jobs.
- Keine destruktiven Git-Aktionen ohne explizite Freigabe.
- Kein Commit sensibler Infrastrukturdaten (`.infra.local`, reale Hostdaten, Secrets).

## Häufige Aufgaben
- Neuen Shell-Job absichern -> frueh `source scripts/role_guard.sh || exit 0` einbauen.
- CI/LLM-Terminal robust fahren -> `./scripts/terminal_safe_run.sh -- <kommando>` verwenden.
- Neues Leak-Muster aufnehmen -> `.publish-guard` erweitern, dann `./scripts/publish_audit.sh --history` laufen lassen.
- Backup-Retention anpassen -> `scripts/backup_db_gfs.sh` (Daily/Weekly/Monthly) aendern.
- Peer driften synchronisieren -> `./scripts/sync_code_to_peer.sh` verwenden.

## Bekannte Fallstricke
- Fehlt `.role`, ist der Default `primary` (sicher fuer Produktion, gefaehrlich auf falsch konfiguriertem Failover).
- Dienstnamen koennen zwischen Doku und lokaler systemd-Realitaet driften; Diagnos-Servicechecks dann pruefen.
- Code-Sync schliesst absichtlich Laufzeitdateien (`*.db`, `.state`, `.secrets`) aus; Probleme dort nicht mit Code-Sync suchen.
- Prompt-Paste (`(.venv) user@host:...`) fuehrt in VS Code Tasks oft zu Exit 1; Safe-Runner erkennt und blockt dies frueh.
- Workspace-Pfadwechsel (OS-Migration `Dokumente/PVAnlage` -> `Dokumente/PVAnlage`): installierte Units in `/etc/systemd/system/` und die `.venv` (bin-Shebangs + `pyvenv.cfg`) tragen absolute Alt-Pfade. Folge: `203/EXEC` beim Service-Restart und laufende Prozesse auf bereits verschwundenen Binaries. Beide Stellen mit-migrieren, dann `daemon-reload` + Restart.
- Pfadwechsel trifft auch die **User-Crontab** (`crontab -l`): Aggregations-Jobs (`min1`/`fifteen`/`daily`/`monthly`) laufen `cd <alt-pfad> && python3 -m collector.aggregate.*` und scheitern still mit `ModuleNotFoundError: No module named 'collector'`. Symptom: `raw_data` frisch, aber `data_1min`/`data_15min`/`hourly_data` stehen -> Monitoring-Chart endet abrupt. Fix: `crontab -l | sed 's#alt#neu#g' | crontab -`. Lücke per `min1._aggregate_1min_impl(conn,cur,bucket_ts)` aus `raw_data` nachfüllen (nur soweit Retention reicht).
- Failover-DB-Mirror (`failover_sync_db.sh`) braucht Key-Auth Failover->Primary; nach SD-Reflash fehlt der Host-Key (`ssh-keyscan`) und der Pull-Key in `authorized_keys` des Primary.

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)

## Human-Doku
- `doc/system/DUAL_HOST_ARCHITECTURE.md`
- `doc/system/PUBLISH_GUARD.md`
- `doc/system/GIT_WORKFLOW.md`
