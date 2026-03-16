# MEGA-BAS — Uebersicht und Einordnung

**Stand:** 16. Maerz 2026  
**Status:** Planungs- und Referenzdokument

---

## 1. Einordnung im Projekt

MEGA-BAS gehoert fachlich in den Bereich **Automation-Hardware**.

Deshalb liegen die Unterlagen nicht mehr lose im Wurzelverzeichnis `doc/`,
sondern gesammelt unter `doc/automation/megabas/`.

Aktuelle Rolle im Projekt:

- zusaetzliche Sensorik und I/O fuer kuenftige Automation
- I2C-HAT fuer Pi4/Pi5
- optionaler RS485-Traeger fuer kuenftige WP-/Feldbus-Anbindungen

---

## 2. Relevante Dokumente

| Dokument | Zweck |
|---|---|
| `doc/automation/HARDWARE_SETUP.md` | Setup und Verkabelung auf dem Pi |
| `doc/automation/TODO.md` | Phasenplan fuer Sensorik, Relais, WP und Integration |
| `doc/automation/BEOBACHTUNGSKONZEPT.md` | geplanter Einsatz in Observer/Automation |
| `doc/automation/megabas/MODBUS_REFERENZ.md` | knappe operative RTU-Hinweise |

---

## 3. Projektstatus

- Hardware ist als kuenftige Erweiterung eingeplant
- I2C-/RS485-Nutzung ist noch nicht produktiv eingebunden
- die aktuelle Heizpatrone laeuft produktiv ueber Fritz!DECT, nicht ueber MEGA-BAS

---

## 4. Dokumentationsregel

Dieses Verzeichnis enthaelt nur projektbezogene, verdichtete Referenzen.

Vollstaendige Herstellerdokumentation bleibt extern verlinkt und wird nicht
1:1 ins Projekt gespiegelt.