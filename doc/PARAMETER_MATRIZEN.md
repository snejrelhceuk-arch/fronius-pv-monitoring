# Parameter-Matrizen — PV-Anlage Erlau

**Erstellt:** 2026-02-20  
**System:** 37.59 kWp / 3 WR / Erlau 51.01 °N 12.95 °O

---

## 1. PV-Erzeuger-Matrix (alle 7 Strings)

### Systemübersicht

| WR | Ort | Strings | kWp gesamt | Besonderheit |
|---|---|---|---|---|
| F1 Gen24 12kW | Wohnhaus | S1, S2, S3, S4 | 19.32 | Mit BYD-Batterie DC-gekoppelt |
| F2 Gen24 10kW | Heizhaus | S5, S6, S7 | 12.42 | Kein Speicher |
| F3 Symo 4.5kW | Wohnhaus Süd | S8 | 5.85 | Fassade SSO 90° |

### String-Matrix (Temporal & Saisonal)

| String | Azimut | Neigung | kWp | Optimum Sommer | Optimum Winter | Jahresbeitrag | Besonderheit |
|---|---|---|---|---|---|---|---|
| S1 (WH SSO) | 142° | 52° | 5.04 | 08:00–14:00 | 09:00–14:00 | ~25 % | Morgen-Starter, spiegelt S2 |
| S2 (WH NNW) | 322° | 52° | 4.59 | 15:00–21:00 | — | ~15 % | **NNW-Fenster!** Sommer = Abend-PV |
| S3 (WH SSO) | 142° | 45° | 4.59 | 08:30–14:30 | 09:00–14:30 | ~22 % | Flacher als S1, etwas länger |
| S4 (WH NNW) | 322° | 45° | 5.10 | 15:00–21:00 | — | ~13 % | Zusammen mit S2 Abend-Fenster |
| S5 (HH WSW Flach) | 242° | 18° | 6.12 | 11:00–19:00 | 12:00–16:00 | ~30 % | Flachdach, kurzer Schatten |
| S6 (HH WSW Fass.) | 242° | 90° | 2.22 | 13:00–19:00 | — | ~8 % | Fassade, steil, Sommer bevorzugt |
| S7 (HH WSW Fass.) | 242° | 90° | 4.08 | 13:00–19:00 | — | ~12 % | Fassade, steil, Sommer bevorzugt |
| S8 (WH SSO Fass.) | 150° | 90° | 5.85 | 09:00–13:00 | 09:30–12:30 | ~15 % | Fassade, steil, Winter-Morgen stärker |

### NNW-Fenster (S2 + S4) — saisonal

Das NNW-Fenster ist der kritischste Faktor für die Abend-Strategie.

| Monat | NNW aktiv von | NNW aktiv bis | Max-Leistung | Bemerkung |
|---|---|---|---|---|
| Jan | — | — | 0 | Sonne geht bei ~210° unter |
| Feb | — | — | 0 | Sonnentiefe zu flach für NNW |
| Mär | ~19:00 | ~19:30 | ~0.5 kW | Erstes Mini-Fenster |
| Apr | ~18:30 | ~20:00 | ~2.0 kW | Nutzbar für Abendstrategie |
| Mai | ~18:00 | ~21:00 | ~3.5 kW | Signifikant! |
| Jun | ~17:30 | ~21:30 | ~4.2 kW | **Maximum** — NNW = 70–90 % Abend-PV |
| Jul | ~17:30 | ~21:30 | ~4.0 kW | Wie Juni |
| Aug | ~18:00 | ~21:00 | ~3.2 kW | Nimmt ab |
| Sep | ~18:00 | ~20:00 | ~1.5 kW | Deutlich reduzierter |
| Okt | — | ~19:00 | ~0.3 kW | Kaum nutzbar |
| Nov | — | — | 0 | Kein NNW-Fenster |
| Dez | — | — | 0 | Kein NNW-Fenster |

> **Automation-Implikation:**  
> Im Sommer (Mai–Aug) sollte der Nachmittagsalgorithmus SOC_MAX **nicht** bereits um 15:00 auf 100 % zeigen, da S2+S4 noch 3–4 h weiter laden. SOC_MAX-Erhöhung idealerweise erst wenn NNW-Fenster auch ausgeschöpft.

