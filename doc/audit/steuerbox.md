# Audit — Steuerbox (Rolle E)

**Datum:** 2026-05-29 · **Audit-ID:** DEEP-2026-05-29

Rolle E nimmt Operator-Intents entgegen (eigener Port), validiert und schreibt **nur** `operator_overrides` (Intent-DB) — **keine** Hardware. Umsetzung der Intents erfolgt durch Rolle C.

## Befunde

| # | Severity | Befund | Status / Empfehlung |
|---|---|---|---|
| E-01 | HOCH | Doku-Drift Port: mehrere Docs nannten `8001`, Produktion ist **11933** (konfigurierbar via `PV_STEUERBOX_PORT`). | **Korrigiert** in [ARCHITEKTUR.md](../steuerbox/ARCHITEKTUR.md), [SICHERHEIT.md](../steuerbox/SICHERHEIT.md), [LLM_AUSFUEHRUNG.md](../steuerbox/LLM_AUSFUEHRUNG.md). |
| E-02 | HOCH | [ARCHITEKTUR.md](../steuerbox/ARCHITEKTUR.md) listete Endpunkt-pro-Aktion (`hp_toggle`, `wp_offset`, `wattpilot_ctrl`, `regelkreis_toggle` …) — existiert nicht. | **Korrigiert:** real ist **ein** `POST /api/ops/intent` (Feld `action`) plus `GET /api/ops/control-meta`, `/status`, `/audit`, `/health`. 9 erlaubte Aktionen aus `config.STEUERBOX_ALLOWED_ACTIONS` dokumentiert. |
| E-03 | MITTEL | `pause_hp_until_target`-Default: Code nutzt `True`, Card/Doku sagen `False` (seit 2026-05-22). | **Code-Item** — neu in [doc/TODO.md](../TODO.md) aufgenommen (Code an Doku angleichen oder umgekehrt). |
| E-04 | INFO | Code-Anchor der Steuerbox-Cards gültig; Rolle-E (keine Hardware) eingehalten. | OK. |

## Konsistenz Card ↔ Human-Doku

- Nach den Korrekturen sind Port und Endpunkt-Modell zwischen Human-Docs konsistent. `pause_hp`-Default-Drift bleibt als bewusst getrackter Code-Punkt offen.

## Fazit

Größter Doku-Drift im gesamten Audit. Port + Endpunkt-Tabelle waren irreführend und wurden behoben. Verbleibender Punkt ist ein bewusst entschiedenes Code/Doku-Alignment (TODO). Keine Code-Änderung im Audit.
