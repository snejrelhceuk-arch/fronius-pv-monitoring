# Audit: Energievergleich PAC4200 ↔ Fronius-SM — Export-Abweichung

**Datum:** 2026-08-13 · **Rolle:** N (Netzqualität) · **Seite:** `/netzqualitaet/energievergleich`

## 1. Ausgangsbeschwerde

Auf der Seite **Netzqualität → Energievergleich** weichen die Tageswerte
PAC4200 gegenüber dem Fronius Primär-SM ab. Vermutung des Bedieners: „Die
PAC-Werte sind sicher falsch." Da das gesamte NQ-Projekt auf exakten Messungen
beruht, sollte die Ursache bis zur nachhaltigen Lösung geklärt werden.

## 2. Vorgehen

Untersucht wurden: Grundfunktion des NQ-Energiepfads, beide Datenbanken
(Tech-RAM-Snapshots, Primary-Fixpunkte), die Tages-Fixpunkte, der PAC-Live-Zustand
(Register + Leistungen) sowie die Betriebsanleitung (`doc/netzqualitaet`,
Register- und Konfigurationskarte).

## 3. Befunde

### 3.1 Zwei Klassen von Tagen
Der Vergleich (nur echte PAC-Zählertage) zerfällt in:

- **Startup/Lücken-Tage** — 2026-07-12/13/14, 08-04: Export-Register noch in der
  **Anlaufphase** (Stand `0`) bzw. nur **33–46 Snapshots** statt 288 (spärliche
  Collector-Abdeckung im Umzugsfenster REFORMATION). Diese Tage sind **kein
  gültiger PAC-Messwert** und dürfen nicht als Vergleich gewertet werden.
- **Voll abgedeckte Tage** — 07-15, 08-05…08-12 (je ~288 Snapshots): belastbare
  PAC-Messung.

### 3.2 Muster auf den gültigen Tagen
| Größe | PAC ↔ SM |
|---|---|
| **Bezug (Import)** | stimmt gut, ±0…7 % (meist ±3 %), streut um 0 |
| **Einspeisung (Export)** | PAC **systematisch höher**: +5 … +26 % (abs. ≈ +0,03…+0,19 kWh/Tag) |

Der **Netto**-Bezug (Import − Export) ist auf PAC konsistent ~0,09–0,17 kWh/Tag
weiter Richtung Export als beim SM → ein **~4 W mittlerer Wirkleistungs-Offset**.

### 3.3 Was ausgeschlossen werden konnte (kein Fehler)
- **Registerabbild korrekt.** 801 = Bezogene Wirkenergie T1, 809 = Gelieferte
  Wirkenergie T1 (mit Betriebsanleitung abgeglichen).
- **PAC misst und integriert intern korrekt.** 60-s-Live-Test bei Netto-Bezug
  ~660 W: `Wh_imp` stieg exakt um P_tot·dt (11,08 Wh), `Wh_exp` blieb eingefroren.
- **PAC zählt saldierend** (Netto über alle drei Phasen), **wie der Fronius-SM** —
  kein „phasenweise vs. saldierend"-Effekt.
- **Stromwandler korrekt dimensioniert/angeschlossen.** Live-Strombeträge stimmen
  mit dem SM überein (L1 3,0/3,1 A · L2 4,6/4,8 A · L3 2,3/2,4 A). Keine
  vertauschte Richtung im Netto-Ergebnis.
- **Blindleistung stimmt überein** (beide Q ≈ −1650 var).
- **NQ-Pipeline korrekt.** Randscharfe Tagesabgrenzung, Differenzmethode und
  Teleskopierung der Fixpunkte sind konsistent (Import passt ±3 %).

### 3.4 Physikalische Ursache der Rest-Abweichung
Verglichen werden **zwei unabhängige Messgeräte am selben PCC**. Der
Netzanschlusspunkt trägt **hohe kapazitive Blindleistung** bei sehr **niedrigem
Leistungsfaktor** (PF live 0,27–0,45). Ein kleiner Phasenwinkel-Unterschied
zwischen den beiden Messketten (~0,3°, am Rand der 0,2S-Wandlerklasse), angewandt
auf die große Blindleistung, ergibt einen **Netto-Wirkleistungs-Offset ~4 W ≈
0,1 kWh/Tag**. Auf den großen Bezug ist das prozentual vernachlässigbar, auf die
kleine Einspeisung (~0,5 kWh/Tag) prozentual groß. Das erklärt exakt das Muster
„Import passt, Export systematisch +x %".

