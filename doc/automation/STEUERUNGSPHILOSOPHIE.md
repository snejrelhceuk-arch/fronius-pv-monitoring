# Steuerungsphilosophie — PV-Anlage Erlau

**Erstellt:** 2026-03-08  
**Autor:** Betreiber (holistische Ansichten zur PV-Steuerung)  
**Geltungsbereich:** Alle Automation-Entscheidungen, Regel-Design, Parametrierung

---

## 1. Leitprinzipien

### Konservativ, aber PV maximal ausreizen

> Die Anlage soll **jeden verfügbaren kWh aus der PV nutzen**, ohne dabei
> Hardware zu gefährden oder die Betriebsstabilität zu riskieren.
> Lieber einmal zu wenig geschaltet als einmal zu viel.

Nulleinspeiser (0 €/kWh Vergütung) — jedes Watt, das nicht verbraucht wird,
ist verlorene Energie. Die Steuerung muss daher **aktiv** nach Verwertungsmöglichkeiten
suchen, statt nur passiv auf Überschuss zu reagieren.

### Netzbezug vermeiden

> Strom aus dem Netz kostet ~30 ct/kWh. Jede Schaltaktion, die Netzbezug
> verursacht, ist ein Kostenfehler.

Regeln müssen Netzbezug aktiv vermeiden:
- HP-Bursts nur bei nachgewiesenem PV-Überschuss (nicht bei Batterie-Entladung ins Netz)
- 5-Minuten-Glättung des Netzbezugs (kein Abschalten bei kurzen Leistungssprüngen)
- Drain-Modus prüft, ob Energie aus PV oder aus Netz kommt (erzwungene Nachladung erkennen)

### SOC-Grenzen meiden

> LFP-Batterien leben am längsten im Komfortbereich (25–75 %).
> **Nur prognosegesteuert** darf der Komfortbereich verlassen werden.

SOC_MAX wird im Sommer typisch bei 75 % gehalten und erst nachmittags auf 100 %
geöffnet. SOC_MIN wird morgens nur bei ausreichender Prognose auf 5 % gesenkt.
Saisonale Anpassung: Im Winter flexibleres SOC_MAX, im Sommer strenger begrenzt.

---

## 2. Messprinzipien

### Phasenströme statt Gesamtleistung

> **Der Strom wird am SmartMeter F1 (Netz, Zählerplatz) gemessen.**
> Die Phasenströme I_L1_Netz, I_L2_Netz, I_L3_Netz sind die wahren
> Belastungsindikatoren — nicht die Gesamtleistung.

Der SLS (Selektiver Leitungsschutzschalter) am Zählerplatz ist **35A je Phase**
(3-phasig). Die maximale Gesamtleistung beträgt:

$$P_{max} = \sqrt{3} \times 400\,\text{V} \times 35\,\text{A} \approx 24\,\text{kW}$$

**Warum per-Phase und nicht Gesamt?**
- Der SLS löst **je Phase** aus, nicht summiert
- Eine einzelne Phase kann überlastet sein, obwohl die Gesamtleistung unter 24 kW liegt
- Asymmetrische Lasten (HP auf einer Phase, EV auf einer anderen) erfordern Einzelbetrachtung

**SLS ist träge** — 35A als exakte Schwelle ist ausreichend. Keine Warnstufen
nötig. Der SLS löst ohne Vorwarnung aus → Schutzregel muss vor Erreichen der
35A eingreifen.

**Datenfluss:**
```
SmartMeter Netz (F1) → Modbus (modbus_v3.py) → raw_data
  → DataCollector → ObsState.i_l1_netz_a / i_l2_netz_a / i_l3_netz_a
  → RegelSlsSchutz → HP AUS + Wattpilot dimmen
```

**Erweiterungspotenzial:** 1-Minuten-Durchschnittswerte der Phasenströme wären
ebenfalls denkbar (analog zu P_Netz_avg in data_1min) — derzeit werden die
Momentanwerte aus raw_data verwendet.

### Batterie-Ladeleistung als Überschuss-Indikator

> P_PV zeigt bei einem Nulleinspeiser **nicht** die verfügbare PV-Kapazität.
> Der Wechselrichter drosselt, sobald kein Verbraucher abnimmt.
> **P_Batt > 5 kW** ist der zuverlässige Indikator für echten Überschuss.

Deshalb verwendet die HP-Steuerung P_Batt als primären Trigger,
nicht P_PV oder P_Netz.

### Forecast als einziger Voraus-Indikator

> Nur die Prognose weiß, was kommt. Alle anderen Messwerte zeigen
> nur den aktuellen Zustand.

Regeln nutzen `forecast_rest_kwh`, `forecast_power_profile` und
`forecast_quality` für Voraus-Entscheidungen:
- Morgen-Drain: Nur bei guter/mittlerer Prognose
- Phase 1 (Vormittag): rest_kwh ≥ `potenzial_maessig_kwh` (Standard 20 kWh)
- Phase 4 (Abend): Forecast-Stundenleistung als PV-Proxy

---

## 3. Schaltphilosophie

### Burst statt Dauerlauf

