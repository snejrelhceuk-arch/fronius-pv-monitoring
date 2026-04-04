# Netzqualität — Phase-1-Plan

**Stand:** 2026-04-01
**Grundsatz:** Schrittweise optimieren, Komplexität bewusst begrenzen,
Messrauschen nicht mit Erkenntnis verwechseln.

---

## 1. Sofortmaßnahmen (abgeschlossen in v1.2.1)

- Netzfrequenzlinie aus `tag_view.html` ersatzlos entfernt
- `createFrequencyChart()` und alle Referenzen entfernt
- Button „Echtzeit" in Flow → „Maschinenraum" umbenannt
- Route `/maschinenraum` + Kompatibilitätsroute `/echtzeit`
- Button „Netzqualität" im Maschinenraum-Header eingefügt

## 2. Phase-1-Datenvertrag

### Pflichtsignale

| Signal | raw_data | data_1min | data_15min | Anmerkung |
|--------|----------|-----------|------------|-----------|
| `U_L1_L2_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | Nur in raw_data direkt gemessen |
| `U_L2_L3_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | dto. |
| `U_L3_L1_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | dto. |
| `f_Netz` | ✅ vorhanden | ✅ avg/min/max | ✅ avg/min/max | Durchgängig |
| `I_L1_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | Kontextsignal |
| `I_L2_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | dto. |
| `I_L3_Netz` | ✅ vorhanden | ❌ fehlt | ❌ fehlt | dto. |

### Konsequenz

Phase 1 arbeitet zunächst mit 5min-Resampling direkt aus `raw_data`.
Für ältere Tage (Rohdaten gelöscht nach ~3 Tagen) wird aus `data_1min`
mit L-N × √3 approximiert. Für Phase 2 sollte `aggregate_1min.py`
um L-L-Spannungen und Phasenströme erweitert werden.

### raw_data-Retention

`RAW_DATA_RETENTION_DAYS` (default: 3 Tage) → Rohdaten älter als 3 Tage
werden gelöscht. Phase-1-Tagesprofile für ältere Tage nutzen zwangsläufig
den Approximations-Fallback.

## 3. Phase-1-Bausteine

### A: Tagesprofil (✅ Grundversion)

- API: `/api/netzqualitaet/tag?date=YYYY-MM-DD`
- 5min-Buckets aus raw_data, Fallback data_1min
- Chart: Leiterspannungen L-L (3 Linien) + Frequenz (separates Panel)
- Y-Achse Spannung: automatisch skaliert
- Y-Achse Frequenz: 49.9–50.1 Hz (Farbzonen: grün/gelb/orange)

### B: Änderungsbeobachtung (geplant)

- Delta zum Vorwert (ΔU, Δf pro 5min-Intervall)
- Gleitende Standardabweichung (Fenster: 30min)
- Ereigniszähler: Anzahl Sprünge > Schwelle pro Stunde
- Parallelität: gleichzeitige Sprünge auf mehreren Phasen
- **Grundsatz:** Nur robuste Kennzahlen, die gegenüber Messrauschen
  unempfindlich sind. Keine Spektralanalyse in Phase 1.

### C: Lokale Kompensation (geplant)

- Korrelation zwischen Spannungsereignissen und Phasenstromänderungen
- Ursachenklasse: `wahrscheinlich lokal` / `unklar` / `wahrscheinlich netzseitig`
- **Keine harte Kausaldiagnose** — nur Indikation
- Physik: Lokale Laständerung → Strom ↑/↓ gleichzeitig mit Spannungssprung
  → wahrscheinlich lokal. Spannungssprung ohne Stromänderung → netzseitig.

## 4. Phase-2-Ausblick (gesperrt bis Phase 1 stabil)

- Voraggregation L-L-Spannungen + Phasenströme in `aggregate_1min.py`
- Kalenderprofile: Wochentag vs. Wochenende, Feiertag, Ferien, Jahreszeit
- 15min-Handelsmuster: Viertelstundensprünge in der Frequenz
- Unsymmetrie-Kennzahl: (U_max - U_min) / U_avg zwischen L-L-Spannungen
- Optional: Messtechnik-Entscheidung für Oberschwingungen (kHz-Bereich)
  → SmartMeter reicht dafür NICHT; benötigt eigenes HF-Messequipment

## 5. Messtechnik-Einschätzung

| Analyse | SmartMeter (vorhanden) | Zusätzliche HW nötig? |
|---------|------------------------|----------------------|
| RMS-Spannung L-L | ✅ 3s-Auflösung | nein |
| Netzfrequenz | ✅ 3s-Auflösung | nein |
| Phasenströme | ✅ 3s-Auflösung | nein |
| Langfristmuster (mHz–Hz) | ✅ aus Aggregaten | nein |
| Oberschwingungen (kHz) | ❌ nicht möglich | ja, dediziertes PQ-Messgerät |
| Supraharmonics (>9kHz) | ❌ nicht möglich | ja, HF-Analysator |

**Arbeitshypothese:** Alles im mHz- bis niedrigen Hz-Bereich eignet sich
für Langfristmuster. Klassische 50Hz-RMS-Beobachtung eignet sich für
Spannungsqualität und Betriebsverhalten. kHz-Effekte brauchen separate
Messmittel und sollten nicht aus SmartMeter-Daten überinterpretiert werden.

## 6. LLM-Unterstützung

Jede Phase bekommt eine Bewertungsmatrix für die LLM-Unterstützung:
- Fachliche Richtigkeit
- Annahmendisziplin (was wird stillschweigend vorausgesetzt?)
- Halluzinationsrate (Felder/Funktionen die nicht existieren)
- Scope-Treue (bleibt das Modell beim Thema?)
- Umsetzungsdisziplin (wird tatsächlich gebaut oder nur geplant?)

Diese Bewertung wird pro Phase und pro Modell (Gemini / GPT / Claude)
dokumentiert und dient als Einsatzfreigabe für spätere Phasen.
