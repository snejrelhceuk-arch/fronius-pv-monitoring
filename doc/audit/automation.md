# Audit — Automation (Rolle C)

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Rolle C ist die einzige Schreib-Rolle (DB + HTTP/Modbus-Write). Regelwerk in `automation/engine/`, Aktoren, Regeln, Vorausschau.

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| A-01 | NIEDRIG | Dead Code: `_prüfe_extern_respekt()` in [automation/engine/regeln/waermepumpe.py](../../automation/engine/regeln/waermepumpe.py#L66) ist definiert, wird aber nie aufgerufen. | Bereits in [doc/TODO.md](../TODO.md) erfasst — entfernen oder anbinden. |
| A-02 | MITTEL | `engine_vorausschau()` dupliziert die Regel-Liste gegenüber `engine.py`. | **Verifiziert:** Vorausschau ist **vollständig/synchron** (alle Regeln vorhanden). Der frühere TODO „9 fehlende Regeln" (DEEP-2026-06 K-02) ist damit **erledigt**; in TODO auf reine Code-Duplikation reduziert. |
| A-03 | MITTEL | `battery_control_log` wird seit 2026-03 nicht mehr beschrieben (kein `INSERT`), aber noch gelesen. | Reader-Cleanup-TODO bleibt offen ([doc/TODO.md](../TODO.md)); Doku/Card im Audit klargestellt. |
| A-04 | INFO | Heizpatrone-Energieschwelle (`aus_netzbezug_energie_kwh = 0.1`) | **Verifiziert korrekt.** Vorbefund „Card-Mathematik falsch" widerlegt — Matrix-JSON überschreibt Code-Defaults (Zwei-Schichten-Konfig). |
| A-05 | INFO | Rollentrennung: nur C schreibt Hardware. | Eingehalten. Keine Schreibpfade in B/D gefunden. |

## Konsistenz Card ↔ Human-Doku

- [doc/automation/AUTOMATION_ARCHITEKTUR.md](../automation/AUTOMATION_ARCHITEKTUR.md): Rollen-Verweis `A/B/C/D` → **korrigiert** auf `A/B/C/D/E`.
- Automation-Cards: Code-Anchor stichprobenartig gültig.

## Fazit

Rolle C funktional und rollenrein. Keine Code-Änderung im Audit. Offene Punkte ausschließlich in [doc/TODO.md](../TODO.md).