> Die HP läuft nicht kontinuierlich, sondern in **kurzen Bursts** (15–30 Min).
> Nach jedem Burst: Pause, Situation neu bewerten, ggf. nächster Burst.

Vorteile:
- Reagiert auf Wetteränderungen (Wolkendurchgang → kein neuer Burst)
- Batterie kann zwischen Bursts nachladen
- Verhindert Langzeitentladung der Batterie durch HP

### Probierlogik (Nulleinspeiser-Erkennung)

> **„Geht nach dem Einschalten der HP die Erzeugung hoch,
> ist noch Potential vorhanden."**

Der Nulleinspeiser drosselt die PV-Anlage bei Sättigung. Die gedrosselte
Kapazität ist unsichtbar (P_PV zeigt nur den aktuellen Verbrauch). Die
**Probe-Logik** testet aktiv, ob versteckte Kapazität vorhanden ist:

1. **Probe-Burst** (120 s): HP kurz einschalten
2. **Auswertung**: ΔPV ≥ 500 W und Grid ≤ 300 W?
   - **Ja** → WR hatte gedrosselt → Burst verlängern (30 Min)
   - **Nein** → Keine versteckte Kapazität → HP aus, Cooldown (600 s)
3. **Cooldown**: Nächster Probe-Versuch erst nach 10 Min

### Nachladezyklus am Abend (Phase 4)

> **Phase 4 ist kein „Hard Block" mehr.** Die HP darf abends kurze Bursts
> fahren, solange SOC nahe SOC_MAX bleibt und PV noch produziert.

Zyklus:
```
HP EIN → SOC sinkt (HP zieht ~2kW) → SOC < MAX−10% → HP AUS
  → Batterie lädt nach → SOC ≈ MAX → HP EIN → ...
```

Adaptiv zu SOC_MAX: Im Sommer (SOC_MAX = 75%) bedeutet „nahe MAX" ≈ 73%.
Im Winter (SOC_MAX = 100%) bedeutet „nahe MAX" ≈ 98%.

**Primärziel:** Batterie-Vollladung. HP nutzt nur die Restkapazität,
die nach dem Laden übrig bleibt.

### Morgen-Drain nach Sonnenaufgang, nicht nach Batterie

> **Phase 0 startet prognosegetrieben ab sunrise − 1h, nicht erst wenn
> P_Batt > 0 ist.** So wird die Batterie rechtzeitig geleert, bevor
> die PV-Anlage zu produzieren beginnt.

Der alte Trigger `P_Batt > 0` (PV lädt bereits) war falsch bei erzwungener
Netzladung: Dort ist P_Batt > 0, aber die Energie kommt aus dem Netz.
Neuer Trigger: Uhrzeit + Prognose.

### Phase 1 — Wiedereintritt mit reduzierter Schwelle

> Nach einem Vormittags-Burst sinkt P_Batt kurzzeitig (HP hat ~2kW gezogen).
> Die **Wiedereintritts-Schwelle** wird um HP_NENN_W reduziert,
> damit die HP nach der Pause wieder einschalten kann.

Beispiel: min_ladeleistung_morgens = 3000 W. Nach dem ersten Burst und
< 10 Min Pause: Schwelle = max(1000, 3000 − 2000) = 1000 W.

---

## 4. Schutzphilosophie

### Keine Warnstufen beim SLS

> Der SLS löst **ohne Vorwarnung** aus. Deshalb gibt es keine
> Warn-/Alarm-Stufen (anders als bei Batterie-Temperatur).
> Eine einzige Schwelle: 35A je Phase.

### Deterministische Schutzregeln

> Schutzregeln sind **Hardgrenzen, keine Empfehlungen**.
> Sie gelten vor allen Optimierungsregeln.
> Kein Score-System, kein Fuzzy-Override kann sie außer Kraft setzen.

### SOC 5% als absolute Untergrenze

> Unter 5% kann die BYD in den Notaus gehen. Alle SOC-Defaults
> und Fallback-Werte verwenden 5%, nicht 7%.

---

## 5. Saisonale Anpassung

| Parameter | Sommer (Mai–Aug) | Winter (Nov–Feb) | Übergang |
|-----------|-------------------|-------------------|----------|
| SOC_MAX Komfort | 75% | flexibel (bis 100%) | 75% |
| SOC_MIN Stress | 5% | 5% | 5% |
| HP-Drain | ab sunrise−1h | selten (wenig PV) | ab sunrise−1h |
| Phase 4 (Abend) | aktiv (SOC≈75%) | inaktiv (PV reicht nicht) | bedingt |
| Probe-Logik | häufig (viel gedrosselte PV) | selten | gelegentlich |

---

*Letzte Aktualisierung: 2026-03-08*  
*Verwandte Dokumente:* [STRATEGIEN.md](../automation/STRATEGIEN.md) · [SCHUTZREGELN.md](SCHUTZREGELN.md) · [PV_CONFIG_HANDBUCH.md](PV_CONFIG_HANDBUCH.md) · [BEOBACHTUNGSKONZEPT.md](BEOBACHTUNGSKONZEPT.md)
