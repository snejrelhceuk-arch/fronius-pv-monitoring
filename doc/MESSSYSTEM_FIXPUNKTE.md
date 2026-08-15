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

| Zeitraum | Δ iMSys kWh | Δ SM kWh | SM-Abweichung |
|---|---:|---:|---:|
| Jan 2026 | 1101 | — | — |
| Feb 2026 | 1006 | — | — |
| Mär 2026 | 149 | 171.9 | **+15.4 %** |
| Apr 2026 | 125 | 128.7 | **+3.0 %** |
| Mai 2026 | 37 | 36.9 | **−0.3 %** |
| Jun 2026 | 30 | 33.6 | **+12.0 %** |
| Jul 2026 | 39 | 39.7 | **+1.8 %** |
| Aug 1–13 | 21 | 21.3 | **+1.4 %** |

### Monatsdeltas Export (Einspeisung)

| Zeitraum | Δ iMSys kWh | Δ SM kWh | SM-Abweichung |
|---|---:|---:|---:|
| Jan 2026 | 9 | — | — |
| Feb 2026 | 11 | — | — |
| Mär 2026 | 33 | 33.1 | **+0.3 %** |
| Apr 2026 | 25 | 25.8 | **+3.2 %** |
| Mai 2026 | 28 | 29.8 | **+6.4 %** |
| Jun 2026 | 24 | 25.4 | **+5.8 %** |
| Jul 2026 | 22 | 23.9 | **+8.6 %** |
| Aug 1–13 | 7 | 8.9 | **+27.1 %** |

### Befund

- **Import (Bezug):** SM weicht im März stark ab (+15 %), in den Folgemonaten näher an iMSys (±1–3 %), Juni erneut +12 %. Durchschnitt ~+5 %.
- **Export (Einspeisung):** SM liegt durchgängig **leicht über** iMSys (+3–9 %), Aug-Teilmonat zeigt hohe Abweichung (+27 %), aber geringe Absolutmenge (nur 7 kWh iMSys).
- Der **iMSys ist die Wahrheit**; SM ist gegen ihn zu prüfen. Systematische SM-Abweichung bedeutet: auch PAC muss gegen iMSys, *nicht* gegen SM, validiert werden. Erst mit dieser Basis lassen sich die PAC-Tagesabweichungen (systematisch höhere Einspeisung) belastbar bewerten.
