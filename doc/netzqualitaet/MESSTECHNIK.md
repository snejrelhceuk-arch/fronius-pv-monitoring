# Netzqualität — Messtechnik

**Stand:** 2026-04-02

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

## Soll man in den Collector eingreifen?

### Empfehlung

**Nicht als ersten Schritt.**

Der produktive Collector:

- pollt bereits Inverter + 4 SmartMeter
- ist bewusst als Single Instance abgesichert
- soll den Modbus-Pfad fuer den regulaeren Anlagenbetrieb nicht stoeren

Ein kuerzeres Polling im Produktivpfad ist deshalb nur vertretbar, wenn ein
kurzer, isolierter Benchmark zeigt, dass:

- die Poll-Zeiten stabil bleiben
- keine Read-Timeouts zunehmen
- keine Datenluecken entstehen
- keine Seiteneffekte fuer den restlichen Anlagenbetrieb auftreten

### Empfohlene Testreihenfolge

1. **Bestehende 3s-Daten maximal auswerten**.
2. Falls weiter noetig: kurzer Benchmark, der **nur das Netz-SmartMeter** liest.
3. Erst danach ueber Produktiv-Aenderung entscheiden.
4. Falls NQ dauerhaft dichter sampeln soll: **eigenen NQ-Messpfad** aufbauen.

## 1 kHz: sinnvoll oder nicht?

### Sinnvoll fuer

- Grundschwingung 50 Hz mit guter zeitlicher Aufloesung
- niedrige Harmonische bis grob einige hundert Hz
- THD-nahe Auswertungen
- schnellere lokale Spannungs- und Stromspruenge

### Nicht ausreichend fuer

- echte Breitbandanalyse im kHz-Bereich
- Supraharmonics
- HF-Stoerungen von Inverter-, Wallbox- oder Schaltnetzteil-Schaltvorgaengen

### Urteil

**1 kHz ist sinnvoll, wenn die Frage lautet:**

- Wie sehen niedrige Harmonische aus?
- Gibt es im Bereich bis einige hundert Hz erkennbare Muster?
- Wie verhaelt sich die 50-Hz-Groesse kurzfristig?

**1 kHz ist nicht ausreichend, wenn die Frage lautet:**

- Was passiert im Bereich mehrerer kHz bis 100 kHz?
- Welche Leistungselektronik erzeugt welche HF-Struktur?

## Was kommt vom europaeischen Netz wirklich bei uns an?

### Kommt klar durch

- Netzfrequenz und ihre langsamen Abweichungen
- grossraeumige Fahrplan- und Regelleistungs-Effekte
- langsame Spannungsniveau-Verschiebungen

### Kommt gemischt an

- niedrige Oberschwingungen
- Spannungsunsymmetrien und Lastmuster

### Ist meist lokal oder regional gepraegt

- schnellere Schaltmuster von Leistungselektronik
- kHz-Anteile und Supraharmonics
- Stoerspektren einzelner lokaler Verbraucher oder Umrichter

## HW-Matrix

| Klasse | Beispiel | Staerken | Schwaechen | Integrationsaufwand | Urteil |
|--------|----------|----------|------------|----------------------|--------|
| Zusatz-SmartMeter im Fronius-System | Fronius Smart Meter TS 65A-3 | gleiche Semantik, bekannte Register, minimale Software-Reibung | bleibt RMS-/Zaehlerwelt, keine echte PQ-/HF-Analyse | niedrig | bester Fit fuer eng integriertes RMS-NQ |
| Fremdes Modbus-Energie-/PQ-Meter | z. B. Janitza UMG, Siemens PAC, Schneider PowerLogic | teils deutlich mehr PQ-Funktionen, teilweise Harmonische/THD direkt im Geraet | neue Registerwelt, neues Mapping, evtl. Lizenz-/Doku-Aufwand | mittel bis hoch | sinnvoll, wenn Fronius fachlich zu klein wird |
| Dedizierter PQ-Analyzer | portable/stationaere PQ-Messgeraete | fachlich am staerksten fuer Netzqualitaet, oft fertige Norm-Metriken | teuer, schwerer in Dauerbetrieb/API zu integrieren | hoch | richtig fuer echte PQ-Kampagnen |
| Eigene DAQ-/ADC-Messtechnik | DIY bis 1 MHz | maximale Freiheit, Bandbreite, eigene Pipeline | hoechster Entwicklungs- und Sicherheitsaufwand | sehr hoch | stark fuer Forschungsprojekt, nicht fuer schnellen Produktivgewinn |

## Vergleich konkreter PQ-Meter

