# PAC4200 Modbus-Register — Strukturierte Referenz

**Quelle:** Konvertiert aus `Modbus.md` für bessere Lesbarkeit.  
**Gerät:** PAC4200 Stromqualitätsmessgeräte (Proventa/Siemens).  
**Standard:** Modbus TCP, Float = 32-Bit (2 Register à 16 Bit).  
**Zugriff:** R = Read-only, RW = Read/Write.

---

## 1. Netzspannungen (L-N und L-L)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 1      | 2        | Spannung L1-N | Float | V | - | R |
| 3      | 2        | Spannung L2-N | Float | V | - | R |
| 5      | 2        | Spannung L3-N | Float | V | - | R |
| 7      | 2        | Spannung L1-L2 | Float | V | - | R |
| 9      | 2        | Spannung L2-L3 | Float | V | - | R |
| 11     | 2        | Spannung L3-L1 | Float | V | - | R |

---

## 2. Ströme (pro Phase)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 13     | 2        | Strom L1 | Float | A | - | R |
| 15     | 2        | Strom L2 | Float | A | - | R |
| 17     | 2        | Strom L3 | Float | A | - | R |

---

## 3. Scheinleistung (S) — pro Phase

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 19     | 2        | Scheinleistung L1 | Float | VA | - | R |
| 21     | 2        | Scheinleistung L2 | Float | VA | - | R |
| 23     | 2        | Scheinleistung L3 | Float | VA | - | R |

---

## 4. Wirkleistung (P) — pro Phase

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 25     | 2        | Wirkleistung L1 | Float | W | - | R |
| 27     | 2        | Wirkleistung L2 | Float | W | - | R |
| 29     | 2        | Wirkleistung L3 | Float | W | - | R |

---

## 5. Blindleistung (Q, Qn) — pro Phase

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 31     | 2        | Blindleistung L1 (Qn) | Float | var | - | R |
| 33     | 2        | Blindleistung L2 (Qn) | Float | var | - | R |
| 35     | 2        | Blindleistung L3 (Qn) | Float | var | - | R |

---

## 6. Leistungsfaktor (cos φ) — pro Phase

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 37     | 2        | Leistungsfaktor L1 | Float | - | 0 ... 1 | R |
| 39     | 2        | Leistungsfaktor L2 | Float | - | 0 ... 1 | R |
| 41     | 2        | Leistungsfaktor L3 | Float | - | 0 ... 1 | R |

---

## 7. THD Spannung (Total Harmonic Distortion) — Leiterspannungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 43     | 2        | THD Spannung L1-L2 | Float | % | 0 ... 100 | R |
| 45     | 2        | THD Spannung L2-L3 | Float | % | 0 ... 100 | R |
| 47     | 2        | THD Spannung L3-L1 | Float | % | 0 ... 100 | R |

---

## 8. Netzfrequenz

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 55     | 2        | Netzfrequenz | Float | Hz | 45 ... 65 | R |

---

## 9. Mittelwerte (3-phasig)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 57     | 2        | 3-Phasen-Durchschnitt Spannung L-N | Float | V | - | R |
| 59     | 2        | 3-Phasen-Durchschnitt Spannung L-L | Float | V | - | R |
| 61     | 2        | 3-Phasen-Durchschnitt Strom | Float | A | - | R |

---

## 10. Gesamtleistungen (3-phasig)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 63     | 2        | Gesamtscheinleistung (S) | Float | VA | - | R |
| 65     | 2        | Gesamtwirkleistung (P) | Float | W | - | R |
| 67     | 2        | Gesamtblindleistung (Qn) | Float | var | - | R |
| 69     | 2        | Gesamtleistungsfaktor | Float | - | - | R |

---

## 11. Unsymmetrieverhältnisse

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 71     | 2        | Amplitudenunsymmetrie der Spannung | Float | % | 0 ... 100 | R |
| 73     | 2        | Amplitudenunsymmetrie des Stroms | Float | % | 0 ... 100 | R |

---

