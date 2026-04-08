# Handelsgetriebene Schaltzeiten — wissenschaftliche Methodik

Stand: 2026-04-05

## Ziel

Schaltzeiten und Periodizitaeten aus den Messdaten selbst bestimmen,
statt Zeitanker (:00/:15/:30/:45) vorzugeben.

## Verfuegbare Werkzeuge (wissenschaftlich + praktisch)

1. Robuste Event-Detektion auf Zeitreihe
- Signal: f_netz, optional kombiniert mit U- und I-Kanaelen
- Merkmale: Gradient |df/dt|, Step-Differenz pre/post, Nadir, U/I-Deltas
- Vorteil: direkt auf vorhandenen 3s-Rohdaten moeglich

2. Periodensuche (datengetrieben)
- Methode A: Rasterscan ueber Kandidatenperioden (z. B. 300..1800s),
  fuer jede Periode beste Phase und Event-Score bestimmen
- Methode B: Spektral (FFT/Lomb-Scargle) auf Event- oder Dip-Serie
- Methode C: ACF/Periodogramm als zweite, unabhaengige Schaetzung
- Wichtig: harmonische Mehrdeutigkeit (900 vs 1800s etc.) immer explizit prüfen

3. Changepoint-Methoden
- CUSUM, BOCPD, PELT/Ruptures-artige Verfahren (falls spaeter eingefuehrt)
- Nutzen: Zeitpunkte von Zustandswechseln ohne starre Schwellwerte

4. Signifikanz und Nachweis
- Nullmodell (zeitlich geshuffelte oder phasenverschobene Surrogatdaten)
- p-Werte / Effektstaerke fuer "Periodizitaet ist nicht Zufall"

## Wie die Werkzeuge auf eure Daten angewendet werden

Datenbasis:
- nq_samples: ts, f_netz, u_l1_l2, u_l2_l3, u_l3_l1, i_l1, i_l2, i_l3

Pipeline (empfohlen):
1. Alle Tageswerte laden (3s-Raster, keine Voraggregation im ersten Schritt)
2. Leichtes Preprocessing:
   - fehlende Werte filtern
   - optional 1s-Interpolation nur fuer periodische Tests
3. Event-Merkmale pro Zeitindex berechnen:
   - gradient_energy = |df/dt|
   - step_60s = mean(pre_60s) - mean(post_60s)
   - abs_step_60s = |step_60s|
   - local_impact aus U/I-Deltas
4. Spikes speichern:
   - Trigger ueber robusten z-Score oder MAD-Schwelle
   - Tabelle mit ts, step, nadir, local_impact, score
5. Min/Max je Intervall speichern:
   - 1min, 5min, 15min, 60min: min, max, mean, std, spread, quantile
6. Periodizitaet ermitteln:
   - period scan (coarse/fine)
   - unabhaengiger Cross-Check (ACF/FFT)
   - harmonische Aufloesung (Fundamentalperiode vs Vielfache)
7. Nachweisbericht erzeugen:
   - geschaetzte Periode, Phase, Konfidenz, Stabilitaet ueber Tage
   - Anteil netzseitiger vs lokaler Events

## Datenmenge vs Genauigkeit

Grundregel:
- Mittelwertfehler sinkt grob mit 1/sqrt(N)

Konkrete Wirkung fuer eure Anwendung:
1. Mehr Tage verbessern Periodenschaetzung deutlich
- 1 Tag: fragil bei Sondereffekten / Lastprofilen
- 7 Tage: stabile Phase/Periode in der Regel erreichbar
- 30 Tage: robuste Statistik, bessere Trennung von Harmonischen

2. Hoehere zeitliche Aufloesung verbessert Schaltzeit-Jitter
- 3s-Raster begrenzt Zeitauflosung auf einige Sekunden
- 1s-Interpolation verbessert nur numerisch, nicht physikalisch die Messgrenze
- echte Verbesserung kommt erst mit dichterer Messung (separater Sensor)

3. Mehr Features verbessert Klassifikation lokal/netz
- nur f_netz: gute Ereigniserkennung, begrenzte Ursachenzuordnung
- f_netz + U + I: deutlich bessere lokale/netzseitige Trennung

## Performance und Rechneranforderungen

Ist-Zustand (gemessen):
- Script: netzqualitaet/nq_trade_switch_detect.py
- Periodensuche 300..1800s, coarse 15s, fine +-15s
- Laufzeit auf aktuellem System: ca. 10.2s pro Tag

Sizing-Richtwerte:
1. Pi4 ausreichend, wenn
- taegliche Batch-Analyse (nachts)
- keine harte Echtzeitanforderung
- Laufzeitbudget pro Tag <= 30s

2. Pi5 sinnvoll, wenn
- Near-Realtime (z. B. alle 1-5 Minuten) gewuenscht
- mehrere Verfahren parallel laufen (Periodensuche + Changepoint + Reporting)
- unabhängiger NQ-Release-Zyklus vom pv-system gewuenscht

3. Trennung vom pv-system empfehlenswert, wenn
- Analyse CPU-spikes den Produktionspfad stoeren koennen
- NQ schnell iterieren soll (eigene Abhaengigkeiten, eigene Deployments)

## Wichtige methodische Hinweise

1. Periodizitaet nicht fixieren
- Periode und Phase muessen aus Daten geschaetzt werden

2. Harmonische explizit behandeln
- Dominante Spektrallinie kann bei 2x/3x Fundamental liegen
- deshalb immer mehrere Kandidaten + Konsistenz ueber Tage reporten

3. Nachweis = mehrstufig
- Eventdetektion
- Periodenschaetzung
- Signifikanztest gegen Nullmodell
- Stabilitaet ueber mehrere Tage

## Empfohlene naechste Schritte

1. Persistente Ergebnistabellen einfuehren:
- nq_event_spikes
- nq_interval_stats
- nq_period_estimates

2. Multi-Methoden-Estimator bauen:
- Boundary-Scan
- ACF/FFT-Crosscheck
- Konsensentscheidung + Unsicherheitsband

3. 30-Tage-Backtest fahren:
- Tagesweise Periode/Phase
- Drift, Ausreisser, Signifikanz
- Pi4-Laufzeitprofil (CPU/Walltime)
