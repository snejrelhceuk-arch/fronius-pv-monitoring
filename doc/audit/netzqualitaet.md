# Audit — Netzqualität

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Module: `netzqualitaet/nq_analysis.py`, `nq_export.py`, `nq_trade_switch_detect.py`. Eigene `netzqualitaet/db/`. Web-Anbindung über read-only API (Rolle B).

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| NQ-01 | NIEDRIG | NQ-Card trägt `role: B`. | **Bewusst belassen:** Pre-commit erlaubt nur A/B/C/D/E/meta; die NQ-Web-Anbindung ist tatsächlich read-only (B). Kein besserer Enum-Wert vorhanden. Vorbefund „CRITICAL" widerlegt. |
| NQ-02 | NIEDRIG | Cron-Status der NQ-Jobs in Doku ambivalent (aktiv/manuell). | In Card/Doku eindeutig benennen, welcher Job per Cron läuft. |
| NQ-03 | INFO | `nq_trade_switch_detect.run_day` ist manuell auslösbar (kein Auto-Cron). | Entspricht Doku-Absicht. |
| NQ-04 | INFO | Code-Anchor der NQ-Cards gültig. | OK. |

## Konsistenz Card ↔ Human-Doku

- Konsistent bis auf Cron-Status-Wording (NQ-02).

## Fazit

Netzqualität fachlich konsistent. Einziger nennenswerter Punkt ist Wording zum Cron-Status; keine Code- oder kritische Doku-Änderung nötig.
