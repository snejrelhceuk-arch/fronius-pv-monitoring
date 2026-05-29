# Audit — Web / Routes (Rolle B)

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Rolle B ist **read-only** (kein DB-Write, keine Hardware). Flask-Blueprints in `routes/`, `web_api.py`. `FroniusReadOnly` ist bewusste Duplette von `BatteryConfig` (ABCDE-Reinheit > DRY).

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| B-01 | HOCH | `str(e)` in API-Antworten leakt interne Fehlertexte: [routes/system.py](../../routes/system.py#L1557), [L1710](../../routes/system.py#L1710), [L1730](../../routes/system.py#L1730), [L1970](../../routes/system.py#L1970). | Deckt sich mit TODO „Fehlermeldungen entschärfen". Code-Item, in [doc/TODO.md](../TODO.md). |
| B-02 | MITTEL | Rate-Limiting (`flask-limiter`) nicht implementiert. | Bereits in [doc/TODO.md](../TODO.md) (Sicherheit). |
| B-03 | NIEDRIG | `routes/system.py` ~1977 Z. (TODO nennt 1971). | Aufteilungs-TODO existiert; Zeilenzahl nur Richtwert. |
| B-04 | INFO | CORS via `PV_API_CORS_ORIGINS`; Einschränkung bei Öffnung als TODO erfasst. | OK. |
| B-05 | INFO | `FroniusReadOnly` enthält keine Schreibpfade. | **Verifiziert read-only.** Rollentrennung B eingehalten. |

## Konsistenz Card ↔ Human-Doku

- Web-Cards stichprobenartig konsistent; Blueprint-Struktur entspricht Doku.

## Fazit

Read-only-Eigenschaft von B bestätigt. Wichtigster offener Punkt: `str(e)`-Leaks (Sicherheit) — als Code-Item in TODO. Keine Code-Änderung im Audit.
