# Taktung und Eskalation — Diagnos D

**Stand:** 16. Maerz 2026  
**Status:** Planungsdokument

---

## 1. Leitlinie

Keine kalenderbasierten Neustarts des Collectors.

Restarts oder Reboots sind nur dann sinnvoll, wenn die Diagnos-Schicht einen
konkreten Fehlerzustand erkennt und klassifiziert. Standardreaktion ist daher:

1. lesen
2. klassifizieren
3. melden
4. erst dann gezielt eingreifen

---

## 2. Empfohlene Taktung

### Alle 30 bis 60 Sekunden

- `raw_data`-Freshness
- Prozess lebt / systemd aktiv
- CPU-Temperatur
- Unterspannung / Throttling
- LAN / API kurz erreichbar

### Alle 5 Minuten

- `data_1min`, `data_15min` aktuell
- lokale Datentraegerbelegung
- Journal-Fehler kurz scannen
- USB-/RS485-/I2C-Geraete sichtbar

### Alle 15 Minuten

- Mirror-Freshness
- Pi5-Backup-Freshness
- Config-Parse-Checks
- Restart-Zaehler und Drift
- erste SQL-Invarianten

### Stuendlich

- tiefere Aggregations-Stichproben
- Parity der relevanten Configs und Units
- Datenwachstum und Kapazitaet

### Taeglich

- Trendbericht
- Gap-Klassenbericht
- Restore-/Backup-Lage
- Empfehlung: weiter beobachten, gezielt restart, Failover oder Hardware pruefen

---

## 3. Ausfallklassen

| Klasse | Beispiel | Standardreaktion |
|---|---|---|
| **Mikro** | < 2 min | nur zaehlen, sichtbar machen |
| **Kurz** | 2-30 min | Warnung, Folgepruefung |
| **Mittel** | 30 min-6 h | Warnung + vertiefte Diagnose + Eskalation |
| **Lang** | > 6 h | Incident, manuelle Bewertung, moeglicher Failover/Hardwarecheck |

---

## 4. Schutzreaktionen

| Stufe | Aktion | Automatisierbar? |
|---|---|---|
| D1 | Mail / Log / Statusflag | ja |
| D2 | Health-Report mit Ursache und Empfehlung | ja |
| D3 | gezielter Restart eines Hilfsdiensts mit Cooldown | spaeter, nur eng begrenzt |
| D4 | Host-Reboot | nur nach klaren Kriterien, nicht als Standard |
| D5 | Hardwaretausch / Verkabelungspruefung | manuell |

---

## 5. Datenpolitik bei Ausfaellen

- **Technische Reihen:** echte Luecke bleibt sichtbar
- **Statistik:** counter-basierte Korrektur ist erlaubt
- **Diagnos:** markiert die Luecke, verschleiert sie aber nicht