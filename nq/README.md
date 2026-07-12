# nq/ — Netzqualität (Rolle N)

Dediziertes PAC4200-Netzqualitäts-Modul am Netzanschlusspunkt (PCC).
Läuft **host-spezifisch**: Collector auf **Tech**, Aggregation/Analyse auf
**Primary**. Read-only gegenüber der Produktion.

Vollständige Architektur, RAM-Budget-Rechnung und Phasenplan:
[`doc/netzqualitaet/NQ_MODUL.md`](../doc/netzqualitaet/NQ_MODUL.md).

## Struktur

```
nq/
  schema/
    nq_tech_schema.sql       # tmpfs-DB auf Tech (RAW fast/medium/slow + 3-10s-Aggregat)
    nq_primary_schema.sql    # Aggregat-/Analyse-DB auf Primary
  pac_live.py                # verifizierte Registerkarte + read-only Live-Snapshot (Web/Feldtest)
  fieldtest/                 # Phase 0: Refresh-Raten-Feldtest (read-only, kein Speichern)
  collector/                 # Tech: PAC-Client, Block-Poller, tmpfs-Buffer, Kappung
  transfer/                  # Tech-Export + Primary-Ingest (täglich)
  aggregate/                 # Primary: 3-10s → 5min → hourly → daily
  analysis/                  # Primary: Netzereignis-Tools (HF/NF/VLF)
  db/                        # Monats-DBs auf Primary (gitignored)
```

## Live-Anzeige (read-only)

Die verifizierten PAC4200-Messwerte sind live unter **`/pac4200`** sichtbar
(Flow → Maschinenraum → PAC4200), gerendert aus [`pac_live.py`](pac_live.py)
über [`routes/pac4200.py`](../routes/pac4200.py). Reiner Modbus-**Read**, kein
Schreibpfad zum Gerät (Muster wie `FroniusReadOnly`).

## Abgrenzung zu `netzqualitaet/`

`netzqualitaet/` (Legacy, Rolle B) leitet NQ aus vorhandenen Fronius-Smart-Meter-
Daten ab. `nq/` (Rolle N) nutzt ein eigenes **PAC4200**-Messgerät. Beide bestehen
parallel, kein gemeinsames Schema.

## Konfiguration

[`config/nq_config.json`](../config/nq_config.json) — Poll-Raten, tmpfs-Budget,
Retention, Event-Filter, Transfer. Poll-Raten nach 48h-Feldtest nachziehen.

## Implementierung

Die Teilbereiche werden in eigenen Chats gebaut — Prompts unter
`.github/prompts/nq-*.prompt.md`. Reihenfolge: Feldtest → Tech-Collector →
Transfer+Aggregation → Analyse.
