---
title: Recovery-Paket, USB, Secrets, Selfcheck, Update-Strategie (Rolle R)
domain: recovery
role: R
applyTo: "recovery/**"
tags: [recovery, bundle, usb, secrets, selfcheck, offsite, update, upgrade]
status: stable
last_review: 2026-11-14
---

# Recovery-Paket & Lifecycle (Rolle R)

## Gesamtpaket
`recovery/build_recovery_bundle.sh [--with-secrets]` erzeugt ein self-contained
Paket nach `backup/recovery/` (gitignored): git-Bundle (`--all`),
`requirements.txt`, Doku, `MANIFEST.txt` + sha256, Marker `LATEST_RECOVERY`.
Dateiname trägt die **Major-Version** (`v7`). Auf jedem Host vorhaltbar.

## USB-Export (Extrem-Szenario S5)
`recovery/export_usb.sh --dest <mount> [--with-secrets]` kopiert das neueste
Paket auf USB, schreibt `USB_RECOVERY_VERSION` (auf Stick) + `USB_LAST_EXPORT`
(host-seitig, für Selfcheck). Stick **räumlich getrennt** lagern.

## Secrets (machine-id-Problem)
`credential_store` ist an `/etc/machine-id` gebunden → auf Ersatz-HW nicht
entschlüsselbar. `recovery/secrets_bundle.sh create` bündelt `.infra.local`/
`.secrets` **gpg/AES256-passphrase**-verschlüsselt nach `backup/recovery/`.
`restore --target u@ip --subpath <pfad>` legt sie aufs Ziel; **SMTP-Pass dort neu**
setzen (`scripts/set_smtp_password.py`).

## Aktualitäts-Selbstcheck
`recovery/recovery_selfcheck.py` (Timer `pv-recovery-selfcheck`, wöchentlich,
`--build`): vergleicht aktuelle **Major-Version** (git-Tag `vN`) mit Paket- und
USB-Marker; baut veraltetes/fehlendes Paket neu und **mahnt** veralteten USB per
Mail. Ganzzahlige Versionswechsel (Major) sind der Auslöser.

## Off-site-Datensicherung
`recovery/offsite_data_reminder.py` (Timer `pv-offsite-reminder`, monatlich):
Mail-Mahnung, Datensnapshot (Longterm-GFS monthly/yearly + aktuelle DB + Paket)
auf externes Medium zu kopieren und **anderes Gebäude** zu lagern (keine Cloud).

## Update/Upgrade-Strategie (gehört zu R)
- `recovery/pv_auto_update_guard.py` (Timer `pv-auto-update`, täglich): Warn-Mail →
  bei **72 h git-Inaktivität auf Primary** (Aktivität = neuer Commit) apt-Rollout →
  Erfolgs-Mail. Zustand in `.state/auto_update_state.json` (self-init).
- `recovery/pv_update_all_hosts.sh`: apt full-upgrade über alle erreichbaren Pis
  (persistiert tmpfs-DB zuerst, **kein** Auto-Reboot). Das Primitive
  `scripts/pv_maintenance_upgrade.sh` bleibt bewusst in `scripts/` (liegt auf allen
  Peers, wird remote aufgerufen).

## Installation
`recovery/install_recovery.sh` (nur Primary, idempotent): installiert
`pv-auto-update`, `pv-recovery-selfcheck`, `pv-offsite-reminder` (alle
`Persistent=true`) und baut bei Bedarf das Erst-Paket.

## No-Gos / Invarianten
- Secrets/Pakete mit Secrets **nie** ins git (nur `backup/recovery/`, gitignored).
- Mail über `scripts/pv_notify.py` (Produktiv-SMTP), Jobs defensiv (Exit 0).

## Verwandte
- `recovery-overview.card.md`, `recovery-rebuild.card.md`,
  `doc/system/RECOVERY.md`, `doc/system/BACKUP_STRATEGY.md`,
  `doc/system/WARTUNGS_AUTOMATIK.md`.
