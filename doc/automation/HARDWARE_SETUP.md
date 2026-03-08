# Hardware-Setup — MEGA-BAS auf Pi4

> Stand: 2026-02-14

---

## 1. Systemvoraussetzungen

### Raspberry Pi 4 (192.168.2.181)
- Betriebssystem: Raspberry Pi OS
- I2C: **Muss noch aktiviert werden!**
- Python 3 mit `smbus2`

### I2C aktivieren

```bash
# Option A: raspi-config
sudo raspi-config nonint do_i2c 0
sudo reboot

# Option B: Manuell in /boot/config.txt
# Zeile ändern von:
#   #dtparam=i2c_arm=on
# zu:
#   dtparam=i2c_arm=on
sudo reboot
```

### Nach Neustart prüfen

```bash
# I2C-Bus sollte /dev/i2c-1 zeigen
ls /dev/i2c-*

# MEGA-BAS auf Adresse 0x48 finden
i2cdetect -y 1
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 40: -- -- -- -- -- -- -- -- 48 -- -- -- -- -- -- --
```

---

## 2. Software installieren

### Python-Bibliothek

```bash
sudo pip3 install SMmegabas
```

### CLI-Tool (optional aber nützlich)

```bash
cd /home/admin/Dokumente
git clone https://github.com/SequentMicrosystems/megabas-rpi.git
cd megabas-rpi
sudo make install

# Test
megabas 0 board
megabas -h
```

---

## 3. Funktionstest

### Python Quick-Test

```python
import megabas

# Firmware-Version lesen
print("Version:", megabas.getVer(0))

# TRIACs lesen
print("TRIACs:", megabas.getTriacs(0))

# TRIAC 1 einschalten (24VAC Ausgang AC1)
megabas.setTriac(0, 1, 1)
print("TRIAC 1 ON:", megabas.getTriac(0, 1))

# TRIAC 1 ausschalten
megabas.setTriac(0, 1, 0)
print("TRIAC 1 OFF:", megabas.getTriac(0, 1))

# 0-10V Eingang 1 lesen
print("IN1 Spannung:", megabas.getUIn(0, 1), "V")

# 10K Thermistor an Eingang 1 lesen (nur wenn als 10K konfiguriert)
# megabas 0 incfgwr 1 2  (10K Thermistor Mode)
print("IN1 Widerstand 10K:", megabas.getRIn10K(0, 1), "kOhm")

# Versorgungsspannung
print("24V Versorgung:", megabas.getInVolt(0), "V")
print("5V Raspberry:", megabas.getRaspVolt(0), "V")
print("CPU Temp:", megabas.getCpuTemp(0), "°C")
```

### CLI Quick-Test

```bash
# Board-Info
megabas 0 board

# TRIAC schreiben/lesen
megabas 0 trwr 1 on      # TRIAC 1 ein
megabas 0 trrd            # Alle TRIACs lesen
megabas 0 trwr 1 off      # TRIAC 1 aus

# 0-10V Eingang lesen
megabas 0 adcrd 1         # Kanal 1 auslesen

# Thermistor lesen
megabas 0 incfgwr 1 2     # Kanal 1 auf 10K Thermistor umschalten
megabas 0 r10krd 1        # 10K Widerstand lesen

# RTC
megabas 0 rtcrd           # Uhrzeit lesen
```

---

## 4. Verkabelungsplan (Vorläufig)

### Stromversorgung

```
24VAC/DC Netzteil ──────► MEGA-BAS [24VAC/DC] + [GND]
                          (Board versorgt auch den Pi4 über 5V/5A Step-Down)
```

### TRIAC-Ausgänge (24VAC!)

```
MEGA-BAS                    Lastkreis
─────────                   ─────────
AC1 ──► Installationsschütz 24VAC-Spule ──► Heizpatrone 2kW (230V)
AC2 ──► Installationsschütz 24VAC-Spule ──► Klimaanlage 1,3kW (230V)
AC3 ──► Brandschutzklappe 1 Stellantrieb (24VAC)
AC4 ──► Brandschutzklappe 2 Stellantrieb (24VAC)
```

### Analogeingänge (Thermistoren)

```
10K NTC Thermistor ──┬──► IN1 (Speicher oben)
                     └──► GND
10K NTC Thermistor ──┬──► IN2 (Speicher mitte)
                     └──► GND
10K NTC Thermistor ──┬──► IN3 (Speicher unten)
                     └──► GND
10K NTC Thermistor ──┬──► IN4 (Außentemperatur)
                     └──► GND
```

### RS485 — Dimplex WP Modbus RTU (LWPM 410)

```
MEGA-BAS RS485 [A] ──► LWPM 410 RS485 [A]    (Dimplex Art.Nr. 339410)
MEGA-BAS RS485 [B] ──► LWPM 410 RS485 [B]    (~155 EUR)
                 └──► 120Ω Terminierung an beiden Bus-Enden!
```

