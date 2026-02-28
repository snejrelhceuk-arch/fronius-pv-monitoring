# PV-CONFIG Handbuch

**Konfigurationsprogramm für die PV-Batterie-Automation**
Version 1.1 — Stand: 28. Februar 2026

---

## Inhaltsverzeichnis

1. [Starten und Navigation](#1-starten-und-navigation)
2. [Hauptmenü-Übersicht](#2-hauptmenü-übersicht)
3. [Menü 1: Regelkreise ein/aus](#3-menü-1-regelkreise-einaus)
4. [Menü 2: Parameter-Matrix](#4-menü-2-parameter-matrix)
   - [4.1 soc_schutz — Harte Schutzschwellen](#41-soc_schutz--harte-schutzschwellen-priorität-1)
   - [4.2 morgen_soc_min — Morgenöffnung](#42-morgen_soc_min--morgenöffnung-priorität-2)
   - [4.3 nachmittag_soc_max — Nachmittagsanhebung](#43-nachmittag_soc_max--nachmittagsanhebung-priorität-2)
   - [4.4 abend_entladerate — Nachtrationierung](#44-abend_entladerate--nachtrationierung-priorität-2)
   - [4.5 zellausgleich — Monatlicher Vollzyklus](#45-zellausgleich--monatlicher-vollzyklus-priorität-3)
   - [4.6 temp_schutz — Temperaturschutz](#46-temp_schutz--temperaturschutz-priorität-1)
   - [4.7 forecast_plausibilisierung — Prognosekorrektur](#47-forecast_plausibilisierung--prognosekorrektur-priorität-2)
   - [4.8 laderate_dynamisch — Dynamische Laderate](#48-laderate_dynamisch--dynamische-laderate-priorität-2)
   - [4.9 wattpilot_battschutz — EV-Ladeschutz](#49-wattpilot_battschutz--ev-ladeschutz-priorität-1)
5. [Menü 3: Batterie-Scheduler](#5-menü-3-batterie-scheduler)
6. [Menü 4: System-Status](#6-menü-4-system-status)
7. [Menü 5: Solar-Prognose](#7-menü-5-solar-prognose)
8. [Grundlagenwissen](#8-grundlagenwissen)

---

## 1. Starten und Navigation

```bash
# Per SSH auf den Raspberry Pi einloggen, dann:
cd ~/Dokumente/PVAnlage/pv-system
python3 pv-config.py
```

**Bedienung der Whiptail-Menüs:**
- **Pfeiltasten ↑↓** — Eintrag wählen
- **Leertaste** — Checkbox umschalten (in Checklisten)
- **Tab** — zwischen Menü und Buttons wechseln (OK / Abbrechen)
- **Enter** — Auswahl bestätigen
- **Esc** — Zurück / Abbrechen

**Statuszeile (blauer Hintergrund oben):**
Zeigt Live-Werte: PV-Leistung, Hausverbrauch, Netzfluss und Batterie-SOC.

---

## 2. Hauptmenü-Übersicht

| Eintrag | Funktion |
|---------|----------|
| Regelkreise | Automation-Regeln ein-/ausschalten |
| Parameter | Schwellwerte und Grenzen einzelner Regeln anpassen |
| Scheduler | Batterie-Aktionen: Status, Log, manuelle Übersteuerung |
| System | Systemzustand, Warnungen, Prozess-Status |
| Forecast | Solar-Prognose, Genauigkeit, Kalibrierung |
| Beenden | Programm schließen |

---

## 3. Menü 1: Regelkreise ein/aus

Zeigt alle Regelkreise als Checkliste. Ein Regelkreis ist entweder **aktiv** (●) oder **inaktiv** (○).

**Prioritäten:**
- **P1 — SICHERHEIT**: Immer aktiv lassen! Schützt die Hardware.
- **P2 — STEUERUNG**: Optimierungs-Regeln, können einzeln deaktiviert werden.
- **P3 — WARTUNG**: Periodische Aufgaben (z.B. Zellausgleich).

**Score-Gewicht:** Bei Konflikten zwischen Regelkreisen gewinnt der höhere Score. Beispiel: `morgen_soc_min` (Score 72) hat Vorrang über `abend_entladerate` (Score 65).

> **Warnung:** P1-Regeln (soc_schutz, temp_schutz, wattpilot_battschutz) sollten **niemals** deaktiviert werden. Sie verhindern Hardware-Schäden an der BYD HVS.

---

## 4. Menü 2: Parameter-Matrix

Hier werden die Schwellwerte jedes Regelkreises angepasst. Jeder Parameter hat:
- **Wert** — die aktuelle Einstellung
- **Bereich** — erlaubte Grenzen (werden geprüft, Eingabe außerhalb wird abgelehnt)
- **Einheit** — %, kWh, W, h, Faktor, Tage, usw.

### Namenskonventionen

Die Parameter-Kurzn im Menü lassen das Einheiten-Suffix weg:

| Im Menü | Entspricht JSON-Key | Bedeutung |
|---------|---------------------|-----------|
| stop_entladung_unter | stop_entladung_unter_pct | ...unter X **Prozent** |
| min_prognose | min_prognose_kwh | Mindest-Prognose in **kWh** |
| pv_bestaetigung | pv_bestaetigung_w | PV-Schwelle in **Watt** |

Die Einheit steht immer beim angezeigten Wert (z.B. `5%`, `100W`, `5.0kWh`).

---

### 4.1 soc_schutz — Harte Schutzschwellen (Priorität 1)

**Zweck:** Absolute SOC-Grenzen, die nie verletzt werden dürfen. Schützt die BYD-Zellen vor Tiefentladung und Überladung.

**Score:** 90 (höchster aller Regelkreise)
**Zyklus:** fast (jede Minute geprüft)

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| stop_entladung_unter | 7% | 0–20% | **Unter diesem SOC wird die Batterie-Entladung sofort gestoppt.** Das Haus bezieht dann komplett aus dem Netz. Schutz vor Tiefentladung bei LFP-Zellen. |
| drosselung_unter | 10% | 5–30% | **Unter diesem SOC wird die Entladerate auf 50% gedrosselt.** Die Batterie gibt weniger ab, damit sie langsamer sinkt. Bildet einen Puffer vor dem harten Stopp. |
| stop_ladung_ueber | 98% | 80–100% | **Über diesem SOC wird die Ladung gestoppt** (außer Zellausgleich). Schützt vor dauerhafter Vollladung, was bei LFP die Lebensdauer verlängert. |

**Empfehlungen:**
- `stop_entladung_unter`: 5–10% sind sinnvoll. Unter 5% kann die BYD in den Notaus gehen.
- `drosselung_unter`: Sollte 3–5% über `stop_entladung_unter` liegen.
- `stop_ladung_ueber`: 95–100%. Bei 100% findet kein Schutz statt (nur bei Zellausgleich relevant).

---

### 4.2 morgen_soc_min — Morgenöffnung (Priorität 2)

**Zweck:** Morgens die SOC-Untergrenze (SOC_MIN) von Komfort (25%) auf Stress (5%) senken, damit die Batterie vor der PV-Übernahme möglichst leer wird. So steht mittags maximale Kapazität zum Laden bereit.

**Score:** 72
**Zyklus:** fast

**Ablauf:** Sonnenaufgang → wolkenabhängige Wartezeit → PV-Bestätigung → SOC_MIN senken

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| komfort_min | 25% | 10–40% | **SOC_MIN im Normalzustand.** LFP-schonend: Die Batterie wird nie unter diesen Wert entladen, solange keine Regel sie "öffnet". Höher = konservativer (mehr Reserve), niedriger = mehr nutzbare Kapazität. |
| stress_min | 5% | 0–15% | **SOC_MIN bei Öffnung.** An Sonnentagen wird SOC_MIN auf diesen Wert gesenkt: Die Batterie darf morgens fast komplett entleert werden. **0% ist riskant** — die BYD kann abschalten. Empfohlen: 5%. |
| min_prognose | 5.0 kWh | 1–20 kWh | **Mindest-Tagesprognose, damit die Öffnung stattfindet.** Wenn der Forecast weniger als diesen Wert vorhersagt, bleibt SOC_MIN auf Komfort. An bewölkten Tagen (z.B. Prognose 3 kWh) wird nicht geöffnet, um Reserve zu behalten. **Höher = vorsichtiger**, nur an wirklich guten Tagen wird geöffnet. |
| pv_bestaetigung | 100 W | 50–500 W | **Live-PV-Schwelle.** Die Öffnung passiert erst, wenn tatsächlich PV-Leistung über diesem Wert gemessen wird. Verhindert, dass bei Nebel/Hochnebel blind geöffnet wird, obwohl die Sonne astronomisch schon da ist. Höher = konservativer. |
| wolken_klar | 30% | 10–50% | **Grenze "klarer Himmel".** Ist die vorhergesagte Bewölkung unter 30%, startet die Öffnung früh (10–30 Min. nach Sonnenaufgang). Höherer Wert = mehr Tage gelten als "klar". |
| wolken_schwer | 70% | 50–90% | **Grenze "bewölkt".** Über 70% Bewölkung: Spätere Öffnung (60–120 Min. nach Sunrise) oder gar keine Öffnung. Niedrigerer Wert = schon bei mittlerer Bewölkung vorsichtig. |
| morgen_soc_max | 75% | 50–85% | **SOC_MAX morgens begrenzen.** Verhindert, dass PV die Batterie in weniger als einer Stunde volllädt. PV-Überschuss geht stattdessen ins Netz. Nachmittags wird SOC_MAX dann auf 100% erhöht. Niedriger = mehr Einspeisung, höher = schnellere Batterieladung. |
| fenster_ende_nach_sunrise | 3 h | 1–5 h | **Ende des Morgen-Fensters.** Nach X Stunden nach Sonnenaufgang übernimmt der Nachmittag-Regelkreis. Längeres Fenster = mehr Zeit für die Morgenöffnung. |
| drain_rate_fallback | 1.5 kW | 0.5–4.0 kW | **Angenommene Entladerate wenn keine Verbrauchshistorie verfügbar.** Wird nur am ersten Tag nach Reset benötigt. |
| uebernahme_schwelle | 0.8 | 0.5–1.0 | **(Legacy, nicht mehr verwendet.)** PV muss x% des Verbrauchs decken. |
| max_vorlauf | 0.25 h | 0–2 h | **(Legacy, nicht mehr verwendet.)** |

**Typisches Szenario:**
1. 07:00 Sonnenaufgang, Prognose 25 kWh, Bewölkung 20%
2. → Wolken < 30% = "klar" → Offset 15 Min.
3. 07:15 PV = 150 W > 100 W Schwelle → **SOC_MIN wird von 25% auf 5% gesenkt**
4. Batterie entlädt sich auf ~5% durch Hausverbrauch
5. 10:00 PV übernimmt → Batterie wird geladen (SOC_MAX = 75%)

---

### 4.3 nachmittag_soc_max — Nachmittagsanhebung (Priorität 2)

**Zweck:** Nachmittags den SOC_MAX von 75% auf 100% anheben, damit die Batterie vor dem Abend voll wird. Der **Zeitpunkt** wird dynamisch aus dem Clear-Sky-Peak und der Prognose-Leistungskurve berechnet.

**Score:** 55 (mit Fuzzy-Rampe: 60%→95% des Scores nach dynamischem Start)
**Zyklus:** strategic (alle 5–15 Min.)

#### Algorithmus: Clear-Sky-Peak + Leistungsschwelle

```
1. Clear-Sky-Peak bestimmen (Stunde der max. Sonneneinstrahlung, z.B. 12:00h)
2. Im Prognose-Leistungsprofil ab Peak vorwärts laufen
3. Erste Stunde mit Prognoseleistung < effektive Schwelle → Öffnungszeit
4. Effektive Schwelle = oeffnungsschwelle_kw + EV avg30 + WP avg30
   (Großverbraucher erhöhen die Schwelle proportional)
5. Fallback bei fehlenden Daten: Sunset − 3h
```

**Fuzzy-Scoring:** Vor dem dynamischen Startzeitpunkt ist der Score = 0 (keine Aktion). Nach dem Start rampt der Score von 60% auf 95% des Maximalscores proportional zur verbleibenden Zeit bis Sunset. An der Deadline (max_stunden_vor_sunset) wird der volle Score (100%) erreicht.

**Verbraucher-Kontext:** Die 7 kW Basis-Schwelle wird um aktive Großverbraucher erhöht. Beispiel: EV lädt mit 11 kW (Avg30) → effektive Schwelle = 18 kW. Die Engine verwendet **30-Minuten-Mittelwerte** (statt Snapshots), um WP-Taktung und EV-Anlaufphasen zu glätten.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| komfort_max | 75% | 60–90% | **SOC_MAX im Normalzustand.** Die Batterie wird nicht über diesen Wert geladen. Überschüssige PV geht ins Netz (Einspeisung). Ideal für LFP-Lebensdauer: 75% = selten volle Zellen. Höher = mehr Eigenverbrauch, aber weniger Zellleben. |
| stress_max | 100% | 85–100% | **SOC_MAX bei Anhebung.** Vor dem Abend wird SOC_MAX auf diesen Wert erhöht, damit die Batterie möglichst voll in die Nacht geht. 100% = maximale Nachtreserve. |
| start_stunde | 11 h | 10–15 h | **Absolut frühester Start (Minimum).** SOC_MAX wird nie vor dieser Stunde geöffnet, auch bei schwachem Tag. Die tatsächliche Öffnung erfolgt meist deutlich später (dynamisch berechnet aus Clear-Sky-Peak). |
| oeffnungsschwelle_kw | 7 kW | 3–15 kW | **Leistungsschwelle für die Öffnungszeitberechnung.** Ab dem Clear-Sky-Peak sucht der Algorithmus vorwärts die erste Stunde, in der die Prognoseleistung unter diesen Wert sinkt. An dieser Stelle wird SOC_MAX geöffnet. Niedrigerer Wert = spätere Öffnung (mehr Einspeisung), höherer = frühere Öffnung (mehr Batterieladung). Wird automatisch um aktive Verbraucher erhöht (EV, WP). |
| surplus_sicherheitsfaktor | 1.3 | 1.0–2.0 | **(Legacy, noch in Matrix, nicht mehr primär verwendet.)** Der Clear-Sky-Peak-Algorithmus ersetzt die Surplus-Berechnung. |
| wolken_schwer | 85% | 60–100% | **Bewölkungsschwelle.** Ab dieser Bewölkung wird SOC_MAX **sofort** angehoben (ohne auf Surplus zu warten). Verhindert, dass an trüben Tagen die Batterie halbleer in die Nacht geht. |
| max_stunden_vor_sunset | 1.5 h | 0.5–3.0 h | **Deadline.** Spätestens X Stunden vor Sonnenuntergang wird SOC_MAX **in jedem Fall** angehoben. Sicherheitsnetz: Sorgt dafür, dass die Öffnung auch bei fehlenden Prognosedaten stattfindet. |

**Beispiel (sonniger Tag, 28. Feb):**
```
Clear-Sky-Peak:      12:00h
Prognose bei 15h:    8.2 kW > 7 kW → weiter
Prognose bei 16h:    5.7 kW < 7 kW → dyn_start = 16:00h
Score um 12:00h:     0   (vor dyn_start, keine Aktion)
Score um 16:00h:     33  (60% von 55, Rampe beginnt)
Score um 16:30h:     55  (Deadline, voller Score)
→ SOC_MAX wird um 16:00h von 75% auf 100% angehoben
```

**Zusammenspiel mit morgen_soc_min:**

| Phase | SOC_MIN | SOC_MAX | Effekt |
|-------|---------|---------|--------|
| Nacht (0–7h) | 25% | 75% | Komfort-Bereich, Batterie entlädt langsam |
| Morgen (7–12h) | **5%** | 75% | Batterie entleert sich, PV füllt bis 75% |
| Nachmittag (12–16h) | 5% | 75% | PV-Überschuss → Einspeisung (Batterie bei 75% gedeckelt) |
| Nachmittag (16–18h) | 5% | **100%** | SOC_MAX geöffnet → PV füllt Batterie komplett |
| Abend (18–0h) | zurück auf 25% | 100% | Volle Batterie versorgt den Abend |

---

### 4.4 abend_entladerate — Nachtrationierung (Priorität 2)

**Zweck:** Abends und nachts die Entladerate begrenzen, damit die Batterie den ganzen Abend/die ganze Nacht durchhält. Spitzenlasten (Kochen, Backofen) gehen ans Netz.

**Score:** 65
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| abend_start | 15 h | 13–18 h | **Start der Abend-Drosselung.** Ab dieser Uhrzeit wird die maximale Entladerate begrenzt. Früher = mehr Netzanteil am Nachmittag, aber Batterie hält länger. |
| abend_ende | 0 h | 0–2 h | **Ende der Abend-Phase** (0 = Mitternacht). |
| abend_rate | 29% | 10–80% | **Maximale Entladerate am Abend.** 29% der BYD HVS 10.24 kWh ≈ **3.0 kW**. Alles über 3 kW (z.B. Herd mit 4 kW) wird aus dem Netz bezogen. Niedriger = mehr Netzanteil, Batterie hält länger. Höher = mehr Eigenverbrauch, aber Batterie könnte vor Mitternacht leer sein. |
| nacht_start | 0 h | 0–2 h | **Start der Nacht-Phase.** |
| nacht_ende | 6 h | 4–8 h | **Ende der Nacht-Phase.** |
| nacht_rate | 10% | 0–30% | **Maximale Entladerate in der Nacht.** 10% ≈ **1.0 kW** — reicht für Standby-Last (Kühlschrank, Heizung, WLAN). Spart die letzten kWh für den Morgen. |
| kritisch_soc | 10% | 5–20% | **Entladesperre (Hold).** Unter diesem SOC wird die Batterie komplett gesperrt (0 W Entladung). Sicherheitsnetz damit die Batterie nie völlig leer wird. |

**Rechenbeispiel:**
- 18:00 Uhr: SOC = 80%, Kapazität 10.24 kWh × (80%–10%) = **7.2 kWh** nutzbar
- Abend-Rate 3 kW → 7.2 kWh ÷ 3 kW = **2.4 Stunden** bei Volllast
- Real: Grundlast ~400 W + Spitzen → Batterie hält bis ca. 2–4 Uhr nachts
- Nacht-Rate 1 kW → restliche kWh reichen für Standby bis Sonnenaufgang

---

### 4.5 zellausgleich — Monatlicher Vollzyklus (Priorität 3)

**Zweck:** Einmal im Monat die BYD-Batterie komplett laden (100%), damit das BMS einen Zellausgleich (Cell-Balancing) durchführen kann. LFP-Zellen brauchen das regelmäßig für korrekte SOC-Anzeige.

**Score:** 30 (niedrigster — wird von allen anderen Regeln überstimmt)
**Zyklus:** strategic

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| soc_min_waehrend | 5% | 0–10% | **SOC_MIN während des Zellausgleichs.** Bleibt niedrig, damit die Batterie den vollen Bereich nutzt. |
| soc_max_waehrend | 100% | 95–100% | **SOC_MAX während des Zellausgleichs.** Muss 100% sein, damit ein echtes Voll-Laden stattfindet. |
| min_prognose | 50 kWh | 20–80 kWh | **Mindest-PV-Prognose für den Tag.** 50 kWh = sehr sonniger Tag. Nur dann wird ein Vollzyklus ausgelöst, damit genug PV vorhanden ist. |
| notfall_min_prognose | 25 kWh | 10–50 kWh | **Gesenkte Schwelle nach Überschreitung von max_tage.** Wenn seit 45+ Tagen kein Ausgleich stattfand, wird die Schwelle gesenkt. |
| max_tage_ohne_ausgleich | 45 Tage | 20–90 Tage | **Notfall-Frist.** Nach X Tagen wird die Prognoseschwelle gesenkt, auch an mittelmäßigen Tagen wird dann ein Ausgleich versucht. |
| fruehester_tag | 1 | 1–10 | **Frühester Monatstag** für den Zellausgleich. |
| spaetester_tag | 28 | 20–31 | **Spätester regulärer Monatstag.** Danach wird auf nächsten Monat verschoben (es sei denn, max_tage ist überschritten). |

**Hinweis:** An Wintertagen mit nur 5–10 kWh Erzeugung wird die 50-kWh-Schwelle nie erreicht. Dann greift nach 45 Tagen die Notfall-Schwelle (25 kWh).

---

### 4.6 temp_schutz — Temperaturschutz (Priorität 1)

**Zweck:** Die Laderate stufenweise reduzieren, wenn die Batterie-Zelltemperatur steigt. Ergänzt den harten Tier-1-Interrupt (der ab 45°C die Ladung komplett stoppt).

**Score:** 70
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| stufe_25c | 100% | 80–100% | **Laderate bei ≥25°C.** Normal, volle Leistung. |
| stufe_30c | 80% | 50–100% | **Laderate bei ≥30°C.** Leichte Drosselung. Realistisch an heißen Sommertagen, wenn die Batterie im gewärmten Technikraum steht. |
| stufe_35c | 68% | 30–80% | **Laderate bei ≥35°C.** Deutliche Drosselung. Die Batterie wird langsamer geladen, PV-Überschuss geht ins Netz. |
| stufe_40c | 50% | 20–70% | **Laderate bei ≥40°C (Tier-2).** Starke Drosselung. Der Tier-1-Interrupt greift ab 45°C und stoppt komplett. |

**Hinweis:** Im Winter (Batterie bei 15–20°C) greift keine dieser Stufen. Relevant nur im Hochsommer.

---

### 4.7 forecast_plausibilisierung — Prognosekorrektur (Priorität 2)

**Zweck:** Die Tagesprognose mit der tatsächlichen PV-Erzeugung vergleichen und bei Abweichung die Rest-Prognose reduzieren. Verhindert, dass optimistische Prognosen zu falschen Entscheidungen führen.

**Score:** 50
**Zyklus:** strategic

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| abweichung_schwelle | 70% | 30–90% | **IST/SOLL-Verhältnis, ab dem korrigiert wird.** Wenn die tatsächliche PV-Erzeugung unter 70% der Prognose liegt, wird die Rest-Prognose reduziert. Höher = schneller korrigieren (konservativer). |
| korrektur_faktor | 0.7 | 0.3–1.0 | **Reduktionsfaktor.** Rest-Prognose × 0.7 wenn die Schwelle unterschritten ist. Niedriger = stärkere Korrektur. |
| min_betriebsstunden | 2.0 h | 0.5–4.0 h | **Karenzzeit.** Erst nach X Stunden Sonnenlicht wird plausibilisiert. Am frühen Morgen ist die Prognose naturgemäß noch ungenau. |
| cloud_rest_schwer | 80% | 50–100% | **Zusätzliche Wolken-Korrektur.** Wenn die Resttag-Bewölkung über 80% liegt, wird ein zusätzlicher Reduktionsfaktor angewendet. |
| cloud_reduktion_faktor | 0.6 | 0.3–0.9 | **Zusätzlicher Reduktionsfaktor bei schwerer Bewölkung.** Rest-Prognose × 0.6 on top. |

**Beispiel:**
- Prognose: 30 kWh, um 12:00 erst 5 kWh erzeugt (IST/SOLL = 33%)
- 33% < 70% → Rest-Prognose = (30 - 5) × 0.7 = **17.5 kWh** statt 25 kWh
- Nachmittag-Regel verwendet diesen korrigierten Wert → erhöht SOC_MAX früher

---

### 4.8 laderate_dynamisch — Dynamische Laderate (Priorität 2)

**Zweck:** Die Laderate kontextabhängig begrenzen, um Netzüberlast zu vermeiden und die Batterie schonend zu laden.

**Score:** 45
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| komfort_max_laderate | 80% | 50–100% | **Maximale Laderate im Komfort-Bereich** (SOC 25–75%). LFP-schonend: Statt mit vollen 10 kW nur mit 8 kW laden. Verlängert Zellleben. |
| stress_max_laderate | 100% | 80–100% | **Maximale Laderate im Stress-Bereich.** Wenn die Batterie schnell gefüllt werden muss (z.B. vor Sonnenuntergang), wird volle Leistung erlaubt. |
| wp_aktiv_reduktion | 60% | 30–90% | **Laderate wenn Wärmepumpe gleichzeitig läuft.** Die WP zieht bis zu 3 kW. Um Netzüberlast zu vermeiden, wird die Batterie-Laderate auf 60% begrenzt: PV versorgt WP + Batterie gleichzeitig. |
| pv_min_fuer_vollladung | 5000 W | 2000–10000 W | **Mindest-PV-Leistung für volle Laderate.** Unter 5000 W PV wird die Laderate proportional reduziert, damit nicht aus dem Netz geladen wird. |

---

### 4.9 wattpilot_battschutz — EV-Ladeschutz (Priorität 1)

**Zweck:** Schützt die Batterie vor Tiefentladung durch EV-Ladung mit dem Fronius WattPilot (bis zu 22 kW). Ohne Schutz würde die Batterie versuchen, das E-Auto zu speisen und wäre in wenigen Minuten leer.

**Score:** 60
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| ev_leistung_schwelle | 2000 W | 500–5000 W | **Mindest-EV-Leistung damit die Regel greift.** Erst ab 2 kW EV-Ladung wird die Batterie geschützt. Unter 2 kW ist die Last unkritisch. |
| soc_drosselung_ab | 50% | 30–70% | **SOC-Schwelle für Drosselung.** Unter diesem SOC wird die Entladerate reduziert wenn ein EV lädt. Verhindert schnelle Tiefentladung. |
| entladerate_reduziert | 30% | 10–50% | **Reduzierte Entladerate.** ≈ 0.3C bei 10.24 kWh → ca. 3 kW max. Die Batterie gibt nur Grundlast ab, das EV wird primär aus PV/Netz versorgt. |
| soc_min_puffer | 5% | 3–15% | **SOC_MIN-Anhebung.** Wenn SOC innerhalb dieses Puffers über SOC_MIN liegt, wird SOC_MIN temporär angehoben. Verhindert Grenzwert-Oszillation. |
| soc_min_netz | 25% | 15–40% | **SOC_MIN bei Netzumstellung.** Wenn die Batterie zu stark beansprucht wird, wird SOC_MIN auf diesen Wert gesetzt → Batterie hält 25% Reserve und das Haus bezieht aus dem Netz. |
| wolken_toleranz | 300 s | 60–600 s | **Wolkentoleranz.** Kurze PV-Einbrüche (Wolkendurchgang) werden X Sekunden lang toleriert, bevor die Schutzregel greift. Verhindert Flip-Flop bei wechselnder Bewölkung. |

---

## 5. Menü 3: Batterie-Automation

Direkter Zugriff auf die Batterie-Automation und manuelle Übersteuerung.

> **Hinweis (Stand 2026-02-28):** Die Batterie-Steuerung läuft über
> `pv-automation.service` (systemd). Der alte `battery_scheduler.py` via
> Cron ist **deaktiviert** und durch die neue Score-basierte Engine ersetzt.

| Eintrag | Funktion |
|---------|----------|
| **Status anzeigen** | Aktueller Automations-Zustand: aktiver Regelkreis, Score, SOC-Werte, Batterie-Leistung |
| **Letzte Aktionen (24h)** | Log der letzten 20 Engine-Aktionen aus `automation_log` |
| **SOC_MIN Override → 5%** | SOC_MIN sofort auf 5% setzen (Modus wird auf "manual" gestellt) |
| **SOC_MAX Override → 100%** | SOC_MAX sofort auf 100% setzen (Modus wird auf "manual") |
| **SOC auf Komfortwerte** | SOC_MIN und SOC_MAX auf die Komfort-Werte aus der Matrix zurücksetzen (Modus: manual) |
| **SOC auf auto (5–100%)** | SOC_MIN=5%, SOC_MAX=100% setzen, dann Modus auf "auto" → Wechselrichter steuert selbständig |

**Wichtig:** Bei "manual" setzt die Engine die Werte aktiv. Bei "auto" steuert der Fronius Gen24 selbst — die Automation hat dann keine Kontrolle. Manuelle Overrides werden von der Engine im nächsten Zyklus (≤1 Min. fast, ≤15 Min. strategic) überschrieben, wenn der Regelkreis aktiv ist.

---

## 6. Menü 4: System-Status

Zeigt den Gesamtzustand des PV-Systems:

| Eintrag | Beschreibung |
|---------|--------------|
| **Systemcheck** | Alle Dienste prüfen: Collector, Web-API, Scheduler, DB-Größe |
| **Warnungen** | Aktuelle Probleme: fehlende Prozesse, alte Daten, Matrix-Fehler |
| **DB-Status** | SQLite-Datenbankgröße und letzte Einträge |
| **Prozesse** | Laufende Python-Prozesse des PV-Systems |
| **Letzte Aggregate** | Zeitstempel der letzten erfolgreichen Aggregation |

---

## 7. Menü 5: Solar-Prognose

| Eintrag | Beschreibung |
|---------|--------------|
| **Tagesprognose heute** | Erwartete kWh, Wetter, Bewölkung, Sunrise/Sunset, stundenweise Aufschlüsselung, IST-Vergleich |
| **Forecast-Genauigkeit** | Vergleich IST vs. Prognose der letzten 7 Tage mit Abweichung in Prozent |
| **Letzte Kalibrierung** | Status der Solar-Kalibrierung (Korrekturfaktoren, letzte Aktualisierung) |

---

## 8. Grundlagenwissen

### SOC-Bereiche der BYD HVS 10.24 (LFP)

```
  0%  ████░░░░░░░░░░░░░░░░  25% ████████████░░░░  75% ████████████████  100%
      │  Gefahr  │  Stress  │     Komfort      │  Stress  │   Voll   │
      │ Tiefentl │ geöffnet │ LFP-optimal      │ begrenzt │ nur bei  │
      │          │          │ ~3000 Zyklen      │          │ Zellausg │
```

- **Komfort (25–75%):** Idealer Betriebsbereich für LFP. Maximale Zyklenlebensdauer.
- **Stress unten (5–25%):** Wird morgens geöffnet wenn genug PV prognostiziert ist.
- **Stress oben (75–100%):** Wird nachmittags geöffnet um Abendreserve aufzubauen.
- **Gefahr (<5%):** BYD kann in den Notaus gehen. `soc_schutz` verhindert das.

### Prioritäten und Score-Konflikte

Bei gleichzeitig aktiven Regeln entscheidet der Score:

| Regelkreis | Score | Priorität |
|------------|-------|-----------|
| soc_schutz | 90 | P1 Sicherheit |
| morgen_soc_min | 72 | P2 Steuerung |
| temp_schutz | 70 | P1 Sicherheit |
| abend_entladerate | 65 | P2 Steuerung |
| wattpilot_battschutz | 60 | P1 Sicherheit |
| nachmittag_soc_max | 55 | P2 Steuerung |
| forecast_plausibilisierung | 50 | P2 Steuerung |
| laderate_dynamisch | 45 | P2 Steuerung |
| zellausgleich | 30 | P3 Wartung |

**Beispiel:** Wenn `morgen_soc_min` (72) SOC_MIN auf 5% setzen will und `wattpilot_battschutz` (60) SOC_MIN auf 25% anheben will, gewinnt die Morgenöffnung — es sei denn, die EV-Ladung bringt den SOC unter die Schutzschwelle (Score 90).

### Einheiten-Referenz

| Suffix/Einheit | Bedeutung | Beispiel |
|----------------|-----------|----------|
| % | Prozent (SOC, Rate, Bewölkung) | `stop_entladung_unter = 7%` |
| kWh | Kilowattstunden (Energie) | `min_prognose = 5.0 kWh` |
| W | Watt (Leistung) | `pv_bestaetigung = 100 W` |
| h | Stunde (Uhrzeit oder Dauer) | `abend_start = 15 h` = 15:00 Uhr |
| Faktor | Multiplikator (0.0–2.0) | `korrektur_faktor = 0.7` = 70% |
| Tage | Kalender-Tage | `max_tage_ohne_ausgleich = 45` |
| Tag | Monatstag (1–31) | `fruehester_tag = 1` |
| s | Sekunden | `wolken_toleranz = 300 s` = 5 Min. |

### Hardware-Referenz

| Parameter | Wert |
|-----------|------|
| Batterie | BYD HVS 10.2 (LFP) |
| Kapazität | 10.24 kWh |
| Max. Ladeleistung | 10.24 kW (1C) |
| Max. Entladeleistung | 10.24 kW (1C) |
| PV-Anlage | 37.59 kWp (3 Strings) |
| WR-Limit | 26.5 kW (3× Fronius Gen24) |
| Chemie | LiFePO₄ (LFP) |
