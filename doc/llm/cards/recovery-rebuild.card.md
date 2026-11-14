---
title: Host-Rebuild + Manifeste + Integrations-Verifier (Rolle R)
domain: recovery
role: R
applyTo: "recovery/**"
tags: [recovery, rebuild, manifest, integration, tagging, ssh, provisioning]
status: stable
last_review: 2026-11-14
---

# Host-Rebuild (Rolle R)

## Zweck
Einen Ziel-Host von einem Quell-Host (Default: lokal) wiederherstellen, sobald
dort ein SSH-fähiges Basis-System läuft. Verallgemeinert das
`doc/system/REFORMATION_RUNBOOK.md` zu einem wiederholbaren Tool.

## Werkzeug: `recovery/rebuild_host.sh`
```
recovery/rebuild_host.sh <ziel-id> [--from <quell-id>] [--apply]
                         [--push-key] [--with-secrets] [--yes]
```
Ablauf (je Stufe nur mit `--apply`): 0) Key-Push (einmalig, Passwort) ·
1) Code-rsync (Working-Tree + `.git`, ohne Runtime) · 2) `.role` setzen +
`.infra.local`/`.secrets` aus Secrets-Bundle (`--with-secrets`) · 3) venv nativ ·
4) Installer je Rolle (`scripts/install_services.sh`, `scripts/install_nq_services.sh`,
`scripts/install_failover_services.sh`, `scripts/install_kiosk_autostart.sh`,
`recovery/install_recovery.sh`) · 5) Daten-Restore-Hinweis + Smoke.

## Invarianten
- **DRY-RUN ist Default.** Echte Änderungen nur mit `--apply`.
- **Selbstschutz:** Ziel-Rolle == lokale Rolle → Abbruch (kein Selbst-Rebuild).
- **Kein Auto-Writer:** Bei Ziel=primary werden Writer/Automation **nicht**
  gestartet (manuell nach Verifikation; Split-Brain-Schutz).
- Idempotent (rsync/venv/Installer wiederholbar).

## Host-Manifeste: `recovery/hosts/<id>.yaml`
Quelle der Wahrheit für Rebuild + Verifier + Paket. Felder u. a. `role`, `user`,
`ip_env` (Name der `.infra.local`-Var, **keine** Literal-IP), `repo_subpath`,
`services`, `timers`, `cron`, `config_files`, `secret_keys`, `provisioning`.
Schema: `recovery/hosts/_schema.md`. Vorhanden:
`recovery/hosts/primary.yaml`, `recovery/hosts/failover.yaml`,
`recovery/hosts/tech.yaml`, `recovery/hosts/kueche.yaml`.

## Integrationsmanagement / Tagging
Fremddateien (außerhalb Repo) führt `recovery/manifests/system_files.yaml`
(Kategorie, Pfad-Muster, Marker-Fähigkeit). Editierbare tragen Kopf-Marker
`PV-SYSTEM-MANAGED`. `recovery/verify_integration.sh` vergleicht Manifest↔OS:
- **FEHLT** = deklariert, nicht installiert (zählt als Drift).
- **verwaist** = installiert, nicht deklariert (Info). Timer-Backing-Services
  (`pv-x.timer`→`pv-x.service`) gelten automatisch als deklariert.
`--strict` → Exit 1 bei Drift.

## No-Gos
- Niemals den eigenen Host als Ziel. Keine echten IPs/Secrets ins Repo.
- Keine Writer-Scharfschaltung / kein Reboot aus dem Rebuild.

## Verwandte
- `recovery-overview.card.md`, `recovery-package.card.md`,
  `doc/system/RECOVERY.md`, `doc/system/REFORMATION_RUNBOOK.md`,
  `doc/system/FAILOVER_STATUS.md`.
