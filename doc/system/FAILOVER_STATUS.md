# Failover — Status (IST 2026-07-11, nach REFORMATION)

> Beschreibt den **IST-Zustand** des Failover-Hosts. Nach der REFORMATION ist der
> Failover **Pi5-FB** (`192.0.2.195`, admin, `.role=failover`) — **nicht** mehr der
> alte Pi4-Failover (der ist jetzt **Pi4-Küche**: Kiosk + Longterm-GFS).

## Einsatzbereitschaft — Kurzstatus

| Aspekt | Status | Details |
|---|---|---|
| Host | ✅ | Pi5-FB · `192.0.2.195` · admin · Pi 5 Rev 1.0 · 8 GB RAM · NVMe 512 GB · Debian 12 · Py 3.11 |
| Rolle | ✅ | `.role=failover` (read-only) — keine Writer (Collector/Automation/Aggregation) |
| **venv** | ✅ nativ | Pi5 mit Internet → native venv (kein Offline-Klon mehr nötig). Primary+Failover beide Py 3.11/aarch64 = Mirror-kompatibel |
| Code | ✅ | Wöchentlicher Auto-Sync Primary→FB (`pv-failover-codesync.timer`, Mo 04:30) via `scripts/sync_code_to_peer.sh` — hält Code **und** `config/*.json` (inkl. Batterie-Kapazität) aktuell. Host-spezifische Dateien (`.role`, `.infra.local`, `.secrets`, `*.db`) sind ausgeschlossen. |
| Aggregation-Bereitschaft | ✅ | min1/fifteen/daily/monthly/statistics sind in der FB-Crontab **vorgestaged**; sie `exit(0)` bei `role=failover` (no-op) und aktivieren sich automatisch mit `.role=primary`. |
| DB-Mirror | ✅ funktional | `pv-mirror-sync` (Timer 10 min) zieht die Primary-`data.db` von `192.0.2.204` per rsync nach `/dev/shm/fronius_data.db` (tmpfs, atomarer `mv`). Sync-Marker `.state/last_mirror_sync.ok` frisch. SD/NVMe-`data.db` bleibt bewusst älter (Reboot-Fallback). |
| Ticker | ✅ | `pv-ticker.service` aktiv (inkl. 2. Zeile) |
| Backup | ✅ | Zentraler GFS-Empfänger (daily/weekly/monthly/yearly) auf NVMe. Großvater-Longterm-Offload (monthly/yearly) → Pi4-Küche via `scripts/install_longterm_offload.sh` |
| Web | ✅ | `pv-web.service` read-only auf `:8000` |
| Health/Badge | ✅ | Primary (`.204`) prüft `/api/failover_status` jetzt gegen `admin@192.0.2.195`; Flow-Badge **„Safe: Sync"** (grün) |

## Promotion zum Primary (Ernstfall-Runbook)

Vollständige Schritte, um den passiven FB zum Primary zu machen (read-only → Writer):

```
# Stufe 1 — lokale Datenerfassung übernehmen
scripts/failover_activate.sh        # startet pv-collector + pv-wattpilot, stoppt pv-mirror-sync

# Stufe 2 — Rolle wechseln + Writer/Automation scharfschalten
echo primary > .role                # schaltet Rollen-Guards um (Aggregation wird aktiv)
scripts/install_services.sh         # enable/start Writer-Services (collector/web/steuerbox/wattpilot)
sudo systemctl enable --now pv-automation.service   # NICHT rollengeguarded → explizit starten!

# Verifikation
systemctl is-active pv-collector pv-automation pv-web
curl -s localhost:8000/api/system_info | head
crontab -l | grep aggregate        # Aggregations-Cron ist vorgestaged, jetzt aktiv
```

Die Aggregations-Cronjobs sind bereits (role-guarded) installiert und laufen ab
`.role=primary` automatisch — kein manueller Crontab-Schritt nötig.

**Rückweg:** `echo failover > .role` + `scripts/failover_passive.sh` +
`sudo systemctl disable --now pv-automation.service`.

> ⚠️ `pv-automation` self-guarded **nicht** auf die Rolle — auf dem passiven FB darf es
> **nie** laufen (würde Hardware schreiben). Darum nur im Promotion-Schritt starten.

## Offene Punkte (siehe `doc/TODO.md`)

1. **SMTP-Passwort auf Pi5-FB setzen** (Betreiber, einmalig pro Host):
   `sudo .venv/bin/python scripts/set_smtp_password.py`. Verzeichnis (`/etc/pv-system`),
   Config (`.infra.local` PV_NOTIFICATION_*) und Credential-Store (machine-id-gebundene
   Fernet-Verschlüsselung) sind vorbereitet und per Round-Trip getestet;
   `failover_health_check.sh` lädt das Passwort jetzt korrekt via `credential_store`
   (vorher Klartext-Lese-Bug → Alarm wäre gescheitert).
2. **`data_stats.db`** in den Mirror-/Backup-Fluss aufnehmen (aktuell nur täglicher
   Direkt-Sync via `scripts/stats_archive_daily.sh`).
3. **Promotion-Automatisierung (optional):** Ein `failover_promote.sh` könnte Stufe 1+2
   (inkl. `pv-automation`-Start) bündeln; derzeit manuelle Checkliste (s. o.). Bewusst
   ungetestet, da ein echter Promotion-Test Datenverlust riskiert.
