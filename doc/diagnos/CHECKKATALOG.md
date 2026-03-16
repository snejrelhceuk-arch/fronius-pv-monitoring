# Checkkatalog — Diagnos D

**Stand:** 16. Maerz 2026  
**Status:** Planungsdokument

---

## 1. Host und Hardware

| Bereich | Beispiele | Methode |
|---|---|---|
| CPU / SoC | Temperatur, Frequenz, Load | Systemdateien, `vcgencmd`, `/proc`, `uptime` |
| Spannungsqualitaet | Unterspannung, Throttling, historische Flags | Raspberry-Pi-Health-Flags |
| RAM | frei, Pressure, OOM-Hinweise | `/proc/meminfo`, Journal |
| Kernel | I/O-Fehler, USB-Abbrueche, Link-Flaps | `journalctl`, `dmesg`-Auswertung |

## 2. Datentraeger und Backups

| Bereich | Beispiele | Methode |
|---|---|---|
| Primary SD | Belegung, DB-Groesse, Wachstum | `df`, `stat`, Dateivergleich |
| Failover SD | Mirror-Alter, freier Platz | Sync-Marker, `df` |
| Pi5 SSD | Backup-Freshness, Archivrotation, freier Platz | SSH/Remote-Check, Backup-Metadaten |

## 3. Prozesse und Services

| Bereich | Beispiele | Methode |
|---|---|---|
| Collector | aktiv, Restart-Zaehler, Frische | systemd + SQL |
| Web | API erreichbar, systemd-Status | HTTP-Check + systemd |
| Automation | Heartbeat, Fehlerquote, Action-Logs | systemd + DB |
| Wattpilot | Prozess lebt, Polling-Zustand | systemd + DB |
| Cron/Timer | letzter Lauf, Drift, deaktiviert | systemd, Crontab, Log-Check |

## 4. Daten-Freshness

| Bereich | Signal | Ziel |
|---|---|---|
| `raw_data` | letzter Zeitstempel | Collector lebt |
| `data_1min` | letzter Zeitstempel | Minute-Pipeline lebt |
| `data_15min` | letzter Zeitstempel | Quartals-Pipeline lebt |
| `daily_data` | laufender Tag / letzter Abschluss | Tagesaggregation lebt |
| Mirror | Alter der Failover-DB | Failover einsetzbar |
| Pi5-Backup | Alter des letzten GFS-Backups | Langzeit-Restore abgesichert |

## 5. Datenintegritaet

| Pruefung | Ziel |
|---|---|
| Counter monoton bzw. bekannte Reset-Muster | defekte Zaehler oder Schreibartefakte erkennen |
| Tageswerte vs. Counter-Differenzen | Statistik und technische Basis vergleichen |
| `monthly_statistics` vs. `daily_data` | Rollup korrekt |
| `yearly_statistics` vs. `monthly_statistics` | Rollup korrekt |
| Gap-Scan je Tabelle | Unterbrechungen klassifizieren |
| Config-Parse | defekte JSON-/Service-Konfiguration erkennen |

## 6. Parity und Systemkonsistenz

| Bereich | Ziel |
|---|---|
| Git-Stand Primary vs. Failover | gleicher Code-Stand |
| relevante Config-Dateien | gleicher fachlicher Stand |
| systemd-Units | gleiche Betriebsdefinition |
| Cron/Timer | gleiche periodische Ablaufe |
| `.role` und Guards | klare Rollenlage |

## 7. I/O und Infrastruktur

| Bereich | Ziel |
|---|---|
| LAN / Routing | Basis-Erreichbarkeit |
| SSH | Betriebszugang verfuegbar |
| Fronius Modbus / HTTP | Datenquelle erreichbar |
| Wattpilot | Statuszugriff kontrolliert moeglich |
| Fritz!Box | HP-Aktor erreichbar |
| USB-RS485 | kuenftige WP-/MEGA-BAS-Anbindung sichtbar |
| MEGA-BAS | I2C/Board erreichbar, sobald aktiviert |

## 8. Berichtswesen

| Ausgabe | Inhalt |
|---|---|
| Kurz-Warnung | Einzelereignis, Schwelle, Host, Zeit |
| Taeglicher Bericht | Trends, Gaps, Speicher, Restart-Historie |
| Eskalationsbericht | Ursache, Trigger, empfohlene Aktion |