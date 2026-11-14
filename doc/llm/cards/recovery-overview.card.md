---
title: Recovery-Überblick (Rolle R, Szenarien, Artefakte)
domain: recovery
role: R
applyTo: "recovery/**"
tags: [recovery, disaster, rebuild, rolle-r, provisioning, backup, offsite]
status: stable
last_review: 2026-11-14
---

# Recovery-Überblick — Rolle R

## Zweck
Rolle **R** installiert, rekonstruiert und hält das pv-system aktuell —
host-übergreifend. Keine Dauer-Engine, keine `.role`: R ist das Repo-Modul
`recovery/`, präsent auf **allen** Hosts, ruht bis zum Einsatz. Sonder-Schreib-
autorität: Software-/OS-Installation auf **Ziel**-Hosts (getrennt von C).

## Einordnung
- ABCDEN (laufende Fachrollen) + **R** (orthogonale Provisioning/DR-Meta-Rolle).
- R ist **Eigentümer des Backup-Themas** (DR-Sicht). Die laufende GFS-Kette bleibt
  funktional (`doc/system/BACKUP_STRATEGY.md`); Gesamtpaket + Restore + Off-site → R.

## Szenarien (Kurz)
- **S1** Non-Primary-Ersatz → von Primary `recovery/rebuild_host.sh <host>`.
- **S2** Primary defekt, FB ok → FB-Promotion, dann `rebuild_host primary`.
- **S3** Primary+FB aus → von Tech/Küche Primary rekonstruieren.
- **S4** Baseline-Neuinstall → Paket → Nachholen auf aktuellen HEAD.
- **S5** Totalverlust → USB (off-site) + Off-site-Daten → alle 4 Hosts ausrollen.

Vorbedingung: SSH-fähiges Basis-System + Passwort; Key via `--push-key`.

## Artefakte (Owner-Dateien)
- `recovery/hosts/primary.yaml` u. a. — Host-Manifeste (publish-sicher, IP via `*_env`).
- `recovery/rebuild_host.sh` — Host-Rebuild (dry-run-default, Selbstschutz).
- `recovery/build_recovery_bundle.sh` / `recovery/export_usb.sh` — Gesamtpaket + USB.
- `recovery/secrets_bundle.sh` — portables gpg-Secrets-Bundle (machine-id-Problem).
- `recovery/verify_integration.sh` — Integrations-Drift Manifest↔OS.
- `recovery/recovery_selfcheck.py` / `recovery/offsite_data_reminder.py` — Mail-Jobs.
- `recovery/pv_auto_update_guard.py` + `recovery/pv_update_all_hosts.sh` — Update/Upgrade.

## Invarianten
- **Produktionssicherheit zuerst:** Rebuild schaltet **nie** automatisch Writer/
  Automation scharf (`.role=primary` + Writer bleiben manuell — Split-Brain-Schutz).
- **Selbstschutz:** Ein Host rekonstruiert sich **nie selbst** (`rebuild_host.sh`).
- **Aktualität = Major-Version** (Ganzzahl aus git-Tag `vN`, aktuell v7). Paket/USB
  veralten bei Major-Sprung → Selfcheck-Mail.
- **Keine echten IPs/Secrets im Repo** (Publish-Guard): Manifeste referenzieren
  `.infra.local` über `*_env`-Namen; Secrets nur im gitignored `backup/recovery/`.

## No-Gos
- Keine Writer-Scharfschaltung aus dem Rebuild. Kein Auto-Reboot.
- Secrets nie unverschlüsselt ins Paket/USB/git.

## Häufige Aufgaben
- Host ersetzen → `recovery-rebuild.card.md`.
- Paket/USB/Secrets/Off-site → `recovery-package.card.md`.

## Verwandte Cards / Doku
- `doc/system/RECOVERY.md` (Human-Doku), `system-hosts.card.md`,
  `system-ops-guards.card.md`, `recovery-rebuild.card.md`, `recovery-package.card.md`.
