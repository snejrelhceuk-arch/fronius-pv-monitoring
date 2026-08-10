# Checkkatalog — Diagnos D

Alle produktiven read-only Checks, gruppiert nach Modul. Severity-Stufen:
`ok` < `warn` < `crit` < `fail` (Check selbst fehlgeschlagen). Die
Gesamtseverity je Lauf ist stets die schlechteste Einzelseverity.

## Health — [`diagnos/health.py`](../../diagnos/health.py)

| Check | Bedeutung | Schwelle (warn/crit) | Sofort-Alarm |
|---|---|---|---|
| `cpu_temp` | CPU-Temperatur | 75 / 80 °C | ja |
| `throttle` | Pi Unterspannung/Throttling | Flags aktiv → crit; Binary fehlt → fail | ja (crit) |
| `ram` | RAM-Belegung | 85 / 95 % | — |
| `disk_root` | Root-Belegung | 80 / 90 % | ja (crit) |
| `load` | Load-Average | Cores×1 / ×2 | — |
| `uptime` | Uptime (Info) | — | — |
| `service:<unit>` | 5 Kern-Dienste aktiv (`SERVICES`) | inaktiv → crit | ja |
| `freshness:<tabelle>` | Alter des letzten Eintrags (raw_data/data_1min/data_15min/daily_data) | `FRESHNESS_TABLES` | — |
| `mirror_sync_age` | Alter des Failover-Mirror-Markers | 15 / 30 min (**nur failover**) | — |
| `backup_local_gfs_daily` | Alter des jüngsten lokalen GFS-Daily | 30 / 48 h | — |
| `notification_ready` | SMTP-Credential vorhanden (nur primary) | fehlt → crit | — |
| `fritzdect_freshness` | Messsteckdosen liefern frisch (nur primary) | Stale > 1 h → warn | — |
| `log_health` | Überlauf persistenter Logs | 50 / 200 MB (endlose CSV ausgenommen) | — |

## Integrität — [`diagnos/integrity.py`](../../diagnos/integrity.py), [`gap_checks.py`](../../diagnos/gap_checks.py), [`rollup_checks.py`](../../diagnos/rollup_checks.py)

| Check | Bedeutung | Logik |
|---|---|---|
| `integrity:daily_energy_balance` | Verbrauch = PV + Bezug − Einspeisung | Abweichung 300 / 1000 Wh |
| `integrity:fronius_attachment_state` | WR-/Schnittstellen- und Collector-Liveness | aktuelle Poll-Liveness schlägt ältere Vollprüfung |
| `integrity:gaps:<tabelle>` | Zeitlücken je Tabelle | klassifiziert (micro/short/medium/long); Nacht-Standby + „gesetzte" Lücken (>25 h) treiben keinen Alarm |
| `integrity:config_json_parse` | `config/*.json` syntaktisch lesbar | defektes JSON → crit |
| `integrity:monthly_rollup` | monthly_statistics vs. Tagessummen | **feld-differenziert** (s. u.) |
| `integrity:yearly_rollup` | yearly_statistics vs. Monatssummen | **feld-differenziert** (s. u.) |

**Feld-Differenzierung der Rollups:** Fluss-Felder (Solar/Bezug/Einspeisung/
Gesamtverbrauch) sind eichgenaue Counter-Summen und müssen eng zusammenpassen
(relative Toleranz `ROLLUP_FLOW_WARN_PCT`/`_CRIT_PCT`, Absolutboden 2 kWh →
alarmtreibend). Methoden-Felder (Batterieladung/-entladung, Direktverbrauch)
divergieren systematisch (~2–13 %), weil der Monatswert aus der eichgenauen
Counter-Differenz (`data_monthly`) stammt bzw. daraus abgeleitet wird, die
Tagessumme aber aus BMS-Checkpoints/`W_PV_Direct`. Diese Differenz wird
berichtet, treibt aber **keine** Alarmschwere.

## Netzqualität (Rolle N) — [`diagnos/nq_health.py`](../../diagnos/nq_health.py)

Rollen-/deploymentbewusst: ohne NQ-Monats-DB oder auf Failover still. Die
PAC4200-Hardware liest ausschließlich der Tech-Collector; Primary beobachtet
indirekt über frische Aggregate.

| Check | Bedeutung | Schwelle (warn/crit) |
|---|---|---|
| `nq:pipeline_freshness` | Alter des jüngsten 5-min-Aggregats (Kette PAC→Tech→Transfer→Aggregation) | 5 / 9,5 h |
| `nq:energy_freshness` | Alter des jüngsten Tages in `nq_energy_daily` | 2 / 4 Tage |
| `nq:services` | Primary-NQ-Timer scharf (nur installierte Units) | inaktiv/failed → warn |
| `nq:events_recent` | Netzereignisse der letzten 24 h (Info) | kein Alarm |

## Nicht-Ziele (bewusst nicht als aktiver Probe umgesetzt)

- **Aktive LAN/SSH/API-Pings.** Erreichbarkeit wird über Datenfrische bewiesen
  (`freshness:*`, `nq:pipeline_freshness`, `fronius_attachment_state`) statt über
  redundante Netz-Probes — schont die read-only Schicht und die Gegenstellen.
- **Parity aktiver Hosts** (Git-/Config-Diff) läuft über die Ops-Guards
  (`system-ops-guards`), nicht über Diagnos.