### F2 WSW Heizhaus — Fensteranalyse nach Monat

| Monat | Peak-Fenster | Leistungspeak (S5+S6+S7) |
|---|---|---|
| Jan | 12:30–15:00 | ~2.0 kW |
| Feb | 12:00–16:00 | ~3.5 kW |
| Mär | 11:30–17:00 | ~6.0 kW |
| Apr | 11:00–18:00 | ~8.5 kW |
| Mai | 10:30–19:00 | ~10.5 kW |
| Jun | 10:30–19:30 | ~11.0 kW |
| Jul | 10:30–19:30 | ~11.0 kW |
| Aug | 11:00–19:00 | ~10.0 kW |
| Sep | 11:30–17:30 | ~7.5 kW |
| Okt | 12:00–16:00 | ~4.5 kW |
| Nov | 12:30–15:00 | ~2.5 kW |
| Dez | 12:30–14:30 | ~1.5 kW |

---

## 2. Speicher-Matrix

### 2.1 Heimspeicher BYD HVS 10.2 kWh (F1)

| Parameter | Wert |
|---|---|
| Typ | LFP (LiFePO₄) |
| Nennkapazität | 10.24 kWh |
| SOH aktuell | ~92 % |
| Nutzbare Kapazität | ~9.4 kWh |
| Max. Ladeleistung (DC) | 5 kW |
| Max. Entladeleistung (DC) | 5 kW |
| Zelltemperatur Normal | 15–35 °C |
| **Zelltemperatur Warnung** | > 40 °C |
| **Zelltemperatur Alarm** | > 45 °C |
| Selbstentladung | ~1–2 % / Monat |
| SOC-Hardgrenzen Auto-Modus | 5–100 % (Firmware) |
| SOC-Empfehlung Komfort | 25–75 % |
| SOC-Empfehlung Vollbetrieb | 5–100 % |
| Zellausgleich | 1× / Monat, benötigt SOC_MAX = 100 % |
| Modbus (M124) | StorCtl_Mod, InWRte, OutWRte, MinRsvPct, ChaGriSet |

**Nutzbare Energie nach SOC-Range:**

| SOC-Min | SOC-Max | kWh nutzbar |
|---|---|---|
| 5 % | 100 % | 8.9 kWh |
| 25 % | 75 % | 4.7 kWh |
| 5 % | 75 % | 6.6 kWh |
| 25 % | 100 % | 7.0 kWh |

### 2.2 E-Autos (Mobiler Speicher)

| Fahrzeug | Kapazität | Max. Laden | Typ | SOC-Quelle | Schutz-SOC |
|---|---|---|---|---|---|
| Renault Zoe 1 | 52 kWh | 22 kW AC | NMC | Schätzung | Max 85 % (NMC-Schutz) |
| Renault Zoe 2 | 52 kWh | 22 kW AC | NMC | Schätzung | Max 85 % (NMC-Schutz) |
| Citroën e-C4 | ~50 kWh | 11 kW AC | NMC | Schätzung | Max 85 % (NMC-Schutz) |

**E-Auto SOC-Schätzung (Workaround):**
```
soc_est = (kapazität_kwh - (soll_soc/100 * kapazität_kwh) +  geladene_kwh_session) / kapazität_kwh * 100
```
Ungenau durch Ladeverluste (~15–18 %), Kalibrierung aus Solarweb-Daten möglich.

**E-Auto Urgency Score (fuzzy, 0.0–1.0):**

| Situation | Score | Aktion |
|---|---|---|
| SOC > 85 % (NMC-Grenze) | 0.0 | Laden stoppen |
| SOC 70–85 % | 0.1–0.2 | Nur überschuss |
| SOC 50–70 % | 0.3–0.5 | Normal laden bei Überschuss |
| SOC 30–50 % | 0.5–0.7 | Priorisiert laden |
| SOC < 30 % | 0.8–0.9 | Notfall, notfalls Netzbezug |
| SOC < 15 % | 1.0 | Sofortladen, Netz akzeptabel |
| Fahrt in < 2 h bekannt | +0.3 | Zeitkritisch |

---

## 3. Steuerbare Verbraucher-Matrix