**Hinweis:** Fuer die Bezeichnung **Siemens PAC3400** liess sich in der aktuell
greifbaren Siemens-Dokumentation kein belastbarer Produktdatensatz verifizieren.
Als fachlich naechster, heute klar verifizierbarer Siemens-Kandidat ist deshalb
unten der **SENTRON PAC4200** aufgefuehrt.

| Geraet | PQ-/Oberwellen-Funktionen | Max. Harmonikordnung | Entspricht bei 50 Hz | Interne Aufloesung / Abtast-Hinweis | Speicher / Logging | Aussage fuer hoeherfrequente Themen | Kurzurteil |
|--------|---------------------------|----------------------|----------------------|-------------------------------------|-------------------|--------------------------------------|------------|
| Schneider PowerLogic PM5560 | THD, 63rd Harmonic, Logging, Min/Max, Alarm-/Event-Logs | bis 63. Harmonische | ca. 3,15 kHz | 128 samples/cycle | 1,1 MB, Daten-/Alarm-/Event-Logs | stark fuer niedrige Harmonische und saubere PQ-Kennwerte; keine echte HF-/Rohwellenform-Messtechnik | sehr guter Zwischenpunkt zwischen Fronius-SM und echtem PQ-Analyzer |
| Janitza UMG 96RM-E | THD-U / THD-I, Harmonische, RCM, umfangreiche PQ-Kennwerte | bis 40. Harmonische | ca. 2,00 kHz | Hersteller bewirbt PQ-Analyse; offene Rohabtastung nicht der Fokus | 256 MB Messdatenspeicher | gut fuer dauerhafte Beobachtung von Oberschwingungen; fuer kHz/HF weiter klar begrenzt | fachlich stark fuer fest eingebauten PQ-Sensor |
| Siemens SENTRON PAC4200 | THD, Harmonische, Class-0.2/0.2S, Ethernet/Modbus/Optionen | bis 64. Harmonische | ca. 3,20 kHz | Herstellerangabe im Produkttext fokussiert Harmonik-Metriken, nicht Rohsignalzugriff | Logging-/Integrationsklasse, aber nicht als Breitbandrecorder positioniert | im niedrigen kHz-Bereich besser als klassische RMS-Meter; fuer HF weiter keine Endloesung | sinnvoller Siemens-Vergleichskandidat, wenn Modbus-/Industrieintegration wichtig ist |

### Einordnung fuer HF-Fokus

- Alle drei Geraete bleiben **Power-Quality-/Harmonik-Meter**, nicht
  Breitband-Messgeraete.
- Auch die staerkeren Kandidaten enden fachlich grob in der Welt von
  **50 Hz, THD, Unsymmetrie und niedrigen kHz-Anteilen**.
- **Supraharmonics, schnelle Schaltflanken und echte HF-Strukturen** bekommt man
  damit nicht als frei verarbeitbaren Rohdatenstrom.
- Wenn das Projektziel spaeter klar Richtung **Wellenformanalyse > einige kHz**
  kippt, ist ein **separater DAQ-/ADC-Messpfad** zukunftsfaehiger als ein
  weiterer fest eingebauter Panel-Meter.

## Breit verfuegbare CT-Familien fuer PAC4200 am PCC

- Fuer den **PAC4200 am PCC** sind **Messstromwandler der Klassen 0.5S oder
  0.2S** sinnvoller als einfache Installationswandler der Klasse 1.
- Die **S-Klassen** sind besonders interessant, wenn auch bei kleineren Stroemen
  noch brauchbare Genauigkeit erhalten bleiben soll.
- Bei industrieller Serienware ist **5 A** meist am einfachsten zu beschaffen;
  **1 A** ist ebenfalls sinnvoll, aber haeufiger bei spezialisierten Serien oder
  konfigurierbaren Wandlerfamilien zu finden.
- Fuer **THD-/Harmonikbeobachtung** sollte die Bemessungsleistung nicht zu klein
  gewaehlt werden; praktisch sind **1 VA bis 5 VA** deutlich angenehmer als sehr
  knappe 0,2-VA-Wandler.

