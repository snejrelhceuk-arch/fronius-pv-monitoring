# Fronius Gen24 — SOC-Modus (Auto vs. Manuell)

**Erstellt:** 2026-02-20  
**Betrifft:** F1 (Wohnhaus, Gen24 12kW + 2× BYD HVS 20.48 kWh), soweit relevant auch F2

---

## ⚠️ Wichtige Grundregel — gilt ohne Ausnahme

> **Eine Einstellung „Auto mit 75 % SOC_MAX" existiert NICHT.**
>
> Wer diese Kombination meint konfiguriert zu haben, trügt sich:
> Im Auto-Modus hat der Software-Stack keinerlei Einfluss auf SOC_MIN oder SOC_MAX.
> Die Grenzen sind **firmware-intern hardwired auf 5 – 100 %**.

---

## Die zwei Betriebsmodi des Fronius Gen24

### Modus 1: `SOC_MODE = "auto"` (Fronius-Firmware-Automatik)

| Eigenschaft | Wert |
|---|---|
| Steuert | Fronius-Firmware intern |
| SOC_MIN | **fest 5 %** (Firmware-Hardcode) |
| SOC_MAX | **fest 100 %** (Firmware-Hardcode) |
| Schreiben via HTTP-API | **wirkungslos** — kein Fehler, aber keine Wirkung |
| Schreiben via SunSpec Modbus M124 (`InWRte`, `OutWRte`) | **manuell möglich**, aber **nicht** Teil der Automation-Logik |
| Typisches Verhalten | Lädt Batterie auf 100 %, entlädt im Eigenverbrauchsoptimum |

**Was unsere Software im Auto-Modus tun kann:**
- Via Modbus `StorCtl_Mod`, `OutWRte`, `InWRte`: nur manuell über Diagnose-Tool (`automation/battery_control.py`), nicht automatisiert
- Via Modbus `MinRsvPct`: **Notstrom-Reserve** — sperrt Entladung unterhalb dieses SOC-Wertes im Normalbetrieb. Wird **nur** freigegeben wenn die Anlage tatsächlich im Inselbetrieb/Notstrom läuft. Dies ist eine eigene Kategorie — kein SOC_MIN-Ersatz, sondern ein Schutz-Reserve für den Backup-Fall. Nur relevant wenn Backup Power / Notstrom am Gen24 aktiviert und angeschlossen ist.
- Via `ChaGriSet`: Netzbezug zum Laden erlauben / sperren

**Was unsere Software im Auto-Modus NICHT tun kann:**
- SOC_MIN abweichend von 5 % setzen
- SOC_MAX abweichend von 100 % setzen

**⭐ Wann ist Auto-Modus sinnvoll?**  
Genau dann, wenn man die Grenzen *schnell und vollständig öffnen* will (= Vollbetrieb 5–100 %) —
ohne selbst `SOC_MIN = 5` und `SOC_MAX = 100` aggressiv auf den Inverter zu schreiben.
Die Firmware übernimmt das Laden/Entladen mit eigenem Regelungsverhalten und
**„reitet" nicht hart auf den Grenzwerten 5 % und 100 % herum** — das ist
schonender für die LFP-Zellen als ein externer Schreiber, der ständig die Extremwerte erzwingt.

Typische Anwendungsfälle für Auto:
- Zellausgleich (Vollladung gewünscht, aber firmware-geregelt)
- Morgen-Phase: SOC-Boden freigeben, bevor Prognose-Algorithmus die genauen Grenzen setzt
- Immer wenn volle Freigabe gewünscht ist, ohne 5/100 explizit zu erzwingen

---

### Modus 2: `SOC_MODE = "manual"` (via Fronius HTTP-API)

| Eigenschaft | Wert |
|---|---|
| Steuert | PIKO / unsere Software via HTTP-API |
| SOC_MIN | **frei konfigurierbar** via `/config/batteries` HTTP-POST |
| SOC_MAX | **frei konfigurierbar** via `/config/batteries` HTTP-POST |
| SunSpec Modbus | manuell nutzbar, aber nicht durch Engine-Regeln automatisch gesetzt |
| Typisches Verhalten | Ladung stoppt bei SOC_MAX, Entladung stoppt bei SOC_MIN |

**Im Manuell-Modus:** Die drei praxisrelevanten Komfort-Konfigurationen:

| Name | SOC_MIN | SOC_MAX | Wann |
|---|---|---|---|
| **Komfort** | 25 % | 75 % | Normalbetrieb, Batterie schonen |
| **Oben-offen** | 25 % | 100 % | Prognose gut, vollständig aufladen, Untergrenze bleibt |
| **Unten-offen** | 5 % | 75 % | Max. Eigenverbrauch, Überladeschutz bleibt |

> **Manual 5–100 % ist technisch möglich, aber unerwünscht.**  
> Wer volle Freigabe braucht, verwendet stattdessen `Auto` — die Firmware
> regelt schonender und ohne hartes Anfahren der Extremwerte.

**Reihenfolge beim Wechsel in einen Komfort-Bereich (wichtig!):**  
1. Zuerst `SOC_MODE = "manual"` setzen  
2. Dann `SOC_MIN` und `SOC_MAX` schreiben  

