# Diagnos — Statusberichte & Alarm-Semantik

> **Stand:** 2026-06-27 · Schicht D (read-only Diagnose)

Dieses Dokument beschreibt die menschenlesbaren Statusdateien und die
überarbeitete Alarm-Logik, damit die tägliche Sunset-Mail knapp und auch für
Außenstehende verständlich bleibt.

## Statusdateien (`logs/diagnos/`)

Erzeugt von `diagnos/status_report.py:write_status_reports` aus den read-only
Snapshots von `diagnos.integrity.run_all()` und `diagnos.health.run_all()`.
Sie werden bei jedem Sunset-Bericht neu geschrieben; die Mail verweist nur auf
Pfad + Größe.

| Datei | Inhalt |
| --- | --- |
| `RAW-Status.md` | Jede Datenlücke (raw_data / data_1min / data_15min / hourly_data) mit Beginn/Ende, Größe, Klasse, Status (frisch / gesetzt / Nacht-Standby) und Ursachenheuristik. |
| `System-Status.md` | Host-Kennwerte: CPU-Temperatur, Throttle, RAM, SD/Disk, Last, Uptime — plus auffällige Dienste/Frische/Backups. |

**Ursachenheuristik** der Lücken:
- **WR-Nachtstandby** — Lücke vollständig bei Dunkelheit (Sonnenhöhe < 1°), betrieblich normal.
- **WR-Firmware-Update** — Lücke nahe einem dokumentierten Versionswechsel des Wechselrichters.
- **Neustart/Stromausfall** — Lückenende nahe dem letzten Systemstart (Uptime).
- **unbekannt** — nicht eindeutig (kurzer Pollausfall, stale process o. ä.).

## Alarm-Semantik (geändert 2026-06-27)

Ziel: keine Dauerwarnungen für betrieblich normale Zustände.

1. **WR-Anknüpfung / Schnittstellen** (`check_fronius_attachment_state`):
   Maßgeblich ist die *aktuelle* Collector-Liveness. Pollt der Collector frisch
   (≤ 300 s) ohne Fehlerserie, liefern die Wechselrichter — eine ältere oder
   unvollständige gespeicherte Vollprüfung ist dann höchstens **WARN**, nie
   **CRIT**. Reconnect-Versuche gelten nur als Problem, wenn sie fehlschlugen
   **und** der Collector nicht wieder liefert. Ein erfolgreicher oder bereits
   behobener Reconnect (z. B. nach einem WR-Firmware-Update am F2) ist eine
   Info, kein Fehler.

2. **Datenlücken** (`_run_gap_scan`): Eine Lücke, deren Ende länger als
   `GAP_SETTLE_S` (25 h) zurückliegt, gilt als **gesetzt** — der Tag ist
   abgeschlossen, die Aggregationen haben den Stand übernommen. Solche
   historischen Lücken sind der Normalzustand der Datenbank und treiben **keine**
   Alarmschwere mehr; sie bleiben in `RAW-Status.md` und im Feld
   `settled_gap_count` dokumentiert. Nur **frische** Lücken (< 25 h, noch
   behandelbar) sind alarmrelevant.

3. **Diagnos-Filter (Diff zur letzten Mail):** Bereits gemeldete, stabile
   Befunde werden nicht erneut alarmiert, sondern nur nach 7 Tagen erinnert;
   „geheilt" = Rückkehr auf OK. Der Zähler `unterdrückt=` in der Mail ist die
   maßgebliche Gesamtzahl über alle Abschnitte (frühere abschnittsweise
   Teilzahlen wurden entfernt, um Widersprüche zu vermeiden).

## Wo finde ich was?

- **Tägliche Mail:** Kurzfassung + Verweise (Abschnitt „Weiterführende Statusquellen").
- **Statusdateien:** `logs/diagnos/RAW-Status.md`, `logs/diagnos/System-Status.md`.
- **Laufzeit-Logs:** `journalctl -u pv-web -u pv-automation -u pv-collector`.
- **Vollstatus on demand:** `python3 -m diagnos.health --pretty`, `python3 -m diagnos.integrity --pretty`.