| Hersteller / Familie | Typische Klassen | Sekundaer | Einordnung fuer Verfuegbarkeit | Eignung fuer unser Projekt |
|----------------------|------------------|-----------|--------------------------------|----------------------------|
| Siemens 4NC5... Niederspannungs-Stromwandler | 0.5, 0.5S, 0.2S je nach Baureihe | meist 5 A | sehr breite Industrieverbreitung, gut ueber Siemens-/Schaltanlagenkanal und Grosshandel verfuegbar | guter konservativer Standard, wenn robuste klassische 5-A-Kette gewuenscht ist |
| Schneider Electric PowerLogic / METSECT5... | 0.5, 0.5S, teils 0.2 / 0.2S je nach Serie | meist 5 A | hohe Marktverbreitung im PowerLogic-Umfeld, gute Ersatzteil- und Distributorlage | stark, wenn ohnehin Schneider-/PowerLogic-Naehe gewuenscht ist |
| Janitza Steck-/Aufsteck- und Tarifwandler | 0.5, 0.5S, 0.2S je nach Typ | 5 A, teils auch 1 A | in PQ-/Energiemonitoring-Projekten sehr gaengig, in Europa gut beschaffbar | fachlich sehr passend, besonders wenn niedrige Lastbereiche sauber mit abgedeckt werden sollen |
| MBS AG ASK / CTB / aehnliche LV-Messwandler | 0.5, 0.5S, 0.2, 0.2S | 5 A oder 1 A | sehr hohe OEM-/Schaltschrank-Verbreitung, grosse Typenbreite, oft der pragmatischste Beschaffungspfad | einer der besten Kandidaten fuer PAC4200 am PCC, wenn gezielt nach Klasse und Bauform ausgewaehlt wird |
| CHINT BH-0.66I / BH-I | 0.5S, 0.2S je nach Kern-/Typvariante | meist 5 A | global hohe Stueckzahlen und breite Verbreitung im Schaltanlagenmarkt, oft preislich attraktiv | gute Budget-Option, wenn konkrete Datenblaetter und Qualitaet des Lieferkanals sauber geprueft werden |

### Praktische Auswahlregel

- **Wenn Verfuegbarkeit und Industrie-Standard wichtiger sind als Feinoptimierung:**
  Siemens 4NC5 oder Schneider METSECT5.
- **Wenn 1-A-/5-A-Flexibilitaet und metrologische Auswahl wichtiger sind:**
  MBS AG oder Janitza.
- **Wenn eher preisbewusst, aber trotzdem nicht Klasse 1 gewuenscht ist:**
  CHINT BH-0.66I nur mit sauberem Datenblatt und serioesem Lieferkanal.
- **Split-Core** nur dann, wenn Nachruestung ohne Leitungsauftrennung zwingend
  ist; fuer den PCC sind **geschlossene Messstromwandler** fachlich die bessere
  Dauerloesung.

## Im System bleiben oder bewusst herausgehen?

### Fuer das System bleiben spricht

- vorhandene Feldnamen und Semantik sind bereits im Projekt etabliert
- `raw_data`, NQ-Export, Analyse-DB und API existieren schon
- die UI ist bereits im Maschinenraum verankert
- Fronius-SmartMeter sind fuer RMS-, Frequenz- und Lastmuster voll ausreichend

### Gegen reines Fronius-Festhalten spricht

- Fronius ist kein spezialisiertes PQ-System
- fuer Harmonische, THD, Transienten und HF endet die Aussagekraft schnell
- wenn kuenftig echte Oberschwingungs- oder Breitbandanalyse gewollt ist,
  kommen spezialisierte Fremdgeraete oder DIY-Messtechnik fachlich weiter

### Projektentscheidung aktuell

**Fuer die naechste Ausbaustufe ist es besser, im bestehenden System zu
bleiben.**

Begruendung:

- die bestehenden Software-Tools sind fuer RMS-/Trend-/DFD-Analyse bereits
  umfangreich genug
- die Integrationskosten eines fremden Geraets waeren sofort real, der
  fachliche Mehrwert aber erst dann gross, wenn die Fragestellung ueber RMS und
  langsame Zeitreihen hinausgeht
- fuer das Maschinenraum-Konzept ist ein integrierter API-/UI-Pfad im
  Gesamtsystem sinnvoll

**Sobald die Frage aber Richtung Harmonische / THD / HF kippt, gilt diese
Praemisse nicht mehr.** Dann ist fachlich nicht mehr "im Fronius-System
bleiben" entscheidend, sondern ein geeignetes Messmittel.

### Option A — zweites SmartMeter am PCC

**Ziel:** dichteres RMS-/Leistungsmonitoring, aber weiterhin im klassischen
Energiezaehler-/SunSpec-Denken.

Geeignet, wenn gefragt wird:

- mehr zeitliche Dichte als 3s
- getrennte NQ-Erfassung ohne Belastung des produktiven Collectors
- saubere Parallelbeobachtung am Netzanschlusspunkt

