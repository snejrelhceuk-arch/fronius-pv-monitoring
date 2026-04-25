# Netzqualität — Messtechnik

**Stand:** 2026-04-19

## Ausgangslage

Aktuell stammt die Netzqualitaetsbeobachtung aus dem **Primaer-SmartMeter am
Netzanschlusspunkt**:

- Quelle: `PRIM_SM_F1` (Unit 2)
- Zugriff: ueber denselben produktiven Fronius-Modbus-Pfad wie der Collector
- Polling: 3s
- Messgroessen: RMS-Spannungen, Stroeme, Leistung, Leistungsfaktor, Frequenz

Die vorhandenen weiteren SmartMeter haben **andere Aufgaben**:

- `SEC_SM_F2` misst Wechselrichter F2
- `SEC_SM_F3` misst Wechselrichter F3
- `SEC_SM_WP` misst die Waermepumpe

## Wichtige Feststellung

**Von den vorhandenen SmartMetern eignet sich keines als dedizierter
Netzqualitaetssensor ausser dem Primaer-SmartMeter am PCC.**

Die Unterzähler F2/F3/WP sehen nur Teilströme einzelner Abgaenge. Sie koennen
fuer lokale Korrelationen hilfreich sein, aber **nicht** fuer die systemweite
Netzqualitaet am Netzanschlusspunkt.

Wenn Netzqualitaet kuenftig **entkoppelt vom Produktiv-Collector** gelesen werden
soll, braucht es daher **ein zusaetzliches Messgeraet am PCC**, nicht die
Umwidmung eines vorhandenen Unterzaehlers.

## PAC4200 am PCC

Der aktuelle Fokus liegt ausschliesslich auf dem **Siemens SENTRON PAC4200** am
Netzanschlusspunkt. Fruehere Vergleiche mit anderen PQ-Metern oder
Alternativpfaden sind hier bewusst entfernt, damit die Doku nur noch die fuer
dieses Geraet belastbaren Aussagen enthaelt.

## Belastbare PAC4200-Fakten

- Das Geraet ist ein **Power-Quality-/Harmonik-Meter**, kein Rohdatenrecorder.
- Siemens beschreibt **Harmonische 2. bis 64. Ordnung** sowie **THD**.
- Die Messkette ist fuer **TRMS** und fuer sinusfoermige wie verzerrte
  Signale ausgelegt.
- Die oeffentlich greifbare Produktbeschreibung nennt **Modbus TCP** sowie
  optionale Kommunikationsmodule.
- Die oeffentlich greifbare Produktbeschreibung nennt **Class 0.2** bzw.
  **0.2S** im passenden Einsatzzusammenhang.

## Was der PAC4200 sehr wahrscheinlich nicht liefert

- keinen frei zugreifbaren kontinuierlichen Rohdatenstrom der Strom- oder
  Spannungswellenform
- keine fuer externe FFT frei verarbeitbare Samplefolge im Sinne eines
  Oszilloskops oder Recorders
- keine belastbar oeffentlich dokumentierte interne Samplefrequenz
- keine belastbar oeffentlich dokumentierte Angabe, nach wie vielen Netzzyklen
  RMS-, THD- oder Harmonikwerte per Register aktualisiert werden

## Was fuer Harmonische praktisch zu erwarten ist

- Die **61. Harmonische** ist fachlich noch im angegebenen Spektrum bis zur
  64. Ordnung enthalten.
- Falls Siemens diese Groesse per Modbus herausgibt, dann als **intern
  berechneter Ordnungswert** und nicht als Rohsignal.
- **THD** ist dann die verdichtete Summenkennzahl ueber mehrere
  Einzelharmonische.
- Fuer die praktische Integration ist deshalb zwischen **schnellen
  Betriebswerten** und **langsameren Spektralwerten** zu unterscheiden.

## Interne Aktualisierung: was belegt ist und was nicht

Oeffentlich belastbar belegt sind derzeit nur die Funktionsangaben, nicht die
genaue interne Refresh-Logik.

Nicht belastbar oeffentlich verifiziert sind aktuell:

- internes FFT-Fenster
- interne Mittelungsdauer fuer THD
- Register-Refresh fuer Einzelharmonische
- Puffertiefe oder Zwischenspeicher fuer kurzzeitige Spektralwerte
- genaue Trennung zwischen schnell aktualisierten und langsamer aktualisierten
  Registergruppen

