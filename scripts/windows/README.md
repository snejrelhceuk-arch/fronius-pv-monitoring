# Windows-Zugang zum PV-System per SSH

## Überblick

Der Ordner **`pv-system per SSH/`** enthält fertige BAT-Dateien,
die auf **jedem Windows 10/11 PC** per Doppelklick funktionieren.

Einfach den Ordner auf einen USB-Stick kopieren → am beliebigen PC einstecken → starten.

## Dateien

| Datei | Zweck | Wann |
|-------|-------|------|
| `01 — SSH einrichten (einmalig).bat` | SSH-Key generieren & auf Pi4 kopieren | Einmalig pro PC |
| `02 — PV-Config starten.bat` | Konfigurations-Menü per SSH | Tägliche Nutzung |
| `03 — Shell öffnen.bat` | Linux-Kommandozeile auf Pi4 | Bei Bedarf |
| `04 — Verbindung testen.bat` | Ping + SSH + Status prüfen | Bei Problemen |
| `LIES MICH.txt` | Kurzanleitung | Zum Nachlesen |

## Schnellstart

### Erster Start (einmalig pro PC)

1. **`01 — SSH einrichten (einmalig).bat`** doppelklicken
2. Pi4-Passwort eingeben (einmalig)
3. Fertig — SSH-Key ist installiert

### Tägliche Nutzung

**`02 — PV-Config starten.bat`** doppelklicken → Konfigurations-Menü öffnet sich.

## Voraussetzung

**OpenSSH-Client** — ist in Windows 10/11 standardmäßig enthalten.

Falls nicht: *Einstellungen → System → Optionale Features → OpenSSH-Client aktivieren*

## Netzwerk

Die Scripts verbinden zum **Pi4 Primary** (192.168.2.181, User: admin).
Funktioniert nur im lokalen Netzwerk (192.168.2.x) oder über VPN.

## Sicherheit

- Kein offener Port — nur SSH (Port 22)
- Config-Tool schreibt nur JSON-Dateien, kein Modbus/DB-Zugriff
- SSH-Key kann jederzeit widerrufen werden (Zeile aus `~/.ssh/authorized_keys` auf Pi4 entfernen)
- Siehe: `doc/AUTOMATION_ARCHITEKTUR.md` §3 (S1 Config-Schicht)