Pragmatische Kandidatenklasse:

- **zusaetzlicher Fronius Smart Meter TS 65A-3** am PCC, aber auf einem
  **eigenen Lesepfad** und nicht ueber denselben produktiven Collector-Zyklus

**Grenze:** auch damit bekommt man keine echte Breitbandanalyse.

### Option B — dedizierte PQ-/DAQ-Messtechnik

**Ziel:** Harmonische, Transienten, spaeter kHz-Baender.

Geeignet, wenn gefragt wird:

- THD / Harmonische
- Wellenform statt RMS
- spaeter HF und Supraharmonics

Das ist die sauberere Richtung, sobald die Forschungsfrage ueber RMS-Verhalten
hinausgeht.

## Empfehlung zur Geraeteklasse

### Kurzfristig

- wenn ein entkoppelter RMS-Sensor gebraucht wird: **zweites SmartMeter am PCC**
- Fronius bleibt hier wegen Integrationsvorteil der naheliegende erste Schritt

### Mittelfristig

- wenn harmonische Kennwerte oder THD im Vordergrund stehen: **fremdes PQ-Meter
  oder PQ-Analyzer** prioisieren statt noch mehr in die Fronius-Kette zu
  investieren

### Langfristig / Forschung

- fuer breite Spektren und eigene Methoden: **DIY-Messtechnik** mit sauberem
  Front-End und klarer Sicherheitsarchitektur

## DIY bis 1 MHz

## Konkrete Produktkandidaten fuer die Shunt-Architektur

**Ziel dieser Liste:** keine vollstaendige Stueckliste, sondern eine belastbare
**Beobachtungsliste fuer Neu- und Gebrauchtmarkt**. Sie soll helfen, ueber
Monate gezielt nach brauchbaren Produktfamilien Ausschau zu halten.

**Wichtiger Sicherheitshinweis:** Die folgenden Bauteile sind als technische
Kandidaten fuer einen getrennten Forschungs-/Messpfad gedacht. Das ist **keine
freizugebende Netzbaugruppe** fuer unmittelbaren Dauerbetrieb am offenen
Netzanschlusspunkt ohne saubere Schutz-, Isolations- und Gehaeuseauslegung.

### 1. Stromshunt

Fuer die saubere Variante sind **geschraubte Praezisionsshunts mit Kelvin-
Abgriff** interessanter als billige Amperemeter-Shunts aus dem Bastelmarkt.

| Produktfamilie / Beispiel | Typischer Einsatz | Preis grob | Beschaffungsbild | Urteil |
|---------------------------|-------------------|-------------|------------------|--------|
| **Bourns / Riedon RS-, RSN-, RSW-Serie** z. B. `RSN-50-100B-S` | klassische Praezisions-DC-Shunts, geschraubt, gut dokumentiert | ca. 25 bis 80 EUR pro Stueck, je nach Bereich und Genauigkeit | gut ueber Mouser, DigiKey, Newark; teils auch eBay / Restposten | sehr guter Beobachtungskandidat fuer einen sauberen Prototyp |
| **Isabellenhuette Busbar-/Current-Sense-Familien** | hochwertigere Shunt- und Stromsensor-Familien aus Industrie-/Automotive-Umfeld | oft eher 30 bis 120 EUR pro Stueck, teils mehr | eher Distributoren als Gebrauchtmarkt; gebraucht seltener, aber qualitativ stark | technisch stark, kaufmaennisch eher die Premium-Schiene |
| **einfache 50A/75mV- oder 50A/100mV-Shunts** aus Panel-Meter-Umfeld | frueher PoC, Vergleichsaufbau, nicht die saubere Endloesung | ca. 8 bis 20 EUR pro Stueck | sehr haeufig bei eBay, Amazon, Aliexpress | nur fuer fruehe Versuche, nicht fuer maximale Sauberkeit |

**Beobachtungsempfehlung:**

- Fuer den Langfristpfad zuerst nach **Bourns/Riedon RSN** und nach
  **Isabellenhuette** schauen.
- Billig-Shunts nur kaufen, wenn bewusst ein frueher Laboraufbau gemeint ist.

### 2. Isolierte Strommessung am Shunt

Fuer die galvanische Trennung pro Phase sind **isolierte Sigma-Delta-
Modulatoren** der robusteste Suchpfad.

