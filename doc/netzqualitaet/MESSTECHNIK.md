# Netzqualität — Messtechnik

**Stand:** 2026-04-19 · **Modul-Einordnung:** 2026-07-11

> Diese Datei sammelt die belastbaren **PAC4200-Messtechnik-Fakten**. Die daraus
> abgeleitete Modul-Architektur (Collector auf **Tech**, Aggregation/Analyse auf
> **Primary**, Rolle N) ist in [`NQ_MODUL.md`](NQ_MODUL.md) festgelegt.

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

## Verifizierte Registerkarte (Live-Messung 2026-07-11)

Gegen das reale Geraet (`192.0.2.111`, Modbus TCP) bestaetigt. Messwerte als
**FLOAT32** (big-endian, High-Word zuerst), gelesen ab **Modbus-Adresse 1**
(0-basierte Adresse 0 wird vom Geraet **nicht** beantwortet). Plausibilitaet
geprueft: U ~239 V, U_LL ~414 V, f = 50,02 Hz, THD-U ~1,2 %.

| Adresse | Groesse | Einheit |
|--:|---|---|
| 1 / 3 / 5 | U L1-N / L2-N / L3-N | V |
| 7 / 9 / 11 | U L1-L2 / L2-L3 / L3-L1 | V |
| 13 / 15 / 17 | I L1 / L2 / L3 (Betrag; Vorzeichen via P, s. u.) | A |
| 19 / 21 / 23 | S L1 / L2 / L3 | VA |
| 25 / 27 / 29 | P L1 / L2 / L3 | W |
| 31 / 33 / 35 | Q L1 / L2 / L3 | var |
| 37 / 39 / 41 | Leistungsfaktor (PF) L1 / L2 / L3 | — |
| 43 / 45 / 47 | THD-U **L-L** (L1-L2 / L2-L3 / L3-L1) | % |
| 49 / 51 / 53 | **undefiniert** (liefert NaN — hier liegt **kein** THD-I) | — |
| 55 | Frequenz | Hz |
| 57 / 59 / 61 | U Oe L-N / U Oe L-L / I Oe | V / V / A |
| 63 / 65 / 67 | S / P / Q gesamt | VA / W / var |
| 69 | Leistungsfaktor gesamt | — |
| 71 / 73 | Unsymmetrie U / I | % |
| 243 / 245 / 247 | cos φ (Grundschwingung) L1 / L2 / L3 | — |
| 261 / 263 / 265 | THD-U **L-N** je Phase L1 / L2 / L3 | % |
| 267 / 269 / 271 | **THD-I je Phase L1 / L2 / L3** (echte Lage) | % |
| 295 | Neutralleiterstrom I_N | A |

> **Korrektur 2026-07-11:** THD-U-Register 43/45/47 sind **L-L**, nicht L-N.
> Das echte **THD-I liegt bei 267/269/271** (live 38–45 %), nicht bei 49/51/53
> (die liefern NaN und sind undefiniert). Per-Phase-THD-U (L-N) steht bei
> 261/263/265. Grundlage: die vollstaendige Registerreferenz
> [`PAC4200-Modbus.md`](PAC4200-Modbus.md), gegen das reale Geraet bestaetigt.

Energiezaehler als **FLOAT64** (4 Register) ab Adresse **801** (Tarif 1 = aktiver Tarif):

| Adresse | Groesse | Einheit |
|---|---|---|
| 801 | Bezogene Wirkenergie T1 (`Wh_imp`) | Wh |
| 809 | Gelieferte Wirkenergie T1 (`Wh_exp`) | Wh |
| 817 | Bezogene Blindenergie T1 (`varh_imp`) | varh |
| 825 | Gelieferte Blindenergie T1 (`varh_exp`) | varh |
| 833 | Scheinenergie T1 (`VAh`) | VAh |

