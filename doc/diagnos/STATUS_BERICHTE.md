# Diagnos — Statusberichte & Alarm-Semantik

Schicht D (read-only). Beschreibt die menschenlesbaren Statusdateien und die
Alarm-Logik, damit die tägliche Sunset-Mail knapp und auch für Außenstehende
verständlich bleibt.

## Statusdateien (`logs/diagnos/`)

Erzeugt von [`diagnos/status_report.py`](../../diagnos/status_report.py)
(`write_status_reports`) aus den read-only Snapshots von `diagnos.integrity`,
`diagnos.health` und `diagnos.nq_health`. Sie werden bei jedem Sunset-Bericht
neu geschrieben; die Mail verweist nur auf Pfad + Größe.

| Datei | Inhalt |
| --- | --- |
| `RAW-Status.md` | Jede Datenlücke (raw_data / data_1min / data_15min / hourly_data) mit Beginn/Ende, Größe, Klasse, Status (frisch / gesetzt / Nacht-Standby) und Ursachenheuristik. |
| `System-Status.md` | Host-Kennwerte (CPU-Temp, Throttle, RAM, SD/Disk, Last, Uptime), auffällige Dienste/Frische/Backups und das Inventar der persistenten Wartungs-Logs. |
| `Netz-Status.md` | PAC4200-Pipeline-Frische, Tagesenergie-Rollup, Primary-NQ-Timer und Netzereignisse der letzten 24 h (Rolle N). |

**Ursachenheuristik** der Lücken:
- **WR-Nachtstandby** — Lücke vollständig bei Dunkelheit (Sonnenhöhe < 1°), betrieblich normal.
- **WR-Firmware-Update** — Lücke nahe einem dokumentierten Versionswechsel des Wechselrichters.
- **Neustart/Stromausfall** — Lückenende nahe dem letzten Systemstart (Uptime).
- **unbekannt** — nicht eindeutig (kurzer Pollausfall, stale process o. ä.).

## Alarm-Semantik

Ziel: keine Dauerwarnungen für betrieblich normale Zustände.

1. **WR-Anknüpfung / Schnittstellen** (`check_fronius_attachment_state`):
   Maßgeblich ist die *aktuelle* Collector-Liveness. Pollt der Collector frisch
   (≤ 300 s) ohne Fehlerserie, liefern die Wechselrichter — eine ältere oder
   unvollständige gespeicherte Vollprüfung ist dann höchstens **WARN**, nie
   **CRIT**. Ein erfolgreicher oder bereits behobener Reconnect ist eine Info.

2. **Datenlücken** (`_run_gap_scan`): Eine Lücke, deren Ende länger als
   `GAP_SETTLE_S` (25 h) zurückliegt, gilt als **gesetzt** — der Tag ist
   abgeschlossen, die Aggregationen haben den Stand übernommen. Solche Lücken
   treiben **keine** Alarmschwere mehr; sie bleiben in `RAW-Status.md` und im
   Feld `settled_gap_count` sichtbar. Nur **frische** Lücken (< 25 h) sind
   alarmrelevant.

3. **Monats-/Jahresrollup** (`rollup_checks.py`): nur die Fluss-Felder
   (Solar/Bezug/Einspeisung/Gesamtverbrauch) treiben Alarmschwere. Batterie und
   Direktverbrauch divergieren methodisch bedingt (Counter vs.
   BMS-Checkpoints/`W_PV_Direct`) und werden nur berichtet.

4. **Diff-Filter:** Bereits gemeldete, stabile Befunde werden nicht erneut
   alarmiert, sondern nach 7 Tagen erinnert; „geheilt" = Rückkehr auf OK. Der
   Zähler `unterdrückt=` in der Mail ist die maßgebliche Gesamtzahl.

## Wo finde ich was?

- **Tägliche Mail:** Kurzfassung + Verweise (Abschnitt „Weiterführende Statusquellen").
- **Statusdateien:** `logs/diagnos/{RAW,System,Netz}-Status.md`.
- **Laufzeit-Logs:** `journalctl -u pv-web -u pv-automation -u pv-collector`.
- **Vollstatus on demand:** `python3 -m diagnos.health|integrity|nq_health --pretty`.