| Produkt / Familie | Funktion | Preis grob | Beschaffungsbild | Urteil |
|-------------------|----------|-------------|------------------|--------|
| **TI AMC1306M25** | isolierter Sigma-Delta-Modulator fuer kleine Shuntspannungen, ±250 mV | ca. 6 bis 12 EUR pro IC | sehr gut ueber Mouser, DigiKey, TI-Distributoren | mein bevorzugter Standardkandidat |
| **TI AMC1305 / AMC3330-Familie** | aehnliche Klasse; je nach Variante andere Integrationstiefe | ca. 5 bis 15 EUR pro IC | sehr gut verfuegbar | sinnvoll als Alternativpfad, falls AMC1306 knapp ist |
| **Avago / Broadcom ACPL-C87x-Familie** | isolierte Praezisionsverstaerker | grob 8 bis 18 EUR pro IC | weiterhin gut ueber Distributoren, teils Altbestand | brauchbar, aber ich wuerde fuer das Projekt eher bei TI bleiben |

**Beobachtungsempfehlung:**

- Direkt nach **AMC1306M25** suchen.
- Bei gebrauchten Elektronikposten lohnt sich eher das Suchen nach
  **Eval-Boards** als nach losen ICs.

### 3. Isolierte Hilfsversorgungen pro Messpfad

Jeder isolierte Analogeingang braucht praktisch eine kleine getrennte
Versorgung. Hier lohnen sich Standard-DC/DC-Module.

| Produkt / Familie | Funktion | Preis grob | Beschaffungsbild | Urteil |
|-------------------|----------|-------------|------------------|--------|
| **Murata NME0505SC** | 5V-zu-5V, 1 W, isoliert | ca. 8 bis 15 EUR pro Modul | sehr gut ueber DigiKey, Mouser, Arrow; teils eBay | sehr brauchbarer Industriestandard |
| **RECOM R1SX-0505-R** | 5V-zu-5V, 1 W, isoliert | ca. 7 bis 14 EUR pro Modul | sehr gut ueber Distributoren; auch bei Restpostenhaendlern | gleichwertig guter Kandidat |
| **billige B0505S-Module** | 5V-zu-5V-Bastelmodul | ca. 1 bis 4 EUR pro Modul | ueberall verfuegbar | fuer maximale Sauberkeit nicht erste Wahl |

**Beobachtungsempfehlung:**

- Langfristig nach **Murata NME0505SC** oder **RECOM R1SX-0505** schauen.
- Die ganz billigen SIP-Module nur als Laborprobe sehen.

### 4. Mehrkanal-ADC / sichere Datenerfassung

Wenn Strom- und Spannungskanaele auf der sicheren Seite zusammenlaufen sollen,
ist ein simultan abtastender Mehrkanal-ADC die sauberste Loesung.

| Produkt / Familie | Funktion | Preis grob | Beschaffungsbild | Urteil |
|-------------------|----------|-------------|------------------|--------|
| **TI ADS131M08** | 8-kanaliger simultaner 24-bit-Delta-Sigma-ADC | ca. 15 bis 30 EUR pro IC | sehr gut ueber Mouser, DigiKey, TI | sehr guter Kernbaustein fuer 3I + 3U + Reserve |
| **TI ADS131E08 / ADS131A04-Familie** | aehnliche Energie-/Metrologie-ADC-Klasse | grob 12 bis 30 EUR | gut ueber Distributoren | gute Alternativen, wenn Verfuegbarkeit oder Layout es erfordert |
| **fertige ADC-Eval-Boards** | schnellster Prototypweg | oft 80 bis 250 EUR pro Board | eher neu als gebraucht, teils Restposten | schnell, aber teurer |

**Beobachtungsempfehlung:**

- Fuer die Endrichtung zuerst **ADS131M08** beobachten.
- Falls irgendwo guenstig ein **ADS131M08EVM** oder aehnliches Eval-Board
  auftaucht, kann das fuer einen fruehen Aufbau kaufmaennisch sinnvoll sein.

### 5. Controller und Logger

Fuer harte Erfassung und fuer komfortable Speicherung sind **MCU** und
**Rechner** sinnvoll getrennt.

| Produkt / Familie | Rolle | Preis grob | Beschaffungsbild | Urteil |
|-------------------|------|-------------|------------------|--------|
| **STM32 Nucleo H7** z. B. `NUCLEO-H753ZI` | Echtzeit-Erfassung / SPI / Vorverarbeitung | ca. 35 bis 70 EUR | neu gut verfuegbar; gebraucht seltener, aber moeglich | sehr vernuenftiger MCU-Kandidat |
| **Raspberry Pi 5 8 GB** | Logger, Netzwerk, Datenpersistenz, Web/API-nahe Nutzung | ca. 100 bis 130 EUR fuer das Board | starke Verfuegbarkeit, gebraucht zunehmend realistisch | der pragmatischste Rechner |
| **Raspberry Pi 5 Netzteil + Active Cooler + Gehaeuse** | notwendiges Zubehoer fuer Dauerlast | grob 30 bis 60 EUR zusaetzlich | sehr gut verfuegbar | fuer Dauerbetrieb direkt mit einplanen |
| **kleiner Intel NUC / Thin Client gebraucht** | Alternative zum Pi fuer Logger/DB | ca. 80 bis 180 EUR gebraucht | auf eBay und Kleinanzeigen oft gut | interessant, wenn x86 bewusst gewuenscht ist |