## 12. Maximale Werte (Spannungen L-N)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 75     | 2        | Max. Spannung L1-N | Float | V | - | R |
| 77     | 2        | Max. Spannung L2-N | Float | V | - | R |
| 79     | 2        | Max. Spannung L3-N | Float | V | - | R |

---

## 13. Maximale Werte (Spannungen L-L)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 81     | 2        | Max. Spannung L1-L2 | Float | V | - | R |
| 83     | 2        | Max. Spannung L2-L3 | Float | V | - | R |
| 85     | 2        | Max. Spannung L3-L1 | Float | V | - | R |

---

## 14. Maximale Ströme

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 87     | 2        | Max. Strom L1 | Float | A | - | R |
| 89     | 2        | Max. Strom L2 | Float | A | - | R |
| 91     | 2        | Max. Strom L3 | Float | A | - | R |

---

## 15. Maximale Scheinleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 93     | 2        | Max. Scheinleistung L1 | Float | VA | - | R |
| 95     | 2        | Max. Scheinleistung L2 | Float | VA | - | R |
| 97     | 2        | Max. Scheinleistung L3 | Float | VA | - | R |

---

## 16. Maximale Wirkleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 99     | 2        | Max. Wirkleistung L1 | Float | W | - | R |
| 101    | 2        | Max. Wirkleistung L2 | Float | W | - | R |
| 103    | 2        | Max. Wirkleistung L3 | Float | W | - | R |

---

## 17. Maximale Blindleistungen (Qn)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 105    | 2        | Max. Blindleistung L1 (Qn) | Float | var | - | R |
| 107    | 2        | Max. Blindleistung L2 (Qn) | Float | var | - | R |
| 109    | 2        | Max. Blindleistung L3 (Qn) | Float | var | - | R |

---

## 18. Maximale Leistungsfaktoren

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 111    | 2        | Max. Leistungsfaktor L1 | Float | - | 0 ... 1 | R |
| 113    | 2        | Max. Leistungsfaktor L2 | Float | - | 0 ... 1 | R |
| 115    | 2        | Max. Leistungsfaktor L3 | Float | - | 0 ... 1 | R |

---

## 19. Maximale THD Spannungen (L-L)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 117    | 2        | Max. THD Spannung L1-L2 | Float | % | 0 ... 100 | R |
| 119    | 2        | Max. THD Spannung L2-L3 | Float | % | 0 ... 100 | R |
| 121    | 2        | Max. THD Spannung L3-L1 | Float | % | 0 ... 100 | R |

---

## 20. Reserveregister

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 123    | 2        | Reserve | - | - | - | - |
| 125    | 2        | Reserve | - | - | - | - |
| 127    | 2        | Reserve | - | - | - | - |

---

## 21. Maximale Netzfrequenz und Mittelwerte

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 129    | 2        | Max. Netzfrequenz | Float | Hz | 45 ... 65 | R |
| 131    | 2        | Max. 3-Phasen-Durchschnitt Spannung L-N | Float | V | - | R |
| 133    | 2        | Max. 3-Phasen-Durchschnitt Spannung L-L | Float | V | - | R |
| 135    | 2        | Max. 3-Phasen-Durchschnitt Strom | Float | A | - | R |

---

## 22. Maximale Gesamtleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 137    | 2        | Max. Gesamtscheinleistung | Float | VA | - | R |
| 139    | 2        | Max. Gesamtwirkleistung | Float | W | - | R |
| 141    | 2        | Max. Gesamtblindleistung (Qn) | Float | var | - | R |
| 143    | 2        | Max. Gesamtleistungsfaktor | Float | - | - | R |

---

## 23. Minimale Spannungen (L-N)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 145    | 2        | Min. Spannung L1-N | Float | V | - | R |
| 147    | 2        | Min. Spannung L2-N | Float | V | - | R |
| 149    | 2        | Min. Spannung L3-N | Float | V | - | R |

---

