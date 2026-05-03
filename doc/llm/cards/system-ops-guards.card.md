---
title: System Ops-Guards (Rollen, Sync, Backup, Publish)
domain: system
role: meta
applyTo: "scripts/**"
tags: [role-guard, failover, backup, publish-guard, sync]
status: stable
last_review: 2026-05-03
---

# System Ops-Guards

## Zweck
Systemweite Betriebsleitplanken fuer Multi-Host-Betrieb: `.role`-basiertes Verhalten, sichere Code-Synchronisation, Backup-Rhythmus und Publish-Guard vor oeffentlichen Pushes.

## Code-Anchor
- **Python-Rollencheck:** `host_role.py:get_role`, `is_primary`, `is_failover`
- **Shell-Rollencheck:** `scripts/role_guard.sh`
- **Terminal-Safe-Runner:** `scripts/terminal_safe_run.sh`
- **Code-Sync Primary->Failover:** `scripts/sync_code_to_peer.sh`
- **GFS-Backup:** `scripts/backup_db_gfs.sh`
- **Publish-Audit:** `scripts/publish_audit.sh`
- **Service-Definitionen:** `config/systemd/pv-automation.service`, `config/systemd/pv-observer.service`, `config/systemd/pv-wattpilot.service`, `config/systemd/pv-steuerbox.service`

## Inputs / Outputs
- **Inputs:** `.role`, `.infra.local`/ENV, `.publish-guard`, `/dev/shm/fronius_data.db`, Backup-Verzeichnisse unter `backup/db/*`.
- **Outputs:** Rollenbasiertes Enable/Skip von Jobs, rsync-Codeabgleich, GFS-Backups, Publish-Freigabe/Blockade.

## Invarianten
- Ein gemeinsamer Code-Stand auf den Hosts; Verhalten wird ueber `.role` gesteuert, nicht ueber divergenten Code.
- Failover darf keine Writer-Pfade fuer Collector/Aggregation/Automation aktiv betreiben.
- Publish-Pipeline muss vor Push sensible Muster blocken (`.publish-guard` + `publish_audit.sh`).
- GFS-Backups werden aus der RAM-DB per `sqlite3 .backup` erzeugt, nicht per blindem Datei-Copy im Laufbetrieb.
- Terminal-Schutzlogik lebt nur in `scripts/terminal_safe_run.sh`; VS-Code-Tasks nutzen dieses Script unveraendert weiter.

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

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)

## Human-Doku
- `doc/system/DUAL_HOST_ARCHITECTURE.md`
- `doc/system/PUBLISH_GUARD.md`
- `doc/system/GIT_WORKFLOW.md`