**Beobachtungsempfehlung:**

- Wenn du langfristig auf Preis achten willst, lohnt sich das Beobachten von
  **Raspberry Pi 5 8 GB**, aber auch von **gebrauchten Thin Clients / NUCs**.
- Der eigentliche Messaufbau wird durch den Rechner **nicht** billig oder teuer;
  die Analog- und Isolationsseite bleibt der Kostentreiber.

### 6. DIN-Netzteil fuer den Gesamtkasten

| Produkt / Familie | Funktion | Preis grob | Beschaffungsbild | Urteil |
|-------------------|----------|-------------|------------------|--------|
| **Mean Well HDR-30-5** | Hutschienen-AC/DC-Netzteil 5 V | ca. 20 bis 35 EUR | sehr gut ueber Distributoren, teils gebraucht | sehr guter Standardkandidat |
| **Mean Well HDR-60-5** | mehr Reserve fuer Pi + Elektronik | ca. 30 bis 50 EUR | ebenfalls gut verfuegbar | sinnvoll, wenn mehr Reserven geplant sind |
| **Phoenix Contact / Weidmuller DIN-PSU gebraucht** | industrieller Alternativpfad | gebraucht sehr unterschiedlich, oft 25 bis 80 EUR | guter Gebrauchtmarkt | kaufmaennisch interessant, technisch solide |

### 7. Wofuer sich der Gebrauchtmarkt wirklich lohnt

**Gut beobachtbar gebraucht:**

- Raspberry Pi 4 / 5
- Intel NUC / Thin Clients
- Hutschienen-Netzteile von Mean Well, Phoenix Contact, Weidmuller
- Gehaeuse, Kleinverteiler, Klemmenmaterial
- Eval-Boards oder Restposten von Nucleo-/ADC-Boards

**Eher neu kaufen:**

- isolierte Modulator-ICs
- neue isolierte DC/DC-Wandler
- saubere Praezisionsshunts fuer die Endloesung

### Praktische Kaufstrategie fuer dieses Projekt

Wenn das Ziel **maximal sauber, aber ueber Zeit opportunistisch beschafft** ist,
waere meine persoenliche Reihenfolge:

1. **Rechner-/Logger-Seite gebraucht oder guenstig sichern**:
   Raspberry Pi 5 oder kleiner x86-Rechner.
2. **DIN-Netzteil und Gehaeusematerial** opportunistisch gebraucht mitnehmen.
3. **Shunts nur dann kaufen, wenn ein wirklich guter Typ auftaucht**:
   bevorzugt Bourns/Riedon oder Isabellenhuette.
4. **Modulatoren und DC/DC-Module eher neu und einheitlich beschaffen**,
   damit die Analogkette konsistent bleibt.
5. **ADC-/MCU-Plattform** entweder als guenstiges Eval-Board oder sauber neu.

### Meine konkrete Beobachtungsliste ab heute

- **Shunt:** Bourns / Riedon `RSN-50-100B-S` und benachbarte RSN-/RSW-Typen
- **Premium-Shunt:** Isabellenhuette Busbar-/Shunt-Familien
- **Isolations-Frontend:** TI `AMC1306M25`
- **Isolierte Versorgung:** Murata `NME0505SC` oder RECOM `R1SX-0505-R`
- **ADC:** TI `ADS131M08`
- **MCU:** `NUCLEO-H753ZI` oder vergleichbares STM32H7-Nucleo
- **Logger:** Raspberry Pi 5 8 GB oder gebrauchter Intel NUC / Thin Client
- **DIN-Netzteil:** Mean Well `HDR-30-5` oder `HDR-60-5`

**Kurzurteil:** Wenn du ueber laengere Zeit gezielt auf guenstige Gelegenheiten
wartest, lohnt sich der Gebrauchtmarkt vor allem fuer **Rechner, Netzteile,
Mechanik und eventuell Eval-Boards**. Die eigentliche Messqualitaet haengt aber
an **Shunt, Isolation und ADC-Kette**; diese Teile wuerde ich fuer die
Endstufe eher gezielt neu oder aus sehr vertrauenswuerdigen Restbestaenden
nehmen.

