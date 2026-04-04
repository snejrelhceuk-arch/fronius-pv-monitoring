# Netzqualität — Werkzeuge

**Stand:** 2026-04-03

## Zweck

Dieses Dokument ordnet die moeglichen Python-Werkzeuge nach **Sinn vs. Aufwand**
fuer das Netzqualitaets-Teilprojekt ein.

## Empfohlener Werkzeug-Stack

### Kernstack

| Werkzeug | Wofuer konkret | Aufwand | Urteil |
|---------|-----------------|---------|--------|
| `numpy` | Vektorrechnung, Gradienten, Fenster, robuste Kennwerte | niedrig | Pflicht |
| `pandas` | Zeitachsen, Resampling, Rolling-Window, Kalenderprofile | niedrig bis mittel | Pflicht |
| `scipy` | Signaltools, Regression, Korrelation, Welch, Filter | mittel | sehr sinnvoll |
| `matplotlib` | Offline-Diagnoseplots, Scatter, Spektren, QC | niedrig | sinnvoll |

### Erweiterungsstack

| Werkzeug | Wofuer konkret | Aufwand | Urteil |
|---------|-----------------|---------|--------|
| `statsmodels` | STL, ACF/PACF, robuste Zeitreihenmodelle | mittel | sinnvoll ab Phase 2 |
| `scikit-learn` | Clustering, PCA, Anomalie-Features, Outlier-Modelle | mittel bis hoch | optional |
| `pywt` | Wavelets fuer Multi-Skalen-Transienten | hoch | spaeter / nur mit schnellerer Messtechnik |

## Kurzbewertung je Bibliothek

### `numpy`

**Sinn:** sehr hoch

- bereits im Projekt im Einsatz
- ideal fuer `mean/min/max/std`, Gradienten, Differenzen, Masken, robuste Fenster
- fuer `nq_analysis.py` die natuerliche Basis

**Aufwand:** gering

**Fazit:** keine Diskussion, bleibt Basisschicht.

### `pandas`

**Sinn:** hoch

- Zeitreihen mit Zeitstempeln werden lesbarer und pflegeleichter
- Resampling, Rolling-Window und Kalender-Features sind damit deutlich schneller
  umsetzbar als in reinem SQL oder nacktem `numpy`
- besonders sinnvoll fuer Offline-Analysen, Backfills und Reports

**Aufwand:** gering bis mittel

**Fazit:** fuer Analyse- und Reporting-Code sehr sinnvoll. Nicht zwingend im
hot path des produktiven Collectors, aber klar sinnvoll in NQ-Analyse-Skripten.

### `scipy`

**Sinn:** hoch

- lineare und robuste Fits
- Korrelation, Verteilungen, Hypothesentests
- PSD/Welch, sobald eine schnellere Datenquelle vorhanden ist
- Filter und Peaks fuer Ereignisdetektion

**Aufwand:** mittel

**Fazit:** beste Erweiterung nach `numpy`/`pandas`.

### `matplotlib`

**Sinn:** mittel bis hoch

- wichtig fuer Diagnoseplots und Methodenentwicklung
- nicht als Web-Frontend gedacht, aber sehr gut fuer Entwicklungs- und
  Plausibilisierungsplots

**Aufwand:** gering

**Fazit:** fuer Analysearbeit sehr hilfreich, fuer die Web-UI nicht zentral.

### `statsmodels`

**Sinn:** mittel

- gut fuer Trend/Saisonalitaet/Residuum
- ACF/PACF und einfache Zeitreihenmodelle sind fuer Wochen- und Monatsmuster
  nuetzlich

**Aufwand:** mittel

**Fazit:** sinnvoll, sobald Kalenderprofile und laengere Reihen systematisch
ausgewertet werden.

### `scikit-learn`

**Sinn:** begrenzt, solange die Features noch nicht stabil sind

- kann fuer Outlier- oder Cluster-Fragen helfen
- lohnt sich aber erst, wenn physikalisch belastbare Features existieren

**Aufwand:** mittel bis hoch

**Fazit:** kein Startpunkt. Erst nach robuster Merkmalsbildung einsetzen.

### `pywt`

**Sinn:** aktuell gering

- Wavelets sind stark fuer Transienten auf mehreren Skalen
- bei 3s-Samples fehlt die zeitliche Aufloesung fuer den eigentlichen Gewinn
- mit kuenftiger Hochabtastung kann das spaeter interessant werden

**Aufwand:** hoch

**Fazit:** derzeit bewusst zurueckstellen.

## Projektentscheidung

### Sofort einsetzen

- `numpy`
- `pandas`
- `scipy`
- `matplotlib`

### Bei Phase-2-Bedarf nachziehen

- `statsmodels`

### Vorerst nicht priorisieren

- `scikit-learn`
- `pywt`

## Praktische Arbeitsteilung

| Aufgabe | Werkzeug |
|--------|----------|
| Kernmetriken, DFD, Delta, Gradient | `numpy` |
| Zeitfenster, Resampling, Kalendermerkmale | `pandas` |
| Korrelation, Regression, Signalmethoden | `scipy` |
| Entwicklungs- und Diagnoseplots | `matplotlib` |
| Saison-/Trend-Zerlegung | `statsmodels` |
| spaetere explorative Feature-Modelle | `scikit-learn` |
| spaetere Transientenanalyse | `pywt` |

## Pflege-Regel

Dieses Dokument wird aktualisiert, wenn neue Bibliotheken produktiv eingefuehrt
oder bewusst verworfen werden.