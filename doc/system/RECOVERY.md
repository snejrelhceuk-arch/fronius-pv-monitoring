# Rolle R — Recovery / Reconstruction & Provisioning

> **IST-Zustand** der Wiederherstellungs-Schicht. R ist die Meta-Rolle, die das
> pv-system **installiert, rekonstruiert und aktuell hält** — host-übergreifend.
> Produktionssicherheit hat Vorrang: alle Provisionierungs-Werkzeuge sind
> dry-run-default, zielexplizit und schalten **nie** automatisch Writer scharf.

## 1. Einordnung (ABCDEN → ABCDENR)

A–E/N sind Fachrollen des **laufenden** Systems. **R** ist orthogonal: keine
Dauer-Engine, keine `.role`, sondern ein **Repo-Modul `recovery/`**, das auf
**allen** Hosts vorliegt und ruht, bis es gebraucht wird. R besitzt eine
**Sonder-Schreibautorität**: Software-/OS-Installation auf einem **Ziel**-Host
(klar getrennt von C = Hardware-Aktorik der Produktion).

R ist außerdem **Eigentümer des Backup-Themas** (Disaster-Recovery-Sicht): die
laufende GFS-Datenkette läuft funktional unverändert weiter (s.
[BACKUP_STRATEGY.md](./BACKUP_STRATEGY.md)), aber **Gesamtpaket, Restore-Prozeduren
und die Off-site-Datensicherung** gehören zu R.

## 2. Szenario-Matrix

| # | Szenario | R-Antwort | Datenrisiko |
|---|---|---|---|
| S1 | Non-Primary-Pi (FB/Tech/Küche) defekt/Ersatz | Von **Primary**: `recovery/rebuild_host.sh <host> --apply` (Key-Push → Code-rsync → venv → `.role`/Config → Installer → verify) | gering |
| S2 | Primary defekt, FB intakt | **Sofort** FB-Promotion ([FAILOVER_STATUS.md](./FAILOVER_STATUS.md)); dann Ersatz-Primary von FB aus `rebuild_host primary`; DB aus GFS; späterer Rücktausch | gering |
| S3 | Primary **und** FB aus | Von **Tech oder Küche** Primary rekonstruieren (jeder Host trägt Repo + Recovery-Paket; Küche hält Longterm-GFS) | mittel |
| S4 | Baseline-Neuinstall (älterer sicherer Stand) | Fresh-OS+SSH → Recovery-Paket → „Nachholen" per `rebuild_host`/Sync auf aktuellen HEAD + venv | — |
| S5 | **Totalverlust aller Pis** (Brand/Raub) | **Externes Medium (USB, off-site)** + Off-site-Datenmedium → Baseline-OS+SSH → Paket rollt alle 4 Hosts aus | hoch (bis letzter off-site Stand) |

**Vorbedingung (ausreichend):** Auf dem Ziel läuft ein SSH-fähiges Basis-System,
Passwort bekannt. Schlüssel werden per `--push-key` (einmalig, Passwort) gebracht.

## 3. Artefakte

| Artefakt | Zweck |
|---|---|
| `recovery/hosts/<id>.yaml` | **Host-Manifeste**: alle System-Eigenschaften je Pi (publish-sicher, IP via `*_env`) |
| `recovery/manifests/system_files.yaml` | **Integrations-Register** der Fremddateien (systemd/etc/cron/fstab/Identität) |
| `recovery/rebuild_host.sh` | Host-Rekonstruktion (dry-run-default, Selbstschutz, kein Auto-Writer) |
| `recovery/build_recovery_bundle.sh` | **Gesamtpaket** (git-Bundle + requirements + Doku + Checksummen), Major-gekoppelt |
| `recovery/export_usb.sh` | Paket auf USB + Versions-Marker; Mahnung bei Major-Sprung |
| `recovery/secrets_bundle.sh` | **portables** Secrets-Bundle (gpg/AES256, Passphrase) — löst das machine-id-Problem |
| `recovery/verify_integration.sh` | **Drift-Verifier** Manifest ↔ OS (Units/etc/cron/ufw) |
| `recovery/recovery_selfcheck.py` | Aktualitäts-Selbstcheck (Major), Warn-Mail, Auto-Rebuild |
| `recovery/offsite_data_reminder.py` | monatliche Off-site-Mahnung (Mail) |
| `recovery/pv_auto_update_guard.py` + `pv_update_all_hosts.sh` | **Update/Upgrade-Strategie** (72h-Gate, Multi-Host-apt-Rollout) |