Wenn ein eigener Aufbau bis **1 MHz** realistisch ist, dann verschiebt sich die
Entscheidung deutlich:

- **ADC-Rate allein loest das Problem nicht**
- entscheidend sind Isolation, Sicherheit, Front-End, Anti-Aliasing,
  Spannungs- und Stromwandler, Kalibrierung und Zeitbasis

### Technische Kernfragen fuer DIY

1. Wie wird die Netzspannung sicher und galvanisch getrennt erfasst?
2. Wie wird der Strom gemessen: Shunt, Rogowski, Hall, Stromwandler?
3. Wie sieht der Anti-Aliasing-Pfad aus?
4. Wie wird die Messkette kalibriert?
5. Welche Bandbreite ist wirklich noetig: 1 kHz, 20 kHz, 100 kHz, 1 MHz?

### Praktische Bewertung

- Fuer **50 Hz + niedrige Harmonische** ist 1 MHz technisch weit mehr als noetig.
- Fuer **Forschung an schnellen Schaltflanken / HF-Mustern** kann das sinnvoll
  sein, wenn das analoge Front-End sauber geloest ist.

## Vorschlag: Shunt-Messarchitektur mit galvanischer Trennung

### Zielbild

- **Parallelpfad zum Produktivsystem**, nicht als Ersatz fuer den bestehenden
  Fronius-/Collector-Pfad.
- Fokus auf **saubere Wellenformmessung**, THD, Harmonische und spaetere
  Erweiterung in den kHz-Bereich.
- Galvanische Trennung zwischen **Netzseite** und **Auswerte-/Ethernet-Seite**.

### Grundarchitektur

1. **Pro Phase ein Praezisions-Messshunt**
   - vierpoliger Manganin-Shunt
   - typisch auf **40 mV bis 75 mV** bei gewuenschtem Vollstrom ausgelegt
   - Einbau in jede Phase am PCC als eigener Strommesspfad

2. **Kelvin-Abgriff direkt am Shunt**
   - separater Messabgriff fuer Spannungsmessung am Shunt
   - stromfuehrender Lastpfad und Messpfad strikt getrennt fuehren

3. **Isolierte Strommessung pro Phase**
   - differenzieller Praezisionsverstaerker oder besser **isolierter Sigma-Delta-
     Modulator / isolierter Messverstaerker** direkt am Shunt
   - je Kanal **eigene isolierte Versorgung** per isoliertem DC/DC-Wandler
   - Ziel: Stromsignal bereits an der Netzseite in ein galvanisch getrenntes
     Digitalsignal oder robust isoliertes Analogsignal ueberfuehren

4. **Spannungsmessung getrennt vom Strompfad**
   - je Phase abgesicherter Spannungsteiler mit Ueberspannungsschutz und danach
     isolierter Messkette
   - alternativ kleine Messspannungswandler, wenn maximale Robustheit wichtiger
     ist als Bandbreite

5. **Synchrones Mehrkanal-Sampling auf der sicheren Seite**
   - mindestens **3 Stromkanaele + 3 Spannungskanaele**
   - zentrale Erfassung durch MCU/FPGA/SBC-nahe ADC-/Digital-Frontend-Platine
   - gemeinsame Zeitbasis fuer saubere Wirkleistung, Blindleistung, FFT und THD

6. **Auswerterechner / Gateway**
   - Linux-SBC oder Industriecontroller auf Niederspannungsseite
   - Speicherung als Rohdatenringpuffer plus berechnete Kennwerte
   - Ethernet/REST/Modbus-TCP nur auf der sicheren, galvanisch getrennten Seite

### Empfohlene Topologie fuer unser Projekt

- **PCC-Hauptleiter je Phase -> Shunt -> vorhandener Lastpfad**
- je Phase ein **isolierter Stromkanal**
- je Phase ein **isolierter Spannungskanal gegen N**
- galvanisch getrennte Digitalschnittstelle zum Auswerte-SBC
- parallele Ablage in eine eigene **NQ-Shunt-DB**

### Technisch sinnvoller Sampling-Bereich

- **10 kS/s bis 50 kS/s pro Kanal**: sehr gut fuer 50 Hz, THD,
  Oberschwingungen und saubere Ereigniserkennung im unteren kHz-Bereich