## 24. Minimale Spannungen (L-L)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 151    | 2        | Min. Spannung L1-L2 | Float | V | - | R |
| 153    | 2        | Min. Spannung L2-L3 | Float | V | - | R |
| 155    | 2        | Min. Spannung L3-L1 | Float | V | - | R |

---

## 25. Minimale Ströme

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 157    | 2        | Min. Strom L1 | Float | A | - | R |
| 159    | 2        | Min. Strom L2 | Float | A | - | R |
| 161    | 2        | Min. Strom L3 | Float | A | - | R |

---

## 26. Minimale Scheinleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 163    | 2        | Min. Scheinleistung L1 | Float | VA | - | R |
| 165    | 2        | Min. Scheinleistung L2 | Float | VA | - | R |
| 167    | 2        | Min. Scheinleistung L3 | Float | VA | - | R |

---

## 27. Minimale Wirkleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 169    | 2        | Min. Wirkleistung L1 | Float | W | - | R |
| 171    | 2        | Min. Wirkleistung L2 | Float | W | - | R |
| 173    | 2        | Min. Wirkleistung L3 | Float | W | - | R |

---

## 28. Minimale Blindleistungen (Qn)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 175    | 2        | Min. Blindleistung L1 (Qn) | Float | var | - | R |
| 177    | 2        | Min. Blindleistung L2 (Qn) | Float | var | - | R |
| 179    | 2        | Min. Blindleistung L3 (Qn) | Float | var | - | R |

---

## 29. Minimale Leistungsfaktoren

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 181    | 2        | Min. Leistungsfaktor L1 | Float | - | 0 ... 1 | R |
| 183    | 2        | Min. Leistungsfaktor L2 | Float | - | 0 ... 1 | R |
| 185    | 2        | Min. Leistungsfaktor L3 | Float | - | 0 ... 1 | R |

---

## 30. Minimale Netzfrequenz

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 187    | 2        | Min. Netzfrequenz | Float | Hz | 45 ... 65 | R |

---

## 31. Minimale 3-Phasen-Durchschnitte

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 189    | 2        | Min. 3-Phasen-Durchschnitt Spannung L-N | Float | V | - | R |
| 191    | 2        | Min. 3-Phasen-Durchschnitt Spannung L-L | Float | V | - | R |
| 193    | 2        | Min. 3-Phasen-Durchschnitt Strom | Float | A | - | R |

---

## 32. Minimale Gesamtleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 195    | 2        | Min. Gesamtscheinleistung | Float | VA | - | R |
| 197    | 2        | Min. Gesamtwirkleistung | Float | W | - | R |
| 199    | 2        | Min. Gesamtblindleistung (Qn) | Float | var | - | R |
| 201    | 2        | Min. Gesamtleistungsfaktor | Float | var | - | R |

---

## 33. Status und Diagnostik

### Grenzwertverletzungen (Offset 203)

**Modbus Offset 203, Register 2** — 32-Bit Status-Word (4 Bytes):

| Byte | Bit | Signal | Maske | Bedeutung |
|------|-----|--------|-------|-----------|
| 3    | 0–7 | Grenzwert 0–7 | 0x000000FF | Einzelne Grenzwerte |
| 2    | 0–3 | Grenzwert 8–11 | 0x0000FF00 | Weitere Grenzwerte |
| 0    | 0   | Grenzwert VKE | 0x01000000 | VKE-Status |
| 0    | 1–4 | Funktionsblöcke 1–4 | 0x02000000–0x10000000 | Logik-Verknüpfungen |

**Interpretation:**
- 0 = Grenzwert nicht verletzt / Funktion inaktiv
- 1 = Grenzwert verletzt / Funktion aktiv

---

### PMD Diagnose und Status (Offset 205)

**Modbus Offset 205, Register 2** — 32-Bit Diagnose-Word:

| Byte | Bedeutung |
|------|-----------|
| 0    | Systemstatus |
| 1    | Gerätestatus |
| 2    | Gerätediagnose |
| 3    | Komponentendiagnose |

