# Diagnos (Schicht D) — Übersicht

**Schicht D** ist die read-only Selbstdiagnose des PV-Systems: sie beweist den
Zustand von Host, Daten und Netzqualität und eskaliert begründet per E-Mail.
Sie greift nur lesend zu — keine Aktorik, kein Neustart, keine
Datenrekonstruktion.

## Grenzen (Invarianten)

- **Nur lesen, vergleichen, klassifizieren, melden.** Kein Schreibpfad in
  Produktions-DBs, keine Hardware-Steuerung.
- **Keine kalenderbasierten Neustarts** von Collector/Host. Reaktion ist immer
  lesen → klassifizieren → melden.
- **Keine Interpolation/Rekonstruktion** technischer Zeitreihen. Lücken werden
  markiert, nicht verschleiert.
- DB-Zugriff ausschließlich über SQLite `mode=ro`.

## Module

| Modul | Datei | Aufgabe |
|---|---|---|
| Health | [`diagnos/health.py`](../../diagnos/health.py) | Host, Dienste, Datenfrische, Backup/Mirror, Mail-Bereitschaft, Log-Überlauf |
| Integrität | [`diagnos/integrity.py`](../../diagnos/integrity.py) | Tagesbilanz, WR-/Collector-Zustand, Gap-Scan, Config-Parse |
| Rollups | [`diagnos/rollup_checks.py`](../../diagnos/rollup_checks.py) | Monats-/Jahresrollup (feld-differenziert) |
| Gap-Scan | [`diagnos/gap_checks.py`](../../diagnos/gap_checks.py) | Zeitlückenklassifikation je Tabelle |
| Netzqualität | [`diagnos/nq_health.py`](../../diagnos/nq_health.py) | PAC4200-Pipeline, Tagesenergie, NQ-Timer, Netzereignisse (Rolle N) |
| Log-Überlauf | [`diagnos/log_health.py`](../../diagnos/log_health.py) | Größenwache persistenter Wartungs-Logs |
| Statusberichte | [`diagnos/status_report.py`](../../diagnos/status_report.py) | RAW-/System-/Netz-Status.md |
| Schwellwerte | [`diagnos/config.py`](../../diagnos/config.py) | zentrale Grenzwerte, Tabellen, NQ-/Log-Parameter |

Der Versand (Tagesbericht + Sofort-Alarme) läuft über den
Automation-Daemon → [`doc/diagnos/MAIL.md`](MAIL.md). Der Katalog aller Checks
steht in [`CHECKKATALOG.md`](CHECKKATALOG.md), Taktung/Eskalation in
[`TAKTUNG_UND_ESKALATION.md`](TAKTUNG_UND_ESKALATION.md).

## Hardware-Abdeckung

| Hardware | Beobachtung (read-only) |
|---|---|
| Host (Pi5) | CPU-Temp, Throttle/Unterspannung, RAM, Disk, Load, Uptime |
| Fronius GEN24 | `freshness:raw_data` + `fronius_attachment_state` (Modbus/Solar-API/interne API) |
| Batterie (BYD) | `battery_api_ok` im Attachment-State; SOC/Leistung im Tagesbericht |
| Fritz!DECT-Steckdosen | `fritzdect_freshness` (Stale-Erkennung der Messsteckdosen) |
| Wattpilot (EV) | `service:pv-wattpilot` + `wattpilot_daily` im Tagesbericht |
| Wärmepumpe (Dimplex) | WP-Energie im Tagesbericht (`W_WP_total`) |
| PAC4200 (Netzqualität) | `nq:pipeline_freshness` — indirekt über frische Aggregate (Tech-Collector) |

## Speicherorte (Diagnose-/Wartungs-Dateien)

| Pfad | Inhalt | Überlaufschutz |
|---|---|---|
| `logs/diagnos/RAW-Status.md` | Datenlücken je Tabelle mit Ursachenheuristik | bei jedem Sunset überschrieben |
| `logs/diagnos/System-Status.md` | Host-Kennwerte + Auffälligkeiten + Log-Inventar | bei jedem Sunset überschrieben |
| `logs/diagnos/Netz-Status.md` | PAC4200-Pipeline, Tagesenergie, NQ-Timer, Netzereignisse | bei jedem Sunset überschrieben |
| `logs/schaltlog.txt` | Schaltprotokoll aller Aktionen | Zeilen-Cap `MAX_ZEILEN` (schaltlog.py) |
| `logs/wp_netzbetreiber_leistung.csv` | Netzbetreiber-Leistungsnachweis | **bewusst endlos** (Rechtsnachweis) — kein Alarm |
| `logs/wp_bridge_audit.log` | Audit der WP-Bridge-Schreibaktionen (Tech) | klein, append |
| `config/diagnos_alert_state.json` | Diff-State der Diagnos-Mailmeldungen | rollierend (Selbstheilung) |
| `config/nq_alert_state.json` | Diff-State der NQ-Mailmeldungen | rollierend |
| `config/event_notifier_dedup.json` | 1×/Tag-Dedup des Mailversands | Reset bei Tageswechsel |
| `/tmp/*.log` (tmpfs) | Laufzeit-Logs (Gunicorn, Collector, Daemon) | [`scripts/logrotate.sh`](../../scripts/logrotate.sh) (>10 MB/>7 d) + Reboot |

Die Log-Überlaufwache (`log_health`) meldet, falls eine nicht-endlose
persistente Datei die Schwelle (`LOG_OVERFLOW_WARN_MB`/`_CRIT_MB`) reißt.

## Nachsehen

```bash
python3 -m diagnos.health --pretty      # Host/Dienste/Frische/Logs
python3 -m diagnos.integrity --pretty   # Bilanz/Rollups/Gaps
python3 -m diagnos.nq_health --pretty   # Netzqualität (Rolle N)
python3 -m diagnos.status_report        # Statusdateien neu schreiben
```