- **100 kS/s bis 200 kS/s pro Kanal**: sinnvoll, wenn bewusst ueber klassische
  PQ-Meter hinaus in Richtung schnelle Schaltmuster geschaut werden soll
- **1 MS/s und mehr**: nur als eigener Forschungszweig, nicht als erster
  Produktivschritt

### Sicherheits- und Isolationsregeln

- Shunts nur mit ausreichender **Dauerstrom- und Verlustleistungsreserve**
- jede Spannungsabnahme abgesichert, mit **CAT-geeigneter Schutzbeschaltung**
- isolierte DC/DC-Wandler mit ausreichender Bemessungsisolation
- Kriech- und Luftstrecken konsequent fuer Netzspannung dimensionieren
- sternfoermige, kontrollierte Bezugserde auf der sicheren Seite
- kein direkter Netzbezug am SBC, USB oder Ethernet

### Warum diese Architektur fachlich interessant ist

- Shunts sind fuer Strommessung **breitbandiger** und oft linearer als klassische
  Stromwandler
- die gesamte Messkette ist frei definierbar: Rohdaten, FFT, Ereignistrigger,
  eigene Kennwerte
- spaetere Erweiterung auf andere Front-Ends bleibt offen

### Warum diese Architektur trotzdem kein schneller Plug-and-Play-Weg ist

- deutlich hoeherer Aufwand fuer Sicherheit, Isolation und Kalibrierung
- thermische Drift und Verlustleistung des Shunts muessen sauber beherrscht
  werden
- Spannungsmessung und Zeitbasis muessen auf demselben Qualitaetsniveau liegen
  wie die Strommessung
- fuer den ersten Produktivnutzen ist ein CT-/PQ-Meter-Weg einfacher

### Klare Projektempfehlung

- **Wenn schnell nutzbare PCC-Daten mit wenig Risiko gesucht sind:** PAC4200 +
  passend dimensionierte Stromwandler
- **Wenn eigene Wellenformanalyse, Shunt-Messtechnik und spaetere HF-Auswertung
  erforscht werden sollen:** separater, galvanisch getrennter Shunt-Messpfad als
  zweites System neben der bestehenden Infrastruktur
- Der Engpass ist dann nicht die Software, sondern die **sichere und
  messtechnisch brauchbare Analogschnittstelle**.

## Beschaffung: kostenguenstig moeglich?

### Guenstig und sinnvoll

- zusaetzliches SmartMeter fuer entkoppelte RMS-Erfassung
- gebrauchtes Oszilloskop / DAQ fuer gezielte Versuchsfenster
- eigener Prototyp, wenn Isolation und Kalibrierung beherrscht werden

### Guenstig aber mit Vorsicht

- Billig-Logger ohne Rohwellenform sind fuer PQ-Fragen oft zu grob
- Audio-/Soundkarten-Loesungen sind billig, aber sicherheits- und
  kalibrierungstechnisch heikel

### Nicht billig

- echte Power-Quality-Analyzer mit belastbarer THD-/Harmonischen-Qualitaet
- HF-faehige, sichere Dauer-Messtechnik

## Projektentscheidung aktuell

1. Vorhandenes Primaer-SmartMeter weiter ausreizen.
2. Produktiven Collector nicht vorschnell auf dichteres Polling trimmen.
3. Falls zusaetzliche RMS-Dichte benoetigt wird: eigener NQ-Sensor am PCC.
4. Falls Wellenform/Harmonische/HF die eigentliche Frage sind: dedizierte
   Messtechnik statt weiteres Herumoptimieren am Produktiv-Collector.

## Projektgrenze

Das NQ-Thema ist **fachlich ein separates Messtechnik-Projekt**, bleibt aber
bewusst im PV-System sichtbar und bedienbar:

- Datenquelle heute: Export aus dem Hauptsystem in eigene NQ-Monats-DBs
- Analyse: in eigenem NQ-Modul
- Darstellung: ueber die bestehende Web-API im Maschinenraum
- kuenftig moeglich: alternative NQ-Datenquellen, ohne die Maschinenraum-UI
  aufzugeben

Damit bleibt die NQ-Schicht im Gesamtsystem verankert, ohne die Rollen- und
Schreibgrenzen des Kernsystems aufzuloesen.

## Pflege-Regel

Dieses Dokument wird aktualisiert, wenn sich eine der folgenden Entscheidungen
konkretisiert:

- Benchmark fuer kuerzeres Polling am Netz-SmartMeter
- Auswahl eines dedizierten NQ-Sensors am PCC
- Start eines DIY-Messpfads
- Zielbandbreite fuer spaetere Breitbandanalyse