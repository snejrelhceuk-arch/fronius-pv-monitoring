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
| **bei Sonnenuntergang** (`is_day` True→False) | Sunset-Tagesbericht: voller Health-/Integrity-/NQ-Snapshot + Statusdateien |
| **on demand** | `python3 -m diagnos.health\|integrity\|nq_health --pretty` |

Der Sunset-Bericht schreibt bei jedem Lauf `logs/diagnos/RAW-Status.md`,
`System-Status.md` und `Netz-Status.md` neu.

## Sofort-Alarme (crit/fail, 1×/Tag pro Key)

Whitelist — nur fachlich zeitkritische Zustände lösen sofort aus, alles andere
wartet auf den Sunset-Bericht:

- **Health:** `cpu_temp`, `throttle`, `disk_root`, `service:<unit>`.
- **Integrität:** Collector inaktiv (>300 s), Fehlerstrang (≥5 Polls),
  fehlgeschlagener Reconnect (nur wenn der Collector nicht wieder liefert).

Der Versand ist persistent dedupliziert (`config/event_notifier_dedup.json`,
Reset bei Tageswechsel).

## Sunset-Diff-Filter (WARN-Ebene)

Der Tagesbericht meldet nur **neue/eskalierte** Befunde. Stabil-wiederkehrende
Zustände werden unterdrückt und erst nach 7 Tagen erinnert; Rückkehr auf `ok`
heilt den State selbsttätig. Zustand:
`config/diagnos_alert_state.json` (Diagnos) bzw. `config/nq_alert_state.json`
(NQ). Mechanik: [`automation/engine/diagnos_alert_state.py`](../../automation/engine/diagnos_alert_state.py).

## Ausfallklassen (Gap-Scan)

| Klasse | Dauer | Wirkung |
|---|---|---|
| micro | < 2 min | nur zählen |
| short | 2–30 min | warn (frisch) |
| medium | 30 min–6 h | crit (frisch) |
| long | > 6 h | crit (frisch) |

Nacht-Standby (Sonnenhöhe < 1°) und „gesetzte" Lücken (Ende > 25 h zurück,
Aggregationen haben übernommen) treiben **keine** Alarmschwere mehr, bleiben
aber in `RAW-Status.md` sichtbar. Nur frische Lücken (< 25 h) sind
alarmrelevant.

## Datenpolitik bei Ausfällen

- **Technische Reihen:** echte Lücke bleibt sichtbar.
- **Statistik:** counter-basierte Korrektur ist erlaubt (Collector/Aggregation).
- **Diagnos:** markiert die Lücke, verschleiert sie nicht.
