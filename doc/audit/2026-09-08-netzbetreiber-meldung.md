# Meldung einer Netzanomalie (Überfrequenz) am 08.09.2026

> **Hinweis (intern, vor Versand entfernen):** Dieses Schreiben ist bewusst
> **allgemein** gehalten und nennt **ausschließlich** die dem Netzbetreiber
> bekannte Erzeugungsanlage (1 × WR, 21,9 kWp, Wohnhaus). Alle Messwerte sind am
> **Netzanschlusspunkt** erhoben und verraten keine anlageninternen Details.
> Platzhalter `[…]` bitte ausfüllen. Technische Herleitung/Rohdaten liegen intern
> in `doc/audit/2026-09-08-blackout.md`.

---

**Absender:** [Name, Anschrift, Kundennummer]
**Zählernummer (Netzbezug/Einspeisung):** [Zählernummer]
**Anlage:** Photovoltaik, 1 Wechselrichter, 21,9 kWp (Aufdach Wohnhaus)
**An:** [Netzbetreiber / Netzversorger, Anschrift]
**Datum:** [Versanddatum]

**Betreff: Netzstörung am 08.09.2026 – anhaltende Überfrequenz (bis 52,2 Hz) nach
Stromausfall; Bitte um Ursachenklärung**

Sehr geehrte Damen und Herren,

am **08.09.2026** kam es an unserem Hausanschluss [Anschlussadresse] zu einem
Stromausfall mit einer anschließenden, mehrstündigen **Netzanomalie**, die ich
Ihnen hiermit zur Prüfung melde. Meine eigene Netzqualitäts-Messtechnik am
Hausanschluss hat den Vorgang lückenlos aufgezeichnet.

## 1. Sachverhalt (Zeiten lokal, MESZ)

| Zeit | Beobachtung |
|---|---|
| ~08:03 | Netzausfall (Spannung fällt aus, Hausanschluss stromlos) |
| ~10:38 | Spannung kehrt zurück, jedoch mit **stark erhöhter Netzfrequenz** |
| 10:38–13:50 | **anhaltende Überfrequenz** von durchgehend ca. **51,7 Hz**, mit Einzelwerten **bis 52,2 Hz** |
| **13:50** | Frequenz normalisiert sich **schlagartig** auf ~50,0 Hz |
| ~13:52 | Netz wieder regulär; Anlage nimmt Normalbetrieb auf |

Während der gesamten Anomalie (10:38–13:50) lag an allen drei Außenleitern eine
im Betrag **normale, symmetrische Spannung** von ca. **229–234 V** an
(dreiphasig), bei zugleich **klarer Kurvenform** (Oberschwingungsgehalt THD
unauffällig, ~1,7 %). Die Frequenz war also **sauber gemessen** und lag dennoch
dauerhaft weit über dem zulässigen Bereich.

## 2. Einordnung

Das europäische Verbundnetz wird synchron bei **50,0 Hz** betrieben; der zulässige
Regelbereich liegt bei ±0,2 Hz (eine Abweichung von 0,2 Hz entspricht bereits
einem Leistungsungleichgewicht von ca. 3 GW). Eine **über Stunden anhaltende
Frequenz von 51,7–52,2 Hz ist im Verbundnetz physikalisch nicht möglich.** Die
Messwerte belegen daher, dass unser Anschluss in diesem Zeitraum **nicht mit dem
synchronen Verbundnetz**, sondern mit einem **abweichend geregelten
Netz-Abschnitt (inselartiges Verhalten)** verbunden war. Der **schlagartige**
Rücksprung auf 50,0 Hz um 13:50 spricht für einen **Umschalt-/Zuschaltvorgang**
(Wiederankopplung an das Verbundnetz).

## 3. Ausschluss der eigenen Erzeugungsanlage

Ich habe geprüft und kann eindeutig belegen, dass **meine PV-Anlage die
Überfrequenz nicht verursacht hat**:

- Die Anlage hat sich – normgerecht nach **VDE-AR-N 4105** (Abschaltung bei
  f > 51,5 Hz) – **vom Netz getrennt** und während der gesamten Anomalie **keine
  Leistung eingespeist**. Der Einspeisezähler stand faktisch still (Zuwachs im
  einstelligen Wh-Bereich über mehrere Stunden).
- Am Netzanschlusspunkt wurde durchgehend **Leistung bezogen** (Import, ~1,6 kW,
  in Summe ca. 5,6 kWh) – meine Anlage war in diesem Zeitraum also **Verbraucher,
  nicht Erzeuger**. Eine Frequenz-anhebende Quelle muss hingegen **einspeisen**.
- Die PV-Erzeugung war null (Wechselrichter getrennt), der Batteriespeicher ruhte.

Damit ist meine Anlage als Verursacher **physikalisch ausgeschlossen**.

## 4. Auffälligkeit und Bitte um Klärung

Die Überfrequenz hatte zur Folge, dass **jede normkonforme PV-Erzeugung – auch
meine – über die gesamten ~3 Stunden vom Netz getrennt blieb** und der Haushalt
gezwungenermaßen Netzbezug hatte, obwohl (bei normaler Frequenz) eigene Erzeugung
verfügbar gewesen wäre.

Ich bitte Sie um Aufklärung folgender Punkte:

1. **Was war die Ursache** der anhaltenden Überfrequenz (51,7–52,2 Hz) an meinem
   Anschluss zwischen ca. 10:38 und 13:50 Uhr?
2. War in diesem Zeitraum ein **inselartiger Netzabschnitt** aktiv (z. B. im Zuge
   der Wiederversorgung nach dem Ausfall), und wenn ja, **wie wurde dessen
   Frequenz geregelt**?
3. Kann eine **ungewollte Inselbildung** durch eine rückspeisende Quelle im
   Niederspannungsabschnitt (z. B. eine Erzeugungsanlage mit nicht ausgelöstem
   Netz- und Anlagenschutz) ausgeschlossen werden? Dies wäre
   **sicherheitsrelevant** (Gefährdung bei Arbeiten am vermeintlich
   spannungsfreien Netz).
4. Bestand für angeschlossene Betriebsmittel durch die Überfrequenz ein
   **Schädigungsrisiko**, und wie wird ein Wiederauftreten verhindert?

Für eine Rückmeldung sowie – falls vorhanden – die **Störungs-/Wiederversorgungs-
protokolle** des betroffenen Ortsnetzes am 08.09.2026 wäre ich dankbar. Meine
aufgezeichneten Messdaten (Frequenz, Spannung je Phase, Leistung) stelle ich Ihnen
auf Wunsch zur Verfügung.

Mit freundlichen Grüßen

[Name]

---

### Anlage: Messwert-Auszug (am Hausanschluss, 08.09.2026)

| Größe | Wert im Anomalie-Fenster (10:38–13:50) |
|---|---|
| Netzfrequenz | durchgehend ~51,7 Hz; Minimum ~50,9 Hz; **Maximum ~52,2 Hz** |
| Spannung L1 / L2 / L3 | ~229 / ~229 / ~234 V (symmetrisch, dreiphasig) |
| Oberschwingung THD (U) | ~1,7 % (unauffällige, saubere Kurvenform) |
| Wirkleistungsfluss | **Bezug** ~1,6 kW (Summe ~5,6 kWh); **keine Einspeisung** |
| Frequenz-Normalisierung | 13:50 Uhr, sprunghaft auf ~50,0 Hz |