#### Byte 0: Systemstatus

| Bit | Signal | Maske | Zugriff |
|-----|--------|-------|---------|
| 0   | Kein Synchronisierimpuls | 0x01000000 | R |
| 1   | Konfigurationsmenü aktiv | 0x02000000 | R |
| 2   | Spannung übersteuert | 0x04000000 | R |
| 3   | Strom übersteuert | 0x08000000 | R |

#### Byte 1: Gerätestatus

| Bit | Signal | Maske | Zugriff |
|-----|--------|-------|---------|
| 0   | Modul Steckplatz 1 | 0x00010000 | R |
| 1   | Impulsfrequenz zu hoch | 0x00020000 | R |
| 2   | Modul Steckplatz 2 | 0x00040000 | R |

#### Byte 2: Gerätediagnose

| Bit | Signal | Maske | Zugriff |
|-----|--------|-------|---------|
| 0   | Basiskonfiguration geändert | 0x00000100 | R |
| 1   | Grenzwertüberschreitung gespeichert | 0x00000200 | R |
| 2   | Impulsfrequenz zu hoch (Diagnose) | 0x00000400 | R |
| 3   | Neustart des Geräts | 0x00000800 | R |
| 4   | Energiezähler zurückgesetzt | 0x00001000 | R |

#### Byte 3: Komponentendiagnose (Slot 1 & 2)

| Bit | Signal | Maske | Zugriff |
|-----|--------|-------|---------|
| 0   | Slot 1 Parameteränderungen | 0x00000001 | R |
| 1   | Slot 1 I&M-Datenänderungen | 0x00000002 | R |
| 2   | Slot 1 Firmwareupdate aktiv | 0x00000004 | R |
| 3   | Firmwareupdate verfügbar | 0x00000008 | R |
| 4   | Bootloader-Update-Flag | 0x00000010 | R |
| 5   | Slot 2 Parameteränderungen | 0x00000020 | R |
| 6   | Slot 2 I&M-Datenänderungen | 0x00000040 | R |
| 7   | Slot 2 Firmware aktiv | 0x00000080 | R |

---

## 34. Digital I/O und Tarif

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 207    | 2        | Digitalausgänge Status | ULong | - | Bit 0–1 | R |
| 209    | 2        | Digitaleingänge Status | ULong | - | Bit 0–1 | R |
| 211    | 2        | Aktiver Tarif | ULong | - | 0=Tarif1, 1=Tarif2 | R |

---

## 35. Betriebszähler und Ereignisprotokollierung

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 213    | 2        | Betriebsstundenzähler | ULong | s | 0 ... 999.999.999 | RW |
| 215    | 2        | Universalzähler | ULong | - | 0 ... 999.999.999 | RW |
| 217    | 2        | Änderungszähler Grundparameter | ULong | - | - | R |
| 219    | 2        | Änderungszähler alle Parameter | ULong | - | - | R |
| 221    | 2        | Änderungszähler Grenzwerte | ULong | - | - | R |
| 223    | 2        | Zähler alle Ereignisse | ULong | - | - | R |
| 225    | 2        | Zähler alle Alarme | ULong | - | - | R |
| 227    | 2        | Zähler Lastgangeinträge | ULong | - | - | R |
| 229    | 2        | Zähler Sonstiges | ULong | - | - | R |

---

## 36. Status Digital I/O Module 1 & 2

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 231    | 2        | Status Digitalausgänge Modul 1 | ULong | - | Bit 0–1 | R |
| 233    | 2        | Status Digitaleingänge Modul 1 | ULong | - | Bit 0–1 | R |
| 235    | 2        | Status Digitalausgänge Modul 2 | ULong | - | Bit 0–1 | R |
| 237    | 2        | Status Digitaleingänge Modul 2 | ULong | - | Bit 0–1 | R |

---