| Verbraucher | Leistung (el.) | Steuerungskanal | Reaktionszeit | Flexi-Grad | Status |
|---|---|---|---|---|---|
| Wattpilot E-Auto | 1.4–22 kW | WebSocket CMD | < 2 s | sehr hoch | ✅ aktiv |
| Dimplex WP SIK 11 | 2.1–4.3 kW | Modbus RTU (SG-Ready) | ~30 s | mittel | ⚠️ nicht integriert |
| Heizpatrone (geplant) | 2–4 kW | Fritz!DECT / Relais | < 5 s | hoch | ❌ nicht vorhanden |
| Klimaanlage (falls) | 0.5–2 kW | — | — | mittel | ❌ nicht vorhanden |

---

## 4. Beobachtungs-Matrix (Physikalische Parameter)

| Parameter | Kanal | Einheit | Polling | Für Automation |
|---|---|---|---|---|
| PV-Gesamtleistung | Modbus M103 | W | 5 s | Erzeuger-Überschuss |
| PV je String (MPPT) | Modbus M160 | W | 5 s | Strategie-Auswahl |
| Batterie SOC | M124 ChaState | % | 5 s | Lade-Algorithmen |
| Batterie SOH | HTTP API | % | 60 s | Kapazitätskalkulation |
| Batterie Temp | HTTP API BMS | °C | 60 s | Schutzregel T>40 |
| Netz-Leistung | Modbus M103 | W | 5 s | Bezug/Einspeisung |
| Haus-Verbrauch | Berechnung | W | 5 s | Lastprofile |
| SOC_MODE | HTTP API | string | 15 min | Modus-Verifikation |
| SOC_MIN / SOC_MAX | HTTP API | % | 15 min | Konsistenzprüfung |
| Wattpilot Leistung | WebSocket | W | 2 s | EV-Lastabwurf |
| Wolken | Open-Meteo | % | 15 min | Prognose |
| WP Leistung | Modbus RTU | W | — | ⚠️ fehlt |
| WW-Temperatur | MEGA-BAS Temp | °C | — | ⚠️ fehlt |

---

## 5. Netz-Matrix (Bezug und Einspeisung)

### 5.1 Anschlussparameter

| Parameter | Wert |
|---|---|
| Anschluss | 3-phasig (L1, L2, L3) |
| Nennspannung | 230 V / 400 V |
| **Hauptsicherung** | **3 × 40 A** |
| **Max. zulässige Gesamtleistung** | **3 × 40 A × 230 V = 27.6 kW** |
| Netzfrequenz normal | 50.0 Hz ± 0.2 Hz |
| Einspeisekonto | Netzbetreiber, kein Direktvermarkter |

### 5.2 Bezug (Import vom Netz) — Klassifikation

| Klasse | Situation | Größenordnung | Bewertung |
|---|---|---|---|
| Ausgleichs-kurz | Momentane PV-Schwankung, sofort ausgeglichen | < 1 kW, < 30 s | ✅ Normal, akzeptabel |
| Unvermeidbar-Nacht | Nacht, keine PV, Batterie entladen | 0.5–3 kW | ✅ Normal |
| Winter-Mangel | PV-Ertrag < Hausverbrauch | 0.5–5 kW | ✅ Normal |
| EV-Laden mit Netz | Wattpilot, kein PV-Überschuss | 1.4–22 kW | ⚠️ Teuer — Urgency prüfen |
| WP + EV gleichzeitig | Wärmepumpe + E-Auto | 6–26 kW | ⚠️ Überlastrisiko! |
| **KRITISCH: Überlast** | WP (4.3) + EV (22) + Haushalt (2) | **28.3 kW > 27.6 kW** | ❌ **HAUPTSICHERUNG** |

### 5.3 Überlastschutz — Hauptsicherung 3 × 40 A

> **⚠️ ACHTUNG:** Die Kombination Wattpilot-Max (22 kW) + Wärmepumpe-Max (4.3 kW) + Haushalt (2 kW) ergibt **28.3 kW** — das übersteigt die Hauptsicherung (27.6 kW).

**Schutzregel (deterministisch, nicht übersteuerbar):**

