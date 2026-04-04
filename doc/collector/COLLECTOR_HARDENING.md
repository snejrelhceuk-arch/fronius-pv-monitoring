# Collector Hardening — Modbus & Attachment-Validierung

**Stand:** 2026-04-03

## Validierung F1/F2 nach Firmware-Update (2026-04-03)

- Zeitpunkt Pruefung: 2026-04-03 ca. 18:22
- Zeitfenster Update-Effekt: ab ca. 00:00 bis etwa 00:04 lokaler Zeit
- Beobachtung im Journal:
  - kurzzeitige `Modbus Connect Failed`
  - danach temporaer `Kein SunSpec Header` fuer Unit 2/3/4/6
  - anschliessend automatische Erholung, F1/F2 wieder stabil lesbar
- Live-Validierung erfolgreich:
  - Unit 2 (`PRIM_SM_F1`) liefert SunSpec Header + Modell `203`
  - Unit 3 (`SEC_SM_F2`) liefert SunSpec Header + Modell `203`
  - dokumentierte Solar-API (`GetPowerFlowRealtimeData`, `GetInverterRealtimeData`,
    `GetMeterRealtimeData`, `GetStorageRealtimeData`) antwortet mit HTTP 200
  - undokumentierte interne API bleibt erreichbar wie erwartet:
    - `/status/common`: HTTP 200
    - `/api/config/batteries`, `/api/config/common`: HTTP 401 +
      `X-WWW-Authenticate` (Fronius-Hybrid-Digest-Challenge vorhanden)

## Reconnect-Retry fuer kritische SmartMeter

- Polling wurde gehaertet: Wenn F1/F2 (`prim_sm`, `sec_sm_F2`) in einem Zyklus
  keine `meter_data` liefern, folgt ein sofortiger Modbus-Reconnect + Retry.
- Wenn auch der Retry fuer F1/F2 scheitert, wird der Poll verworfen statt als
  NULL-Datensatz in `raw_data` zu landen.
- Implementiert in `modbus_v3.py`, Funktion `_read_poll_devices()`.

## Automatische Pruefung bei Versionswechsel

Der Collector fuehrt nun automatisch einen Versions-Snapshot ueber SunSpec
Model 1 (`Vr`, `SN`) fuer Inverter und alle SmartMeter durch.

### Ablauf

1. Beim Start wird der gespeicherte Attachment-State geladen
   (`config/fronius_attachment_state.json`).
2. Nach jedem Poll-Zyklus wird ein aktueller Versions-Snapshot erstellt
   und mit dem gespeicherten verglichen.
3. Bei erkannter Aenderung startet automatisch eine fest definierte
   Vollpruefung aller Anknuepfungspunkte.

### Pruefumfang

- Modbus Unit 1/2/3/4/6 inkl. erwarteter SunSpec-Modelle
- Dokumentierte Solar-API-Endpunkte
- Interne Fronius-Endpunkte inkl. `X-WWW-Authenticate`-Challenge
- SunSpec-Discovery ueber Unit-IDs 1..10, um geaenderte
  Model-/Unit-Kombinationen sichtbar zu machen

### Persistenz

Alle Ergebnisse werden persistent gespeichert in:

    config/fronius_attachment_state.json

Struktur:

```json
{
  "initialized_ts": <unix>,
  "last_seen_ts": <unix>,
  "version_snapshot": {
    "inverter_sn": "...", "inverter_vr": "...",
    "prim_sm_sn": "...", "prim_sm_vr": "...",
    "sec_sm_f2_sn": "...", "sec_sm_f2_vr": "...",
    "sec_sm_f3_sn": "...", "sec_sm_f3_vr": "...",
    "sec_sm_wp_sn": "...", "sec_sm_wp_vr": "..."
  },
  "last_validation": { ... }
}
```

### Relevante Funktionen in modbus_v3.py

| Funktion | Aufgabe |
|----------|---------|
| `_load_attachment_state()` | State-Datei laden (Startup) |
| `_save_attachment_state()` | State-Datei persistieren |
| `_build_version_snapshot()` | SunSpec Model 1 Vr/SN aller Geraete auslesen |
| `_validate_all_attachment_points()` | Vollpruefung Modbus + API + Discovery |
| `_version_change_check_and_revalidate()` | Vergleich + Trigger bei Aenderung |
