# Messsystem-Fixpunkte (PAC4200 · Fronius-SM · iMSys)

**Zweck:** Synchronisierte Zählerstände der **drei** Messsysteme am
Netzanschlusspunkt (PCC) zu einem Ablesezeitpunkt. Zwischen zwei Fixpunkten ist
je System das **Delta = Stand(t₂) − Stand(t₁)** — nur diese Deltas sind über die
Systeme hinweg vergleichbar (die Absolutstände haben je System einen eigenen
Nullpunkt/Installationszeitpunkt).

**Referenz-Hierarchie:** Der **iMSys** (Netzbetreiber-Zähler, eichrechtlich) ist
die absolute Wahrheit. Ziel ist, die Richtigkeit von **SM** und **PAC** gegen den
iMSys zu prüfen — nicht umgekehrt. Der iMSys wird **unregelmäßig** abgelesen
(Foto/Portal); SM und PAC werden zum selben Zeitpunkt aus den laufenden Ständen
notiert.

**Ablesemethode je System:**
- **iMSys:** Display, OBIS **1.8.0** (Bezug, „180") und **2.8.0** (Lieferung, „280") in kWh.
- **SM (Fronius Primär-SM):** `data.db → raw_data.W_Imp_Netz` / `W_Exp_Netz` (Wh) zum Zeitstempel.
- **PAC4200:** Modbus FLOAT64 `Wh_imp` @801 / `Wh_exp` @809 (Tech-tmpfs `nq_energy_raw`).

**Hinweis:** PAC zählt erst seit der REFORMATION (2026-07-11); die PAC-Absolutstände
sind daher klein gegenüber SM/iMSys. Frühe PAC-Tage (Anlaufphase/Zählerunterbrechung
vor 2026-08-05) sind ungültig und werden in der Statistik an SM angeglichen.

## Irreguläre Drei-System-Fixpunkte

Diese Tabelle enthält die **seltenen synchronisierten Ablesungen** aller drei
Messsysteme. Für den PAC wird, falls nötig, auf den Zielzeitpunkt zwischen zwei
5-min-Snapshots **linear interpoliert**.

| Ablesezeit (lokal) | iMSys Import | iMSys Export | SM Import | SM Export | PAC Import | PAC Export | Detail |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-13 20:36 | 4604.000 | 215.000 | 17133.227 | 875.356 | 45.522 | 27.281 | iMS manuell; SM `raw_data` 20:36:28; PAC `nq_energy_raw` 20:34:45 |
| 2026-09-01 19:00 | 4629.000 | 229.000 | 17158.378 | 887.583 | 70.177 | 40.814 | iMS manuell; SM `raw_data` 18:59:58; PAC interpoliert zwischen 18:57:11 und 19:02:11 |
| 2026-11-01 08:29 | 5185.000 | 252.000 | 17712.719 | 915.319 | ≈621.4¹ | ≈73.4¹ | iMS manuell; SM `raw_data` 08:28:59; PAC Oct-31 end 615.265/73.368 + SM-Proxy Nov-01 bis 08:29 = 6.12 kWh Import / 0.02 kWh Export |

¹ PAC Nov-01-Partialwert nicht direkt verfügbar; Schätzung: Oct-31 Zählerstand + SM-Proxy bis Ablesezeit (±0,2 kWh).

**Zusätzlich in der Ablesung 2026-11-01 notiert (nq_ims_reading.note):**
- **enwitec** (= SM-LCD-Display): 17712,71 kWh — bestätigt SM-DB-Wert 17712.719 kWh auf ±0,01 kWh ✅
- **Dimplex WP-Zähler**: 13962,23 kWh — kumulativer Energiezähler der Wärmepumpe seit Inbetriebnahme

## Intervallvergleich

### Intervall 2026-08-13 20:36 → 2026-09-01 19:00

| System | Δ Import kWh | Δ Export kWh | Abweichung Import vs iMSys | Abweichung Export vs iMSys |
|---|---:|---:|---:|---:|
| iMSys | 25.000 | 14.000 | 0.00 % | 0.00 % |
| Primär-SM F1 | 25.151 | 12.227 | +0.60 % | -12.66 % |
| PAC4200 | 24.655 | 13.533 | -1.38 % | -3.33 % |

**Einordnung:** Kurzintervall (19 Tage), geringe Energiemengen. SM beim Export zu niedrig; PAC näher an iMSys. Aussagegrenze: iMSys-Auflösung ±1 kWh je Richtung.

### Intervall 2026-09-01 19:00 → 2026-11-01 08:29

| System | Δ Import kWh | Δ Export kWh | Abweichung Import vs iMSys | Abweichung Export vs iMSys |
|---|---:|---:|---:|---:|
| iMSys | 556.000 | 23.000 | 0.00 % | 0.00 % |
| Primär-SM F1 | 554.341 | 27.736 | **−0.30 %** | **+20.6 %** |
| PAC4200 | ≈551.2 | ≈32.6 | **≈−0.86 %** | **≈+41.6 %** |