```
IF grid_bezug_w > 24000 THEN
    IF ev_power_w > 0 THEN
        wattpilot_reduzieren(target_w = max(1400, ev_power_w - (grid_bezug_w - 22000)))
    IF wp_power_w > 2000 AND ev_power_w == 0 THEN
        LOG WARN "WP-Leistung hoch, Netz-Sicherheit prüfen"
```

**Schwellen-Empfehlung:**

| Schwelle | Wert | Aktion |
|---|---|---|
| Warnung | > 22 kW Netzbezug | Log + Slack-Alert |
| Alarm | > 24 kW Netzbezug | Wattpilot drosseln  |
| Not-Stop | > 26 kW Netzbezug | Wattpilot auf 1.4 kW (Min) |

### 5.4 Einspeisung (Export ins Netz) — Klassifikation

| Klasse | Situation | Bewertung |
|---|---|---|
| Ausgleichs-kurz | PV-Peak > Sofortverbrauch, Batterie voll | ✅ Akzeptabel (kurz) |
| Strukturell | PV-Überschuss ohne Abnehmer über Stunden | ⚠️ Wirtschaftlich suboptimal |
| **NO-GO dauerhaft** | Einspeisung trotz leerem EV oder kaltem WW | ❌ Überschuss nicht genutzt |
| Technisch-Notfall | WR-Regelversagen, kein Verbraucher | ⚠️ Abnormale Situation |

> **Nulleinspeiser-Konzept** gilt für dieses System: Einspeisung ins Netz soll auf nahe-0 reduziert werden. Überschuss-Priorität:  
> 1. Batterie laden (bis SOC_MAX)  
> 2. Wattpilot aktivieren / erhöhen  
> 3. Wärmepumpe forcieren  
> 4. Erst dann: Export

**Einspeisung-Begrenzung bei Überproduktion:**

| Situation | Maßnahme |
|---|---|
| PV >> Verbrauch, Batterie voll, EV nicht da | F2 und/oder F3 abschalten (Modbus) |
| F1 muss für Batterie-Management laufen | F2 oder F3 via Modbus auf 0 drosseln |
| Alle WR unter Volllast, Netz-Export | Wattpilot auf Maximum hochsetzen (wenn EV da) |

### 5.5 Netz-Phasensymmetrie (F1 DC-Kopplung)

F1 (Gen24 12kW) ist 3-phasig angeschlossen. Die Batterie kompensiert auf allen 3 Phasen.
F2 und F3 sind ebenfalls 3-phasig. Asymmetrie entsteht nur durch Einphasen-Lasten im Haushalt.

| Parameter | Normal | Warnung |
|---|---|---|
| Phasen-Unsymmetrie Netz | < 3 A | > 10 A |
| Monitoring | Modbus M103 PhVphA–C | — |

---

## 6. Strategie-Matrix (geplant)

| Szenario | Erkennungsregel | Haupt-Aktion | Sekundär-Aktion |
|---|---|---|---|
| Klarer Sonnentag | cloud < 20 %, forecast > 30 kWh | SOC_MIN früh öffnen | Abend: SOC_MAX erst 17 Uhr |
| Wölkiger Tag | cloud 40–70 % | SOC_MIN halbwegs öffnen | Wattpilot-Solar-Tracking |
| Schlechter Tag | cloud > 80 % oder forecast < 5 kWh | Batterie halten (25 %) | Netzbezug-Optimierung |
| Zellausgleich | Bedingungen OK (SOC > 30, forecast > 50) | SOC_MAX = 100 %, Mode = manual | 1× / Monat |
| E-Auto Notfall | ev_urgency > 0.8 | EV-Laden forcieren (ggf. Netz) | Batterie-Entladung stoppen |
| WP SG-Ready (geplant) | PV_überschuss > 3 kW | WP SG-Ein | Warmwasser aufheizen |
| Überlast-Schutz | grid_bezug > 24 kW | Wattpilot drosseln | WP reduzieren (geplant) |

---

*Letzte Aktualisierung: 2026-02-20*  
*Verwandte Dokumente:* [BEOBACHTUNGSKONZEPT.md](BEOBACHTUNGSKONZEPT.md) · [SCHUTZREGELN.md](SCHUTZREGELN.md) · [FRONIUS_SOC_MODUS.md](FRONIUS_SOC_MODUS.md)
