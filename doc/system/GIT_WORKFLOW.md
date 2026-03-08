# Git Workflow

> Stand: 2026-03-01

## Branch-Struktur

Einziger Branch: **`main`**. Kein Feature-Branching — direktes Commit auf `main`.

```
main (HEAD)
  └── origin/main  →  GitHub: snejrelhceuk-arch/fronius-pv-monitoring
```

## Arbeitsweise

```bash
# Status prüfen
git status

# Änderungen committen
git add <files>
git commit -m "Beschreibung"

# Push zu GitHub
git push origin main
```

## Post-Commit Hook: Ollama-Sync

Bei jedem Commit wird automatisch das lokale Ollama-Wissensmodell aktualisiert:
`ollama/post-commit-ollama.sh` → synchronisiert Repo-Kontext in das LLM.

## Code-Sync auf Hosts

Drei Hosts teilen denselben Code-Stand (siehe `doc/DUAL_HOST_ARCHITECTURE.md`):

| Host | Pfad | Sync |
|------|------|------|
| Primary (Pi4, 192.168.2.181) | `/home/admin/Dokumente/PVAnlage/pv-system` | `git pull` |
| Failover (Pi4, 192.168.2.105) | `/home/jk/Dokumente/PVAnlage/pv-system` | `scripts/sync_code.sh` |
| Backup (Pi5, 192.168.2.195) | analog | `scripts/sync_code.sh` |

## .gitignore

Nicht versioniert: `*.db`, `*.log`, `__pycache__/`, `*.pid`, `.venv/`, `.secrets`

## Deployment

Services nach Code-Änderung neu starten:

```bash
sudo systemctl restart pv-observer
sudo systemctl restart pv-automation
sudo systemctl restart pv-wattpilot
./restart_webserver.sh
```