> **Korrektur 2026-07-12:** Die frueheren Adressen @805/809/813/817 waren
> falsch — @805 ist **Bezogene Wirkenergie T2** (Bezug Tarif 2), nicht Lieferung!
> Das Blockschema ist: alle Bezug-T1/T2 zuerst, dann alle Lieferung-T1/T2,
> dann alle Blind usw. (nicht abwechselnd Bezug/Lieferung). Deshalb stand
> `Wh_exp` (ehemals @805) immer auf 0 — es war der ungenutzten Tarif-2-Zaehler.
> `DOUBLE_READ_COUNT` auf 36 erhoehen (801..836, um @833 zu erreichen).
> Quelle: `doc/netzqualitaet/Modbus.md` A.3.6.

Code: [`../../nq/pac_live.py`](../../nq/pac_live.py) (`FLOAT_MAP`, `FLOAT2_MAP`, `DOUBLE_MAP`).
Read-only Live-Anzeige: `/pac4200` (Flow -> Maschinenraum -> PAC4200).
Vollstaendige Registerreferenz: [`PAC4200-Modbus.md`](PAC4200-Modbus.md).

### Vorzeichen der Stroeme (Zweirichtungszaehler, verifiziert 2026-07-11)

Der PAC4200 liefert die **RMS-Stroeme (Adr. 13/15/17) als vorzeichenlose
Betraege** — auch wenn eine Phase einspeist. Am PCC ist der Zaehler jedoch ein
**Zweirichtungszaehler**: die Stromrichtung ergibt sich aus dem **Vorzeichen der
Phasen-Wirkleistung** P (Adr. 25/27/29). Konvention im System:

- **P_Lx < 0** (Einspeisung/Lieferung) -> Strom der Phase wird **negativ** gefuehrt.
- **P_Lx >= 0** (Bezug) -> Strom positiv.
- Angezeigte **Stromsumme** = vorzeichenbehaftete Summe `Is_L1 + Is_L2 + Is_L3`
  (netzt Bezug gegen Einspeisung; ~0 A bei Erzeugung ≈ Verbrauch).

Der Register-Betrag bleibt als `I_Lx` erhalten; der vorzeichenbehaftete Wert
steht als `Is_Lx` (+ `Isum`) im Snapshot. Live verifiziert (z. B. `I_L3` mit
`P_L3 < 0` -> `-4,87 A`, `Isum` netzt korrekt). `Iavg` (Adr. 61) ist der
**vorzeichenlose** Geraetemittelwert und wird fuer die Richtungsanzeige nicht
verwendet. Code: `_build_screens` / Screen `Strom` in
[`../../nq/pac_live.py`](../../nq/pac_live.py).

### Gemessene Refresh-Raten (Phase-0-Kurzlauf, 250 ms-Polling)

- **RMS / Leistung / PF / THD-U:** aendern sich bei ~99 % der Reads -> interne
  Aktualisierung **<= 250 ms**. Fast-Block bei 500 ms unkritisch.
- **Frequenz (Adr. 55):** aendert sich nur ~alle **6–10 s** (dt_median 6,0–9,8 s
  je Lauf) -> dichteres Pollen liefert nur Wiederholwerte; Frequenz gehoert in
  einen langsamen Takt.
- **THD-I (Adr. 267–271):** liefert **echte Werte** (live 38–45 %, verifiziert
  2026-07-11). Die frueher genutzten Adressen 49–53 sind undefiniert (NaN) —
  Registerlage korrigiert (s. o.).
- **Einzelharmonische (ungerade H3..H31): per Modbus verfügbar (A.3.10)**
  — H1 (Grundschwingung) in V/A, H3..H31 als % der Grundschwingung. Drei
  Blöcke ohne Zeitstempel: U L-N @9001–@9095, Strom I @11001–@11095, U L-L
  @22001–@22095. Schrittformel: `base + ordinal*6 + phase_offset`
  (ordinal 0=H1, 1=H3, …, 15=H31). Adressen aus Betriebsanleitung
  Tab. A-17..A-19 (S. 240ff.); Endadressen @9095/@11095/@22095 bestätigt.

## Pflege-Regel

Dieses Dokument wird aktualisiert, wenn sich eine der folgenden PAC4200-
bezogenen Fragen belastbar klaert:

- verifizierte Registerliste fuer schnelle Betriebswerte
- verifizierte Registerliste fuer THD und Einzelharmonische
- gemessene Refresh-Zeiten des Geraets unter realem Polling

---

## Feldtest-Ergebnisse: PAC4200 Register-Refresh-Raten (2026-07-12)

**Methode:** `nq/fieldtest/pac_refresh_probe.py` und inline-Probe, Polling 250 ms
(Block A) bzw. 500 ms (Block B+C), je 5 Minuten, von Primary (192.0.2.204) direkt
auf PAC 192.0.2.111 (read-only, kein Speichern).

### Block A — FLOAT_MAP (Adr. 1..73), Polling 250 ms, 5 min, 1200 Polls

| Gruppe | Größen | Änderungsrate | dt_median |
|---|---|---|---|
| Phasenspannungen | U_L1N, U_L2N, U_L3N | 100 % | 0,25 s |
| Leiter-Leiter-Spannungen | U_L12, U_L23, U_L31 | 100 % | 0,25 s |
| Phasenströme | I_L1, I_L2, I_L3 | 100 % | 0,25 s |
| Scheinleistung | S_L1, S_L2, S_L3 | 100 % | 0,25 s |
| Wirkleistung | P_L1, P_L2, P_L3 | 100 % | 0,25 s |
| Blindleistung | Q_L1, Q_L2, Q_L3 | 100 % | 0,25 s |
| Leistungsfaktor | PF_L1, PF_L2, PF_L3 | 100 % | 0,25 s |
| THD-U L-L | THDu_L12, THDu_L23, THDu_L31 | 100 % | 0,25 s |
| Mittelwerte + Totale | Uavg_LN, Uavg_LL, Iavg, S_tot, P_tot, Q_tot, PF_tot | 100 % | 0,25 s |
| Unsymmetrie | Unbal_U, Unbal_I | 100 % | 0,25 s |
| **Frequenz** | **FREQ** | **2 %** | **10,00 s** |

**Fazit Block A:** Alle RMS-, Leistungs- und THD-LL-Werte aktualisieren sich
bei jedem 250-ms-Poll (~4 Hz intern). Frequenz aktualisiert intern **exakt alle
10 Sekunden** — 200-ms- oder 250-ms-Polling für FREQ ist sinnlos, 10-s-Intervall
reicht vollständig.

### Block B — FLOAT2_MAP (Adr. 243..295), Polling 500 ms, 5 min, 121 Reads

| Gruppe | Größen | Änderungsrate | dt_median |
|---|---|---|---|
| cos φ (Grundschwingung) | cosphi_L1, cosphi_L2, cosphi_L3 | 99 % | 0,50 s |
| Phasenwinkel | ang_L1, ang_L2, ang_L3 | 99 % | 0,50 s |
| THD-U L-N | THDu_L1, THDu_L2, THDu_L3 | 99 % | 0,50 s |
| THD-I | THDi_L1, THDi_L2, THDi_L3 | 99 % | 0,50 s |
| Verzerrungsstrom | Idist_L1, Idist_L2, Idist_L3 | 99 % | 0,50 s |
| Neutralleiterstrom | I_N | 99 % | 0,50 s |

**Fazit Block B:** Alle Werte ändern sich bei jedem 500-ms-Poll — das Gerät
aktualisiert Block B mindestens so schnell wie Block A (~250 ms intern). 500-ms-
oder 250-ms-Polling erfasst alle Messwertänderungen vollständig.

### Harmonik-Blöcke D/E/F — @9001 (UN), @11001 (I), @22001 (ULL), Polling 1 s, 1 min, 61 Polls

Einzelharmonische H1 (Grundschwingung, V/A) + H3..H31 (% der Grundschwingung),
je 3 Phasen, 3 Blöcke = 144 Werte gesamt. Repräsentant: L1-Kanal je Block.

