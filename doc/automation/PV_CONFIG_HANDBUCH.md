# PV-CONFIG Handbuch

**Konfigurationsprogramm für die PV-Batterie-Automation**
Version 1.7 — Stand: 9. April 2026

---

## Inhaltsverzeichnis

1. [Starten und Navigation](#1-starten-und-navigation)
2. [Hauptmenü-Übersicht](#2-hauptmenü-übersicht)
3. [Menü 1: Regelkreise ein/aus](#3-menü-1-regelkreise-einaus)
4. [Menü 2: Parameter-Matrix](#4-menü-2-parameter-matrix)
   - [4.0 soc_extern — SOC-Extern-Toleranz](#40-soc_extern--soc-extern-toleranz)
  - [4.1 tier1_alarmierung — Mail/Alarm bei kritischen Werten](#41-tier1_alarmierung--mailalarm-bei-kritischen-werten)
  - [4.1a sls_schutz — SLS-Netzschutz 35A/Phase](#41a-sls_schutz--sls-netzschutz-35aphase-priorität-1)
   - [4.2 morgen_soc_min — Morgenöffnung](#42-morgen_soc_min--morgenöffnung-priorität-2)
   - [4.3 nachmittag_soc_max — Nachmittagsanhebung](#43-nachmittag_soc_max--nachmittagsanhebung-priorität-2)
  - [4.4 komfort_reset — Abend-Reset auf Komfortwerte](#44-komfort_reset--abend-reset-auf-komfortwerte-priorität-2)
   - [4.5 zellausgleich — Quartalszellausgleich](#45-zellausgleich--quartalszellausgleich-priorität-3)
   - [4.7 forecast_plausibilisierung — Prognosekorrektur](#47-forecast_plausibilisierung--prognosekorrektur-priorität-2)
   - [4.9 wattpilot_battschutz — EV-Ladeschutz](#49-wattpilot_battschutz--ev-ladeschutz-priorität-1)
   - [4.10 heizpatrone — HP-Burst-Steuerung](#410-heizpatrone--hp-burst-steuerung-priorität-2)
  - [4.11 klimaanlage — Temperatur- und Prognosesteuerung](#411-klimaanlage--temperatur--und-prognosesteuerung-priorität-2)
   - [4.12 ww_absenkung — WW-Nachtabsenkung](#412-ww_absenkung--ww-nachtabsenkung-priorität-2)
   - [4.13 heiz_absenkung — Heiz-Nachtabsenkung](#413-heiz_absenkung--heiz-nachtabsenkung-priorität-2)
   - [4.14 ww_verschiebung — WW-Bereitung verschieben](#414-ww_verschiebung--ww-bereitung-verschieben-priorität-2)
   - [4.15 heiz_verschiebung — Heiz-Soll verschieben](#415-heiz_verschiebung--heiz-soll-verschieben-priorität-2)
   - [4.16 ww_boost — WW-Soll bei PV-Überschuss](#416-ww_boost--ww-soll-bei-pv-überschuss-anheben-priorität-2)
   - [4.17 wp_pflichtlauf — WP Täglicher Pflichtlauf](#417-wp_pflichtlauf--wp-täglicher-pflichtlauf-priorität-2)
   - [4.18 heiz_bedarf — FBH-Heizbedarf nach Außentemperatur](#418-heiz_bedarf--fbh-heizbedarf-nach-außentemperatur-priorität-2)
5. [Menü 3: Batterie-Automation](#5-menü-3-batterie-automation)
6. [Menü 4: System-Status](#6-menü-4-system-status)
7. [Menü 5: Solar-Prognose](#7-menü-5-solar-prognose)
8. [Menü 6: Heizpatrone (Fritz!DECT)](#8-menü-6-heizpatrone-fritzdect)
9. [Menü 9: Handbuch anzeigen](#9-menü-9-handbuch-anzeigen)
10. [Grundlagenwissen](#10-grundlagenwissen)

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
| Handbuch | Öffnet dieses Handbuch direkt im pv-config Scroll-Dialog |
| Beenden | Programm schließen |

---

## 3. Menü 1: Regelkreise ein/aus

Zeigt alle Regelkreise als Checkliste. Ein Regelkreis ist entweder **aktiv** (●) oder **inaktiv** (○).

**Prioritäten:**
- **P1 — SICHERHEIT**: Immer aktiv lassen! Schützt die Hardware.
- **P2 — STEUERUNG**: Optimierungs-Regeln, können einzeln deaktiviert werden.
- **P3 — WARTUNG**: Periodische Aufgaben (z.B. Zellausgleich).

**Score-Gewicht:** Bei Konflikten zwischen Regelkreisen gewinnt der höhere Score. Beispiel: `morgen_soc_min` (Score 72) hat Vorrang über `wattpilot_battschutz` (Score 60).

> **Warnung:** Die P1-Regeln `sls_schutz` und `wattpilot_battschutz` sollten **niemals** deaktiviert werden.
> Tier-1-Alarmierung (Temperatur/SOC/Netz) bleibt aktiv und meldet bei Bedarf per Event-Mail.

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
| extern_respekt | 1800 s | 900–7200 s | **Toleranzzeit bei extern geänderten SOC-Werten (30 Min).** Alle SOC-Steuerungsregeln (morgen_soc_min, nachmittag_soc_max, komfort_reset, forecast_plausi, zellausgleich) pausieren für diese Dauer. Tier-1-Alarmierung läuft unabhängig weiter. |

**Sicherheit:** Tier-1-Checks (Temperatur, SOC) setzen weiterhin Alarm-Flags. Direkte Modbus-Aktionen für Laderaten laufen nicht automatisiert. Batterie-Schutz erfolgt über SOC_MIN/SOC_MAX (HTTP-API).

**Erkennungsmechanik:** Der `SocExternTracker` (Singleton in `soc_extern.py`) vergleicht pro Engine-Zyklus SOC_MIN/SOC_MAX mit den vorherigen Werten. Änderungen werden als Engine-intern erkannt wenn die Engine kurz zuvor ein Kommando mit diesem Zielwert registriert hat (Grace-Window: 5 Min). Alle anderen Änderungen → extern → Toleranzperiode startet.

---

### 4.1 tier1_alarmierung — Mail/Alarm bei kritischen Werten

**Zweck:** Kritische Zustände werden per Event-Notifier gemeldet (1x pro Event/Tag),
ohne automatische Laderaten-Eingriffe.

**Quelle:** `config.py` (`NOTIFICATION_EVENTS`, `EVENT_THRESHOLDS`)

| Event | Standard | Wirkung |
|-------|----------|---------|
| batt_temp_40 | aktiv | Mail bei `batt_temp_max_c >= 40°C` |
| batt_soc_kritisch | aktiv | Mail bei `batt_soc_pct < 5%` |
| netz_ueberlast | aktiv | Mail bei `grid_power_w >= 24kW` |
| sls_ueberlast | aktiv | Mail bei `i_max_netz_a >= 35A` |

**Hinweis:** Zusätzlich setzt Tier-1 Alarm-Flags im ObsState. Der aktive Batterieschutz
läuft über SOC_MIN/SOC_MAX der Regelkreise.

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

### 4.4 komfort_reset — Abend-Reset auf Komfortwerte (Priorität 2)

**Zweck:** Abends die Batterie-SOC-Grenzen auf den Komfort-Bereich (25–75%) zurücksetzen. Schützt LFP-Zellen vor dauerhaftem Stress-Zustand (z.B. SOC_MIN=5% über Nacht). Zusätzlich: intelligenter Früh-Reset am Nachmittag, wenn die PV-Restprognose nicht für eine Erholung reicht.

**Score:** 70
**Zyklus:** fast

**Entscheidungslogik (Abend-Reset):**

| Abend-SOC | Morgen-Prognose | Entscheidung |
|-----------|-----------------|-------------|
| SOC > 25% | ≥ 20 kWh | SOC_MIN bleibt bei 5% — draint über Nacht, morgens Drain-Algo |
| SOC > 25% | < 20 kWh | SOC_MIN → 25% (Nachtladung nötig) |
| **SOC ≤ 25%** | **egal** | **SOC_MIN → 25% — Stress vermeiden!** |

> **Kernregel:** Ist die Batterie abends bereits im Stress-Bereich (SOC ≤ komfort_min),
> wird SOC_MIN **immer** auf Komfort zurückgesetzt. Nur wenn noch genug Ladung vorhanden
> ist UND morgen genug PV kommt, darf SOC_MIN niedrig bleiben.

**Früh-Reset (Nachmittag):**
Wenn nachmittags (ab `frueh_reset_ab_h`) die PV-Restprognose unter `erholung_schwelle_kwh` fällt, wird SOC_MIN sofort auf 25% angehoben. Hysterese (`erholung_hysterese_kwh`) verhindert Flackern.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|--------|
| komfort_min | 25% | 10–40% | **SOC_MIN im Normalzustand.** LFP-optimiert: unter 25% = Stress. |
| komfort_max | 75% | 60–90% | **SOC_MAX im Normalzustand.** LFP-optimiert: über 75% = Stress. |
| reset_nach_sunset_h | 0 h | 0–3 h | **Abend-Reset-Zeitpunkt.** 0 = sofort bei Sunset. |
| frueh_reset_ab_h | 13 h | 11–16 h | **Frühester Zeitpunkt für Nachmittags-Früh-Reset.** |
| erholung_schwelle | 10 kWh | 5–20 kWh | **Prognose-Rest < Schwelle → Früh-Reset (SOC_MIN sofort auf 25%).** |
| erholung_hysterese | 2 kWh | 1–5 kWh | **Anti-Flicker:** Aufhebung erst bei Schwelle + Hysterese. |
| nachtlade_schwelle | 20 kWh | 5–50 kWh | **Morgen-Prognose für Abend-Override.** Nur wenn SOC > komfort_min UND Morgen ≥ Schwelle bleibt SOC_MIN niedrig. |

**Beispiel (sonniger Tag, Batterie leer):**
```
18:30 Uhr: SOC = 17%, Morgen-Prognose = 107 kWh
→ SOC (17%) ≤ komfort_min (25%) → Komfort-Reset: SOC_MIN 5% → 25%
→ Grid-Ladung über Nacht auf 25%, Stress-Zustand vermieden
```

**Beispiel (sonniger Tag, Batterie voll):**
```
18:30 Uhr: SOC = 45%, Morgen-Prognose = 107 kWh
→ SOC (45%) > komfort_min (25%) UND Prognose (107) ≥ 20 kWh
→ SOC_MIN bleibt bei 5% → draint über Nacht → morgens Drain-Algo
```

> ⚠️ Vorgänger: Historisch gab es hier eine registerbasierte Abendrationierung.
> Diese ist seit 2026-03-07 dauerhaft entfernt.

---

### 4.5 zellausgleich — Quartalszellausgleich (Priorität 3)

**Zweck:** Einmal pro Quartal (Q1–Q4) die BYD-Batterie über den Fronius Auto-Modus auf 100 % laden, damit das BMS einen Zellausgleich (Cell-Balancing) durchführen kann. LFP-Zellen brauchen das regelmäßig für korrekte SOC-Anzeige.

**Modus:** Die Regel schaltet die Batterie in den Fronius-`auto`-Modus. Der Wechselrichter verwaltet die SOC-Grenzen selbst (Firmware-intern 5–100 %). Die Batterie lädt bei PV-Überschuss natürlich auf 100 % und balanciert die Zellen. **Kein manuelles 5/100 %-Setzen mehr** — damit entfällt das frühere Ping-Pong mit KomfortReset. KomfortReset stellt abends wieder auf `manual 25–75 %` zurück.

**Score:** 30 (niedrigster — wird von allen anderen Regeln überstimmt)  
**Zyklus:** strategic  
**Auslösung:** frühestens ab `frueheste_stunde_h` (Standard 10:00) — verhindert Nacht-Trigger durch morgendliche Prognose-Daten.

**Flow-Anzeige:** Wenn der Quartalszellausgleich noch aussteht, erscheint in der Batterie-Infozeile (Flow-Ansicht) der Indikator **`ZAusgl.`** (gelb).

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| min_prognose | 50 kWh | 20–80 kWh | **Mindest-PV-Prognose für den Tag.** 50 kWh = sehr sonniger Tag. Nur dann wird ein Vollzyklus ausgelöst. |
| notfall_min_prognose | 25 kWh | 10–50 kWh | **Gesenkte Schwelle nach Überschreitung von max_tage.** Wenn seit 92+ Tagen kein Ausgleich stattfand, wird die Schwelle gesenkt. |
| max_tage_ohne_ausgleich | 92 Tage | 30–180 Tage | **Notfall-Frist (ca. 1 Quartal).** Nach X Tagen wird die Prognoseschwelle gesenkt. |
| frueheste_stunde_h | 10.0 h | 8–14 h | **Früheste Tageszeit** für den Trigger. Verhindert Auslösung nachts oder früh morgens. |
| fruehester_tag | 1 | 1–10 | **Frühester Monatstag** innerhalb des neuen Quartals. |
| spaetester_tag | 28 | 20–31 | **Spätester regulärer Monatstag.** Danach wird auf das nächste Quartal verschoben (es sei denn, max_tage ist überschritten). |

**Hinweis:** An Wintertagen mit nur 5–10 kWh Erzeugung wird die 50-kWh-Schwelle nie erreicht. Dann greift nach 92 Tagen die Notfall-Schwelle (25 kWh).

**Zyklus-Erkennung (seit 2026-03-26):** Der Marker `last_balancing`/`letzter_ausgleich` wird automatisch gesetzt, wenn ein konservativ erkannter Vollzyklus vorliegt. Kriterien: Tages-SOC_MAX nahe 100 %, ausreichende Spannweite und genug Messpunkte. Damit verhindern wir Fehltrigger durch kurze Peaks oder lückenhafte Daten.

---

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

### 4.9 wattpilot_battschutz — EV-Ladeschutz (Priorität 1)

**Zweck:** Schützt die Batterie vor Tiefentladung durch EV-Ladung mit dem Fronius WattPilot (bis zu 22 kW). Schutz erfolgt ausschließlich über SOC_MIN-Anhebung (keine automatische Ratensteuerung).

**Zusatzlogik:** In den letzten 2 Stunden vor Sonnenuntergang setzt die Regel bei laufender EV-Ladung und `SOC < 25%` den `SOC_MIN` auf 25%, damit die Batterie nicht weiter entleert wird.

**Score:** 60
**Zyklus:** fast

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| ev_leistung_schwelle | 2000 W | 500–5000 W | **Mindest-EV-Leistung damit die Regel greift.** Erst ab 2 kW EV-Ladung wird die Batterie geschützt. Unter 2 kW ist die Last unkritisch. |
| soc_min_puffer | 5% | 3–15% | **SOC_MIN-Anhebung.** Wenn SOC innerhalb dieses Puffers über SOC_MIN liegt, wird SOC_MIN temporär angehoben. Verhindert Grenzwert-Oszillation. |
| soc_min_netz | 25% | 15–40% | **SOC_MIN bei Netzumstellung.** Wenn die Batterie zu stark beansprucht wird, wird SOC_MIN auf diesen Wert gesetzt → Batterie hält 25% Reserve und das Haus bezieht aus dem Netz. |
| sunset_guard_h | 2 h (fix) | — | **Fester Sunset-Guard.** Letzte 2h vor Sunset + EV-Ladung + SOC < 25% → SOC_MIN auf 25%. |
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

> **Grundprinzip (seit 2026-03-14): HP = Überlaufventil.** Die Batterie wird
> ZUERST auf SOC_MAX gefüllt. Erst wenn SOC den Deckel erreicht (innerhalb 5%
> bei Phase 1/2/3, innerhalb 2% bei Phase 1b/4) darf die HP als Senke für
> PV-Überschuss einspringen. Phase 0 erfordert zusätzlich Mindest-Sonnenstunden.

| Phase | Bedingung | Burst-Dauer | Zweck |
|-------|-----------|-------------|-------|
| **0 — Morgen-Drain** | ab sunrise−1h, sunshine_h ≥ 5, SOC > 20%, Prognose gut, Forecast ≥ 4 kW | 45 Min. | Batterie gezielt leeren — Warmwasser als Senke |
| **1 — Vormittag** | **SOC ≥ MAX−5%**, rest_h > 5, rest_kwh ≥ 40 kWh (Forecast mindestens `mittel`), P_Batt > 3 kW | 30 Min. | Überlaufventil: Batterie am Deckel, HP nutzt Restkapazität |
| **1b — Nulleinspeiser-Probe** | SOC ≥ MAX−2%, Batt idle, Forecast ≥ HP-Last | 120 s (Probe) → 30 Min. bei Erfolg | WR-Drosselung erkennen, stille PV-Kapazität nutzen |
| **2 — Mittags** | **SOC ≥ MAX−5%**, P_Batt > min_lade, rest_kwh deckt Batt + Reserve | 30 Min. | Hauptphase bei Batterie-Sättigung |
| **3 — Nachmittags** | **SOC ≥ MAX−5%**, rest_h < 3 und ≥ 2, konservativ | 15 Min. | Kurze Restzeit → nur kurze Bursts |
| **4 — Abend** | rest_h < 2, SOC ≥ MAX−2%, PV ≥ 1500W | 15 Min. (kurz) | Nachladezyklus: EIN/AUS nach SOC-Nähe zu MAX |

**Phase 0 (Morgen-Drain) im Detail:**

Wenn `morgen_soc_min` den SOC_MIN früh auf 5% öffnet, entlädt sich die Batterie durch den Hausverbrauch. Bei niedrigem Verbrauch (z.B. 500 W) dauert das sehr lange. Phase 0 schaltet die HP gezielt ein, um die Batterie schneller zu leeren — das Warmwasser wird als Energiesenke genutzt.

**Bedingungen (alle müssen erfüllt sein):**
- Uhrzeit vor `drain_fenster_ende` (Standard: 10:00)
- **Sonnenstunden ≥ `drain_min_sunshine_h` (Standard: 5.0h)** — NEU seit 2026-03-14. An Regentagen mit wenig prognostizierter Sonne (z.B. 3.5h) wird kein Drain ausgeführt: die Batterie-Energie wird für den Haushalt gebraucht.
- Haushalt < 700 W, WP < 500 W, EV < 1000 W (wenig anderweitiger Verbrauch)
- SOC > `drain_start_soc` (Standard: 20%)
- `forecast_quality` ist „gut“ oder „mittel“
- Forecast zeigt ≥ 4 kW in den kommenden Stunden (PV wird kommen)

**Drain-Notaus:** Im Drain-Modus toleriert der Notaus die Batterie-Entladung (die ja gewollt ist). Er greift aber ein wenn:
- SOC ≤ `drain_min_soc_pct` (Batterie leer genug)
- Haushalt/WP/EV-Verbrauch steigt über die Schwellen (mit 1.2× Hysterese bei Haushalt)
- Netzbezug, WW-Übertemperatur oder Burst-Timer-Ablauf

**Notaus-Kriterien (HART vs. KONTEXTABHÄNGIG):**

| # | Kriterium | Typ | Autoritätsschaltung | Wirkung |
|---|-----------|-----|---------------------|--------|
| 1 | WW-Temperatur ≥ 78 °C | **HART** | Sofort | Verbrühungs-/Überdruckschutz |
| 2 | SOC ≤ `stop_entladung_unter` (5%) | **HART** | Sofort | Absoluter Tiefentladeschutz (Tier-1) |
| 3 | SOC ≤ `extern_notaus_soc_pct` (15%) | **HART** | Sofort | Autoritäts-Override: manuelle Einschaltung überstimmt bei niedrigem SOC |
| 4 | `rest_h < min_rest_h` (2h vor Sunset) | **DIFFERENZIERT** | **Pausiert** | Phase 4 Abend-Zyklus: SOC ≈ MAX + PV ok → HP erlaubt; sonst AUS |
| 5 | Batterie entlädt — potenzialabhängig | **KONTEXT** | **Pausiert** | Abhängig von Potenzial und SOC_MAX (s.u.) |
| 6 | Verbraucher-Konkurrenz (WP/EV) | **KONTEXT** | **Pausiert** | Abhängig von Potenzial-Stufe (s.u.) |
| 7 | Netzbezug Ø7 Min > `notaus_netzbezug_w` | **KONTEXT** | **Pausiert** | Nur wenn weder Istwert-Veto noch Forecast-Veto greifen |
| 8 | Burst-Timer abgelaufen | **KONTEXT** | **Pausiert** | Kein Timer bei manuellem Einschalten |

**Netzbezug-Vetos (seit 2026-03-28):**
- **Istwert-Veto:** Wenn aktueller Netzbezug `< notaus_netzbezug_aktuell_veto_w`, wird kein HP-Notaus ausgelöst.
- **Forecast-Veto (nur bei `forecast_quality = gut`):** HP darf weiterlaufen, wenn `forecast_rest_kwh` den dynamischen Bedarf deckt:
  `Batteriebedarf + Haushaltsbedarf bis Sunset + Sicherheitsreserve + optional Klima-Last`.

Der Batteriebedarf ist SoC-abhängig: bei niedrigem SoC hoch (bis Volladung),
ab `notaus_forecast_batt_ignore_ab_soc_pct` wird kein zusätzlicher
Batterie-Ladebedarf mehr eingerechnet.

**Autoritätsschaltung (seit 2026-03-14):** Bei manueller Einschaltung (Fritz!DECT Taster
oder App) respektiert die Engine die Nutzer-Entscheidung für `extern_respekt_s`
(Standard 30 Min, einstellbar 15 Min–2 h). Nur **Übertemperatur**, **SOC ≤ 5%** und
**SOC ≤ 15%** (`extern_notaus_soc_pct`) dürfen sofort überstimmen. Phase 4 und alle
weichen Kriterien pausieren. Bei manuellem Ausschalten gilt analog eine
EIN-Sperre für die gleiche Dauer.

**Forecast-Bewertung (Tagesprognose kWh):**

Die HP-Steuerung nutzt dieselbe zentrale Forecast-Bewertung wie SolarForecast,
SOC-Regeln und pv-config. Die Schwellen liegen im Regelkreis `forecast_bewertung`.

| Stufe | Schwelle | Parallel-Betrieb | Batterie-Entladung toleriert? |
|-------|----------|-------------------|-------------------------------|
| `schlecht` | < `schlecht_unter_kwh` | HP nicht automatisch, kein Parallel-Betrieb | **Nie** — HP immer AUS bei Entladung |
| `mittel` | `schlecht_unter_kwh` bis < `mittel_unter_kwh` | HP + WP parallel, EV blockiert | Nur wenn SOC_MAX ≤ 75% |
| `gut` | ≥ `mittel_unter_kwh` | HP + WP + EV alle parallel | **Immer** — genug Sonne für alles |

Standardwerte: `schlecht_unter_kwh = 40`, `mittel_unter_kwh = 100`.

**Logik:** Morgens/Vormittags steht SOC_MAX typisch bei 75% (Batterie wird gedrosselt,
Verbraucher haben Vorrang). In dieser Phase toleriert die Engine Batterie-Entladung bei
mittlerer/guter Prognose, weil PV die Batterie später wieder füllt. Erst wenn
SOC_MAX auf 100% geht (Nachmittag) wird die Batterie-Entladung strenger bewertet.

**Autoritätsschaltung (Extern-Erkennung):** Wenn die HP außerhalb der Engine eingeschaltet wird (pv-config Menü 6, Fritz!Box-App, physischer Schalter), erkennt die Engine dies automatisch: HP ist EIN, aber kein Burst/Drain läuft. In diesem Fall gilt für `extern_respekt_s` (Standard: 30 Min, einstellbar 15 Min–2 h) die **Nutzer-Autorität**: alle weichen Kriterien UND Phase 4 pausieren. Nur **Übertemperatur**, **SOC ≤ 5%** (Tier-1/Tiefentladeschutz) und **SOC ≤ 15%** (`extern_notaus_soc_pct`) überstimmen sofort. Bei manuellem Ausschalten sperrt die Engine hp_ein für die gleiche Dauer.

> **Hinweis:** Der Notaus läuft im Engine fast-cycle (60 s) und ist
> **immer aktiv**, auch wenn der Regelkreis auf `aktiv: false` steht.
> HARTE Kriterien (Temperatur, SOC-Schutzgrenze, extern_notaus_soc)
> greifen auch während der Autoritätsschaltung.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|--------|
| min_ladeleistung | 5000 W | 2000–10000 W | **Mindest-Batterie-Ladeleistung (Basis).** Wird prognoseabhängig herunterskaliert: gut=50% (2500W), mittel=70% (3500W), schlecht=100% (5000W). Der Burst-Timer schützt vor Flip-Flop nach dem Einschalten. |
| min_ladeleistung_morgens | 3000 W | 1000–8000 W | **Vormittags-Schwelle.** Bei Forecast mindestens `mittel` (`rest_kwh ≥ 40 kWh`) reichen 3 kW Ladeleistung, weil genug Sonne für Batterie+HP erwartet wird. |
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
| notaus_netzbezug | 500 W | 0–500 W | **Netzbezug-Schwelle (Ø7 Min).** Basisgrenze für HP-Notaus durch Netzbezug. |
| notaus_netzbezug_aktuell_veto_w | 200 W | 0–1000 W | **Istwert-Veto.** Wenn aktueller Netzbezug darunter liegt, blockiert das den HP-Netz-Notaus (Schutz gegen veralteten Durchschnitt). |
| notaus_forecast_sicherheit_kwh | 5.0 kWh | 0–12 kWh | **Sicherheitsreserve.** Fester Zusatzpuffer im Forecast-Veto. |
| notaus_forecast_haushalt_min_w | 500 W | 100–3000 W | **Haushalts-Mindestlast.** Untergrenze für den bis Sunset eingeplanten Haushaltsbedarf. |
| notaus_forecast_batt_ziel_soc_pct | 100% | 75–100% | **Batterie-Ziel-SOC.** Bis zu diesem SOC wird Batteriebedarf in den Forecast-Bedarf einberechnet. |
| notaus_forecast_batt_ignore_ab_soc_pct | 95% | 80–100% | **Batteriebedarf-Bypass.** Ab diesem SOC zählt kein zusätzlicher Batterie-Ladebedarf mehr. |
| notaus_forecast_klima_last_w | 1300 W | 0–3000 W | **Klima-Zusatzlast.** Wird nur angerechnet, wenn die Klimaanlage aktuell läuft. |
| notaus_forecast_klima_plan_h | 4.0 h | 0–12 h | **Klima-Planhorizont.** Maximaler Stundenanteil der Klima-Last in der Forecast-Bedarfsrechnung. |
| speicher_temp_max | 78 °C | 60–85 °C | **Warmwasser-Übertemperatur.** HP sofort AUS bei ≥78 °C. Schutz vor Verbrühung/Überdruck. |
| schlecht_unter_kwh | 40.0 kWh | 5–150 kWh | **Zentrale Grenze für `schlecht`.** Unterhalb davon ist die Prognose schlecht. Wirkt auf SolarForecast, SOC-Regeln, HP und pv-config. |
| mittel_unter_kwh | 100.0 kWh | 20–250 kWh | **Zentrale Grenze für `mittel`.** Ab diesem Wert gilt die Prognose als `gut`. Muss größer als `schlecht_unter_kwh` sein. |
| drain_fruehstart_vor_sunrise_h | 1.0 h | 0–3 h | **Drain-Frühstart vor Sonnenaufgang.** Phase 0 startet ab `sunrise − dieser_Wert`. |
| drain_min_sunshine_h | 5.0 h | 0–12 h | **Mindest-Sonnenstunden für Drain (NEU 2026-03-14).** Phase 0 wird blockiert wenn die prognostizierten Sonnenstunden unter diesem Wert liegen. An Regentagen braucht der Haushalt die Batterie-Energie. 0 = deaktiviert (kein Sonnenstunden-Guard). |
| drain_start_soc_pct | 20% | 10–50% | **Drain-SOC-Startschwelle.** Phase 0 nur wenn SOC über diesem Wert. |
| drain_stop_soc_pct | 15% | 5–30% | **Drain-SOC-Untergrenze.** Drain-Notaus schaltet HP aus wenn SOC diesen Wert erreicht. |
| drain_max_haushalt | 700 W | 200–2000 W | **Max. Hausverbrauch für Drain.** HP-Drain nur bei niedrigem Haushalt — sonst leert die Batterie schon schnell genug. |
| drain_max_wp | 500 W | 100–2000 W | **Max. WP-Leistung für Drain.** Wenn WP läuft, braucht die Batterie keinen zusätzlichen Drain. |
| drain_max_ev | 1000 W | 200–5000 W | **Max. EV-Ladung für Drain.** EV verbraucht bereits genug Batterie. |
| drain_min_prognose | 4.0 kW | 2–10 kW | **Mindest-Prognoseleistung.** Forecast muss in den kommenden Stunden ≥ diesen Wert in kW zeigen. Stellt sicher, dass PV die Batterie später wieder füllt. |
| drain_fenster_ende | 10.0 h | 8–12 h | **Drain nur vor dieser Uhrzeit.** Standard 10:00 — danach produziert PV und Phase 1–3 übernehmen. |
| drain_burst_dauer | 2700 s | 900–5400 s | **Drain-Burst Maximaldauer (45 Min).** Sicherheits-Backstop — Drain-Notaus (SOC, Verbraucher) beendet den Drain meist früher. |
| drain_abschalt_verzoegerung_min | 5 min | 1–10 min | **Verzögerung beim Drain-Abschalten durch Verbrauchsspitzen.** Haushaltsgeräte (Wasserkocher, Backofen, Hauswasserwerk) unterbrechen den Drain erst nach anhaltender Überschreitung des jeweiligen Schwellwerts. **Nicht verzögert (sofort): SOC-Schutz, WW-Übertemperatur und Netzbezug.** Standard 5 Min. |
| abend_soc_ein_unter_max_pct | 2% | 1–5% | **Abend-Zyklus EIN-Schwelle.** HP darf an wenn SOC ≥ SOC_MAX − diesen Wert. |
| abend_soc_aus_unter_max_pct | 10% | 5–20% | **Abend-Zyklus AUS-Schwelle.** HP muss aus wenn SOC < SOC_MAX − diesen Wert. |
| abend_max_entladung_w | 1000 W | 0–3000 W | **Max Entladeleistung im Abend-Zyklus.** HP aus wenn Batterie stärker entlädt. |
| abend_min_pv_w | 1500 W | 500–5000 W | **Mindest-PV für Abend-Zyklus.** PV muss noch genug liefern, damit Phase 4 überhaupt anspringt. |
| probe_dauer_s | 120 s | 30–300 s | **Probe-Burst-Dauer (Phase 1b).** HP wird kurz eingeschaltet um WR-Drosselung zu erkennen. |
| probe_cooldown_s | 600 s | 120–1800 s | **Probe-Wartezeit.** Nach gescheiterter Probe kein neuer Versuch für diese Dauer. |
| probe_pv_delta_min_w | 500 W | 100–2000 W | **Mindest-PV-Anstieg.** Probe gilt als Erfolg wenn PV um ≥ diesen Wert steigt. |
| probe_grid_max_w | 300 W | 0–1000 W | **Max. Netzbezug nach Probe.** Probe gilt als gescheitert wenn Netzbezug über diesem Wert. |
| batt_idle_toleranz_w | 800 W | 300–1500 W | **Phase 1b: Batterie-Idle-Fenster.** Prüfung auf `abs(P_Batterie) < diesen_Wert` zur Nulleinspeiser-Erkennung. Höher = toleranter gegen normalen Batterie-Quiescent-Strom (±300–600W). Seit 2026-03-24. |
| grid_ok_toleranz_w | 500 W | 200–1000 W | **Phase 1b: Grid-Toleranz-Fenster.** Prüfung auf `abs(P_Grid) < diesen_Wert` zur Netzbezug-Minimierung bei Nulleinspeiser-Probe. Höher = toleranter gegen Hausverbrauch-Schwankungen. Seit 2026-03-24. |
| kurz_burst_max_s | 420 s | 180–900 s | **Kurz-Burst maximale Dauer (7 Min).** HP läuft maximal diese Zeit bei kurzen Restperioden (z.B. Wolkenbruch, Abend). Standard 420s (7 Min) seit 2026-03-24; vorher 300s. |
| kurz_burst_limit | 2 | 1–5 | **Max. Kurz-Bursts hintereinander.** Nach dieser Zahl von Kurz-Bursts > 5-Min-Päuse erzwungen. Verhindert Flip-Flop-Muster. Seit 2026-03-24. |
| kurz_burst_sperre_s | 1800 s | 300–3600 s | **Sperrzeit nach Kurz-Burst-Limit erreicht (30 Min).** HP wird für diese Dauer blockiert wenn `kurz_burst_limit` Bursts hintereinander stattgefunden haben. Standard 1800s (30 Min) seit 2026-03-24; vorher 420s. |
| extern_respekt | 1800 s | 900–7200 s | **Autoritätszeit (30 Min, 15 Min–2 h).** Bei manueller Einschaltung: Engine respektiert Nutzer-Entscheidung, nur Übertemp und SOC ≤ extern_notaus_soc überstimmen. Bei manuellem Ausschalten: hp_ein für diese Dauer gesperrt. |
| extern_notaus_soc | 15% | 5–30% | **Autoritäts-Override bei niedrigem SOC.** Wird HP manuell eingeschaltet, überstimmt die Engine bei SOC ≤ diesem Wert und schaltet HP aus (Batterieschutz). |

**Rechenbeispiel (sonniger Märztag, ≈ 45 kWh Prognose, 9h Sonne):**
```
06:30 — Sunrise 07:30, SOC = 25%, Sonnenstunden = 9h
  Phase 0: sunrise−1h = 06:30 ✓, sunshine_h=9 ≥ 5 ✓, SOC 25% > 20% ✓, Prognose gut ✓
  → HP EIN (Drain 45 Min.) — Batterie gezielt leeren

  Gegenbeispiel (Regentag): sunshine_h = 3.5 < 5.0
  → Phase 0 BLOCKIERT (Batterie für Haushalt reserviert)

10:30 — SOC = 15% (Drain-Stop), P_Batt = +3.5 kW, Forecast_rest = 38 kWh
  Phase 1: rest_h = 7.5 > 5 ✓, rest_kwh = 38 > 20 ✓
  SOC = 15% vs. SOC_MAX(75%)−5 = 70%? 15% < 70% ✗
  → Phase 1 BLOCKIERT (Batterie erst auf ≥70% füllen!)

11:45 — SOC = 71% (≥ 70% = MAX−5), P_Batt = +3.8 kW
  Phase 1: SOC ✓, P_Batt > 3 kW ✓ → HP EIN (Burst 30 Min.)

12:00 — SOC = 73% (≈ SOC_MAX), P_Batt ≈ 0, WR drosselt
  Phase 1b Probe: SOC ≥ MAX−2% ✓, Batt idle ✓, Forecast ok ✓
  → HP EIN (Probe 120 s) — PV steigt um 1.2 kW, Netzbezug 50W
  → Probe Erfolg → Burst lang (30 Min.)

14:00 — SOC = 85%, SOC_MAX = 100%, P_Batt = +5.1 kW
  Phase 2: SOC 85% ≥ 95% (MAX−5)? 85% < 95% ✗
  → Phase 2 BLOCKIERT (SOC erst auf 95% bringen!)

15:30 — SOC = 96%, rest_h = 1.5 < 2.0
  Phase 4: SOC ≥ MAX−2% ✓, PV ≥ 1500W ✓, Entladung < 1000W ✓
  → HP EIN (Abend-Zyklus 15 Min.)
  SOC sinkt auf 89% → SOC < MAX−10% → HP AUS → Batterie lädt nach
```

> **Erstinbetriebnahme:** Der Regelkreis wird mit `aktiv: false` ausgeliefert. Vor dem Einschalten: `.secrets` mit `FRITZ_USER`/`FRITZ_PASSWORD` füllen, AIN prüfen (Menü 6 → Verbindungstest), dann im Menü 1 (Regelkreise) aktivieren. Die Schwellwerte sollten an echten Sonnentagen kalibriert werden.

---

### 4.11 klimaanlage — Temperatur- und Prognosesteuerung (Priorität 2)

**Zweck:** Klimagerät über Fritz!DECT als Thermoschutz für das Heizhaus steuern.
Vor Sonnenaufgang gilt ein konservativer Start, nach Sonnenaufgang ein sicherer
temperaturgeführter Betrieb.

**Score:** 52
**Zyklus:** fast
**Aktor:** `fritzdect` (`klima_ein` / `klima_aus`)

**Bedingungslogik (vereinfacht):**
- Startfreigabe erst ab `sunrise - 1h`.
- **Vor Sonnenaufgang:** EIN nur bei `forecast_quality = gut` UND `Temp >= initial_temp_c`.
- **Nach Sonnenaufgang:**
  - bei `forecast_quality = gut`: EIN ab `initial_temp_c_gut_nach_sunrise`
  - sonst: EIN ab `initial_temp_c_maessig`
- **Laufender Betrieb (vor/nach Sunrise):** temperaturgeführt mit Hysterese `temp_hysterese_k`.
  AUS, wenn `Temp < (Startschwelle - Hysterese)`.
- Abschalten: nach Sonnenuntergang UND `SOC < sunset_soc_stop_pct`.

**Temperaturquelle:**
- Primärwert ist die Temperatur der Klima-Steckdose (`klima_temp_c`).
- Wenn kein Sensorwert vorliegt, wird mit `initial_temp_c` als Fallback gerechnet.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| initial_temp_c | 15 °C | 10–20 °C | Vor-Sunrise-Schwelle (nur mit Forecast gut) und Fallback, wenn kein Sensorwert vorhanden ist. |
| initial_temp_c_maessig | 20 °C | 15–25 °C | Nach-Sunrise-Einschaltschwelle für sicheren Thermoschutzbetrieb. |
| initial_temp_c_gut_nach_sunrise | 15 °C | 12–25 °C | Nach-Sunrise-Einschaltschwelle bei Forecast `gut` (früherer Start als maessig möglich). |
| temp_hysterese_k | 1.0 K | 0.2–3.0 K | Temperatur-Hysterese gegen die jeweilige Einschalt-Schwelle. |
| sunset_soc_stop_pct | 90% | 30–100% | Abschaltschwelle nach Sonnenuntergang: Klima AUS bei `SOC < Wert`. |
| extern_respekt_s | 1800 s | 300–7200 s | **Autoritätszeit (30 Min, 5 Min–2 h).** Bei manuellem Einschalten: Engine respektiert Nutzer-Entscheidung, nur Sunset+SOC-Schutz (`sunset_soc_stop_pct`) überstimmt. Bei manuellem Ausschalten: `klima_ein` für dieselbe Dauer gesperrt. |
| schaltintervall_s | 1800 s | 900–2700 s | **Schaltfrequenz-Fenster (15–45 Min).** Beobachtungszeitraum für AUS-Lastflanken-Zählung. Treten innerhalb dieses Fensters 2× HIGH→LOW-Flanken am SD-Zähler auf (Kompressor-intern oder SD-Schaltung), wird der Cooldown aktiviert. |
| cooldown_s | 3600 s | 1800–5400 s | **Kompressor-Schutzpause (30–90 Min).** EIN-Sperre ab dem zweiten AUS-Ereignis. Schützt den Kompressor vor zu kurzen Zyklen — SD geht aktiv aus, echte Pause statt geräte-interner Mikro-Pausen. Steuerbox-Override überstimmt den Cooldown. Im Flow sichtbar als ⏸ Nmin (amber). |

**Extern-Erkennung (Autoritätsschaltung):** Identisch zum HP-Muster (§4.10). Die Engine erkennt automatisch, wenn die Klimaanlage außerhalb der Engine eingeschaltet wird (Steuerbox, Fritz!Box-App, physischer Schalter): Klima ist EIN, aber kein Engine-Kommando liegt vor (180 s Grace-Window). In diesem Fall gilt für `extern_respekt_s` die Nutzer-Autorität: Temperaturlogik pausiert. Nur die harte Sicherheit (nach Sonnenuntergang bei `SOC < sunset_soc_stop_pct`) überstimmt sofort.

**Schaltfrequenz-Schutz:** Erkennt Kompressor-AUS-Ereignisse über **Lastflanken am Steckdosen-Zähler** (`klima_power_w`, Hysterese 600 W → 200 W). Damit werden auch geräte-interne Kurzzyklen erfasst (Klimagerät taktet selbst, SD bleibt EIN, Last springt ~1 kW ↔ ~30 W) — nicht nur SD-Schaltvorgänge. Bei 2× AUS-Flanke innerhalb `schaltintervall_s` wird `klima_ein` für `cooldown_s` gesperrt (SD geht aktiv aus, gibt dem Kompressor echte Pause). Steuerbox-Hold (aktiver Override) überstimmt den Cooldown; nach Ablauf der Steuerbox-Respektzeit greift die Frequenzprüfung wieder normal. Mindestabstand 60 s zwischen gezählten Events (Dedup gegen Last-Wackler). Der Cooldown-Zustand überlebt einen Daemon-Neustart (Persistenz in RAM-DB `engine_flags`).

---

### 4.12 ww_absenkung — WW-Nachtabsenkung (Priorität 2)

**Zweck:** Warmwasser-Solltemperatur (WP Modbus Reg 5047) nachts absenken, um
Standby-Verluste zu minimieren. Morgens automatisch auf Standardwert zurücksetzen.

**Score:** 45
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_ww_soll`)

**Logik:**
- 22:00–03:00: WW-Soll von `standard_temp_c` um `absenkung_k` reduzieren (57→50°C).
- Ab 03:00: Auf `standard_temp_c` zurückstellen.
- `extern_respekt_s`: Manuell gesetzte Werte werden für 30 Min respektiert.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| standard_temp_c | 57 °C | 42–65 °C | WW-Solltemperatur im Normalbetrieb |
| absenkung_k | 7 K | 0–10 K | Absenkungsbetrag (Nacht-Soll = Standard − K) |
| start_h | 22 h | 18–23 h | Beginn der Absenkung |
| ende_h | 3 h | 1–9 h | Ende der Absenkung (Rückkehr auf Standard) |
| extern_respekt_s | 1800 s | 0–7200 s | Schutzzeit bei externer Änderung |

---

### 4.13 heiz_absenkung — Heiz-Nachtabsenkung (Priorität 2)

**Zweck:** Heiz-Festwertsoll (WP Modbus Reg 5037) abends absenken. Morgens um
03:00 auf Standardwert zurück — rechtzeitig für die Fußbodenheizung (Bäder).

**Score:** 44
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_heiz_soll`)

**Logik:**
- 18:00–03:00: Heiz-Soll von `standard_temp_c` um `absenkung_k` reduzieren (37→30°C).
- Ab 03:00: Auf `standard_temp_c` zurückstellen.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| standard_temp_c | 37 °C | 28–47 °C | Heiz-Soll im Normalbetrieb |
| absenkung_k | 7 K | 0–10 K | Absenkungsbetrag |
| start_h | 18 h | 15–23 h | Beginn der Absenkung |
| ende_h | 3 h | 1–9 h | Ende der Absenkung |
| extern_respekt_s | 1800 s | 0–7200 s | Schutzzeit bei externer Änderung |

---

### 4.14 ww_verschiebung — WW-Bereitung verschieben (Priorität 2)

**Zweck:** Bei schlechter Energiebilanz (SOC niedrig, PV gering, aber guter
Forecast) die WW-Bereitung verschieben, indem WW-Soll vorübergehend abgesenkt
wird. Die WP pausiert die WW-Bereitung, SOC wird geschont.

**Score:** 47
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_ww_soll`)

**Bedingungslogik (Aktivierung):**
- SOC < `soc_schwelle_pct` (10%) UND PV < `pv_min_w` (2000 W)
- Forecast-Rest > `forecast_rest_min_kwh` (10 kWh) → genug Sonne erwartet
- WW-Ist > `ww_min_c` (45°C) → genug Reserven vorhanden
- Proaktiv: Greift auch wenn WP nicht aktiv ist

**Rücknahme:** PV > `pv_restore_w` ODER SOC > `soc_restore_pct` ODER Timeout `max_verschiebung_h`

**Sunset-Ausnahme:** < 2h vor Sonnenuntergang: Forecast-Schwelle halbiert.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| soc_schwelle_pct | 10 % | 5–50 % | SOC-Aktivierungsschwelle |
| pv_min_w | 2000 W | 1000–10000 W | PV-Aktivierungsschwelle |
| forecast_rest_min_kwh | 10 kWh | 3–30 kWh | Min. Forecast-Rest |
| ww_min_c | 45 °C | 35–55 °C | WW-Mindesttemperatur |
| verschiebung_k | 7 K | 1–15 K | Absenkungsbetrag |
| pv_restore_w | 3000 W | 1500–10000 W | PV-Rücknahme-Schwelle |
| soc_restore_pct | 30 % | 10–80 % | SOC-Rücknahme-Schwelle |
| max_verschiebung_h | 1 h | 0.5–6 h | Max. Verschiebungsdauer |

---

### 4.15 heiz_verschiebung — Heiz-Soll verschieben (Priorität 2)

**Zweck:** Analog zu WW-Verschiebung, aber für den Heizkreis. Bei schlechter
Energiebilanz Heiz-Soll absenken um Kompressor-Starts zu vermeiden.

**Score:** 46
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_heiz_soll`)

Gleiche Bedingungslogik und Sunset-Ausnahme wie ww_verschiebung. Parameter analog.

---

### 4.16 ww_boost — WW-Soll bei PV-Überschuss anheben (Priorität 2)

**Zweck:** Bei vollen Batterien (SOC > 90%) und Netzeinspeisung den PV-Überschuss
thermisch in Warmwasser puffern, statt einzuspeisen.

**Score:** 48
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_ww_soll`)

**Bedingungslogik:**
- SOC ≥ `soc_min_pct` (90%) UND Grid-Export ≥ `grid_export_min_w` (2000 W)
- WW-Ist < `ww_max_c` (60°C) → Sicherheitslimit
- WW-Verschiebung darf nicht gleichzeitig aktiv sein

**Rücknahme:** SOC < Schwelle ODER Export < Schwelle ODER WW ≥ Max ODER Timeout.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| soc_min_pct | 90 % | 70–100 % | SOC-Mindestwert für Boost |
| grid_export_min_w | 2000 W | 500–5000 W | Min. Netzeinspeisung |
| ww_max_c | 60 °C | 55–70 °C | WW-Sicherheitslimit |
| boost_temp_c | 62 °C | 55–70 °C | Boost-Zieltemperatur |
| max_boost_h | 2 h | 0.5–4 h | Max. Boost-Dauer |

---

### 4.17 wp_pflichtlauf — WP Täglicher Pflichtlauf (Priorität 2)

**Zweck:** Sicherstellen dass die WP mindestens einmal täglich den Kompressor
startet (Schmierung, Ventilbewegung). Im Sommer würde sie sonst tagelang
stillstehen.

**Score:** 49
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_heiz_soll`)

**Logik:**
- Wenn WP heute noch nicht gelaufen ist UND Uhrzeit ≥ `pflichtlauf_ab_h` (12:00):
  Heiz-Soll auf `boost_temp_c` (55°C) setzen für max `max_boost_min` (30 min).
- Endet automatisch wenn WP anspringt oder Timeout erreicht.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| pflichtlauf_ab_h | 12 h | 8–16 h | Frühester Start |
| boost_temp_c | 55 °C | 40–55 °C | Boost-Zieltemperatur |
| max_boost_min | 30 min | 10–60 min | Max. Boost-Dauer |

---

### 4.18 heiz_bedarf — FBH-Heizbedarf nach Außentemperatur (Priorität 2)

**Zweck:** Wenn die Fußbodenheizung (Fritz!DECT) Wärme anfordert (fbh_aktiv=1)
und es draußen kalt ist, den Heiz-Soll anheben oder auf Standard halten.
Überstimmt Absenkung/Verschiebung per Kommando-Deduplizierung (höchster WP-Score).

**Datenquellen:**
- FBH-Status: Fritz!DECT Steckdose „Fußbodenheizung" (AIN lt. fritz_config.json), State 0/1
- Außentemperatur: WP-Sensor (Dimplex SIK 11 TES, Modbus Reg 1)

**Score:** 50 (höchster aller WP-Regeln)
**Zyklus:** fast
**Aktor:** `waermepumpe` (`set_heiz_soll`)

**Prioritätsstufen:**

| Außentemperatur | Priorität | Heiz-Soll |
|-----------------|-----------|-----------|
| ≤ 5°C (kalt) | 100 % | Standard + `boost_k` (37+3 = 40°C) |
| 5–15°C (mild) | Mittel | Standard halten (37°C) |
| > 15°C (warm) | Gering | Keine Aktion |

**Rücknahme:** FBH inaktiv, Außentemp > 15°C oder Timeout.

| Parameter | Standard | Bereich | Wirkung |
|-----------|----------|---------|---------|
| temp_kalt_c | 5 °C | −10–10 °C | Volle Priorität unterhalb (Boost) |
| temp_mild_c | 15 °C | 5–25 °C | Mittlere Priorität unterhalb. Darüber: keine Aktion. |
| boost_k | 3 K | 0–10 K | Zuschlag bei ≤ temp_kalt_c |
| max_bedarf_h | 3 h | 1–8 h | Max. Dauer des Heizbedarf-Boosts |

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

## 9. Menü 9: Handbuch anzeigen

Öffnet die Datei `doc/automation/PV_CONFIG_HANDBUCH.md` direkt in pv-config
als scrollbaren Dialog. Damit sind Parameter-Hilfe und Bedienhinweise ohne
Editor-Wechsel per SSH verfügbar.

## 10. Grundlagenwissen

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
- **Gefahr (<5%):** BYD kann in den Notaus gehen. Tier-1-Alarmierung und SOC_MIN-Regeln schützen davor.

### Prioritäten und Score-Konflikte

Bei gleichzeitig aktiven Regeln entscheidet der Score:

| Regelkreis | Score | Priorität |
|------------|-------|-----------|
| **sls_schutz** | **95** | **P1 Sicherheit** |
| morgen_soc_min | 72 | P2 Steuerung |
| wattpilot_battschutz | 60 | P1 Sicherheit |
| nachmittag_soc_max | 55 | P2 Steuerung |
| forecast_plausibilisierung | 50 | P2 Steuerung |
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
| Schaltaktor | Fritz!DECT 200/210 (AIN …) |
| Fritz!Box | AHA-HTTP-API via login_sid.lua |
