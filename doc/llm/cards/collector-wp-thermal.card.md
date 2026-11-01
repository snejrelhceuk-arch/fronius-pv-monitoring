---
title: WP-Thermik & COP/SCOP (Dimplex-Wärmemengen via Modbus)
domain: collector
role: A
applyTo: "collector/aggregate/wp_thermal.py"
tags: [waermepumpe, wp, cop, scop, modbus, waermemenge, thermisch]
status: stable
last_review: 2026-11-01
---

# WP-Thermik & COP/SCOP

## Zweck
Erfasst die thermische Leistungsfähigkeit der Dimplex-WP als **COP** (24h) und
**SCOP** (12 Monate) — ohne Zusatzhardware. Quelle sind die internen
Dimplex-Wärmemengen- und Laufzeit-Zähler (Modbus-Historie 5.2), gegengerechnet
mit der elektrischen WP-Tagesenergie (`daily_data.W_WP_total`, sekundärer SM).

## Code-Anchor
- **Leseschicht (Zähler):** `wp_modbus.py:get_wp_energy` (+ `_poll_energy_local`/`_poll_energy_remote`, `WP_WAERMEMENGE_REGS`, `WP_LAUFSTUNDEN_REGS`, `_combine_waermemenge`)
- **Bridge-Endpunkt (Tech):** `wp_bridge/wp_bridge_api.py:wp_energy` (`GET /api/wp/energy`)
- **Tagesaggregation (Primary):** `collector/aggregate/wp_thermal.py:update_wp_thermal_daily` (cron stündlich :13)
- **Schema:** `db_init.py` → `wp_thermal_daily`
- **Web-Serving (Rolle B, read-only):** `routes/system/battery.py:_fetch_wp_cop` → `result['wp_cop']`
- **Anzeige:** `templates/flow_view.html` (Maschinenraum-WP-Zeile: `… · COP x,xx · SCOP x,xx`)

## Inputs / Outputs
- **Inputs:** Dimplex-Modbus Wärmemenge Heizen (Reg 5096–5098) + WW (5099–5101), Laufstunden Verdichter/Pumpen (72–77); `daily_data.W_WP_total` (el. Tagesenergie).
- **Outputs:** `wp_thermal_daily` (Zähler-End-Stände + Tagesdelta thermisch, `verdichter1_h_delta`, `el_kwh`, `cop`).

## Wärmemengen-Decode (Dimplex-Dezimal-Split)
3 uint16-Register kodieren eine große Dezimalzahl:
`Gesamt_kWh = reg_9_12 * 1e8 + reg_5_8 * 1e4 + reg_1_4`.
Beispiel (Feldwert): Heizen `[5612, 3, 0]` → 35612 kWh; WW `[9823, 1, 0]` → 19823 kWh.

## Invarianten
- **Read-only ggü. Hardware.** `get_wp_energy()` liest nur (FC=3). Kein Schreibpfad; Rollentrennung bleibt (A liest via Bridge, kein Hardware-Write aus A/B/D).
- **COP = thermal_delta / el_kwh**, nur wenn `el_kwh ≥ 1.0 kWh` und `thermal_delta ≥ 0` (sonst `cop=NULL`, Quantisierungs-/Rauschschutz).
- **Deltas self-healing:** Jeder Lauf rechnet alle Tagesdeltas per Self-Join auf den Vortag neu. Der COP eines Tages wird erst belastbar, sobald der **Folgetag** einen End-Stand hat (Zähler-Snapshot = End des laufenden Tages).
- **SCOP (12 Mon.) = Σ thermal_delta / Σ el_kwh** über die letzten 365 Tage (nur Tage mit belastbarem COP). Baut sich ab Einführung auf (keine rückwirkende Thermik-Rekonstruktion möglich — Zähler sind kumulativ).
- **Zähler-Auflösung** 1 kWh / 1 h → Tagesdelta ±1 kWh quantisiert (für 24h-COP unkritisch).

## No-Gos
- Keine Rateneingriffe/Schreibregister über diesen Pfad — `get_wp_energy` ist reine Monitoring-Leseschicht.
- Wärmemengen-Register **nicht** als Momentanleistung interpretieren (kumulative Zähler).
- Kein Poll schneller als nötig: Zähler ändern sich stündlich → 5-min-Cache (`_WP_ENERGY_CACHE_TTL`).

## Häufige Aufgaben
- Neue Laufzeit-/Zählergröße aufnehmen → `WP_LAUFSTUNDEN_REGS`/`WP_WAERMEMENGE_REGS` in `wp_modbus.py` + Spalte in `wp_thermal_daily` (`db_init.py`) + Aggregation in `wp_thermal.py`.
- COP-Schwelle justieren → `_COP_MIN_EL_KWH` in `wp_thermal.py`.
- Anzeige ändern → `_fetch_wp_cop` (Route) + WP-Zeile in `flow_view.html`.

## Bekannte Fallstricke
- **Lifetime-Plausibilität:** Σ thermisch (Modbus) / Dimplex-el.-Zähler (manuelle Ablesung, `nq_ims_reading.note`) ≈ 3,97 — sanity-Anker, nicht für Tages-COP nutzen.
- **el. Quelle ist der sekundäre SM** (`W_WP_total`, Unit 4), **nicht** der Dimplex-interne el.-Zähler. Beide Baselines unterscheiden sich (SM ab REFORMATION, Dimplex ab Installation 2021).
- Bridge-Ausfall → `get_wp_energy()` liefert `None`, Aggregation überspringt den Lauf (kein Datenverlust, Zähler kumulativ).
- Bootstrap-Tag zeigt `COP –` bis der Folgetag einen Snapshot hat.

## Verwandte Cards
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md) — `W_WP_total`, `P_WP`
- [`automation-regel-heizpatrone.card.md`](./automation-regel-heizpatrone.card.md) — WP-Steuerung (C-Rolle, Schreibpfad)
- [`web-flow-view.card.md`](./web-flow-view.card.md) — Maschinenraum-Anzeige

## Human-Doku
- `doc/automation/WP_REGISTER.md` (§5 Historie/Laufzeiten)
- `doc/automation/WP_INTEGRATION.md` (COP/SCOP-Messung)