**Modbus RTU Konfiguration:**
- Baudrate: 19200 (lt. Dimplex-Doku für WPM_H)
- Slave ID: 1
- Protokoll: Modbus RTU
- Python-Lib: `pymodbus` (`pip3 install pymodbus`)

**Voraussetzung:** WPM muss Steckplatz "Serial Card / BMS Card" haben.
Kompatibel ab WPM 2004, Software H_H50.

**Datenpunkte (Auswahl):**
- Temperaturen: Außen (R1), Rücklauf (R2), WW (R3), Vorlauf (R9), Sole (R6)
- Schreibbar: WW-Solltemp (5047), Betriebsmodus (5015), Smart Grid (Coil 3+4)
- Status: Betrieb (103), Sperren (104), Störungen (105)
- Historie: Laufstunden Verdichter (72), Flanschheizung (78), Wärmemengen (5096ff)

---

## 5. Sicherheitshinweise

### 5.1 TRIAC-Ausgänge — ⚠️ AC-only!

**TRIACs sind KEINE potentialfreien Kontakte!**
- Halbleiter-AC-Schalter, schalten bei Nulldurchgang ab
- **Funktionieren NICHT mit dem 24VDC-Bus!**
- Max. Rating (v4.2): **1A / 120V AC**
- Benötigen separate AC-Quelle (24VAC-Trafo) falls verwendet

**Empfehlung:** Statt TRIACs → **Eight Relays HAT** ($45) stacken:
- Potentialfreie Kontakte (N.O./N.C.)
- Schalten AC und DC (4A/120VAC)
- Kompatibel mit dem vorhandenen 24VDC-Bus
- 8 Relaisausgänge → mehr als genug für alle Aktoren

### 5.2 Allgemeine Sicherheit

1. **Niemals 230V/400V direkt an MEGA-BAS-Ausgänge!** Max. 120V AC an TRIACs.
2. **Alle 230V/400V-Lasten über Installationsschütze** schalten.
3. **Sicherheitstemperaturbegrenzer (STB)** am Speicher ist Pflicht — unabhängig von Software.
4. **FI-Schutzschalter** im Lastkreis der Heizpatrone.
5. **Schütz-Dimensionierung** muss zur Last passen:
   - Heizpatrone 2kW/230V → ~9A → mind. 20A Schütz (AC-1 Kategorie)
   - Klimaanlage 1,3kW/230V → ~6A → mind. 16A Schütz
   - Später 3-Phasen-Heizpatrone: 3×20A Schütz (AC-1)
6. **Watchdog nutzen:** MEGA-BAS Hardware-Watchdog stellt sicher, dass bei
   Software-Absturz die TRIACs abgeschaltet werden.

---

## 6. TRIAC-Spitzensperrspannung & Induktive Lasten

### Typischer TRIAC auf MEGA-BAS: Z0109MA (oder vergleichbar)

| Parameter | Wert |
|-----------|------|
| $V_{DRM}$ | **600V** (repetitive Spitzensperrspannung) |
| $I_{T(RMS)}$ | 1A |
| $I_{TSM}$ | ~10A (Stoß) |
| Typ | Snubberless-fähig |

### Analyse: Rückspannungspulse an Schützspulen

```
24VAC Installationsschütz, typisch 3-10 VA:
  • Spulenstrom: 0,1 - 0,4 A
  • Induktivität: 1 - 5 H
  • Rückspannungspuls beim Abschalten: 80 - 150V Spitze
  • TRIAC V_DRM: 600V
  • Sicherheitsfaktor: 600V / 150V = 4,0 → AUSREICHEND

Zum Vergleich bei 230VAC (nicht unser Fall!):
  • Rückspannungspuls: 600 - 1200V Spitze
  • Sicherheitsfaktor: 600V / 1200V = 0,5 → NICHT AUSREICHEND!
  → Bei 230VAC wäre Snubber PFLICHT
```

### Empfehlung für 24VAC-Schützspulen

**Option A: Kein Snubber (funktioniert bei 24VAC)**
- 600V $V_{DRM}$ > 150V Rückspannung → sicher
- TVS-Schutz auf MEGA-BAS Inputs vorhanden
- Einfachste Lösung

**Option B: RC-Snubber (empfohlen für Langlebigkeit + EMV)**
```
Parallel zur Schützspule:
  R = 100Ω / 0,5W
  C = 100nF / 275V AC (X2-Klasse)
  Kosten: ~0,50 EUR pro Aktor
```

**Option C: Varistor (Alternative)**
```
Parallel zur Schützspule:
  S07K30 (Klemmspannung ~47V bei 1mA)
  Begrenzt Rückspannung auf ~50V
```
