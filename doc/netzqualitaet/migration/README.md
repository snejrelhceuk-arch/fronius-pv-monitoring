# NQ-Doku — Migrationsarchiv

**Stand:** 2026-07-11

Dieser Ordner archiviert **überholte / duplizierte NQ-Dokumente**, die bei der
Einführung des Moduls `nq/` (Rolle N, 2026-07-11) konsolidiert wurden. Sie sind
**nicht mehr maßgeblich** — die verbindlichen Aussagen stehen in der aktiven
`doc/netzqualitaet/`-Ebene.

## Warum archiviert

Vor der REFORMATION existierten NQ-Notizen mit **veralteten Prämissen**:

- Collector auf **Pi5** statt (jetzt) **Pi4-Tech** (Rolle N);
- alte Host-IPs (`192.168.2.x`) und alte Rollenzuordnung;
- ein separater „NQ-Workspace" und ein Subdirectory-`TODO.md`
  (widerspricht dem No-Go „keine TODOs in Subdirectories").

Diese Inhalte wurden in die konsolidierten, aktiven Dokumente überführt.

## Wo die Inhalte jetzt stehen

| Archiviert (`2026-07-09/`) | Aktiv / maßgeblich |
|---|---|
| `NQ_ROOT_README.md`, `README.md` | [`../README.md`](../README.md), [`../NQ_MODUL.md`](../NQ_MODUL.md) |
| `PHASE_1_PLAN.md`, `TODO.md` | [`../NQ_MODUL.md`](../NQ_MODUL.md) §9 (Phasenplan) + [`../../TODO.md`](../../TODO.md) |
| `MESSTECHNIK.md` | [`../MESSTECHNIK.md`](../MESSTECHNIK.md) (aktualisiert) |
| `METHODEN.md`, `TOOLS.md`, `TRADE_SWITCH_DETECTION.md` | gleichnamige Dateien in [`..`](..) |
| `cpu_thermal_*_2026-04-19.log` | Feldtest-Rohlogs (nur Referenz) |

## Verbindliche Host-/Architektur-Entscheidung

Siehe [`../NQ_MODUL.md`](../NQ_MODUL.md): Collector auf **Pi4-Tech**
(`192.0.2.181`, RAM-first), Aggregation/Analyse auf **Pi5-Primary**
(`192.0.2.204`). Rollenmodell: [`../../system/ABCDEN_ROLLENMODELL.md`](../../system/ABCDEN_ROLLENMODELL.md).

> Dateien hier **nicht** weiterpflegen. Bei Bedarf löschen, sobald die
> Konsolidierung endgültig abgenommen ist.