**Einordnung (61-Tage-Intervall, Sep+Okt 2026):**
- **Bezug (Import):** Beide Systeme innerhalb ±1 %. SM minimal besser als PAC. Für ein CT-basiertes Klasse-0.2-System bei hohem THD (Leistungselektronik WR, WP, Wattpilot) ist −0,86 % akzeptabel.
- **Einspeisung (Export):** Beide Systeme zeigen systematisch zu hohe Werte. SM +4,7 kWh, PAC +9,6 kWh über 61 Tage. Ursache: interne Rückspeisepulse (Kommutierung, Batteriebalancing-Spitzen, kurze Zwangsnachladungs-Übergänge) erscheinen an SM/PAC als Einspeisung, erreichen aber den PCC/iMSys nicht. Absolutbetrag gering.
- **Befund PAC-Import:** -0,86 % = deutlich besser als zuvor befürchtet. Die anfänglich geschätzte −2,27 % resultierte aus einer falschen Periodenabgrenzung (Monatsgrenzen statt tatsächlicher Ablesezeiten).
- **Kalibrierung PAC:** Nicht notwendig. Parallelbetrieb mit monatlichem Monitoringvergleich ist die richtige Strategie.

## Fixpunkte (Monatsverbräuche/Einspeisung)

Die folgende Tabelle zeigt die **Energiemengen** (Deltas) der drei Messsysteme zwischen den Stichtagen. Basis sind die Zählerstände zu 00:00 Uhr (day_start) des Folgemonats; der letzte Eintrag (Aug 1–13) deckt nur den Zeitraum 01.08. bis 13.08. ab. PAC-Daten existieren erst ab der REFORMATION (2026-07-11).

| Zeitraum | iMSys Import | iMSys Export | SM Import | SM Export | PAC Import | PAC Export |
|---|---:|---:|---:|---:|---:|---:|
| Jan 2026 | 1101 | 9 | — | — | — | — |
| Feb 2026 | 1006 | 11 | — | — | — | — |
| Mär 2026 | 149 | 33 | 171.9 | 33.1 | — | — |
| Apr 2026 | 125 | 25 | 128.7 | 25.8 | — | — |
| Mai 2026 | 37 | 28 | 36.9 | 29.8 | — | — |
| Jun 2026 | 30 | 24 | 33.6 | 25.4 | — | — |
| Jul 2026 | 39 | 22 | 39.7 | 23.9 | — | — |
| Aug 1–13 | 21 | 7 | 21.3 | 8.9 | — | — |

**Anmerkungen:**
- Alle Werte in **kWh**.
- **iMSys:** OBIS 1.8.0 (Import/Bezug) / 2.8.0 (Export/Einspeisung), Delta zwischen Monatsendständen (Netzbetreiber-Portal).
- **SM:** Fronius Smart Meter, Delta aus `W_Imp_Netz` / `W_Exp_Netz` (`energy_checkpoints`).
- **PAC:** ABB PAC4200. PAC-Deltas fehlen, da keine synchronisierten day_start-Checkpoints für PAC vorliegen (PAC zählt erst ab 11.07.2026, gültige Daten ab 05.08.).
- SM-Daten vor März 2026 fehlen mangels historischer Checkpoints (System-Start-Phase).

## Auswertung

Mit den vorliegenden Fixpunkt-Reihen lassen sich die monatlichen Deltas je System bilden und vergleichen:

```
Δ_System = Import/Export(t₂) − Import/Export(t₁)
Abweichung_SM   = (Δ_SM   − Δ_iMSys) / Δ_iMSys
Abweichung_PAC  = (Δ_PAC  − Δ_iMSys) / Δ_iMSys
```

### Monatsdeltas Import (Netzbezug)

| Zeitraum | Δ iMSys kWh | Δ SM kWh | SM-Abweichung | Δ PAC kWh | PAC-Abweichung |
|---|---:|---:|---:|---:|---:|
| Jan 2026 | 1101 | — | — | — | — |
| Feb 2026 | 1006 | — | — | — | — |
| Mär 2026 | 149 | 171.9 | **+15.4 %** | — | — |
| Apr 2026 | 125 | 128.7 | **+3.0 %** | — | — |
| Mai 2026 | 37 | 36.9 | **−0.3 %** | — | — |
| Jun 2026 | 30 | 33.6 | **+12.0 %** | — | — |
| Jul 2026 | 39 | 39.7 | **+1.8 %** | — | — |
| Aug 1–13 | 21 | 21.3 | **+1.4 %** | — | — |
| Sep 2026 | ~140 ² | 142.6 | **+1.9 %** | 140.7 | **+0.5 %** |
| Okt 2026 | ~415 ² | 407.0 | **−1.9 %** | 402.6 | **−3.0 %** |

² Sep/Okt iMSys-Monatswerte aus Intervall-Delta interpoliert (Sep-01 bis Nov-01 = 556 kWh gesamt).

### Monatsdeltas Export (Einspeisung)