## 37. Phasen-Parameter (cos φ, Phasenwinkel, THD)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 243    | 2        | cos φ L1 | Float | - | - | R |
| 245    | 2        | cos φ L2 | Float | - | - | R |
| 247    | 2        | cos φ L3 | Float | - | - | R |
| 249    | 2        | Phasenverschiebungswinkel L1 | Float | ° | - | R |
| 251    | 2        | Phasenverschiebungswinkel L2 | Float | ° | - | R |
| 253    | 2        | Phasenverschiebungswinkel L3 | Float | ° | - | R |
| 255    | 2        | Phasenwinkel L1–L1 | Float | ° | - | R |
| 257    | 2        | Phasenwinkel L1–L2 | Float | ° | - | R |
| 259    | 2        | Phasenwinkel L1–L3 | Float | ° | - | R |

---

## 38. THD Spannungen (pro Phase, Einzelleiterspannungen)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 261    | 2        | THD Spannung L1 | Float | % | 0 ... 100 | R |
| 263    | 2        | THD Spannung L2 | Float | % | 0 ... 100 | R |
| 265    | 2        | THD Spannung L3 | Float | % | 0 ... 100 | R |

---

## 39. THD Ströme (pro Phase)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 267    | 2        | THD Strom L1 | Float | % | 0 ... 100 | R |
| 269    | 2        | THD Strom L2 | Float | % | 0 ... 100 | R |
| 271    | 2        | THD Strom L3 | Float | % | 0 ... 100 | R |

---

## 40. Stromverzerrung (pro Phase)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 273    | 2        | Verzerrung Strom L1 | Float | A | - | R |
| 275    | 2        | Verzerrung Strom L2 | Float | A | - | R |
| 277    | 2        | Verzerrung Strom L3 | Float | A | - | R |

---

## 41. Blindleistung (Qtot und Q1) — pro Phase

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 279    | 2        | Gesamtblindleistung L1 (Qtot) | Float | var | - | R |
| 281    | 2        | Gesamtblindleistung L2 (Qtot) | Float | var | - | R |
| 283    | 2        | Gesamtblindleistung L3 (Qtot) | Float | var | - | R |
| 285    | 2        | Blindleistung L1 (Q1) | Float | var | - | R |
| 287    | 2        | Blindleistung L2 (Q1) | Float | var | - | R |
| 289    | 2        | Blindleistung L3 (Q1) | Float | var | - | R |

---

## 42. Unsymmetrien und Neutralleiter

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 291    | 2        | Spannungsunsymmetrie | Float | % | 0 ... 100 | R |
| 293    | 2        | Stromunsymmetrie | Float | % | 0 ... 100 | R |
| 295    | 2        | Neutralleiterstrom | Float | A | - | R |

---

## 43. Gesamtblindleistung (3-phasig)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 297    | 2        | Gesamtblindleistung (Qtot) | Float | var | - | R |
| 299    | 2        | Gesamtblindleistung (Q1) | Float | var | - | R |

---

## 44. Gleitende Mittelwerte — Spannungen (L-N und L-L)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 301    | 2        | Gleitender MW Spannung L1-N | Float | V | - | R |
| 303    | 2        | Gleitender MW Spannung L2-N | Float | V | - | R |
| 305    | 2        | Gleitender MW Spannung L3-N | Float | V | - | R |
| 307    | 2        | Gleitender MW Spannung L1-L2 | Float | V | - | R |
| 309    | 2        | Gleitender MW Spannung L2-L3 | Float | V | - | R |
| 311    | 2        | Gleitender MW Spannung L3-L1 | Float | V | - | R |

---

## 45. Gleitende Mittelwerte — Ströme

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 313    | 2        | Gleitender MW Strom L1 | Float | A | - | R |
| 315    | 2        | Gleitender MW Strom L2 | Float | A | - | R |
| 317    | 2        | Gleitender MW Strom L3 | Float | A | - | R |

---

## 46. Gleitende Mittelwerte — Scheinleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 319    | 2        | Gleitender MW Scheinleistung L1 | Float | VA | - | R |
| 321    | 2        | Gleitender MW Scheinleistung L2 | Float | VA | - | R |
| 323    | 2        | Gleitender MW Scheinleistung L3 | Float | VA | - | R |

