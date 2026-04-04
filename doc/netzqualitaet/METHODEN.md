# Netzqualität — Methoden

**Stand:** 2026-04-03

## Zweck

Dieses Dokument beschreibt, **welche Analyseverfahren für die vorhandenen
Netzspannungs- und Netzfrequenzdaten sinnvoll sind** und welche Verfahren erst
mit zusätzlicher Messtechnik belastbar werden.

Ausgangspunkt ist die aktuelle Datenbasis:

- Primärquelle: Fronius Smart Meter Netz (`PRIM_SM_F1`, Unit 2)
- Signale: L-L-Spannungen, L-N-Spannungen, Phasenströme, Frequenz, Wirkleistung,
  Blindleistung, Leistungsfaktor
- Produktions-Polling: `POLL_INTERVAL = 3s`
- NQ-Export: eigene Monats-DBs in `netzqualitaet/db/`

## Grundsatz

**Vorhandene Messungen zuerst bis an die physikalische und statistische Grenze
ausreizen.** Keine Komplexität einführen, solange robuste Kennzahlen mit den
vorhandenen 3s-RMS-Daten noch Erkenntnis liefern.

Das aktuelle System misst **Betriebs- und Qualitätsmuster im Sekunden- bis
Stundenbereich**, aber **nicht die Wellenform im 50-Hz-Zyklus**. Deshalb sind
Methoden auf zwei Ebenen zu trennen:

1. **Zeitreihen-Methoden auf RMS-/Mittelwertdaten** — sofort sinnvoll
2. **Spektral-/Breitbandmethoden auf Rohwellenformen** — erst mit eigener
   Hochabtast-Messtechnik sinnvoll

## Sinnvolle Methoden mit der aktuellen 3s-Datenbasis

| Methode | Nutzen | Aufwand | Urteil |
|--------|--------|---------|--------|
| Robuste Fensterkennwerte (`avg`, `min`, `max`, `spread`, `std`, `median`, `MAD`) | Fängt Nadirs, Spruenge und Volatilitaet ein | niedrig | Pflicht |
| Grenzfenster-Analyse an `:00/:15/:30/:45` | DFD / Handelsmuster direkt sichtbar | niedrig | Pflicht |
| Rolling-Std / Rolling-Quantile | Unruhige Zeitfenster sauber erkennen | niedrig | sehr sinnvoll |
| Delta-Analyse zum Vorwert | Lastspruenge und Spannungsspruenge sichtbar | niedrig | sehr sinnvoll |
| Korrelation Strom ↔ Spannung | lokal vs. netzseitig besser trennen | mittel | sehr sinnvoll |
| Regressionsmodell fuer Spannungsbereinigung | lokale Rueckwirkung herausrechnen | mittel | sehr sinnvoll |
| Kalenderprofile (Wochentag, Wochenende, Feiertage, Jahreszeit) | Wiederkehrende Muster erkennen | mittel | sinnvoll |
| Changepoint-/Ereignis-Erkennung | stabile Schwellwert-Events statt Bauchgefuehl | mittel | sinnvoll |
| STL / Trend-Saisonalitaet | gut fuer laengere Reihen und Wochenprofile | mittel | Phase 2 |

## Methoden, die aktuell nur eingeschraenkt sinnvoll sind

| Methode | Problem mit aktueller Datenbasis | Urteil |
|--------|----------------------------------|--------|
| FFT / Spektren auf 3s-Daten | Nur extrem langsame Schwingungen sichtbar, keine 50-Hz-Details | nur fuer Langfristmuster |
| Wavelets auf 3s-Daten | Zu grobe zeitliche Aufloesung fuer echte Transienten | spaeter |
| ML-Anomalieerkennung | Ohne saubere Features produziert sie eher interessante als belastbare Befunde | nachrangig |
| Klassische Oberschwingungsanalyse | Mit 3s-RMS-Daten prinzipiell nicht moeglich | nicht mit aktueller Quelle |

## Empfohlene Ausbaureihenfolge

### Stufe A — jetzt

- 5min-Buckets von `avg` auf **`avg/min/max/std/spread`** erweitern
- Vor-/Nachher-Metriken an 15min-Grenzen ausbauen
- Spannungsbereinigung mit gemessener Schleifenimpedanz integrieren
- Kalenderprofile fuer DFD-Staerke und Spannungsspread aufbauen
- Ereignislisten statt reiner Linienplots erzeugen

### Stufe B — nach Stabilisierung

- Robustere Regressionsmodelle fuer `U ~ I_local + Uhrzeit + Grenztyp`
- Changepoint-Erkennung fuer Spruenge in Spannung / Frequenz
- Vergleichsprofile: Werktag vs. Wochenende vs. Feiertag
- Wochen- und Monatsberichte aus `nq_daily_summary`

### Stufe C — nur mit neuer Messtechnik

- Harmonische / THD
- Frequenzbaender oberhalb weniger Hz
- Transienten im Millisekundenbereich
- Supraharmonics / HF-Effekte von Leistungselektronik

## Empfehlung zum Collector

### Produktionsregel

**Den produktiven Collector nicht einfach auf kuerzeres Polling stellen.**

Begruendung:

- derselbe Poller liest bereits Inverter plus vier SmartMeter
- Single-Instance-Schutz ist bewusst eingebaut
- die Dokumentation warnt ausdruecklich vor Konkurrenz auf dem Modbus-Pfad
- `poll_once()` oeffnet pro Zyklus eine Verbindung, liest 5 Geraete sequenziell
  und schlaeft danach erneut `POLL_INTERVAL`

Ein aggressiveres Polling auf dem Primary kann:

- die Timing-Reserve des Collectors aufbrauchen
- Timeout-Risiko erhoehen
- Write-/Read-Kollisionen mit anderen Fronius-Funktionen verschaerfen
- im Fehlerfall genau die Produktionsstabilitaet beschaedigen, die geschuetzt
  werden soll

### Wenn kuerzeres Polling getestet werden soll

Dann nur als **isolierter Messversuch**, nicht sofort im produktiven Dauerbetrieb:

1. Nur `PRIM_SM_F1` lesen, nicht alle 5 Geraete.
2. Testfenster kurz halten, z. B. 10-30 Minuten.
3. Parallel `t_poll_ms`, Timeout-Rate und Datenluecken protokollieren.
4. Keine zweite Poller-Instanz auf demselben produktiven Pfad starten.
5. Erst nach belastbarem Benchmark ueber Produktivuebernahme entscheiden.

## Was die aktuelle Datenbasis bereits leisten kann

- DFD an den 15-Minuten-Grenzen
- Vollstunde vs. Viertelstunde
- lokale Lastspruenge und Rueckwirkung auf Spannungen
- Tages-/Wochenmuster von Netzfrequenz und Spannungsniveau
- Unsymmetrie der drei Leiterspannungen
- Ereignishaeufigkeit und Volatilitaet

## Was sie nicht leisten kann

- Harmonische des 50-Hz-Signals
- THD-konforme PQ-Analyse
- schnelle Inverter-Schaltmuster im kHz-Bereich
- Supraharmonics / HF-Stoerquellen
- forensische Aussagen ueber einzelne Halbwellen oder Schaltkanten

## Pflege-Regel

Dieses Dokument wird aktualisiert, wenn sich mindestens einer der folgenden
Punkte aendert:

- Polling-Frequenz oder Collector-Architektur
- verfuegbare NQ-Signale
- Analyse-Metriken in `nq_analysis.py`
- Entscheidung pro/contra neue Messtechnik