→ **Keine** Verdrahtungs-/Einstellungs-Fehlfunktion. Die absolute Genauigkeit der
kleinen Einspeisung an diesem Low-PF-Punkt ist inhärent durch die Kombination
beider Geräte begrenzt. Welches Gerät näher an der Eichgröße liegt, ist ohne den
Netzbetreiber-Zähler (iMS) **nicht** entscheidbar (das 0,2S-PAC ist a priori das
genauere Gerät).

### 3.5 Eigentlicher Defekt: fabrizierte „0,0 %"-Tage
`nq/transfer/nq_energy_sm_correct.py` hatte am 2026-08-08 acht PAC-Tage mit den
**SM-Werten überschrieben** (`src='sm_corrected'`), um „0,0 % Abweichung" zu
erzeugen. Damit wurden **echte, unabhängige Messungen zerstört** und die reale
(kleine, erklärbare) Export-Abweichung **verschleiert**. Genau dieser Kontrast
— alte Tage künstlich „0,0 %", neue Tage real „+15 %" — erzeugte den Eindruck
eines plötzlichen Problems. Für ein Mess-Integritäts-Projekt ist das Überschreiben
mit einem Fremdgerät unzulässig.

Die Fixpunkte (`*_start`) blieben unangetastet → die realen Deltas waren
rekonstruierbar (z. B. 08-05/06/07 realer Export 0,642 / 0,609 / 0,953 kWh statt
der fabrizierten 0,591 / 0,579 / 0,763 — dasselbe Über-Zähl-Muster).

## 4. Lösungsschritte (durchgeführt)

1. **Reale Messwerte wiederhergestellt** — `nq_energy_recompute --apply`: leitet
   die Tages-Deltas ausschließlich aus den echten PAC-`*_start`-Fixpunkten ab
   (Teleskopierung, Anlaufphasen-/Reset-Guards, idempotent). Alle 13 Tage von
   `sm_corrected`/roh auf echte `counter`/`partial`-Werte zurückgesetzt.
2. **Fabrikations-Werkzeug entfernt** — `nq/transfer/nq_energy_sm_correct.py`
   (Schwellen-Automatik, überschrieb auch **gültige** Tage) gelöscht und durch
   `nq/transfer/nq_energy_invalidate.py` ersetzt: gleicht **nur explizit benannte**
   ungültige Tage an SM an (`src='sm_substitute'`), keine Automatik.
3. **Wirklich ungültige Tage an SM angeglichen** (für die kumulativen „everlasting"-
   Statistiken / Tooltip-Klammerwerte): 2026-07-12/13/14 (Anlaufphase, Export-
   Register `0`) und 2026-08-04 (nur 33 Snapshots) → `sm_substitute`. Der **gültige**
   Tag 07-15 (288 Snapshots) und **alle Tage ab 08-05** behalten die realen
   PAC-Werte (Beschluss: ab 05.08. gilt PAC, bis der iMSys-Abgleich mehr sagt).
4. **Doku richtiggestellt** — `doc/netzqualitaet/ENERGIE_ABLESEMETHODE.md`
   (`sm_substitute` dokumentiert, realistische Schwellen, IST-Befund + physikalische
   Erklärung); Aggregations-Card ergänzt.
5. **Drei-System-Fixpunkte angelegt** — `doc/MESSSYSTEM_FIXPUNKTE.md` (iMSys/SM/PAC
   synchron, erste Ablesung 2026-08-13 20:36). Basis für den iMSys-Abgleich.

## 5. Empfehlung (offen)

- **iMS/Netzbetreiber-Zähler regelmäßig ablesen** und in `doc/MESSSYSTEM_FIXPUNKTE.md`
  (bzw. `nq_ims_reading`) eintragen. Nur dieser eichrechtliche Zähler ist der
  absolute Referenzpunkt; zwischen zwei Ablesungen je System das Intervall-Delta
  bilden und gegen den iMSys vergleichen. Erst damit lässt sich entscheiden, ob
  PAC oder Fronius-SM näher an der Wahrheit liegt — und damit die systematisch
  höhere PAC-Einspeisung (kein Monats-Ausgleich) belastbar bewerten.
- **Weiter beobachten:** Export-Abweichung PAC↔SM auf den gültigen Tagen (ab 08-05)
  bleibt einseitig positiv (+5…+26 %); im Monatsverlauf findet kein Ausgleich statt.
- Für die Musteranalyse selbst (U, f, PF, THD/Harmonik) ist die kleine
  Export-Energie-Abweichung **irrelevant**; diese Größen sind davon unberührt.