Fuer die Projektplanung bedeutet das: Die erreichbare Datendichte wird nicht vom
Ethernet begrenzt, sondern primaer davon, **wie oft der PAC4200 seine internen
Kennwerte wirklich neu berechnet und in die Register schreibt**.

## Sinnvolle Registerbloecke fuer den PAC4200

### Schneller Block

Diese Werte sind die naheliegendsten Kandidaten fuer dichteres Polling:

- Spannungen je Phase
- Stroeme je Phase
- Wirk-, Blind- und Scheinleistung
- Leistungsfaktor
- Frequenz

### Mittlerer Block

Diese Werte sind fachlich interessant, duerften aber typischerweise nicht so
schnell sinnvoll erneuert werden wie reine RMS-/Leistungswerte:

- THD Spannung je Phase
- THD Strom je Phase
- Unsymmetrie- oder aehnliche PQ-Kennwerte, falls verfuegbar

### Langsamer Block

Diese Werte sind volumenstark und sollten getrennt behandelt werden:

- Einzelharmonische 2. bis 64. Ordnung fuer Spannung
- Einzelharmonische 2. bis 64. Ordnung fuer Strom
- langsamere Zaehler-, Demand-, Min-/Max- oder Diagnosewerte

## Praktische Polling-Einordnung fuer den PAC4200

Solange keine belastbare Siemens-Doku zur internen Refresh-Logik vorliegt,
sollte das Polling konservativ und blockweise aufgebaut werden.

- **500 ms** ist ein plausibler Startwert fuer schnelle RMS- und
  Leistungswerte.
- **1 s** ist ein plausibler Startwert fuer THD-Werte.
- **1 bis 5 s** ist ein plausibler Startwert fuer volle Harmonikbloecke.
- **200 ms** kann als Kurzbenchmark sinnvoll sein, ist aber ohne Geraetetest
  kein guter Default.
- Alles deutlich schneller als **200 ms** hat ein hohes Risiko, vor allem nur
  dieselben intern noch nicht erneuerten Werte mehrfach zu lesen.

## Datendichte: was praktisch erreichbar wirkt

Wenn nur ein schneller Betriebswerte-Block gelesen wird:

- **1 s** Polling entspricht **3600 Zeitpunkten pro Stunde**
- **500 ms** Polling entspricht **7200 Zeitpunkten pro Stunde**
- **200 ms** Polling entspricht **18000 Zeitpunkten pro Stunde**

Wenn zusaetzlich das volle Harmonikbild gespeichert wird, steigt die Datenmenge
stark an.

- Ordnungen **2 bis 64** ergeben **63 Harmonikwerte** pro Groessenart
- bei **3 Phasen** und getrennt fuer **Spannung und Strom** sind das
  **378 Einzelwerte pro Snapshot**
- bei **1 Hz** waeren das bereits **1 360 800 Harmonikwerte pro Stunde**

Die Engstelle ist damit weniger das Netzwerk als vielmehr:

- Datenbankschreibrate
- Verdichtung und Aggregation
- Abfragekosten in API und UI
- die offene Frage, wie oft der PAC4200 diese Spektralwerte intern real neu
  erzeugt

## Klare Projektempfehlung fuer den PAC4200

- schnelle Betriebswerte von spektralen Werten trennen
- THD und Einzelharmonische nicht im selben engen Zyklus pollen wie RMS-Werte
- volle Harmonikregister nur dann dicht lesen, wenn ein klarer Analysebedarf
  besteht
- zunaechst per Benchmark pruefen, ab welcher Pollrate Werte real wechseln statt
  nur erneut gelesen zu werden

## Stromwandler-Hinweis fuer den PAC4200

Fuer den PAC4200 am PCC bleiben **Messstromwandler der Klasse 0.2S** fachlich
passend, wenn die Genauigkeit auch bei kleineren Stroemen sauber bleiben soll.

Fuer die konkrete Beschaffung im Projekt ist bereits ein **150/5A 0,2S**-
Wandler gesetzt. Das ist fuer die PAC4200-Doku hier ausreichend; weitere
Produktvergleiche werden bewusst nicht mehr gefuehrt.

## Pflege-Regel

Dieses Dokument wird aktualisiert, wenn sich eine der folgenden PAC4200-
bezogenen Fragen belastbar klaert:

- verifizierte Registerliste fuer schnelle Betriebswerte
- verifizierte Registerliste fuer THD und Einzelharmonische
- gemessene Refresh-Zeiten des Geraets unter realem Polling
- bewaehrter Polling-Zyklus fuer den produktiven Einsatz am PCC