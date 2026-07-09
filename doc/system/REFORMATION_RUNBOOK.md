# REFORMATION — Migrations-Runbook & Rollback

> Operativer Ablauf für den Rollen-Cutover. Stand-Basis: 2026-07-09.
> Leitplanke: **Betriebssicherheit vor Tempo** — Shadow/Canary vor Cutover, genau
> ein Primary mit Writer-Diensten, Failover strikt read-only.

## Zielrollen

| Host | IP | User | Rolle NEU | Dienste |
|---|---|---|---|---|
| Pi5-NQ | .204 | admin | **Pi5-Primary** | A–E aktiv, WP via Bridge (remote) |
| Pi5-Backup | .195 | admin | **Pi5-F&B** | Failover (read-only) + Backup + Ticker |
| Pi4-Failover | .105 | jk | **Pi4-Kueche** | Kiosk + Longterm-Backup (GFS m/y) |
| Pi4-Primary | .181 | admin | **Pi4-Tech** | WP/HW-Bridge (local), keine Engine |

## Fortschritt (erledigt)

- **Gate 0 — Backups:** Workspace-Tarball + Git-Bundle sha256-verifiziert auf
  `.195:~/reformation_backup/2026-07-09/`.
- **Gate 1 — NQ:** NQ-Workspace (`.204:~/Documents/NQ`) als Tarball+Bundle gesichert,
  sha256 + Restore-Test OK unter `.../nq/`.
- **Fase 2/3 — Code:** WP-Transport local/remote ([wp_modbus.py](../../wp_modbus.py)),
  Bridge ([wp_bridge/wp_bridge_api.py](../../wp_bridge/wp_bridge_api.py)),
  Unit ([config/systemd/pv-wp-bridge.service](../../config/systemd/pv-wp-bridge.service)),
  Tests [tests/test_wp_transport.py](../../tests/test_wp_transport.py) (15 grün),
  Bridge-Live-Smoke (health/401/400) OK.
- **Python-Konsistenz:** durch Rollentausch gelöst — Primary+Failover sind beide
  Pi5 (Python 3.11.2, aarch64), venv-/Mirror-kompatibel. Kein System-Python-Umbau.

## Verifizierte Voraussetzungen (Pi5-NQ .204)

- Debian 12 / aarch64 / Python 3.11.2, Internet (pypi 200) → native venv baubar.
- Reachability OK: Fronius .122:502, Wattpilot .176:80, FritzBox .1:80, alle Pi-SSH.
- Keine serielle WP-HW (korrekt — WP über Bridge auf Pi4-Tech).

## Fase 2 — Bridge live (Gate 2)

Auf Pi4-Tech (.181) erst **nach** Cutover aktivieren (Serial-Contention mit laufender
`pv-automation` vermeiden). Ablauf: siehe
[PI4_TECH_BRIDGE_HANDBUCH.md](./PI4_TECH_BRIDGE_HANDBUCH.md). Verifikation: status-Read +
erlaubter Write+Readback + verbotenes Register → 400.

## Fase 4 — Pi5-NQ Shadow → Primary

1. **Repo-Deploy (.204):** Working-Tree von .181 per rsync (ohne `.venv`, `data.db*`,
   `backup/`, `tmp/`) nach `~/Dokumente/PVAnlage/pv-system`. Git-History via Bundle.
2. **venv nativ bauen:** `python3.11 -m venv .venv`; Pakete auf **aktuellem** .181-Stand
   installieren (`pip list` von .181 als Referenz — **nicht** die veralteten Pins in
   `requirements.txt`).
3. **Config Shadow:** `.role=failover` (read-only!), `.infra.local` mit
   `PV_WP_BACKEND_MODE=remote`, `PV_WP_REMOTE_BASE_URL=http://192.0.2.181:8091`;
   `.secrets` von .181 übernehmen (read-Credentials). **Keine** Writer-Units enablen.
4. **Mirror:** `pv-mirror-sync` (data.db → `/dev/shm`) einrichten; Freshness prüfen.
5. **Shadow-Lauf (Gate 4, 24h):** Web:8000 read-only, Import-Checks, Latenz/Reserve.
6. **Cutover (kurze Wartung):**
   a. **RAM-DB-Transfer:** auf .181 `pv-collector` kurz stoppen → RAM-DB
      (`/dev/shm/fronius_data.db`) atomar nach .204 **und** .195 übernehmen
      (rsync, sha256) → Raw-Datenverlust minimal.
   b. `.role=primary` auf .204; Writer-Units (collector, automation, web, wattpilot,
      steuerbox, ha-bridge) + Timer + Cron aktivieren.
   c. Auf .181: Writer-Units **stop+disable**, `.role` entfällt, Bridge (Fase 2) starten.
   d. Smoke: Web:8000, Collector frisch, Automation tickt, WP read/write via Bridge.

## Fase 5 — Pi5-F&B (.195)

`.role=failover`, Mirror von neuem Primary (.204), read-only Web, Backup-Empfang +
Ticker (inkl. 2. Zeile) beibehalten. Gate 5: Mirror-Lag im Soll, kein Writer.

## Fase 6 — Pi4-Kueche (.105)

Kiosk + Longterm-Backup; optional GFS monthly/yearly hierher auslagern
(daily/weekly bleiben Primary/F&B). Gate 6: Retention erfüllt.

## Fase 7 — Cutover-Nachlauf (Gate 7, 48h Hypercare)

Freshness, Failover-Gesundheit, WP-Kommandos, Ticker, Backup-Reports.

## Rollback (verpflichtend, pro Fase)

| Trigger | Sofortmaßnahme |
|---|---|
| DB-Freshness-Lücke / Collector-Crashloop nach Cutover | Auf .204 Writer stop+disable; auf **.181** `.role=primary` wiederherstellen, Writer-Units re-enable+start (alter Zustand). Bridge auf .181 stoppen. |
| WP write failure über Bridge | Automation-WP-Aktor liefert bounded-Retry-Fehler (fail-safe, kein Split-Brain). Bridge-Logs prüfen; ggf. `PV_WP_BACKEND_MODE=local` zurück auf altem Primary. |
| Split-Brain-Verdacht (2 Writer) | Sofort einen Writer-Satz stoppen; nur EIN Host mit `.role=primary` + aktiven Writern. |
| Shadow instabil (Gate 4) | Cutover nicht starten; .204 bleibt Shadow, Produktion unverändert auf .181. |

Voller Rollback in Minuten: alter Primary .181 ist bis zum finalen Disable
unverändert lauffähig; Backups (Gate 0) + Git-Bundle auf .195 als letzte Reserve.
