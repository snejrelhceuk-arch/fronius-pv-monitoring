---
title: Feldnamen-Referenz (Konventionen, Dupletten, Stolperfallen)
domain: collector
role: A
tags: [feldnamen, semantik, dupletten]
status: stable
last_review: 2026-05-03
---

# Feldnamen-Referenz

## Zweck
Die wichtigsten Feldnamen mit ihrer Bedeutung, ihren Einheiten und ihren häufigsten Verwechslungen. Wer Daten liest, muss diese Referenz kennen, sonst entstehen schnell falsche Bilanzen (z. B. "PV = `W_AC_Inv`" — falsch).

## Code-Anchor
- **Aggregations-Producer:** `aggregate_1min.py` (Hauptliste der berechneten Felder, ~L60–90)
- **Collector-Producer:** `modbus_v3.py`, `collector.py`
- **Quell-Doku:** `doc/collector/FELDNAMEN_REFERENZ.md`

## Konventionen
- DB-Spalten: `snake_case`, oft Anteils-Großbuchstaben aus Modbus-Quellen (`W_AC_Inv`, `P_Netz`).
- JSON/Web-API: lowercase (`p_ac_inv`).
- Einheiten: `P_*` = Watt (Momentanleistung), `W_*` = Watt-Stunden (Energie über Periode), `U_*` = Volt, `I_*` = Ampere.

## Kritische Dupletten / Verwechslungen
- **`W_AC_Inv` ≠ PV-Erzeugung.** Inkludiert Batterie-Durchfluss. **Echte PV** = `W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3` (siehe `aggregate_1min.py`).
- **`W_WP` (Wärmepumpe) ≠ Wattpilot.** WP=Stiebel-Eltron, Wattpilot=Fronius/go-e Wallbox.
- **`P_Netz`:** positiv = Bezug, negativ = Einspeisung.
- **`W_Exp_Netz`:** negativ → mit `abs()` zu Einspeisung machen.
- **Wattpilot-Solarweb:** zeigt nur PV-Direkt-Anteil; Netzbezug-Anteil unsichtbar — eigene `wattpilot_daily`-Quelle nutzen.

## Top-Felder (gekürzt)
| Feld | Quelle | Bedeutung |
|---|---|---|
| `P_AC_Inv` | Modbus | AC-Leistung am WR (inkl. Batterie) |
| `P_DC1`, `P_DC2` | Modbus | DC-Leistung pro String |
| `SOC_Batt` | Modbus | Batterie-SOC (%) |
| `U_Batt_API`, `I_Batt_API` | Solar-API | Batterie-Spannung/-Strom |
| `P_Netz` | Modbus/Smart Meter | Netzleistung (s. Vorzeichen) |
| `P_F2`, `P_F3` | Modbus | Phasen-Leistungen |
| `P_WP` | FritzDECT | Wärmepumpe |
| `W_Ertrag` | berechnet | PV-Ertrag (Periode) |
| `W_Einspeis`, `W_Bezug` | berechnet | Netz-Bilanz |
| `W_Direct` | berechnet | PV→Verbrauch direkt |
| `W_inBatt_PV`, `W_inBatt_Grid` | berechnet | Batterie-Ladung Quelle |
| `W_outBatt` | berechnet | Batterie-Entladung |

## Invarianten
- Wer ein neues Feld einführt, muss Einheit + Vorzeichen + Quelle dokumentieren — **bevor** es in `aggregate_*.py` einfließt.
- Bilanzfelder (`W_*`) niemals über Periodengrenzen mischen.

## No-Gos
- Keine Eigeninterpretation von `W_AC_Inv` als PV.
- Keine WP/Wattpilot-Verwechslung.
- Keine Vorzeichen-Inversionen ohne Tests.

## Häufige Aufgaben
- Neue Bilanzgröße einführen → Berechnung in `aggregate_1min.py` + Schema-Spalte (`db_init.py`) + Doku-Eintrag in `doc/collector/FELDNAMEN_REFERENZ.md` und ggf. hier ergänzen.
- Vorzeichen-Bug debuggen → `P_Netz` und `W_Exp_Netz` separat prüfen.

## Bekannte Fallstricke
- Vorzeichen-Konvention bei `P_Netz` und `W_Exp_Netz` ist **invers** — leicht zu verwechseln.
- Wattpilot-`eto` ist Gesamt-Counter (nicht Tageswert) → Tagesdelta in `wattpilot_daily.energy_wh`.
- Wattpilot-Wert in Solarweb-Statistik ist unvollständig (nur PV-Anteil) → eigene Quelle nutzen.

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-wattpilot-collector.card.md`](./collector-wattpilot-collector.card.md) — `eto`, `session_wh`

## Human-Doku
- `doc/collector/FELDNAMEN_REFERENZ.md`
