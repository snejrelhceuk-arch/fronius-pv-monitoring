# Taktung und Eskalation — Diagnos D

## Leitlinie

Keine kalenderbasierten Neustarts. Reaktion ist immer **lesen →
klassifizieren → melden**. Eingriffe (Restart/Reboot) sind kein Bestandteil von
Diagnos.

## Taktung (IST)

Die Checks laufen im Automation-Daemon
([`automation/engine/automation_daemon.py`](../../automation/engine/automation_daemon.py)):

| Takt | Was |
|---|---|
| **alle 10 min** | Sofort-Alarm-Prüfung: `pruefe_integrity_alarme()` + `pruefe_health_alarme()` (nur crit/fail-Whitelist) |
| **bei Tageswechsel 00:00** | Tagesbericht: reiner Energie-Auszug (Tag/Monat/Jahr/Gesamt); aktualisiert entkoppelt die Statusdateien |
| **on demand** | `python3 -m diagnos.health\|integrity\|nq_health --pretty` |

Der Tagesbericht aktualisiert einmal täglich (entkoppelt, best-effort)
`logs/diagnos/RAW-Status.md`, `System-Status.md` und `Netz-Status.md`.

## Sofort-Alarme (crit/fail, 1×/Tag pro Key)

Whitelist — nur fachlich zeitkritische Zustände (CRIT/FAIL) lösen aus. Die
WARN-Ebene wird **nicht** gemeldet (der Tagesbericht ist rein energiebezogen):

- **Health:** `cpu_temp`, `throttle`, `disk_root`, `service:<unit>`.
- **Integrität:** Collector inaktiv (>300 s), Fehlerstrang (≥5 Polls),
  fehlgeschlagener Reconnect (nur wenn der Collector nicht wieder liefert).

Der Versand ist persistent dedupliziert (`config/event_notifier_dedup.json`,
Reset bei Tageswechsel).

## WARN-Ebene: nicht mehr in der Mail

Der Tagesbericht ist ein reiner Energie-Auszug. WARN-Befunde (Health,
Integrität, Netzqualität) werden **nicht** mehr per Mail gemeldet — nur
CRIT/FAIL lösen einen Sofort-Alarm aus. Der frühere Diff-Filter
(`diagnos_alert_state.py`, `config/diagnos_alert_state.json`) ist damit aus dem
Mailpfad genommen. Der aktuelle Systemzustand bleibt über
`python3 -m diagnos.health|integrity|nq_health --pretty` und die
`logs/diagnos/*-Status.md` einsehbar.

## Ausfallklassen (Gap-Scan)

| Klasse | Dauer | Wirkung |
|---|---|---|
| micro | < 2 min | nur zählen |
| short | 2–30 min | warn (frisch) |
| medium | 30 min–6 h | crit (frisch) |
| long | > 6 h | crit (frisch) |

Nacht-Standby (Sonnenhöhe < 1°), „gesetzte" Lücken (Ende > 25 h zurück,
Aggregationen haben übernommen) und **akzeptierte** Lücken
(`config/diagnos_gap_accept.json`, per `python3 -m diagnos.gap_accept` bestätigt)
treiben **keine** Alarmschwere mehr, bleiben aber in `RAW-Status.md` sichtbar.
Nur frische, nicht akzeptierte Lücken (< 25 h) sind alarmrelevant.

## Datenpolitik bei Ausfällen

- **Technische Reihen:** echte Lücke bleibt sichtbar.
- **Statistik:** counter-basierte Korrektur ist erlaubt (Collector/Aggregation).
- **Diagnos:** markiert die Lücke, verschleiert sie nicht.
