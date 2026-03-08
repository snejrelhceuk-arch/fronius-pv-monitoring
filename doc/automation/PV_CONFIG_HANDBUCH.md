# PV-CONFIG Handbuch

**Konfigurationsprogramm für die PV-Batterie-Automation**
Version 1.5 — Stand: 8. März 2026

---

## Inhaltsverzeichnis

1. [Starten und Navigation](#1-starten-und-navigation)
2. [Hauptmenü-Übersicht](#2-hauptmenü-übersicht)
3. [Menü 1: Regelkreise ein/aus](#3-menü-1-regelkreise-einaus)
4. [Menü 2: Parameter-Matrix](#4-menü-2-parameter-matrix)
   - [4.0 soc_extern — SOC-Extern-Toleranz](#40-soc_extern--soc-extern-toleranz)
   - [4.1 soc_schutz — Harte Schutzschwellen](#41-soc_schutz--harte-schutzschwellen-priorität-1)
   - [4.1a sls_schutz — SLS-Netzschutz 35A/Phase](#41a-sls_schutz--sls-netzschutz-35aphase-priorität-1)
   - [4.2 morgen_soc_min — Morgenöffnung](#42-morgen_soc_min--morgenöffnung-priorität-2)
   - [4.3 nachmittag_soc_max — Nachmittagsanhebung](#43-nachmittag_soc_max--nachmittagsanhebung-priorität-2)
   - [4.4 ~~abend_entladerate~~ — ENTFERNT](#44-abend_entladerate--entfernt)
   - [4.5 zellausgleich — Monatlicher Vollzyklus](#45-zellausgleich--monatlicher-vollzyklus-priorität-3)
   - [4.6 ~~temp_schutz~~ — ENTFERNT](#46-temp_schutz--entfernt)
   - [4.7 forecast_plausibilisierung — Prognosekorrektur](#47-forecast_plausibilisierung--prognosekorrektur-priorität-2)
   - [4.8 ~~laderate_dynamisch~~ — ENTFERNT](#48-laderate_dynamisch--entfernt)
   - [4.9 wattpilot_battschutz — EV-Ladeschutz](#49-wattpilot_battschutz--ev-ladeschutz-priorität-1)
   - [4.10 heizpatrone — HP-Burst-Steuerung](#410-heizpatrone--hp-burst-steuerung-priorität-2)
5. [Menü 3: Batterie-Automation](#5-menü-3-batterie-automation)
6. [Menü 4: System-Status](#6-menü-4-system-status)
7. [Menü 5: Solar-Prognose](#7-menü-5-solar-prognose)
8. [Menü 6: Heizpatrone (Fritz!DECT)](#8-menü-6-heizpatrone-fritzdect)
9. [Grundlagenwissen](#9-grundlagenwissen)

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
| Heizpatrone | Fritz!DECT-Steckdose: Status, Konfiguration, Test, manuell EIN/AUS |
| Beenden | Programm schließen |

---

## 3. Menü 1: Regelkreise ein/aus

Zeigt alle Regelkreise als Checkliste. Ein Regelkreis ist entweder **aktiv** (●) oder **inaktiv** (○).

**Prioritäten:**
- **P1 — SICHERHEIT**: Immer aktiv lassen! Schützt die Hardware.
- **P2 — STEUERUNG**: Optimierungs-Regeln, können einzeln deaktiviert werden.
- **P3 — WARTUNG**: Periodische Aufgaben (z.B. Zellausgleich).

**Score-Gewicht:** Bei Konflikten zwischen Regelkreisen gewinnt der höhere Score. Beispiel: `morgen_soc_min` (Score 72) hat Vorrang über `wattpilot_battschutz` (Score 60).

> **Warnung:** Die P1-Regel `wattpilot_battschutz` sollte **niemals** deaktiviert werden. Sie verhindert Tiefentladung durch EV-Ladung.
> *(Die ehemaligen P1-Regeln `soc_schutz` und `temp_schutz` wurden am 2026-03-07 entfernt — Lade-/Entladeraten-Begrenzung ist wirkungslos, da der GEN24 DC-DC-Konverter bei ~22 A HW-limitiert. Tier-1-Alarme bleiben aktiv.)*

**Heizpatrone (P2) deaktivieren:** Wird der HP-Regelkreis deaktiviert, werden keine neuen Bursts/Drains mehr gestartet. Der **Notaus-Pfad bleibt immer aktiv** — eine manuell oder per Burst eingeschaltete HP wird beim nächsten Zyklus sicher abgeschaltet (Burst-Timer, Netzbezug, Entladung). Die HP bleibt also nicht "vergessen" eingeschaltet.

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

### 4.0 soc_extern — SOC-Extern-Toleranz

**Zweck:** Wenn SOC_MIN oder SOC_MAX manuell in der Fronius App (oder einem anderen externen Tool) geändert werden, respektiert die Engine diese Werte für eine konfigurierbare Toleranzzeit. Das verhindert, dass die Automation sofort überschreibt.

**Muster:** Analog zur Heizpatronen-Extern-Erkennung (§4.10 `extern_respekt`). Die Engine erkennt automatisch, ob eine SOC-Änderung von ihr selbst oder extern stammt.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|--------|
| extern_respekt | 1800 s | 0–7200 s | **Toleranzzeit bei extern geänderten SOC-Werten (30 Min).** Alle SOC-Steuerungsregeln (morgen_soc_min, nachmittag_soc_max, komfort_reset, forecast_plausi, zellausgleich) pausieren für diese Dauer. Schutzregeln (soc_schutz, temp_schutz) sind NICHT betroffen. 0 = deaktiviert. |

**Sicherheit:** Tier-1-Checks (Temperatur, SOC) setzen weiterhin Alarm-Flags. Direkte Modbus-Aktionen (Lade-/Entladeraten) wurden am 2026-03-07 entfernt — der GEN24 DC-DC-Konverter begrenzt bei ~22 A hardwareseitig. Batterie-Schutz erfolgt über SOC_MIN/SOC_MAX (HTTP-API).

**Erkennungsmechanik:** Der `SocExternTracker` (Singleton in `soc_extern.py`) vergleicht pro Engine-Zyklus SOC_MIN/SOC_MAX mit den vorherigen Werten. Änderungen werden als Engine-intern erkannt wenn die Engine kurz zuvor ein Kommando mit diesem Zielwert registriert hat (Grace-Window: 5 Min). Alle anderen Änderungen → extern → Toleranzperiode startet.

---

### 4.1 soc_schutz — Tier-1-Alarmschwellen (ehem. Priorität 1)

**Zweck:** Absolute SOC-Grenzen für Tier-1-Alarme. Tier-1 setzt Alarm-Flags bei Schwellwert-Verletzung; der aktive Batterie-Schutz erfolgt über SOC_MIN/SOC_MAX der Steuerungsregeln.

> **Hinweis (2026-03-07):** Die Regel `RegelSocSchutz` (Score 90, Modbus-basierte Lade-/Entladeraten-Steuerung) wurde entfernt. Grund: GEN24 DC-DC ~22 A HW-Limit macht Software-Ratenlimits wirkungslos. Die Parameter `stop_entladung_unter` und `stop_ladung_ueber` werden weiterhin als Tier-1-Alarmschwellen genutzt. `drosselung_unter` wurde entfernt.

**Zyklus:** fast (jede Minute geprüft)

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| stop_entladung_unter | 7% | 0–20% | **Unter diesem SOC wird ein Tier-1-Alarm gesetzt.** Steuerungsregeln (morgen_soc_min, komfort_reset) verwenden ihren eigenen SOC_MIN ≥ 5%, der die BYD vor Tiefentladung schützt. |
| stop_ladung_ueber | 98% | 80–100% | **Über diesem SOC wird ein Tier-1-Alarm gesetzt** (außer Zellausgleich). Steuerungsregeln setzen SOC_MAX ≤ 100%. |

**Empfehlungen:**
- `stop_entladung_unter`: 5–10% sind sinnvoll. Unter 5% kann die BYD in den Notaus gehen.
- `stop_ladung_ueber`: 95–100%. Bei 100% findet kein Alarm statt.

---

### 4.1a sls_schutz — SLS-Netzschutz 35A/Phase (Priorität 1)

**Zweck:** Überwacht die Phasenströme am Netz-SmartMeter (F1) und schützt vor Auslösung des SLS (Selektiver Leitungsschutzschalter) am Zählerplatz.

**Hintergrund:** Der SLS ist 35A/3-phasig. Maximale Gesamtleistung: √3 × 400V × 35A ≈ 24 kW. Der SLS ist **träge** — 35A je Phase als Schwelle reicht aus. Er löst **ohne Vorwarnung** aus.

**Score:** 95 (× 1.5 = 142 bei Auslösung — höchster Score aller Regeln)
**Zyklus:** fast
**Implementierung:** `RegelSlsSchutz` in `automation/engine/regeln/schutz.py`

> **Hinweis:** Diese Regel ist als Schutzregel (`'schutz'` im Namen) immer aktiv und wird parallel zu allen anderen Regeln ausgeführt. Sie kann **nicht deaktiviert** werden.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| sls_strom_max | 35.0 A | 25–40 A | **SLS-Auslösestrom je Phase** (L1N, L2N, L3N). Primärer Trigger: max(I_L1, I_L2, I_L3) > 35A. SLS ist träge — 35A exakt reicht. |
| sls_leistung_max | 24000 W | 18000–26000 W | **Fallback-Gesamtleistung** (√3 × 400V × 35A ≈ 24 kW). Wird nur verwendet wenn Phasenströme nicht verfügbar sind (SmartMeter-Ausfall). |

**Messung:** Phasenströme I_L1_Netz, I_L2_Netz, I_L3_Netz aus dem Fronius SmartMeter (Netz, am Zählerplatz F1). Datenfluss: raw_data → DataCollector → ObsState.i_l1_netz_a / i_l2_netz_a / i_l3_netz_a → RegelSlsSchutz.

**Aktionen bei Auslösung:**
1. HP AUS (fritzdect) — Sicherheitshalber, falls wider Erwarten noch an
2. Wattpilot auf Minimum dimmen (wattpilot) — bei EV > 1500W
3. E-Mail-Benachrichtigung (`sls_ueberlast`) — 1×/Tag via EventNotifier

**Warum per-Phase und nicht Gesamt?** Der SLS löst je Phase aus. Eine asymmetrische Last (HP auf L1, EV auf L2) kann eine Phase überlasten, obwohl die Gesamt-leistung unter 24 kW liegt. Siehe [STEUERUNGSPHILOSOPHIE.md](STEUERUNGSPHILOSOPHIE.md) §2.

**Empfehlung:** Diesen Wert nicht ändern, solange kein SLS-Austausch stattfindet.

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
| morgen_vorlauf | 15 min | 0–60 min | **Morgen-Vorlauf.** Die gesamte Morgen-Mechanik (Forecast-Fetch, SOC_MIN-Zeitfenster, Verzögerungsberechnung) wird um X Minuten vor Sunrise vorgezogen. Sorgt dafür, dass die Prognose und SOC-Entscheidung früher verfügbar sind. 0 = kein Vorlauf. |
| drain_rate_fallback | 1.5 kW | 0.5–4.0 kW | **Angenommene Entladerate wenn keine Verbrauchshistorie verfügbar.** Wird nur am ersten Tag nach Reset benötigt. |
| uebernahme_schwelle | 0.8 | 0.5–1.0 | **(Legacy, nicht mehr verwendet.)** PV muss x% des Verbrauchs decken. |

**Typisches Szenario (morgen_vorlauf = 15 min):**
1. 06:45 Sunrise in 15 Min. → Forecast-Fetch wird getriggert (Vorlauf)
2. 06:45 Prognose 25 kWh, Bewölkung 20% → Zeitfenster ab 06:45 offen
3. 06:50 PV@SR+1h = 2000 W > 1500 W Schwelle → **SOC_MIN wird von 25% auf 5% gesenkt**
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
| abend_rate | 29% | 10–80% | **Maximale Entladerate am Abend.** 29% der 2× BYD HVS 20,48 kWh ≈ **5.9 kW**. Alles darüber wird aus dem Netz bezogen. Niedriger = mehr Netzanteil, Batterie hält länger. Höher = mehr Eigenverbrauch, aber Batterie könnte vor Mitternacht leer sein. ⚠️ *Regel aktuell deaktiviert (März 2026).* |
| nacht_start | 0 h | 0–2 h | **Start der Nacht-Phase.** |
| nacht_ende | 6 h | 4–8 h | **Ende der Nacht-Phase.** |
| nacht_rate | 10% | 0–30% | **Maximale Entladerate in der Nacht.** 10% ≈ **1.0 kW** — reicht für Standby-Last (Kühlschrank, Heizung, WLAN). Spart die letzten kWh für den Morgen. |
| kritisch_soc | 10% | 5–20% | **Entladesperre (Hold).** Unter diesem SOC wird die Batterie komplett gesperrt (0 W Entladung). Sicherheitsnetz damit die Batterie nie völlig leer wird. |

**Rechenbeispiel:**
- 18:00 Uhr: SOC = 80%, Kapazität 20.48 kWh × (80%–10%) = **14.3 kWh** nutzbar
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

### 4.6 ~~temp_schutz~~ — ENTFERNT

> **Entfernt am 2026-03-07.** Die Regel `RegelTempSchutz` (Score 70) wurde komplett entfernt.
> **Grund:** Laderate-Begrenzung via SunSpec Model 124 (InWRte/StorCtl_Mod) ist wirkungslos — der GEN24 DC-DC-Konverter limitiert bei ~22 A hardwareseitig. Tier-1 überwacht weiterhin die Zelltemperatur und setzt **Alarm-Flags** bei Überschreitung (≥45 °C), führt aber keine Modbus-Aktionen mehr aus.
> **Parameter:** `stufe_25c`, `stufe_30c`, `stufe_35c`, `stufe_40c` — alle deprecated in `battery_control.json`.

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

### 4.8 ~~laderate_dynamisch~~ — ENTFERNT

> **Entfernt am 2026-03-07.** Die Regel `RegelLaderateDynamisch` (Score 45) wurde komplett entfernt.
> **Grund:** Laderate-Begrenzung via SunSpec Model 124 ist wirkungslos — der GEN24 DC-DC-Konverter limitiert bei ~22 A (~9,5 kW) hardwareseitig, was unter dem BMS-Nennwert von 1C (20,48 kW) liegt. Eine zusätzliche Software-Drosselung bringt keinen Nutzen.
> **Parameter:** `komfort_max_laderate`, `stress_max_laderate`, `wp_aktiv_reduktion`, `pv_min_fuer_vollladung` — alle deprecated in `battery_control.json`.

---

### 4.9 wattpilot_battschutz — EV-Ladeschutz (Priorität 1)

**Zweck:** Schützt die Batterie vor Tiefentladung durch EV-Ladung mit dem Fronius WattPilot (bis zu 22 kW). Ohne Schutz würde die Batterie versuchen, das E-Auto zu speisen und wäre in wenigen Minuten leer. Schutz erfolgt ausschließlich über SOC_MIN-Anhebung (2 Stufen).

> **Hinweis (2026-03-07):** Die ehemalige Stufe 2 (Entladeraten-Drosselung via `soc_drosselung_ab`/`entladerate_reduziert`) wurde entfernt — GEN24 DC-DC ~22 A HW-Limit macht Software-Ratenlimits wirkungslos. Die verbleibenden 2 Stufen arbeiten mit SOC_MIN-Anhebung.

**Score:** 60
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| ev_leistung_schwelle | 2000 W | 500–5000 W | **Mindest-EV-Leistung damit die Regel greift.** Erst ab 2 kW EV-Ladung wird die Batterie geschützt. Unter 2 kW ist die Last unkritisch. |
| soc_min_puffer | 5% | 3–15% | **SOC_MIN-Anhebung.** Wenn SOC innerhalb dieses Puffers über SOC_MIN liegt, wird SOC_MIN temporär angehoben. Verhindert Grenzwert-Oszillation. |
| soc_min_netz | 25% | 15–40% | **SOC_MIN bei Netzumstellung.** Wenn die Batterie zu stark beansprucht wird, wird SOC_MIN auf diesen Wert gesetzt → Batterie hält 25% Reserve und das Haus bezieht aus dem Netz. |
| wolken_toleranz | 300 s | 60–600 s | **Wolkentoleranz.** Kurze PV-Einbrüche (Wolkendurchgang) werden X Sekunden lang toleriert, bevor die Schutzregel greift. Verhindert Flip-Flop bei wechselnder Bewölkung. |

---

### 4.10 heizpatrone — HP-Burst-Steuerung (Priorität 2)

**Zweck:** Heizpatrone (2 kW) im Warmwasserspeicher über eine Fritz!DECT-Steckdose einschalten, wenn die PV-Anlage deutlich mehr erzeugt als Batterie und Haus benötigen — gesteuert über Batterie-Ladeleistung und Solar-Prognose.

**Score:** 40
**Zyklus:** fast
**Aktor:** `fritzdect` (Fritz!Box AHA-HTTP-API)

**Warum nicht P_PV oder SOC als Trigger?**
- **Nulleinspeiser:** Der Fronius-Wechselrichter drosselt PV, sobald Batterie+Haus gesättigt sind. `P_PV` zeigt dann nicht die wahre Sonnenleistung.
- **SOC_MAX ≈ 75%:** Die Batterie wird aus Langlebigkeitsgründen selten über 75% geladen. SOC ≥ 90% ist praktisch unerreichbar.
- **Batterie-Ladeleistung (`batt_power_w`)** ist der zuverlässige Indikator: Wenn die Batterie mit >5 kW lädt, hat die Anlage echten Überschuss.

**6-Phasen-Logik:**

| Phase | Bedingung | Burst-Dauer | Zweck |
|-------|-----------|-------------|-------|
| **0 — Morgen-Drain** | ab sunrise−1h, SOC > 20%, Prognose gut, Forecast ≥ 4 kW | 45 Min. | Batterie gezielt leeren — Warmwasser als Senke |
| **1 — Vormittag** | rest_h > 5, rest_kwh > 20, P_Batt > 3 kW (initial) / > 1 kW (Wiedereintritt) | 30 Min. | Langer Tag, großzügig Warmwasser machen |
| **1b — Nulleinspeiser-Probe** | SOC ≈ MAX, Batt idle, Forecast ≥ HP-Last | 120 s (Probe) → 30 Min. bei Erfolg | WR-Drosselung erkennen, stille PV-Kapazität nutzen |
| **2 — Mittags** | P_Batt > min_lade, rest_kwh deckt Batt + Reserve | 30 Min. | Hauptphase bei Batterie-Sättigung |
| **3 — Nachmittags** | rest_h < 3 und ≥ 2, konservativ | 15 Min. | Kurze Restzeit → nur kurze Bursts |
| **4 — Abend** | rest_h < 2, SOC ≈ MAX, PV ≥ 1500W | 15 Min. (kurz) | Nachladezyklus: EIN/AUS nach SOC-Nähe zu MAX |

**Phase 0 (Morgen-Drain) im Detail:**

Wenn `morgen_soc_min` den SOC_MIN früh auf 5% öffnet, entlädt sich die Batterie durch den Hausverbrauch. Bei niedrigem Verbrauch (z.B. 500 W) dauert das sehr lange. Phase 0 schaltet die HP gezielt ein, um die Batterie schneller zu leeren — das Warmwasser wird als Energiesenke genutzt.

**Bedingungen (alle müssen erfüllt sein):**
- Uhrzeit vor `drain_fenster_ende` (Standard: 10:00)
- Batterie lädt nicht (P_Batt < 500 W, also kein PV-Überschuss)
- Haushalt < 700 W, WP < 500 W, EV < 1000 W (wenig anderweitiger Verbrauch)
- SOC > 10% (nicht schon fast leer)
- `forecast_quality` ist „gut“ oder „mittel“
- Forecast zeigt ≥ 4 kW in den kommenden Stunden (PV wird kommen)

**Drain-Notaus:** Im Drain-Modus toleriert der Notaus die Batterie-Entladung (die ja gewollt ist). Er greift aber ein wenn:
- SOC ≤ `drain_min_soc_pct` (Batterie leer genug)
- Haushalt/WP/EV-Verbrauch steigt über die Schwellen (mit 1.2× Hysterese bei Haushalt)
- Netzbezug, WW-Übertemperatur oder Burst-Timer-Ablauf

**Notaus-Kriterien (HART vs. KONTEXTABHÄNGIG):**

| # | Kriterium | Typ | Extern-Hysterese | Wirkung |
|---|-----------|-----|------------------|--------|
| 1 | `rest_h < min_rest_h` (2h vor Sunset) | **DIFFERENZIERT** | — | Phase 4 Abend-Zyklus: SOC ≈ MAX + PV ok → HP erlaubt; sonst AUS |
| 2 | WW-Temperatur ≥ 78 °C | **HART** | Sofort | Verbrühungs-/Überdruckschutz |
| 3 | SOC ≤ `stop_entladung_unter` (5%) | **HART** | Sofort | Absoluter Tiefentladeschutz (aus soc_schutz) |
| 4 | Batterie entlädt — potenzialabhängig | **KONTEXT** | Pausiert 1h | Abhängig von Potenzial und SOC_MAX (s.u.) |
| 5 | Verbraucher-Konkurrenz (WP/EV) | **KONTEXT** | Pausiert 1h | Abhängig von Potenzial-Stufe (s.u.) |
| 6 | Netzbezug > 200 W | **KONTEXT** | Pausiert 1h | Kurzzeitig normal bei HP-Zuschalten |
| 7 | Burst-Timer abgelaufen | **KONTEXT** | Pausiert 1h | Kein Timer bei manuellem Einschalten |

**Potenzial-Skala (Tagesprognose kWh):**

Die HP-Steuerung klassifiziert die Tagesprognose in Potenzial-Stufen und passt
die Regeln daran an:

| Stufe | Schwelle | Parallel-Betrieb | Batterie-Entladung toleriert? |
|-------|----------|-------------------|-------------------------------|
| `niedrig` | < 15 kWh | HP nur solo (kein WP/EV) | **Nie** — HP immer AUS bei Entladung |
| `maessig` | 15–20 kWh | HP nur solo (kein WP/EV) | Nur wenn SOC_MAX ≤ 75% (Batterie noch nicht voll angefordert) |
| `ausreichend` | 20–30 kWh | HP + WP parallel, EV blockiert | Nur wenn SOC_MAX ≤ 75% |
| `gut` | ≥ 30 kWh | HP + WP + EV alle parallel | **Immer** — genug Sonne für alles |

**Logik:** Morgens/Vormittags steht SOC_MAX typisch bei 75% (Batterie wird gedrosselt,
Verbraucher haben Vorrang). In dieser Phase toleriert die Engine Batterie-Entladung bei
mäßigem/ausreichendem Potenzial, weil PV die Batterie später wieder füllt. Erst wenn
SOC_MAX auf 100% geht (Nachmittag) wird die Batterie-Entladung strenger bewertet.

**Extern-Erkennung:** Wenn die HP außerhalb der Engine eingeschaltet wird (pv-config Menü 6, Fritz!Box-App, physischer Schalter), erkennt die Engine dies automatisch: HP ist EIN, aber kein Burst/Drain läuft. In diesem Fall gelten für `extern_respekt_s` (Standard: 1 Stunde) nur die **HARTEN** Kriterien. Danach übernimmt die Engine wieder normal.

> **Hinweis:** Der Notaus läuft im Engine fast-cycle (60 s) und ist
> **immer aktiv**, auch wenn der Regelkreis auf `aktiv: false` steht.
> HARTE Kriterien (Temperatur, SOC-Schutzgrenze, Sunset) greifen
> auch während der Extern-Hysterese.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|--------|
| min_ladeleistung | 5000 W | 2000–10000 W | **Mindest-Batterie-Ladeleistung (Basis).** Wird potenzialabhängig herunterskaliert: gut=50% (2500W), ausreichend=70% (3500W), mäßig/niedrig=100% (5000W). Der Burst-Timer schützt vor Flip-Flop nach dem Einschalten. |
| min_ladeleistung_morgens | 3000 W | 1000–8000 W | **Vormittags-Schwelle.** Bei guter Tagesprognose (>20 kWh) reichen 3 kW Ladeleistung, weil genug Sonne für Batterie+HP erwartet wird. |
| min_rest_kwh | 12.0 kWh | 5–30 kWh | **Mindest-Restprognose.** HP-Burst nur wenn die Rest-Tagesprognose genug kWh zeigt, um Batterie voll zu laden UND HP zu versorgen. |
| min_rest_kwh_morgens | 20.0 kWh | 10–40 kWh | **Vormittags-Mindestprognose.** Lang genug Sonne erwartet für HP + Batterie + eventuelle EV-Ladung. |
| min_rest_h | 2.0 h | 1–4 h | **Schwelle für Phase 4 (Abend-Nachladezyklus).** Unter 2 h PV bis Sonnenuntergang → kein normaler Burst. Stattdessen Phase 4: HP nur wenn SOC ≈ MAX und PV noch ausreicht. |
| min_rest_h_morgens | 5.0 h | 3–8 h | **Vormittag-Minimum.** Nur bei >5 h Restsonne wird die lockere Morgenschwelle angewendet. |
| burst_dauer_lang | 1800 s | 600–3600 s | **Burst-Dauer bei guter Prognose (30 Min).** HP läuft maximal diese Zeit, dann aus und Pause. |
| burst_dauer_kurz | 900 s | 300–1800 s | **Burst-Dauer bei mäßiger Prognose (15 Min).** Kürzere Einschaltzeit bei weniger Reserven. |
| min_pause | 300 s | 60–600 s | **Mindestpause zwischen Bursts.** Verhindert Flip-Flop (z.B. Wolke durchzieht → AUS → sofort wieder EIN). |
| max_wattpilot | 500 W | 0–5000 W | **Obergrenze EV-Ladung.** (Legacy, durch Potenzial-Logik ersetzt.) HP darf mit EV parallel laufen wenn Potenzial ≥ `gut`. |
| batt_reserve | 2.0 kWh | 0.5–5.0 kWh | **Prognose-Reserve.** Restprognose muss Batterie-Volladung + diese Reserve decken, damit HP erlaubt wird. |
| batt_reserve_nachmittag | 3.0 kWh | 1–8 kWh | **Größere Reserve nachmittags.** Weniger Restzeit → mehr Puffer für sichere Volladung. |
| notaus_netzbezug | 200 W | 0–500 W | **Netzbezug-Schwelle (Ø5 Min).** Wenn der geglättete 5-Minuten-Durchschnitt des Netzbezugs diesen Wert überschreitet → HP AUS. Glättung verhindert Abschaltung durch kurzzeitige Leistungssprünge (±10 kW). |
| speicher_temp_max | 78 °C | 60–85 °C | **Warmwasser-Übertemperatur.** HP sofort AUS bei ≥78 °C. Schutz vor Verbrühung/Überdruck. |
| potenzial_gut_kwh | 30.0 kWh | 15–60 kWh | **Tagesprognose für Potenzial "gut".** Ab hier: HP + WP + EV alle parallel, Batterie-Entladung immer toleriert. |
| potenzial_ausreichend_kwh | 20.0 kWh | 10–40 kWh | **Tagesprognose für "ausreichend".** HP + WP parallel (kein EV). Entladung toleriert wenn SOC_MAX ≤ 75%. |
| potenzial_maessig_kwh | 15.0 kWh | 5–30 kWh | **Tagesprognose für "mäßig".** HP nur solo (kein WP/EV). Entladung toleriert wenn SOC_MAX ≤ 75%. Unter diesem Wert → "niedrig": HP nur bei explizitem Burst, keine Entladung toleriert. |
| drain_fruehstart_vor_sunrise_h | 1.0 h | 0–3 h | **Drain-Frühstart vor Sonnenaufgang.** Phase 0 startet ab `sunrise − dieser_Wert`. |
| drain_start_soc_pct | 20% | 10–50% | **Drain-SOC-Startschwelle.** Phase 0 nur wenn SOC über diesem Wert. |
| drain_stop_soc_pct | 15% | 5–30% | **Drain-SOC-Untergrenze.** Drain-Notaus schaltet HP aus wenn SOC diesen Wert erreicht. |
| drain_max_haushalt | 700 W | 200–2000 W | **Max. Hausverbrauch für Drain.** HP-Drain nur bei niedrigem Haushalt — sonst leert die Batterie schon schnell genug. |
| drain_max_wp | 500 W | 100–2000 W | **Max. WP-Leistung für Drain.** Wenn WP läuft, braucht die Batterie keinen zusätzlichen Drain. |
| drain_max_ev | 1000 W | 200–5000 W | **Max. EV-Ladung für Drain.** EV verbraucht bereits genug Batterie. |
| drain_min_prognose | 4.0 kW | 2–10 kW | **Mindest-Prognoseleistung.** Forecast muss in den kommenden Stunden ≥ diesen Wert in kW zeigen. Stellt sicher, dass PV die Batterie später wieder füllt. |
| drain_fenster_ende | 10.0 h | 8–12 h | **Drain nur vor dieser Uhrzeit.** Standard 10:00 — danach produziert PV und Phase 1–3 übernehmen. |
| drain_burst_dauer | 2700 s | 900–5400 s | **Drain-Burst Maximaldauer (45 Min).** Sicherheits-Backstop — Drain-Notaus (SOC, Verbraucher) beendet den Drain meist früher. |
| abend_soc_ein_unter_max_pct | 2% | 1–5% | **Abend-Zyklus EIN-Schwelle.** HP darf an wenn SOC ≥ SOC_MAX − diesen Wert. |
| abend_soc_aus_unter_max_pct | 10% | 5–20% | **Abend-Zyklus AUS-Schwelle.** HP muss aus wenn SOC < SOC_MAX − diesen Wert. |
| abend_max_entladung_w | 1000 W | 0–3000 W | **Max Entladeleistung im Abend-Zyklus.** HP aus wenn Batterie stärker entlädt. |
| abend_min_pv_w | 1500 W | 500–5000 W | **Mindest-PV für Abend-Zyklus.** PV muss noch genug liefern, damit Phase 4 überhaupt anspringt. |
| probe_dauer_s | 120 s | 30–300 s | **Probe-Burst-Dauer (Phase 1b).** HP wird kurz eingeschaltet um WR-Drosselung zu erkennen. |
| probe_cooldown_s | 600 s | 120–1800 s | **Probe-Wartezeit.** Nach gescheiterter Probe kein neuer Versuch für diese Dauer. |
| probe_pv_delta_min_w | 500 W | 100–2000 W | **Mindest-PV-Anstieg.** Probe gilt als Erfolg wenn PV um ≥ diesen Wert steigt. |
| probe_grid_max_w | 300 W | 0–1000 W | **Max. Netzbezug nach Probe.** Probe gilt als gescheitert wenn Netzbezug über diesem Wert. |
| extern_respekt | 3600 s | 0–7200 s | **Extern-Hysterese.** Wenn HP außerhalb der Engine eingeschaltet wird, pausieren WEICHE Notaus-Kriterien für diese Dauer. HARTE Kriterien (Temp, SOC-abs, Sunset) wirken immer sofort. 0 = deaktiviert (Notaus greift sofort wie bisher). |

**Rechenbeispiel (sonniger Märztag, ≈ 45 kWh Prognose):**
```
06:30 — Sunrise 07:30, SOC = 25%
  Phase 0: sunrise−1h = 06:30 ✓, SOC 25% > 20% ✓, Prognose gut ✓
  → HP EIN (Drain 45 Min.) — Batterie gezielt leeren

10:30 — SOC = 15% (Drain-Stop), P_Batt = +3.5 kW, Forecast_rest = 38 kWh
  Phase 1: rest_h = 7.5 > 5 ✓, rest_kwh = 38 > 20 ✓, P_Batt > 3 kW ✓
  → HP EIN (Burst 30 Min.)

12:00 — SOC = 98% (≈ SOC_MAX), P_Batt ≈ 0, WR drosselt
  Phase 1b Probe: SOC ≥ MAX−2% ✓, Batt idle ✓, Forecast ok ✓
  → HP EIN (Probe 120 s) — PV steigt um 1.2 kW, Netzbezug 50W
  → Probe Erfolg → Probe → Burst lang (30 Min.)

14:00 — SOC = 85%, SOC_MAX = 100%, P_Batt = −1.5 kW (Wolke)
  Potenzial: "gut" → Entladung toleriert ✓
  Phase 2: HP bleibt an (laufender Burst respektiert)

16:00 — rest_h = 1.5 < 2.0, SOC = 97%, SOC_MAX = 100%, PV = 2.1 kW
  Phase 4: SOC ≥ MAX−2% ✓, PV ≥ 1500W ✓, Entladung < 1000W ✓
  → HP EIN (Abend-Zyklus 15 Min.)
  SOC sinkt auf 89% → SOC < MAX−10% → HP AUS → Batterie lädt nach
```

> **Erstinbetriebnahme:** Der Regelkreis wird mit `aktiv: false` ausgeliefert. Vor dem Einschalten: `.secrets` mit `FRITZ_USER`/`FRITZ_PASSWORD` füllen, AIN prüfen (Menü 6 → Verbindungstest), dann im Menü 1 (Regelkreise) aktivieren. Die Schwellwerte sollten an echten Sonnentagen kalibriert werden.

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

## 8. Menü 6: Heizpatrone (Fritz!DECT)

Steuert die 2-kW-Heizpatrone im Warmwasserspeicher über eine Fritz!DECT-Steckdose (AHA-HTTP-API).

**Zugangsdaten:** Werden in `.secrets` gespeichert (nicht in JSON), genau wie `FRONIUS_PASS` und `WATTPILOT_PASSWORD`.

| Eintrag | Funktion |
|---------|----------|
| **HP-Status** | Gerätename, Schaltzustand (EIN/AUS), aktuelle Leistung (W), Energiezähler (Wh) |
| **Konfiguration** | Fritz!Box-IP, AIN, Zugangsdaten (.secrets bearbeiten) |
| **Verbindungstest** | Ping → Login → AHA-API → Gerätename auslesen (3-Stufen-Test) |
| **HP manuell EIN** | Sofortiges Einschalten (mit Sicherheitsabfrage). Umgeht die Automation! |
| **HP manuell AUS** | Sofortiges Ausschalten |
| **Schwellwerte** | Öffnet den Regelkreis `heizpatrone` in der Parametermatrix (→ §4.10) |

> **Ersteinrichtung:**
> 1. Fritz!Box-IP prüfen (Standard: 192.168.178.1)
> 2. `.secrets` → `FRITZ_USER` und `FRITZ_PASSWORD` eintragen
> 3. AIN der Steckdose eingeben (Fritz!Box → Smart Home → Geräte)
> 4. Verbindungstest durchführen
> 5. Menü 1 → Regelkreis `heizpatrone` aktivieren

---

## 9. Grundlagenwissen

### SOC-Bereiche der 2× BYD HVS 20.48 kWh (LFP)

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
| **sls_schutz** | **95** | **P1 Sicherheit** |
| ~~soc_schutz~~ | ~~90~~ | ~~P1~~ ENTFERNT (2026-03-07) |
| morgen_soc_min | 72 | P2 Steuerung |
| ~~temp_schutz~~ | ~~70~~ | ~~P1~~ ENTFERNT (2026-03-07) |
| ~~abend_entladerate~~ | ~~65~~ | ~~P2~~ ENTFERNT (2026-03-07) |
| wattpilot_battschutz | 60 | P1 Sicherheit |
| nachmittag_soc_max | 55 | P2 Steuerung |
| forecast_plausibilisierung | 50 | P2 Steuerung |
| ~~laderate_dynamisch~~ | ~~45~~ | ~~P2~~ ENTFERNT (2026-03-07) |
| heizpatrone | 40 | P2 Steuerung |
| zellausgleich | 30 | P3 Wartung |

**Beispiel:** Wenn `morgen_soc_min` (72) SOC_MIN auf 5% setzen will und `wattpilot_battschutz` (60) SOC_MIN auf 25% anheben will, gewinnt die Morgenöffnung — die verbleibende SOC-Schutzgrenze kommt aus den Tier-1-Alarm-Schwellen und SOC_MIN-Steuerung der aktiven Regeln.

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
| Batterie | 2× BYD HVS parallel (LFP, BCU 2.0 Master) |
| Kapazität | 20.48 kWh (2× 10.24 kWh) |
| Max. Ladeleistung | ~9,5 kW effektiv (GEN24 DC-DC ~22 A HW-Limit; nominell 12 kW) |
| Max. Entladeleistung | ~9,5 kW effektiv (GEN24 DC-DC ~22 A HW-Limit; nominell 12 kW) |
| PV-Anlage | 37.59 kWp (3 Strings) |
| WR-Limit | 26.5 kW (3× Fronius Gen24) |
| Chemie | LiFePO₄ (LFP) |
| Heizpatrone | 2 kW (Warmwasserspeicher) |
| Schaltaktor | Fritz!DECT 200/210 (AIN 00000 0000000) |
| Fritz!Box | AHA-HTTP-API via login_sid.lua |
