# Backup-Strategie — verteilte GFS-Kette, SD-schonend

> IST-Zustand der Datensicherung über die Vier-Host-Topologie.
> Grundprinzip: **RAM-first** (Produktiv-DBs in tmpfs, SD-Writes minimieren) und
> **verteilt-redundant** (je weiter außen in der Kette, desto langlebiger die Kopie).

---

## 1. Datenfluss (drei Hardware-Stufen)

```
Pi5-Primary (.204)            Pi5-FB (.195)                     Pi4-Küche (.105)
RAM-DB /dev/shm               Live-Mirror + GFS-Erzeugung       Langzeit-Archiv
  data.db                      data.db (tmpfs, alle 10 min)      pv-longterm-archive/
     │  persist (zyklisch)        │  backup_db_gfs.sh 03:00         ▲  append-only
     ▼                            ▼  daily/weekly/monthly/yearly    │  monthly/yearly
  data.db (SD, Fallback)       backup/db/* (NVMe)  ───────────────►─┘  (03:40, nur neue)
```

- **Primary** schreibt selbst **keine** `data.db`-GFS-Stufen (SD-schonend). Die GFS-Kette
  erzeugt der **FB** aus seinem tmpfs-Mirror.
- **monthly/yearly liegen redundant auf FB UND Küche** (getrennte Hardware) — der Offload
  **ergänzt** nur und **löscht nie** (`rsync --ignore-existing`, kein `--delete`).

---

## 2. Wer schreibt wann wohin

| Host | Quelle | Job (Trigger) | Zeit | Ziel | Stufe |
|---|---|---|---|---|---|
| Primary | `/dev/shm/fronius_data.db` | Persist-Zyklus | zyklisch | `data.db` (SD) | Hot-Fallback |
| Primary | `monitoring.db`/`analysis.db` | `backup_tiered_dbs_gfs.sh` (cron) | 03:00 | `backup/tiered/*` + Sync FB | Stufe 2+3 |
| Primary | NQ-DBs | `pv-nq-backup.timer` | 03:00 | NQ-GFS | NQ |
| FB | Primary `data.db` | `pv-mirror-sync.timer` | alle 10 min | `/dev/shm` (Mirror) | Live-Mirror |
| FB | tmpfs-Mirror | `backup_db_gfs.sh` (cron) | 03:00 | `backup/db/{daily,weekly,monthly,yearly}` (NVMe) | Sohn/Vater/Großvater |
| FB | FB-GFS monthly/yearly | `pv-longterm-offload.timer` | 03:40 | Küche `pv-longterm-archive/` | Langzeit |
| Küche | — (nur Empfänger) | — | — | `~/pv-longterm-archive/{monthly,yearly}` | Langzeit-Archiv |

GFS-Retention auf FB: `DAILY_KEEP=7`, `WEEKLY_KEEP=5`, `MONTHLY_KEEP=12`, yearly dauerhaft
(siehe [`scripts/backup_db_gfs.sh`](../../scripts/backup_db_gfs.sh)).

---

## 3. Langzeit-Archiv auf Pi4-Küche

- **Rolle:** reines Langzeit-Archiv auf getrennter Hardware/Standort. **Keine** Engine,
  **kein** Failover-Mirror, **kein** 10-Minuten-Pull.
- **Mechanismus:** [`scripts/backup_longterm_offload.sh`](../../scripts/backup_longterm_offload.sh)
  läuft auf dem **FB** (Timer `pv-longterm-offload`, täglich 03:40). Er spiegelt nur die
  **Großvater-Ebene** (`monthly`, `yearly`) per `rsync -az --ignore-existing`.
  - **Append-only:** einmal archivierte Stände bleiben, auch wenn der FB sie rotiert.
  - **Fail-safe:** ist die Küche offline oder `PV_KUECHE_HOST` ungesetzt, überspringt der
    Job sich ohne Fehler.
  - **Kadenz-Effekt:** täglicher Trigger, aber reale Schreibvorgänge nur bei **neuen**
    monthly/yearly-Dateien → effektiv monatlich/jährlich, SD-schonend.
- **Installation (nur auf FB):** [`scripts/install_longterm_offload.sh`](../../scripts/install_longterm_offload.sh).
- **Konfiguration** (FB `.infra.local`): `PV_KUECHE_HOST`, `PV_KUECHE_ARCHIVE_BASE=pv-longterm-archive`.
  Voraussetzung: SSH-Key-Auth vom FB-Nutzer zum Küche-Nutzer (Ziel aus `PV_KUECHE_HOST`).

### Speicher-Budget (Küche-SD ~29 GB, ~18 GB frei)

| Stufe | Größe/Datei | Zuwachs/Jahr | Tragfähigkeit |
|---|---|---|---|
| monthly | ~226 MB | ~2,7 GB | ✅ ~6 Jahre |
| yearly | ~226 MB | ~0,2 GB | ✅ |
| weekly | ~226 MB | ~11,8 GB | ❌ füllt die Karte in ~1,2 Jahren |

→ Aktiv gespiegelt werden **monthly + yearly**. `weekly` ist auf der 29-GB-Karte
**nicht** langzeittragfähig (Opt-in nur mit größerer Karte, s. `doc/TODO.md`).

---

## 4. Wiederherstellung

```
gunzip -k data_YYYY-MM.db.gz        # → data.db
sqlite3 data.db "PRAGMA integrity_check;"
```

Quelle je nach Alter: aktuelle Stände vom FB (`backup/db/*`), Langzeit aus dem
Küche-Archiv (`pv-longterm-archive/*`).

---

## 5. Verwandtes

- [`scripts/backup_db_gfs.sh`](../../scripts/backup_db_gfs.sh) — GFS-Erzeugung (FB)
- [`scripts/backup_tiered_dbs_gfs.sh`](../../scripts/backup_tiered_dbs_gfs.sh) — Stufe 2+3 (Primary)
- [`scripts/backup_longterm_offload.sh`](../../scripts/backup_longterm_offload.sh) — Offload FB→Küche
- [`DUAL_HOST_ARCHITECTURE.md`](./DUAL_HOST_ARCHITECTURE.md) §7
- Cards: [`system-ops-guards`](../llm/cards/system-ops-guards.card.md), [`system-hosts`](../llm/cards/system-hosts.card.md)
- Offene Punkte: [`doc/TODO.md`](../TODO.md)