---

## 47. Gleitende Mittelwerte — Wirkleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 325    | 2        | Gleitender MW Wirkleistung L1 | Float | W | - | R |
| 327    | 2        | Gleitender MW Wirkleistung L2 | Float | W | - | R |
| 329    | 2        | Gleitender MW Wirkleistung L3 | Float | W | - | R |

---

## 48. Gleitende Mittelwerte — Blindleistungen (Qn)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 331    | 2        | Gleitender MW Blindleistung L1 (Qn) | Float | var | - | R |
| 333    | 2        | Gleitender MW Blindleistung L2 (Qn) | Float | var | - | R |
| 335    | 2        | Gleitender MW Blindleistung L3 (Qn) | Float | var | - | R |

---

## 49. Gleitende Mittelwerte — Blindleistungen (Qtot)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 337    | 2        | Gleitender MW Gesamtblindleistung L1 (Qtot) | Float | var | - | R |
| 339    | 2        | Gleitender MW Gesamtblindleistung L2 (Qtot) | Float | var | - | R |
| 341    | 2        | Gleitender MW Gesamtblindleistung L3 (Qtot) | Float | var | - | R |

---

## 50. Gleitende Mittelwerte — Blindleistungen (Q1)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 343    | 2        | Gleitender MW Blindleistung L1 (Q1) | Float | var | - | R |
| 345    | 2        | Gleitender MW Blindleistung L2 (Q1) | Float | var | - | R |
| 347    | 2        | Gleitender MW Blindleistung L3 (Q1) | Float | var | - | R |

---

## 51. Gleitende Mittelwerte — Leistungsfaktoren

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 349    | 2        | Gleitender MW Leistungsfaktor L1 | Float | - | 0 ... 1 | R |
| 351    | 2        | Gleitender MW Leistungsfaktor L2 | Float | - | 0 ... 1 | R |
| 353    | 2        | Gleitender MW Leistungsfaktor L3 | Float | - | 0 ... 1 | R |

---

## 52. Gleitende Mittelwerte — Gesamtleistungen

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 355    | 2        | Gleitender MW Gesamtscheinleistung | Float | VA | - | R |
| 357    | 2        | Gleitender MW Gesamtwirkleistung | Float | W | - | R |
| 359    | 2        | Gleitender MW Gesamtblindleistung (Qn) | Float | var | - | R |
| 361    | 2        | Gleitender MW Gesamtblindleistung (Qtot) | Float | var | - | R |
| 363    | 2        | Gleitender MW Gesamtblindleistung (Q1) | Float | var | - | R |
| 365    | 2        | Gleitender MW Gesamtleistungsfaktor | Float | - | - | R |
| 367    | 2        | Gleitender MW Neutralleiterstrom | Float | A | - | R |

---

## 53. Spezialisierte Zähler

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 369    | 2        | Prozessbetriebsstundenzähler | ULong | s | 0 ... 999.999.999 | RW |
| 371    | 2        | Universalzähler 2 | ULong | - | 0 ... 999.999.999 | RW |
| 373–391 | 2        | Impulszähler 0–10 (Offset +2) | ULong | - | 0 ... 999.999.999 | RW |

---

## 54. Periode & Lastegang (Offset 483–543)

### Zeitstempel und Periode

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 483    | 4        | Zeitstempel der aktuellen Periode | Timestamp | - | - | R |
| 489    | 2        | Länge der aktuellen Periode | ULong | s | - | R |
| 517    | 2        | Zeit seit Beginn der Periode | ULong | s | - | R |
| 519    | 2        | Tatsächliche Subintervalldauer | ULong | s | - | R |

### Mittelwerte in aktueller Periode

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 489    | 2        | Mittelwert Scheinleistung | Float | VA | - | R |
| 491    | 2        | Mittelwert Wirkleistung Bezug | Float | W | - | R |
| 493    | 2        | Mittelwert Blindleistung Bezug | Float | var | - | R |
| 495    | 2        | Mittelwert Wirkleistung Lieferung | Float | W | - | R |
| 497    | 2        | Mittelwert Blindleistung Lieferung | Float | var | - | R |

