---
title: Diagnos Health (Host, Services, Freshness)
domain: diagnos
role: D
applyTo: "diagnos/health.py"
tags: [health, services, freshness, mirror, backup]
status: stable
last_review: 2026-05-03
---

# Diagnos Health

## Zweck
Read-only Zustandspruefung fuer Host, Services und Datenfrische. Liefert eine schnelle Erstbewertung (ok/warn/crit/fail), bevor tiefe Integritaetschecks laufen.

## Code-Anchor
- **Hauptlauf:** `diagnos/health.py:run_all`
- **Host-Checks:** `diagnos/health.py:check_cpu_temp`, `check_throttle`, `check_ram`, `check_disk`, `check_load`, `check_uptime`
- **Service-Checks:** `diagnos/health.py:check_all_services`
- **Freshness:** `diagnos/health.py:check_freshness`
- **Mirror/Backup:** `diagnos/health.py:check_mirror_sync_age`, `check_local_gfs_backup_age`
- **Schwellwerte/Tabellen:** `diagnos/config.py` (`SERVICES`, `FRESHNESS_TABLES`, Warn-/Crit-Grenzen)

## Inputs / Outputs
- **Inputs:** `/proc/*`, `/sys/class/thermal/*`, `vcgencmd`, `systemctl`, read-only SQLite auf `/dev/shm/fronius_data.db`, `.role`, Mirror-/Backup-Marker.
- **Outputs:** JSON auf stdout (`overall` + `checks[]`), Warnungen auf stderr, Exit-Code 0/1/2.

## Invarianten
- Diagnos bleibt strikt read-only: DB-Zugriff nur via `mode=ro`, keine Aktorik.
- Gesamtseverity ist immer die schlechteste Einzelseverity aus allen Checks.
- Freshness-Schwellen werden zentral ueber `diagnos/config.py` gesteuert.
- `mirror_sync_age` gilt nur fuer Rolle `failover`; auf `primary` wird bewusst `skipped` geliefert.

## No-Gos
- Keine Service-Restarts, kein Auto-Healing, kein Kill von Prozessen in `diagnos/health.py`.
- Keine Schreibzugriffe auf Produktionsdatenbanken.
- Kein Hardware-Schreibzugriff (Fronius/FritzDECT/Wattpilot).

## Häufige Aufgaben
- Neue Unit ueberwachen -> `diagnos/config.py:SERVICES` erweitern.
- Freshness fuer neue Tabelle -> `diagnos/config.py:FRESHNESS_TABLES` erweitern.
- Schwellwerte nachziehen -> `CPU_TEMP_*`, `DISK_*`, `MIRROR_*`, `BACKUP_*` in `diagnos/config.py` anpassen.

## Bekannte Fallstricke
- Service-Namen in `diagnos/config.py` koennen von lokalen systemd-Unit-Namen abweichen und false-crit erzeugen.
- Auf Hosts ohne `vcgencmd` faellt `check_throttle` auf `fail`.
- Bei fehlender RAM-DB (`/dev/shm/fronius_data.db`) werden Freshness-Checks als `fail` gemeldet, auch wenn Persist-DB intakt ist.

## Verwandte Cards
- [`diagnos-integrity.card.md`](./diagnos-integrity.card.md)
- [`system-ops-guards.card.md`](./system-ops-guards.card.md)
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)

## Human-Doku
- `doc/diagnos/DIAGNOS_KONZEPT.md`
- `doc/diagnos/CHECKKATALOG.md`
- `doc/diagnos/TAKTUNG_UND_ESKALATION.md`
