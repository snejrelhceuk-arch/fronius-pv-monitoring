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

## Fixpunkte

| Ablesezeit (lokal) | System | Import kWh | Export kWh | Quelle / Detail |
|---|---|---:|---:|---|
| 2026-08-13 20:36     | iMSys | 4604.000    | 215.000  | OBIS 1.8.0 / 2.8.0 (abgelesen 20:36) |
| 2026-08-13 20:36:28  | SM    | 17133.227   | 875.356  | `W_Imp_Netz` / `W_Exp_Netz` |
| 2026-08-13 20:34:45  | PAC   | 45.522      | 27.281   | `Wh_imp` @801 / `Wh_exp` @809 (Tech-tmpfs) |

## Auswertung

Sobald ein **zweiter** Ablesesatz vorliegt, je System das Intervall-Delta bilden
und vergleichen:

```
Δ_System = Import/Export(t₂) − Import/Export(t₁)
Abweichung_SM   = (Δ_SM   − Δ_iMSys) / Δ_iMSys
Abweichung_PAC  = (Δ_PAC  − Δ_iMSys) / Δ_iMSys
```

Der iMSys-Bezug ist die Referenz; SM- und PAC-Abweichung zeigen, welches Gerät
näher an der Eichgröße liegt. Erst mit dieser Basis lassen sich die
PAC-Tagesabweichungen (v. a. die systematisch höhere Einspeisung) belastbar
bewerten.
