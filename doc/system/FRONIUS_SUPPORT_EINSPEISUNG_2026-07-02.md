# Fronius/Solar.web Support — Einspeise-Zwischenfall 2026-07-02

> **Status: ENTWURF — nicht automatisch versandt.** Bitte vor dem Senden prüfen.
> Kontaktweg: Solar.web → Hilfe/Support bzw. Fronius Technical Support (Solar.web
> Portal → „?" / Support-Ticket, alternativ Fronius-Händler/Installateur).

## Betreff
Symo GEN24 12.0 Plus — Sekundär-Wechselrichter (F3) ignoriert dynamische
Einspeisebegrenzung (Soft-Limit 0 W); anhaltende Netzeinspeisung trotz
„Mehrere Wechselrichter limitieren = Ein"

## Kurzbeschreibung
Am 2026-07-02 kam es über mehrere Stunden zu ungewollter Netzeinspeisung
(≈2,97 kWh statt normal < 1 kWh/Tag), obwohl die dynamische
Einspeisebegrenzung (Soft Limit Trip) auf 0 W konfiguriert ist und
„Mehrere Wechselrichter limitieren (Soft Limit + I/O-Leistungsmanagement)"
aktiviert ist. Der GEN24 (F1) regelte seine eigenen MPP-Tracker und einen
zweiten Strang (F2) korrekt auf Minimum ab — **ein dritter Erzeuger (in
unserer Messung „F3") wurde jedoch NICHT abgeregelt** und speiste
unkontrolliert weiter ein.

## Beobachtung (Messdaten, 3-s-Auflösung)
- **09:01:00** Batterie erreicht SOC 75 % (obere Grenze) → Ladung stoppt
  (Batteriestrom 20,6 A → 0 A), F1-DC-Ernte bricht von 6530 W auf 112 W ein.
- Gleichzeitig: **F2** wird auf ~46 W abgeregelt (Soft-Limit greift),
  **F3** bleibt bei ~2200 W und steigt sonnenstandsbedingt bis ~3200 W.
- Ergebnis: anhaltende **Einspeisung 0,5–1,8 kW** (Momentspitzen bis −9 kW),
  weil F1/F2 bereits am Minimum sind und F3 nicht reagiert.
- **10:34→10:35**: sobald eine Hauslast (~1,8 kW) zugeschaltet wird, ramp'en
  F1/F2 hoch und die Einspeisung verschwindet — F3 bleibt die ganze Zeit
  konstant am Maximum (kein Curtailment erkennbar).
- Beendet erst gegen **14:29**, als die obere Batteriegrenze auf 100 % angehoben
  wurde und die Batterie den Überschuss aufnahm.

Interpretation: Das Soft-Limit/Leistungsmanagement erreicht F1 und F2, aber
**nicht F3**. Mögliche Ursachen aus Fronius-Sicht (bitte prüfen):
- Kommunikations-/Kopplungsverlust F3 ↔ GEN24-Master (Modbus/Solar-API/IO).
- F3 nicht Teil der „Multiple Inverter Limiting"-Gruppe / Fehlkonfiguration.
- Firmware-/DNO-Setpoint-Problem am Sekundärgerät.

## Fragen an den Support
1. Wie stelle ich sicher, dass **alle** gekoppelten Wechselrichter (inkl. F3)
   dem Soft-Limit (0 W) unterliegen?
2. Gibt es ein Log/Statusregister, das anzeigt, ob ein Sekundär-WR das
   Curtailment-Signal empfängt/befolgt?
3. Empfehlung zur Überwachung/Alarmierung eines solchen „Runaway"-Zustands
   direkt am GEN24?

## Sofortmaßnahmen unsererseits (bereits umgesetzt)
- Soft-Limit-Wert von versehentlich 30 W zurück auf **0 W** gesetzt.
- Automations-seitiger **Nulleinspeisungs-Schutz** aktiviert: erkennt
  anhaltende Einspeisung und öffnet den Batterie-Puffer (SOC_MAX→100 %),
  warnt per Mail/Log (siehe `doc/llm/cards/automation-einspeise-schutz.card.md`).

## System Information (Anlage — vom Nutzer bereitgestellt, 2026-07-02)
```
Gerätename           Symo GEN24 12.0 Plus SC
Hardware ID          pilot-0.6e-228656451809016825
WebUI                1.34.1-6
Softwareversion      ROW 1.40.9-1
Software-Revisionen  GEN24 1.40.9-1 | Kronos 1.8.2-33111 | KronosV3 3.8.6-34722
                     Rhea 2.15.1-2 | S12RW 0.0.0-0 | S12RW-pilot 1.34.1-10
                     Zeus 3.7.2-24728 | imx6sx-pilot 1.34.1-10
Hardware-Revisionen  3PN12SC-35301005046480016 (4,071,870 | 0.2B | 3PN12SC)
                     PILOT-34059501800002252   (4,071,452 | 0.6E_B | PILOT)
                     ROX-L-34489501700001261   (4,071,779 | 0.2A_B | ROX-L)
Netzwerk (Ethernet)  IP <LAN-intern>/24, Gateway/DNS <LAN-intern> (statisch)
Lizenz               SN 35237382 | Nennleistung 12000 W | Art.-Nr. 4,210,189,002
Aktivierte Features  41,300,221 Battery Operation | 41,300,222 Full Backup
Grid Code            DE2F >4,6kVA cos phi=1 (Germany), Id 1507352 (0x170018), V 01.00.14.00
Einspeisebegrenzung  Leistungsbegrenzung on; Gesamte DC-Anlagenleistung 26500 W
                     Dynamische Einspeisebegrenzung (Soft Limit) on
                     Max. Netzeinspeise-Leistung (Soft Limit Trip) 0 W
                     Abschaltfunktion (Hard Limit Trip) off
                     WR-Leistung auf 0% bei SmartMeter-Trennung: off
                     Mehrere Wechselrichter limitieren (Soft Limit + I/O): on
```
