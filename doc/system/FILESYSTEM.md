# Filesystem-Layout (Root vs. Rollen-Pakete)

Stand: 2026-05-16

## Zweck
Dieses Dokument erklaert, welche Dateien bewusst im Workspace-Root liegen und warum.
Grundlage ist die ABCDE-Rollentrennung aus [AGENTS.md](../../AGENTS.md).

## Leitprinzip (ABCDE)
- Rolle A (Collector) sammelt Daten und schreibt nur in `raw_data`.
- Rolle B (Web-API) ist read-only und schreibt weder DB noch Hardware.
- Rolle C (Automation) ist die einzige Rolle mit aktiven Schreibpfaden zu Hardware.
- Rolle D (Diagnos) liest und alarmiert, schreibt aber keine Hardware.
- Rolle E (Steuerbox) schreibt nur Intents, keine direkte Hardware.
- Architektur-Regel: Rollentrennung ist wichtiger als DRY.

## Warum nicht alles in collector/
`collector/` ist A-spezifisch. Rollenuebergreifende Module duerfen nicht in einen A-Namespace verschoben werden,
wenn sie auch von B/C/D genutzt werden. Sonst entstuenden implizite Rollenkopplungen.

## Python-Dateien im Root und ihre Rolle
Aktuell liegen 14 Python-Dateien im Root:

### Entrypoints und Runtime
- [collector.py](../../collector.py): Start-Entrypoint fuer Rolle A.
- [web_api.py](../../web_api.py): Start-Entrypoint fuer Rolle B.
- [gunicorn_config.py](../../gunicorn_config.py): Runtime-Konfiguration fuer Web-API/Gunicorn.
- [pv-config.py](../../pv-config.py): Betriebs-/Setup-Skript.
- [host_role.py](../../host_role.py): Host-Rollenlogik (Primary/Failover-Kontext).

### Rollenuebergreifende Kernmodule
- [config.py](../../config.py): zentrale Konfiguration fuer mehrere Rollen.
- [db_init.py](../../db_init.py): Schema/Initialisierung, von mehreren Rollen genutzt.
- [db_utils.py](../../db_utils.py): gemeinsame DB-Helfer.
- [fronius_api.py](../../fronius_api.py): Fronius-API-Bausteine fuer Collector und Automation.
- [wattpilot_api.py](../../wattpilot_api.py): Wattpilot-Client fuer Collector und Automation.
- [wp_modbus.py](../../wp_modbus.py): WP-Modbus-Zugriff fuer Automation/Support-Pfade.
- [solar_forecast.py](../../solar_forecast.py): Forecast-Baustein fuer API/Automation.
- [solar_geometry.py](../../solar_geometry.py): Geometrie-Baustein fuer Forecast/API/Tools.
- [statistics_corrections.py](../../statistics_corrections.py): Korrekturregeln fuer Statistik-Pipeline.

## Rollen-Pakete (Ordner)
- [collector/](../../collector/): Rolle A (Sammeln, Buffer, Aggregation).
- [automation/](../../automation/): Rolle C (Steuerlogik/Aktoren).
- [diagnos/](../../diagnos/): Rolle D (Diagnose/Alerts).
- [routes/](../../routes/): Rolle B (API-Routen, read-only).
- [steuerbox/](../../steuerbox/): Rolle E (Intent-Schicht).

## Entscheidungsregel fuer künftige Ablagen
- A-only Modul -> in [collector/](../../collector/).
- Rollenuebergreifendes Modul -> im Root lassen.
- B/D duerfen keine schreibenden Hardwarepfade enthalten.
- Bei Grenzfaellen gilt: ABCDE-Reinheit vor DRY.
