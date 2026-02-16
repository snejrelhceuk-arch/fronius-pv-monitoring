# Solar-Ertragsprognose: Scaffold-Architektur

> Dokumentation der physikbasierten PV-Ertragsprognose für die Anlage Erlau, Mittelsachsen  
> 37,59 kWp | 7 Strings | 5 Orientierungen | 3 Wechselrichter  
> Stand: 2026-02-16

## Konzept: PV-Modellierungskette

Bei komplexen Anlagen mit verschiedenen Ausrichtungen, Verschattungen und Fassaden-Modulen
ist eine strukturierte Trennung von **statischen Geometrie-Parametern** und **dynamischen
Wetterdaten** der Goldstandard. Anstatt für jeden Zeitschritt alles neu zu berechnen, wird
eine einmalig berechnete **Geometrie-Matrix** ("Scaffold") mit variablen Wetterdaten verknüpft.

### Die Berechnungskette

```
Schritt A: Astronomie          Schritt B: Wetter → Modul       Schritt C: Thermik & Verluste
┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────────┐
│ Zeitstempel          │       │ E_ext = E_dir·cos(θ) │       │ Zelltemperatur T_c       │
│ Breiten-/Längengrad  │──────►│       + E_diff,sky   │──────►│ aus T_amb, Wind, POA     │
│ → Azimut + Zenitwinkel│       │       + E_refl       │       │ P = η·A·POA·(1-γ·(Tc-25))│
└──────────────────────┘       └──────────────────────┘       └──────────────────────────┘
     (rein geometrisch)           (Geometrie × Wetter)            (Thermisches Modell)
```

**Variablen:**
- **θ** — Einfallswinkel (Angle of Incidence, aus Scaffold)
- **E_dir** — Direkteinstrahlung (aus Wetterdaten)
- **E_diff,sky** — Diffuses Himmelslicht (Perez-Modell)
- **E_refl** — Albedo/Bodenreflexion
- **γ** — Temperaturkoeffizient (-0,35 %/°C)

## Implementation: Zwei-Schichten-Architektur

### Schicht 1: `GeometryScaffold` (solar_geometry.py)

pvlib-basierte Klasse, die für einen Zeitvektor die gesamte Geometrie **einmalig vektorisiert** berechnet:

```python
scaffold = GeometryScaffold(times_local, PV_STRINGS, shading_mask=SHADING_MASK)
# → scaffold.solar_position   (Azimut, Elevation, Zenith für alle Zeitpunkte)
# → scaffold.compute_string_dc_power(weather_df)  → DataFrame pro String
# → scaffold.compute_inverter_power(strings_dc)    → AC nach Clipping
```

**Berechnungsschritte pro String:**
1. **Perez-Transposition** — GHI/DNI/DHI → POA (Plane of Array) inkl. Albedo
2. **Verschattungsmaske** — Lookup-Table (Azimut × Elevation → Faktor 0..1)
3. **SAPM-Zelltemperatur** — aus POA, Umgebungstemp., Windgeschwindigkeit
4. **Temperaturkorrektur** — Faktor 1 + γ·(T_cell - 25°C), begrenzt auf 0.70–1.10
5. **String-Faktoren** — Kalibrierung, Optimierer-Gain (aus geometry_config.json)
6. **Inverter-Clipping** — AC-Limit pro Wechselrichter + WR-Wirkungsgrad

### Schicht 2: Legacy-Fallback (ohne pvlib)

Wenn pvlib nicht verfügbar: Meeus-Sonnenstand + Klucher-Diffusmodell + isotrope
Bodenreflexion. Weniger genau, aber autark lauffähig.

### Schicht 3: Empirische Kalibrierung (solar_forecast.py)

Multi-Faktor-Regressionsmodell aus historischen Daten:
```
PV_kWh = a · GHI + b · Sonnenstunden + c
```
Koeffizienten in `config/solar_calibration.json`, automatisch via `--calibrate` aktualisierbar.

## Konfigurationsdateien

| Datei | Inhalt |
|-------|--------|
| `config/geometry_config.json` | Performance Ratio, Temp-Koeff., Albedo, Atmosphäre, String-Faktoren, Verschattungsmaske, Azimut-Offset, saisonale Modultemperaturen |
| `config/solar_calibration.json` | Empirische Kalibrierung: GHI-Faktor, Multi-Faktor-Koeffizienten, R², monatliche Faktoren |
| `config/clearsky_profile.json` | Cache: Clear-Sky 365×24h Profiltabelle (generiert) |
| `config/efficiency_table.json` | Cache: Neigungswinkel-Effizienztabelle 37×19 (generiert) |

## String-Konfiguration (7 Strings, 3 WR)

| String | kWp | Neig. | Azimut | Wechselrichter | Beschreibung |
|--------|-----|-------|--------|----------------|-------------|
| F1-S1 | 6,90 | 52° | SSO (-22,5°) | F1 (12kW) | Satteldach Süd |
| F1-S2 | 6,90 | 52° | NNW (157,5°) | F1 | Satteldach Nord |
| F1-S3 | 2,76 | 45° | SSO (-22,5°) | F1 | Gaube/Anbau Süd |
| F1-S4 | 2,76 | 45° | NNW (157,5°) | F1 | Gaube/Anbau Nord |
| F2-S5 | 6,75 | 18° | WSW (67,5°) | F2 (10kW) | Flachdach West |
| F2-S6+7 | 5,67 | 90° | WSW (67,5°) | F2 | Fassade West |
| F3-S8 | 5,85 | 90° | SSO (-22,5°) | F3 (4,5kW) | Fassade Süd |

## Nutzung

```bash
# Tagesprognose
python3 solar_forecast.py --today

# Stündlich (pvlib-Scaffold-Pfad)
python3 solar_forecast.py --hourly

# Kalibrierung gegen reale Produktionsdaten
python3 solar_forecast.py --calibrate

# Clear-Sky-Profiltabelle neu generieren
python3 solar_geometry.py --clearsky

# Effizienztabelle (Azimut×Neigung) generieren
python3 solar_geometry.py --efficiency
```

## Warum pvlib?

pvlib ist der **Industriestandard** für PV-Modellierung in Forschung und Ingenieurwesen:
- Fertige Perez-Transposition (anisotropes Diffusmodell)
- SAPM-Zelltemperaturmodell (Sandia Array Performance Model)
- Präzise Sonnenposition (NREL SPA, <0,001° Genauigkeit)
- Validiert gegen Messdaten weltweit

**View-Factor-Ansatz:** Die Verschattungsmaske in `geometry_config.json` ist eine
einfache Form der View-Factor-Berechnung — sie bestimmt, wie viel Himmel ein Modul
bei gegebener Sonnenposition "sieht". Diese Faktoren sind rein geometrisch und werden
nur einmal definiert.

## Datenquellen

- **Wetter:** Open-Meteo Forecast API (DWD ICON-D2, 2,2 km Raster, kostenlos)
- **Strahlung:** GHI + DNI + DHI (alle 3 Komponenten für korrekte GTI-Berechnung)
- **Kalibrierung:** Historische Produktion aus data.db vs. Open-Meteo Archive API