## 4. Versions-Kopplung (Aktualität)

Aktualität koppelt an die **Major-Version** (Ganzzahl aus git-Tag `vN`, aktuell
`v7`). Paket/USB gelten als veraltet, sobald die Major-Version springt
(`v7`→`v8`). Der wöchentliche Selfcheck (`pv-recovery-selfcheck.timer`) baut ein
fehlendes/veraltetes Paket neu (`--build`) und mahnt veralteten **USB** per Mail.

## 5. Secrets-Portabilität (kritisch)

`credential_store` ist an `/etc/machine-id` gebunden → auf Ersatz-HW **nicht**
entschlüsselbar. Deshalb: `secrets_bundle.sh create` bündelt `.infra.local` +
`.secrets` **passphrase-verschlüsselt** (gpg) nach `backup/recovery/` (gitignored).
Beim Restore (`rebuild_host … --with-secrets`) werden sie auf das Ziel gelegt; der
**SMTP-Pass wird auf dem Ziel neu** gesetzt (`scripts/set_smtp_password.py`), weil
der machine-id-gebundene Store host-lokal bleibt.

## 6. Tagging & Integrationsmanagement

Repo-Dateien sind durch git eindeutig. Fremddateien (außerhalb des Repos) führt
das **Register** `recovery/manifests/system_files.yaml` (Kategorie, Pfad-Muster,
Marker-Fähigkeit). Editierbare Fremddateien tragen den Kopf-Marker
`PV-SYSTEM-MANAGED`; nicht-markerfähige nur über Register. `verify_integration.sh`
meldet **fehlende** (deklariert, nicht installiert) und **verwaiste** (installiert,
nicht deklariert) `pv-*`-Units je Host-Rolle.

## 7. Off-site Datensicherung

`pv-offsite-reminder.timer` (monatlich) mahnt, einen Datensnapshot (Longterm-GFS
monthly/yearly + aktuelle DB + Recovery-Paket) auf ein **externes Medium** zu
kopieren und **räumlich getrennt** (anderes Gebäude auf dem Grundstück, keine
Cloud) zu lagern — Schutz vor Brand/Raub.

## 8. Installation

```bash
bash recovery/install_recovery.sh     # pv-auto-update + selfcheck + offsite (nur Primary)
```

Rebuild eines Hosts (Beispiel FB):

```bash
recovery/rebuild_host.sh failover                 # Dry-Run-Plan
recovery/rebuild_host.sh failover --push-key --apply   # einmalig Key
recovery/rebuild_host.sh failover --apply --with-secrets
```

## 9. Verwandtes

- [DUAL_HOST_ARCHITECTURE.md](./DUAL_HOST_ARCHITECTURE.md) — Topologie, `.role`
- [REFORMATION_RUNBOOK.md](./REFORMATION_RUNBOOK.md) — Vorlage des Rebuild-Ablaufs
- [FAILOVER_STATUS.md](./FAILOVER_STATUS.md) — Promotion FB→Primary
- [BACKUP_STRATEGY.md](./BACKUP_STRATEGY.md) — laufende GFS-Datenkette
- [WARTUNGS_AUTOMATIK.md](./WARTUNGS_AUTOMATIK.md) — Drift-/Abgleich-Timer
- Cards: `doc/llm/cards/recovery-*.card.md`
