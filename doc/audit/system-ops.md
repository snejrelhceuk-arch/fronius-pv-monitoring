# Audit — System / Ops

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Übergreifend: Hosts/UFW, Rollenmodell-Doku, IP-Strategie, Cards-Code-Anchor-Integrität, Publish-Guard.

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| S-01 | HOCH | [AGENTS.md](../../AGENTS.md) nannte Pi4-Primary-UFW „noch nicht aktiviert (TODO)". | **Korrigiert** auf „aktiv (seit 2026-05-03)" — deckt sich mit User-Memory (UFW seit 2026-05-03 auf .181 aktiv). |
| S-02 | NIEDRIG | Dateiname `ABCD_ROLLENMODELL.md` (kosmetische Legacy, Modell ist A–E). | **Nicht umbenannt** (Link-Bruch-Risiko); Verweise sprachlich auf „A/B/C/D/E" korrigiert. |
| S-03 | INFO | IP-Platzhalter-Strategie (`192.0.2.x` in Doku vs. `192.168.2.x` real). | **Bewusst/konsistent** — Publish-Guard maskiert sensible IPs. |
| S-04 | INFO | Code-Anchor aller geprüften Cards (11 Stichproben) gültig. | OK. |
| S-05 | INFO | `last_review`-Pflicht bei Card-Edits (Pre-commit). | Eingehalten: einzige editierte Card (collector-db-schema) auf 2026-05-29 gesetzt. |

## Konsistenz & Pflege

- TODO-Disziplin „keine TODOs in Subdirectories" eingehalten; alle Code-Punkte in [doc/TODO.md](../TODO.md).
- `ollama/system_prompt_kern.md` enthielt nicht-existente `battery_control_log`-Retention → korrigiert.

## Fazit

Wichtigster Ops-Befund (UFW-Status in AGENTS.md) behoben. IP-Strategie und ABCD-Dateiname sind bewusste/kosmetische Punkte ohne Handlungsdruck. Keine Code-Änderung im Audit.
