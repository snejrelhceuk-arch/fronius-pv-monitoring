---
title: System Hosts + Deployment (Pi-Topologie, Sync, Dienst-Map)
domain: system
role: meta
applyTo: "scripts/**"
tags: [hosts, deployment, rsync, sync, pi, tech, failover, kueche, rolle-n]
status: stable
last_review: 2026-08-06
changes:
	- 2026-08-06: Card angelegt. Deployment auf integrierte Pi's (Tech/FB/Küche) ist autorisiert (wie Primary) — s. AGENTS.md Deployment-Policy. Dienst→Host-Map + Sync-Werkzeuge + Tech-Deploy-Rezept dokumentiert.
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
- **Einzel-Host-Sync:** `scripts/sync_code_to_peer.sh`.
- **NQ-Dienst-Installer (role-aware):** `scripts/install_nq_services.sh` (installiert je Rolle die
  passenden systemd-Units/Timer).
- **Rolle über `.role`** (gitignored) — nie über Code-Divergenz.

### Rezept: gezieltes Tech-Deploy (Rolle-N-Collector)
```
# von Primary aus (reale IP aus .infra.local → PV_TECH_IP):
rsync -az nq/ config/nq_config.json  admin@$PV_TECH_IP:Dokumente/PVAnlage/pv-system/nq/…
ssh admin@$PV_TECH_IP 'sudo -n systemctl restart pv-nq-poller.service'
```
(Poller ist idempotent, `Restart=always`, ~0,5 s PAC-Lücke bei Neustart.)

## Dienst → Host (Kurz)
- **Primary:** `pv-web`, `pv-automation`, `pv-collector`, NQ-Primary-Timer
  (`pv-nq-agg-transfer`, `pv-nq-aggregate`, `pv-nq-analysis(-hf-nf)`, `pv-nq-energy-rollup(-month/-year)`,
  `pv-nq-primary-cap`, `pv-nq-event-transfer`).
- **Tech:** `pv-nq-poller`, `pv-nq-energy`, `pv-wp-bridge`.
- **FB:** `pv-ticker`, Failover-/Backup-Empfang.
- **Küche:** Kiosk, Longterm-GFS-Offload.

## Workspace-Vollständigkeit
Der Primary-Workspace ist die **vollständige Quelle**. Liegen auf anderen Hosts
pv-system-Programme/Skripte/Docs, die hier fehlen, werden sie **hierher integriert**
(nicht der `volkszaehlung`-Hook auf Fremdhost-Zählung erweitert).

## Code-Anchor
- **Voll-Sync:** `scripts/sync_workspace_all_hosts.sh`
- **Einzel-Sync:** `scripts/sync_code_to_peer.sh`
- **NQ-Installer:** `scripts/install_nq_services.sh`
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