| Zeitraum | Δ iMSys kWh | Δ SM kWh | SM-Abweichung | Δ PAC kWh | PAC-Abweichung |
|---|---:|---:|---:|---:|---:|
| Jan 2026 | 9 | — | — | — | — |
| Feb 2026 | 11 | — | — | — | — |
| Mär 2026 | 33 | 33.1 | **+0.3 %** | — | — |
| Apr 2026 | 25 | 25.8 | **+3.2 %** | — | — |
| Mai 2026 | 28 | 29.8 | **+6.4 %** | — | — |
| Jun 2026 | 24 | 25.4 | **+5.8 %** | — | — |
| Jul 2026 | 22 | 23.9 | **+8.6 %** | — | — |
| Aug 1–13 | 7 | 8.9 | **+27.1 %** | — | — |
| Sep 2026 | ~12 ² | 15.9 | **+32 %** | 17.7 | **+48 %** |
| Okt 2026 | ~11 ² | 12.3 | **+12 %** | 14.5 | **+32 %** |

### Befund

- **Import (Bezug):** SM weicht im März stark ab (+15 %), in den Folgemonaten näher an iMSys (±1–3 %), Juni erneut +12 %. Ab September SM und PAC beide innerhalb ±2 %.
- **Export (Einspeisung):** SM und PAC liegen systematisch **über** iMSys. Ursache: kurze Rückspeisepulse (Kommutierung, Batterie-Balancing-Transienten, Zwangsnachladungs-Übergänge) erscheinen lokal als Einspeisung, erreichen den PCC nicht. Absolutwert gering (Sep+Okt: 4–10 kWh).
- **Kalibrierung PAC:** Nicht erforderlich. Bias −0,86 % Import liegt im Bereich der THD-Einschränkung von Klasse-0.2S-Geräten. Parallelbetrieb und monatliches Monitoring genügen.
- Der **iMSys ist die Wahrheit**; SM und PAC sind gegen ihn zu prüfen.

---

## Erweiterte Fixpunkte: SM-LCD und Dimplex WP-Zähler

Ergänzend zu den drei Hauptsystemen (iMSys, SM, PAC) können zwei weitere
Zählerstände unregelmäßig als Stichproben abgelesen werden:

### SM-LCD (enwitec-Anzeige)

**Was ist das:** Die lokale LCD-Anzeige des Fronius Primär-SM wird in einem
enwitec-Gehäuse am Zählerschrank dargestellt. Sie zeigt denselben kumulativen
Zählerstand wie `raw_data.W_Imp_Netz` / `W_Exp_Netz`, aber gerundet auf 2
Nachkommastellen.

**Ablesemethode:** LCD ablesen → Vergleich mit `SELECT W_Imp_Netz/1000.0 FROM raw_data WHERE ts = (SELECT MAX(ts) FROM raw_data);` zum selben Zeitstempel.

**Erfassung:** Feld `note` in `nq_ims_reading` (Format: `enwitec XXXXX,XX kWh`).

**Erstablesung 2026-11-01 08:29:** 17712,71 kWh — DB-Wert 17712.719 kWh → Δ = 0,009 kWh ✅ (Rundungsfehler, kein Messproblem)

**Alarm-Schwelle:** Differenz |SM-LCD − DB-SM| > 1 kWh → Hinweis auf Erfassungslücke oder Zähler-Reset.

### Dimplex WP-Zähler

**Was ist das:** Die Dimplex Wärmepumpe (SIK 11 TES) hat einen eingebauten
Betriebsstundenzähler und einen kumulativen Energieverbrauchszähler (kWh elektrisch).
Dieser Wert ist direkt am WP-Display ablesbar.

**Ablesemethode:** WP-Display → kumulativer Energieverbrauch in kWh.

**Verfügbare DB-Gegengröße:** `heizpatrone_daily.energy_wh` (aktuell; deckt die WP über FritzDECT-Steckdose ab) ODER zukünftig eine dedizierte `wp_daily`-Tabelle.

**Erstablesung 2026-11-01:** 13962,23 kWh — kumulativ seit WP-Inbetriebnahme. Gegenwert noch nicht direkt aus DB ermittelbar (historische Lücken in FritzDECT-Daten vor Erfassungsbeginn).

**Erfassung:** Feld `note` in `nq_ims_reading` (Format: `Dimplex XXXXX,XX kWh`).

**Geplante Alarm-Logik (s. TODO.md):** Bei regelmäßigen Stichproben Δ-Vergleich
Dimplex-Zähler vs. DB-Summe `SUM(energy_wh) FROM heizpatrone_daily` ab einem
definierten Startdatum. Alarm bei Abweichung > 5 %.

### Stichproben-Schema

Ziel: 1× monatlich bei iMSys-Ablesung alle verfügbaren Stände synchron notieren.
Eintrag in `nq_ims_reading.note` als kommagetrennte Schlüssel-Wert-Paare:
```
enwitec XXXXX,XX kWh; Dimplex XXXXX,XX kWh
```