### Kumulierte Werte in aktueller Periode

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 499    | 2        | Kumulierte Scheinleistung | Float | VA | - | R |
| 501    | 2        | Kumulierte Wirkleistung Bezug | Float | W | - | R |
| 503    | 2        | Kumulierte Blindleistung Bezug | Float | var | - | R |
| 505    | 2        | Kumulierte Wirkleistung Lieferung | Float | W | - | R |
| 507    | 2        | Kumulierte Blindleistung Lieferung | Float | var | - | R |

### Min/Max in aktueller Periode

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 509    | 2        | Max. Wirkleistung in Periode | Float | W | - | R |
| 511    | 2        | Min. Wirkleistung in Periode | Float | W | - | R |
| 513    | 2        | Max. Blindleistung in Periode | Float | var | - | R |
| 515    | 2        | Min. Blindleistung in Periode | Float | var | - | R |
| 525    | 2        | Max. Scheinleistung in Periode | Float | VA | - | R |
| 527    | 2        | Min. Scheinleistung in Periode | Float | VA | - | R |

### Periode-Informationen (Offset 523)

| Byte | Bit | Signal | Maske | Bedeutung |
|------|-----|--------|-------|-----------|
| 0    | 0   | Tarifinformation | 0x01 | Tarif-ID |
| 1    | 0–3 | Qualitätsinformation | 0x0F | Qualitäts-Flag |
| 2    | -   | Reserve | - | Reserviert |
| 3    | 0–3 | Blindleistungs-Info | 0x0F | Blindleistungs-Typ |

---

## 55. Momentane Periode (Offset 529–543)

| Offset | Register | Name | Format | Einheit | Bereich | Zugriff |
|--------|----------|------|--------|---------|---------|---------|
| 529    | 2        | Kumulierte Wirkleistung Bezug (momentan) | Float | W | - | R |
| 531    | 2        | Kumulierte Blindleistung Bezug (momentan) | Float | var | - | R |
| 533    | 2        | Kumulierte Wirkleistung Lieferung (momentan) | Float | W | - | R |
| 535    | 2        | Kumulierte Blindleistung Lieferung (momentan) | Float | var | - | R |
| 537    | 2        | Max. Wirkleistung (momentan) | Float | W | - | R |
| 539    | 2        | Min. Wirkleistung (momentan) | Float | W | - | R |
| 541    | 2        | Max. Blindleistung (momentan) | Float | var | - | R |
| 543    | 2        | Min. Blindleistung (momentan) | Float | var | - | R |

---

## Notizen und Konventionen

### Datentypen
- **Float:** 32-Bit IEEE-754, belegt 2 Register (à 16 Bit).
- **ULong / Unsigned long:** 32-Bit Ganzzahl, belegt 2 Register.
- **Timestamp:** 32-Bit Unix-Zeit (Sekunden seit 1970), belegt 4 oder 2 Register je nach Konfiguration.

### Zugriff
- **R:** Read-only (Lesezugriff)
- **RW:** Read-Write (Lese- und Schreibzugriff)

### Registeradressierung
- Modbus nutzt **0-basierte Offsets**, aber viele Dokumentationen verwenden **1-basierte Nummerierung**.
- Diese Tabellen verwenden **Offset** (0-based).
- Jedes Register ist **16 Bit breit**; 32-Bit-Werte (Float, ULong) benötigen **2 Register**.

### Blindleistung (Q)
- **Qn:** Grundschwingung (Fundamental)
- **Q1:** Erste Harmonische
- **Qtot:** Gesamtblindleistung (alle Harmonischen)

### Phasennotation
- **L-N:** Phasenleiterspannung (Phase gegen Neutralleiter)
- **L-L:** Leiterspannung (Phase gegen Phase)