| Block | Adressen | Änderungsrate | dt_median | Beispielwerte (L1) |
|---|---|---|---|---|
| UN (U L-N %) | @9001..@9096 | **98 %** | **1,0 s** | H1=237,4 V, H5=1,01 %, H7=0,72 %, H3=0,38 % |
| I (%) | @11001..@11096 | **98 %** | **1,0 s** | H1=2,26 A, H3=0,40 %, H5=0,39 %, H7=0,24 % |
| ULL (U L-L %) | @22001..@22096 | **98 %** | **1,0 s** | H1=411,3 V, H5=0,98 %, H7=0,66 %, H3=0,13 % |

**Fazit:** Harmonische aktualisieren intern mit **~1 Hz** — identisch zu Block B.
Das `slow_ms = 5000`-Polling erfasst jeden 5. Update; 1–2 s wäre optimal.
Kein Unterschied zwischen Spannungs- und Stromharmonischen in der Refresh-Rate.

### Block C — FLOAT3_MAP (Adr. 75..144, Max-Werte), Polling 500 ms, 5 min, 121 Reads

| Gruppe | Größen | Änderungsrate | dt_median |
|---|---|---|---|
| Umax L-N | Umax_L1N, Umax_L2N, Umax_L3N | **0 %** | — |
| Umax L-L | Umax_L12, Umax_L23, Umax_L31 | **0 %** | — |
| Imax | Imax_L1, Imax_L2, Imax_L3 | **0 %** | — |
| Pmax | Pmax_L1, Pmax_L2, Pmax_L3, Pmax_tot | **0 %** | — |
| Qmax, Smax | Qmax_tot, Smax_tot | **0 %** | — |
| FREQmax | FREQmax | **0 %** | — |

**Fazit Block C:** Max-Werte sind Geräte-interne historische Extremwerte und
ändern sich im normalen Betrieb nicht (nur bei neuem Extremum). Polling alle
60–300 s ist mehr als ausreichend. Für den Produktivbetrieb reicht 1×/Min oder
seltener.

### Empfohlene Polling-Gruppen (nach Feldtest, bestätigt 2026-07-12)

| Gruppe | Größen | Empfohlenes Polling | Feldtest-Befund |
|---|---|---|---|
| **Fast** | U_L1N–U_L31, I_L1–I_L3, P/Q/S je Phase+Total, PF, Unbal, THDu_LL (Block A) | **250–500 ms** | 100 % Änderungsrate bei 250 ms — Grenzrate des PAC |
| **Medium** | THDu_LN, THDi, cosphi, ang, Idist, I_N (Block B) | **500 ms – 1 s** | 99 % Änderungsrate bei 500 ms — gleiche interne Rate wie Block A |
| **FREQ** | FREQ (Block A, Adr. 55) | **10 s** | Exakt 10-s-Refresh intern; 2 % Änderungsrate bei 250 ms — alles schnellere ist Redundanz |
| **Max-Werte** | Umax, Imax, Pmax, FREQmax (Block C, Adr. 75–144) | **60–300 s** | 0 % Änderungsrate in 5 min Normalsbetrieb — nur bei neuem Extremum |
| **Einzelharmonische** | H3..H31 U/I (A.3.10, @9001/@11001/@22001) | **1–2 s** | **98 % Änderungsrate bei 1 s** — gleiche interne Rate wie Block B; `slow_ms=5000` konservativ korrekt |
| **Energiezähler** | wh_imp, wh_exp, varh_*, vah (Adr. 801–817 FLOAT64) | **60 s** | kumulativ, Differenzmethode |

> **Konfiguration in `config/nq_config.json`:**  
> `fast_ms=500` (Block A+B gemeinsam), `slow_ms=5000` (Harmonische — konservativ
> korrekt, Refresh ~1 s, erfasst jeden 5. Update), `energy_s=60`.  
> FREQ wird im Fast-Snapshot mitgelesen; der 10-s-Aggregator (`nq_agg_10s`)
> glättet die Redundanz (min/avg/max über identische FREQ-Werte → korrekter Mittelwert).
- bewaehrter Polling-Zyklus fuer den produktiven Einsatz am PCC