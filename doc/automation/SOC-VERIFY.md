# SOC-Verify
1) Aussage "immer Komfort" ist zu stark und so nicht haltbar.
2) In logs/schaltlog.txt existieren erfolgreiche Nicht-Komfort-Schaltungen.
3) Beispiele: set_soc_min=5 OK und set_soc_max=100 OK sind mehrfach vorhanden.
4) Gleichzeitig dominieren Komfort-Resets (set_soc_min=25, set_soc_max=75).
5) Das System versucht oft Nicht-Komfort, scheitert dabei aber haeufig.
6) Besonders auffaellig: viele FEHLER bei set_soc_min=5 (Zellausgleich-Pfad).
7) Dadurch entsteht praktisch oft Komfortwirkung trotz anderer Sollbefehle.
8) Die alte Proxy-Autarkie in der Simulation war methodisch zu grob.
9) blocked_discharge/blocked_charge allein bildet echte Energiefluesse nicht ab.
10) Sinnvoller ist eine energiebasierte Autarkiekennzahl aus Netzbezug/Verbrauch.
11) Formale Zielgroesse: Autarkie = 1 - E_Grid_Import / E_Consumption.
12) Schutz sollte getrennt als Band-/Zeit-Metrik bewertet werden.
13) Relevante Schutzanteile: Stunden <10%, <15%, >90%, plus Schaltstress.
14) Damit werden kurze 5%-Fenster nicht als "kostenlos" behandelt.
15) Erwartung: Schutzscore sinkt realistisch bei haeufiger Nacht-Oeffnung.
16) Erwartung: Autarkiescore steigt bei sinnvoller Nachmittagsladung auf 100%.
17) Das passt zur Betriebslogik: tags 75%, nachmittags bedarfsorientiert 100%.
18) Die Kernfrage ist daher nicht "Simulierbar ja/nein", sondern Modelltreue.
19) Vollstaendige 1:1-Produktionsabbildung bleibt komplex und fragil.
20) Entscheidungsfaehig ist dennoch ein reduziertes, transparentes Bewertungsmodell.
21) Mindestanforderung: getrennte Scores fuer Autarkie und Schutz.
22) Zusatznutzen: Konflikte zwischen Komfort und Nachtversorgung werden sichtbar.
23) Schaltlog-Validierung bleibt Pflicht fuer jede Simulationsaussage.
24) FEHLER/OK/DRY-RUN sollten als Realisierungsfaktor in die Bewertung eingehen.
25) So werden theoretische Vorteile nicht ueberbewertet.
26) Ergebnislage aktuell: Nicht-Komfort existiert, aber mit hoher Fehlerrate.
27) Deshalb ist "immer Komfort" falsch, "oft Komforteffekt" jedoch zutreffend.
28) Fuer Entscheidungen gilt: erst Kennzahlen trennen, dann Varianten vergleichen.
29) Dieser Vermerk dokumentiert den verifizierten Zwischenstand.
