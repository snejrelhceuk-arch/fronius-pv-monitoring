# Host-Manifest-Schema (Rolle R)

Jede Datei `recovery/hosts/<id>.yaml` beschreibt **vollständig und
publish-sicher**, wie ein Host rekonstruiert wird. Konkrete IPs/Pfade/Secrets
stehen **nie** hier, sondern werden zur Laufzeit aus `.infra.local`
(gitignored) über die genannten `*_env`-Variablen aufgelöst.

## Felder

| Feld | Bedeutung |
|---|---|
| `id` | Kurzname (primary/failover/tech/kueche) |
| `role` | Wert der `.role`-Datei (primary\|failover\|tech\|kueche) |
| `user` | Login-User (klartext, nicht geheim) |
| `ip_env` | Name der `.infra.local`-Variable mit der Host-IP (keine Literal-IP im Repo) |
| `repo_subpath` | Repo-Pfad **relativ zum Home** des Users |
| `os` / `python` / `hardware` | Systemeigenschaften (Soll) |
| `engine` | true, wenn der Host Writer/Engine (A–E) betreibt |
| `wp_backend_mode` | remote\|local\|none (WP-Transport) |
| `services` | systemd-Units `enable --now` (rollen-passend) |
| `timers` | systemd-Timer `enable --now` |
| `cron` | Cron-Einträge (meist role-guarded, aktiviert sich ab `.role`) |
| `config_files` | host-spezifische, **nicht** versionierte Dateien aus dem Recovery-Bundle |
| `secret_keys` | erwartete `credential_store`-Schlüssel (nur Namen) |
| `tmpfs` | tmpfs/RAM-DB-Einrichtung |
| `kiosk` / `ufw` | Kiosk-Autostart / Firewall aktiv |
| `provisioning.venv` | `native` (mit Internet) oder `mirror` (von Peer) |
| `provisioning.data_restore` | `gfs` \| `mirror` \| `none` |
| `provisioning.rebuild_from` | bevorzugte Quelle (host-id) für `rebuild_host.sh` |
| `notes` | Besonderheiten |

## Invarianten

- **Genau ein** Host mit `role: primary` darf Writer betreiben (Split-Brain-Schutz).
- `config_files` + `secret_keys` definieren, was das **Recovery-Bundle** mitführen
  muss, damit der Host autark wieder aufgebaut werden kann.
- Manifeste sind die **Quelle der Wahrheit** für `rebuild_host.sh`,
  `verify_integration.sh` und `build_recovery_bundle.sh`.
