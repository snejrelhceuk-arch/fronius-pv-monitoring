# Publish-Guard — Technische Absicherung gegen Daten-Leaks

**Stand:** 2026-03-18
**Status:** Aktiv (seit Security-Audit 2026-03-18)

---

## 1. Zweck

Das Repository wird öffentlich gehostet. Lokal enthält der Workspace
umfangreiche Infrastruktur-Dokumentation, die **nicht** veröffentlicht werden
soll — interne IPs, Hostnamen, Benutzernamen, Geräte-Seriennummern, E-Mail-Adressen
und SMTP-Konfiguration.

Dieses Dokument beschreibt die **drei technischen Schutzschichten**, die
verhindern, dass sensible Daten ins öffentliche Repo gelangen.

---

## 2. Schicht 1: `.infra.local` (Laufzeit-Override)

**Datei:** `.infra.local` (Repo-Root, gitignored)
**Template:** `.infra.local.example` (getrackt, neutrale Platzhalter)

Alle sensiblen Konfigurationswerte (IPs, Benutzernamen, Pfade, E-Mail) werden
**nicht** im Code hardcoded, sondern über `config.load_local_setting()` aus
`.infra.local` geladen. Der Code enthält nur neutrale Fallback-Defaults
(RFC 5737 Dokumentations-IPs `192.0.2.x`, `example.invalid` etc.).

### Python (config.py):
```python
INVERTER_IP = load_local_setting('PV_INVERTER_IP', '192.0.2.122')
```

### Shell (scripts/load_infra_env.sh):
```bash
source "$(dirname "$0")/load_infra_env.sh"
ssh "${PV_FAILOVER_HOST:-failover-user@failover-host}" ...
```

### Schlüssel-Übersicht:

| Schlüssel | Zweck | Default (öffentlich) |
|---|---|---|
| `PV_INVERTER_IP` | Fronius GEN24 Modbus | `192.0.2.122` |
| `PV_FAILOVER_IP` / `_USER` / `_HOST` | Failover-Pi4 | `192.0.2.105` / `failover-user` |
| `PV_PRIMARY_HOST` / `_IP` / `_REPO` | Primary-Pi4 | `primary-user@primary-host` |
| `PV_WATTPILOT_IP` | WattPilot Go | `192.0.2.197` |
| `PV_PI5_BACKUP_HOST` / `_DB_PATH` / `_BASE` | NVMe-Backup | `backup-user@backup-host` |
| `PV_OLLAMA_SSH_HOST` | LLM-Server | `ollama-host` |
| `PV_NOTIFICATION_EMAIL` / `_SMTP_HOST` / `_SMTP_USER` / `_FROM` | E-Mail-Alerts | `alerts@example.invalid` |
| `PV_SECONDARY_INVERTER_API` | Fronius F2 API | `http://192.0.2.123/...` |

---

## 3. Schicht 2: `.publish-guard` + Pre-Commit-Hook

**Datei:** `.publish-guard` (Repo-Root, getrackt)
**Hook:** `.git/hooks/pre-commit` (Phase 2 im bestehenden Role-Guard-Hook)

### Funktionsweise:

1. Beim `git commit` liest der Hook alle Zeilen aus `.publish-guard`
2. Jede Zeile ist ein `grep -E` Pattern (Regex)
3. Der Index-Inhalt aller staged Dateien wird gegen die Muster geprüft
4. **Bei Treffer: Commit wird blockiert** mit Datei+Zeilennummer

### Aktuelle Sperrmuster:

- Interne IP-Adressen (lokales Subnetz)
- Benutzernamen und Hostnamen der Infrastruktur-Hosts
- Domain- und E-Mail-Fragmente
- SMTP-Provider-Hostname
- Dateisystem-Pfade mit lokalen Home-Verzeichnissen
- Fritz!DECT Geräte-AIN (Seriennummern)

> Die konkreten Muster stehen in `.publish-guard` (tracked).
> Sie verwenden `grep -E` Regex-Syntax.

### Bypass (Notfall):
```bash
git commit --no-verify -m "reason for bypass"
```

---

## 4. Schicht 3: `publish_audit.sh` (Pre-Push-Audit)

**Datei:** `scripts/publish_audit.sh`

Vollständiger Scan, unabhängig vom Hook. Drei Prüfphasen:

| Phase | Prüft | Aufruf |
|---|---|---|
| 1 | Alle getrackten Dateien im Working-Tree | Standard |
| 2 | `.gitignore`-Abdeckung kritischer Dateien | Standard |
| 3 | Gesamte Git-History (alle Commits) | `--history` Flag |

```bash
./scripts/publish_audit.sh            # Phase 1+2 (schnell)
./scripts/publish_audit.sh --history  # Phase 1+2+3 (History-Scan)
```

**Empfehlung:** Vor jedem `git push` ausführen.

---

## 5. Notfall: History nachträglich bereinigen

Falls sensible Daten in die History gelangt sind:

```bash
# 1. Filter-Expressions (lokal, gitignored) enthält die Mapping-Regeln:
cat scripts/filter-expressions.txt

# 2. git-filter-repo ausführen:
git filter-repo \
  --replace-text scripts/filter-expressions.txt \
  --force

# 3. Force-Push:
git push --force --all origin
git push --force --tags origin
```

**Achtung:** Force-Push erfordert temporäres Aufheben des Branch-Schutzes auf GitHub.

---

## 6. `.gitignore`-geschützte Dateien

Folgende Dateien existieren lokal, werden aber **nie** getrackt:

| Datei | Grund |
|---|---|
| `.infra.local` | Echte IPs, Benutzernamen, Pfade |
| `scripts/filter-expressions.txt` | Enthält reale IP-Mappings |
| `pv-automation.service` / `pv-observer.service` / `pv-wattpilot.service` | Host-spezifische Pfade |
| `config/fritz_config.json` | Fritz!Box-Credentials und AINs |
| `doc/SYSTEM_BRIEFING.md` | Vollständiges System-Briefing (internes Wissen) |
| `doc/system/SYSTEM_ARCHITECTURE.md` | Netzwerk-Topologie mit echten IPs |
| `doc/system/DUAL_HOST_ARCHITECTURE.md` | Host-Details |
| `doc/automation/HARDWARE_SETUP.md` | Hardware-Verdrahtung |
| `scripts/windows/` | SSH-Helper mit Benutzerdaten |
| `tools/PV_Anlagendokumentation.pdf` | Anlagen-Dokumentation |
| `logs/schaltlog.txt` | Persistentes Schaltprotokoll |

---

## 7. Zusammenspiel mit VEROEFFENTLICHUNGSRICHTLINIE

| Aspekt | Dokument |
|---|---|
| **Rechtliche Regeln** (Urheberrecht, Hersteller-Texte, Takedown) | `doc/meta/VEROEFFENTLICHUNGSRICHTLINIE.md` |
| **Technische Absicherung** (Hooks, Audit, Filter, gitignore) | dieses Dokument |

Beide Dokumente ergänzen sich: Die Richtlinie definiert **was** nicht veröffentlicht werden darf,
der Publish-Guard stellt **technisch** sicher, dass es nicht passiert.
