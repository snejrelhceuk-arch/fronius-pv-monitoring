---
title: System Hosts + Deployment (Pi-Topologie, Sync, Dienst-Map)
domain: system
role: meta
applyTo: "scripts/**"
tags: [hosts, deployment, rsync, sync, pi, tech, failover, kueche, rolle-n]
status: stable
last_review: 2026-09-29
---

# System Hosts + Deployment

## Zweck
Verbindliche Host-Topologie, **Deployment-Autorisierung** und Sync-/Dienst-Map.
Entwickelt wird auf **Primary**; Code wird per `rsync` zu den integrierten Hosts
verteilt (Verhalten steuert die gitignored `.role`-Datei, **nicht** divergenter Code).

## Hosts (Doku-IPs; reale IPs in `.infra.local`)
| Host | Doku-IP | User | Rolle / Dienste |
|---|---|---|---|
| **Pi5-Primary** | 192.0.2.204 | admin | Produktion A–E + NQ-Primary (Aggregation/Analyse/Rollup). `.role=primary` |
| **Pi5-FB** | 192.0.2.195 | admin | Failover (read-only), Backup-Empfänger, **Dashboard-Ticker** (`pv-ticker`, Port 8050). `.role=failover` |
| **Pi4-Küche** | 192.0.2.105 | jk | Kiosk-Display + Longterm-GFS (monthly/yearly) |
| **Pi4-Tech** | 192.0.2.181 | admin | **NQ-Collector (Rolle N)**: `pv-nq-poller`, `pv-nq-energy`; WP/HW-Bridge (`pv-wp-bridge`, `WP_BACKEND_MODE=local`). RAM-first (tmpfs) |
| Ubuntu-LLM | (extern) | — | Ollama-Host (Ticker-LLM). Zugriff via HTTP-API (`/api/pull`/`/api/generate`), kein SSH nötig. Repo-Teil: `ollama/` |

## Deployment (autorisiert für alle integrierten Pi's)
- **Runtime-Read-only (No-Go #8) bleibt:** Rolle N schreibt keine Produktionsdaten/Aktoren.
  Das **Ausrollen von Code** ist davon unberührt und **erlaubt** — genau wie auf Primary.
- **Voller Workspace-Sync (alle Hosts):** `scripts/sync_workspace_all_hosts.sh` (role-guarded=primary,
  `PV_SYNC_HOSTS`/`PV_SYNC_REMOTE_PATH` aus `.infra.local`, `rsync -az --delete`, nur git-tracked Code —
  Laufzeitdaten `*.db`/`.role`/`.secrets`/`.venv` ausgeschlossen).
- **Einzel-Host-Sync (Failover):** `scripts/sync_code_to_peer.sh`.
- **Tech-Code-Sync (Rolle N) + Poller-Restart-Hook:** `scripts/sync_code_to_tech.sh`
  (git-tracked only; startet `pv-nq-poller`/`pv-nq-energy` **nur** neu, wenn `nq/` oder
  `config/nq_config.json` geändert wurden). Verhindert stillen Tech-Code-Drift.
- **NQ-Dienst-Installer (role-aware):** `scripts/install_nq_services.sh` (installiert je Rolle die
  passenden systemd-Units/Timer). Wird von `scripts/install_services.sh` am Ende mit aufgerufen,
  damit NQ nach Reinstall nicht vergessen wird.
- **Rolle über `.role`** (gitignored) — nie über Code-Divergenz.

### Rezept: gezieltes Tech-Deploy (Rolle-N-Collector)
```
# von Primary aus — ein Kommando (Sync git-tracked + Restart-Hook):
scripts/sync_code_to_tech.sh            # mit Nachfrage
scripts/sync_code_to_tech.sh --force    # ohne Nachfrage (Cron-tauglich)
```
(Der Restart-Hook fasst den Poller nur an, wenn NQ-Code/-Config geändert wurde; Poller ist
idempotent, `Restart=always`, ~0,5 s PAC-Lücke bei Neustart.)

**Tech-Reboot (nicht nur Restart):** immer `scripts/1_reboot_Tech.sh` oder `scripts/pv_tech_safe_reboot.sh` — beide sind Primary-guarded und ziehen zuerst die tmpfs-NQ-Aggregate per `pv_nq_flush.sh` nach Primary. Ohne Flush gehen bis zu 4 h 5-min-Daten verloren (Tech ist RAM-first ohne SD-Persist).

## Dienst → Host (Kurz)
- **Primary:** `pv-web`, `pv-automation`, `pv-collector`, NQ-Primary-Timer
  (`pv-nq-agg-transfer`, `pv-nq-aggregate`, `pv-nq-analysis(-hf-nf)`, `pv-nq-energy-rollup(-month/-year)`,
  `pv-nq-primary-cap`, `pv-nq-event-transfer`, `pv-nq-backup` (GFS tägl. 03:00)).
- **Tech:** `pv-nq-poller`, `pv-nq-energy`, `pv-wp-bridge`.
- **FB:** `pv-ticker`, Failover-/Backup-Empfang.
- **Küche:** Kiosk, Longterm-GFS-Offload.

## Workspace-Vollständigkeit
Der Primary-Workspace ist die **vollständige Quelle**. Liegen auf anderen Hosts
pv-system-Programme/Skripte/Docs, die hier fehlen, werden sie **hierher integriert**
(nicht der `volkszaehlung`-Hook auf Fremdhost-Zählung erweitert).

## Code-Anchor
- **Voll-Sync:** `scripts/sync_workspace_all_hosts.sh`
- **Einzel-Sync (Failover):** `scripts/sync_code_to_peer.sh`
- **Tech-Sync + Poller-Restart-Hook:** `scripts/sync_code_to_tech.sh`
- **NQ-Installer:** `scripts/install_nq_services.sh` (aus `scripts/install_services.sh` aufgerufen)
- **Rollen-Logik:** `host_role.py`

## No-Gos
- Sync-Skripte nur auf Primary ausführen (Role-Guard) — nie Code vom Peer zurück auf Primary.
- Keine realen IPs im Repo (Doku-IP `192.0.2.x`; reale via `.infra.local`).
- `.role`/`.secrets`/`*.db` nie syncen (bereits in den rsync-Excludes).

## Verwandte Cards
- [`system-ops-guards.card.md`](./system-ops-guards.card.md) — Rollen-Guard, Backup, Publish
- [`netzqualitaet-nq-collector.card.md`](./netzqualitaet-nq-collector.card.md) — Tech-Collector (Deploy-Ziel)

## Human-Doku
- `AGENTS.md` (Hosts + Deployment-Policy)
- `doc/system/WR_FERNSTEUERUNG.md`
