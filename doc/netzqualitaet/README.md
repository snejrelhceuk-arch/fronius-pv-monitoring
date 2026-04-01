# Netzqualitäts-Monitoring

Eigenständiges Teilprojekt innerhalb des PV-Systems. Überwacht Leiterspannungen,
Netzfrequenz und (perspektivisch) Muster in der Netzqualität.

## Status

| Phase | Status | Beschreibung |
|-------|--------|-------------|
| Sofortmaßnahme | ✅ erledigt | Frequenzlinie aus Tagesmonitoring entfernt, Echtzeit → Maschinenraum |
| Phase 1 | 🔧 in Arbeit | Tagesprofil L-L-Spannungen + Frequenz, Stromkontext |
| Phase 2 | geplant | Musteranalyse, Kalenderprofile, Voraggregation, Messtechnik-Entscheidung |

## Architektur

- **Route:** `/netzqualitaet` → `templates/netzqualitaet_view.html`
- **API:** `/api/netzqualitaet/tag` → `routes/netzqualitaet.py`
- **Daten:** raw_data (3s) resampelt auf 5min-Raster; Fallback data_1min (L-N × √3)
- **Einstieg UI:** Flow → Maschinenraum → Button „Netzqualität"

## Phase-1-Signale

| Signal | DB-Feld | Quelle | Ebene |
|--------|---------|--------|-------|
| Leiterspannung L1-L2 | `U_L1_L2_Netz` | SmartMeter Netz | raw_data |
| Leiterspannung L2-L3 | `U_L2_L3_Netz` | SmartMeter Netz | raw_data |
| Leiterspannung L3-L1 | `U_L3_L1_Netz` | SmartMeter Netz | raw_data |
| Netzfrequenz | `f_Netz` | SmartMeter Netz | raw_data, data_1min |
| Phasenstrom L1 | `I_L1_Netz` | SmartMeter Netz | raw_data (Kontext) |
| Phasenstrom L2 | `I_L2_Netz` | SmartMeter Netz | raw_data (Kontext) |
| Phasenstrom L3 | `I_L3_Netz` | SmartMeter Netz | raw_data (Kontext) |

## Phase-1-Bausteine (geplant)

1. **Tagesprofil** — Leiterspannungen + Frequenz im 5min-Raster (✅ Grundversion vorhanden)
2. **Änderungsbeobachtung** — Delta, Sprungbetrag, gleitende Streuung, Ereigniszähler
3. **Lokale Kompensation** — Spannungsereignisse gegen Phasenströme spiegeln,
   Ursachenklasse: `wahrscheinlich lokal` / `unklar` / `wahrscheinlich netzseitig`

## Phase-2-Ausblick

- Voraggregation L-L-Spannungen in data_1min / data_15min
- Kalenderprofile (Wochentag, Feiertag, Ferien, Jahreszeit)
- 15min-Handelsmuster-Indikatoren
- Unsymmetrie- und Korrelationskennzahlen
- Messtechnik-Entscheidung für Oberschwingungen (kHz–100kHz)

## Dateien

```
routes/netzqualitaet.py          — API Blueprint
templates/netzqualitaet_view.html — Chart-Seite (ECharts)
doc/netzqualitaet/               — Projektdokumentation
  README.md                      — dieses Dokument
  PHASE_1_PLAN.md                — detaillierter Phase-1-Plan
```
