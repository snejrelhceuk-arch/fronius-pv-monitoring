# Wartungs- & Drift-Automatik

Betreiber-freie Routine-Automatik auf **Primary** (Quelle der Wahrheit). Alle
Timer sind `Persistent=true` (Catch-up nach Downtime), alle Jobs sind
Oneshot/defensiv (Exit 0, nie `failed`) und selbst-initialisierend.

Installation (idempotent, nur Primary):

```bash
scripts/install_maintenance_timers.sh
```

## Timer-Übersicht

| Unit | Intervall | Skript | Zweck | Mail |
|---|---|---|---|---|
| `pv-auto-update` | täglich 08:00 | `scripts/pv_auto_update_guard.py` | Bewachtes apt-Voll-Upgrade über alle Pis | Warn- + Erfolgs-Mail |
| `pv-repo-drift` | ~10 Tage (1./11./21.) | `scripts/pv_repo_drift_remediate.sh` | Repo-Drift Primary↔Pis beseitigen | Report-Mail |
| `pv-doc-drift-report` | ~20 Tage (1./21.) | `scripts/pv_doc_drift_report.py` | Doku-Drift erkennen/aufräumen | Report-Mail |
| `pv-solarweb-compare` | monatlich (5.) | `scripts/solarweb_compare.py` | Solarweb vs. `daily_data` abgleichen | Auffälligkeits-Mail |

Mail-Versand einheitlich über `scripts/pv_notify.py` (Produktiv-SMTP-Pfad
`config.NOTIFICATION_*` + `credential_store`).

## Auto-Update-Guard (72h-Inaktivitäts-Gate)

Zustandsmaschine in `.state/auto_update_state.json` (fehlt/korrupt →
Neu-Initialisierung):

1. **idle → armed:** Stehen apt-Updates an, geht eine **Warn-Mail** raus
   („Rollout in 72 h ohne Aktivität"), Zustand `armed`, `warn_epoch`/`warn_head`
   gesetzt.
2. **Aktivität = neuer git-Commit auf Primary HEAD.** Der Auslöser liegt bei
   `max(warn_epoch, letzter-Commit) + 72 h`; jeder Commit verschiebt ihn.
3. **armed → Rollout:** Nach 72 h Inaktivität läuft `pv_update_all_hosts.sh`
   (apt full-upgrade auf allen erreichbaren Pis, tmpfs-DB wird zuerst
   persistiert, **kein** Auto-Reboot) und es folgt eine **Erfolgs-Mail** mit
   Pro-Host-Status.
4. Verschwinden die Updates vorher (manuell aktualisiert) → Warnung wird
   zurückgesetzt.

Manuell/Ops:

```bash
scripts/pv_auto_update_guard.py --status        # Zustand anzeigen
scripts/pv_auto_update_guard.py --reset         # auf idle
sudo bash scripts/pv_update_all_hosts.sh        # sofort alle Pis upgraden
sudo bash scripts/pv_update_all_hosts.sh --dry-run
```

## Repo-Drift-Remediation

* Lokale tracked-Drift auf Primary → **Auto-Commit lokal** (Betreiber-Policy),
  **kein Push** (origin bleibt unberührt).
* Peers (FB/Tech/Küche) per `sync_code_to_peer.sh` / `sync_code_to_tech.sh` auf
  Primary-Stand (rsync, Deploy-Policy) + Dienst-Restart.
* Commit-Parität aller `PV_SYNC_HOSTS` wird geprüft und gemeldet.

## Doku-Drift-Report

Fährt `tools/doc_drift_engine.py --write --cleanup` (LLM-frei: schreibt/räumt
Drift-Tasks in `doc/llm/_drift/tasks/`) und mailt eine Zusammenfassung nach
Drift-Klasse. Inhaltliche Card-Korrektur bleibt ein Doc-Maintainer-/LLM-Schritt.

## Solarweb-Abgleich

Erzeugt `doc/csv/abgleich_YYYY-MM_daily_vs_pvsystem.csv` aus
`doc/csv/solarweb_daily_YYYY-MM_working.csv` vs. `daily_data` (PV / Netzbezug /
Einspeisung / Batterie-Laden / Verbrauch) und mailt die größten Abweichungen.
Kein Live-Abruf per Default; `--fetch` versucht `fetch_solarweb_daily.py` nur bei
vorhandenen Credentials (nach deren Entfernen läuft der Abgleich weiter auf den
vorhandenen CSVs).