(Schreibt man die Grenzen während des Auto-Modus, haben sie keine Wirkung — der Modus-Wechsel muss zuerst kommen.)

---

## Wie wechselt man den Modus?

### Via Fronius HTTP-API (wie unser Stack es macht)

```python
# fronius_api.py — BatteryConfig.set_soc_mode()
payload = {
    "batteries": [{
        "BAT_M0_SOC_MODE": "manual",   # oder "auto"
        "BAT_M0_SOC_MIN":  25,         # nur wirksam im Manual-Modus
        "BAT_M0_SOC_MAX":  75,         # nur wirksam im Manual-Modus
    }]
}
# POST /config/batteries
# Authentifizierung: HA1=MD5, Rest=SHA256 (Custom Digest)
```

### Via Fronius Web-UI (Solarweb / Wechselrichter-Interface)
Einstellungen → Energiemanagement → Batteriensteuerung

---

## Fehler im ehemaligen Scheduler-Code

> **Hinweis:** `battery_scheduler.py` wurde 2026-02-28 archiviert und durch die
> 4-Schichten-Automation-Engine ersetzt (`pv-automation.service`).
> Die SOC-Steuerung erfolgt jetzt über `battery_control.py` + Regelkreise
> in `automation/engine/`. Die hier beschriebenen Modus-Erkenntnisse bleiben
> gültig als Referenz für das Fronius SOC-Verhalten.

Im ehemaligen `battery_scheduler.py` wurde an mehreren Stellen irrtümlich angenommen,
dass man im Auto-Modus SOC-Grenzen schreiben kann:

```python
# ❌ Fehler — hatte keine Wirkung, und ist konzeptionell falsch:
inverter.set_soc_mode("auto")
inverter.set_soc_min(5)    # wirkungslos im Auto-Modus!
inverter.set_soc_max(100)  # wirkungslos im Auto-Modus!

# ✅ Korrekt für vollständige Batterie-Freigabe (z.B. Zellausgleich):
# → Auto-Modus: Firmware übernimmt, kein aggressives 5/100-Anfahren
inverter.set_soc_mode("auto")   # reicht! 5–100 % sind hardwired, schonender als Manual 5/100

# ✅ Rückkehr in Komfort-Bereich (Reihenfolge beachten!):
inverter.set_soc_mode("manual")  # ERST Modus wechseln
inverter.set_soc_min(25)         # DANN Grenzen schreiben
inverter.set_soc_max(75)         # (oder 25/100 für oben-offen, oder 5/75 für unten-offen)
```

Betroffen: `_check_balancing()` (setzt Auto + 5/100 → die 5/100-Schreiber sind überflüssig, `Auto` allein genügt).  
`_apply_comfort_defaults()` (setzt Manuell + 25/75 — war bereits korrekt ✅).

---

## Aktuell beobachteter Live-State  (Stand: 2026-02-20)

```
BAT_M0_SOC_MODE:  auto   ← manuell gesetzt via Fronius-UI
BAT_M0_SOC_MIN:   5      ← ohne Wirkung in Auto-Modus
BAT_M0_SOC_MAX:   100    ← ohne Wirkung in Auto-Modus
StorCtl_Mod:      0      ← kein Modbus-Raten-Limit aktiv
SOC aktuell:      23.6 %
```

> **Hinweis:** Der Scheduler überschreibt manuell gesetzte Werte beim nächsten
> Cron-Run (alle 15 min) via `_verify_consistency()`.

---

## Konsequenzen für die Automation

1. **Zellausgleich:** `_check_balancing()` setzt `Auto` — ✅ richtig so. Die überflüssigen `set_soc_min(5)` / `set_soc_max(100)` Aufrufe danach können entfernt werden.
2. **Vollständige Freigabe** (Morgen-Phase öffnen, Überschuss-Laden): `Auto` verwenden — Firmware regelt schonender als Manual 5/100.
3. **Rückkehr in Komfort-Bereich:** zwingend `Manual` zuerst setzen, dann Grenzen. Drei Varianten:
   - `manual + 25/75` — Normalbetrieb/Komfort
   - `manual + 25/100` — Oben-offen (Vollladung erlaubt, Reserve unten bleibt)
   - `manual + 5/75` — Unten-offen (Vollentladung erlaubt, Überladeschutz bleibt)
4. **Standard-Reset** (`_apply_comfort_defaults()`) setzt `manual + 25/75` — ✅ passt.
5. **Manual 5–100 %** vermeiden — dafür gibt es Auto.
6. **Auto-Modus** ist kein Fehler, sondern ein legitimes Werkzeug für schnelle, schonende Grenz-Öffnung.

---

## Referenz

- [Fronius SunSpec Implementation Guide Model 124](https://www.fronius.com/~/downloads/Solar%20Energy/Modbus/42,0410,2049.pdf)
- `fronius_api.py` — `set_soc_mode()`, `set_soc_min()`, `set_soc_max()`
- `battery_control.py` — SOC-Steuerung (Nachfolger von battery_scheduler.py)
- `automation/engine/` — Regelkreise `RegelSocSchutz`, `RegelZellausgleich` etc.
