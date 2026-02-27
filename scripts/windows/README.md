# Windows-Terminal Zugang zum PV-System

## Überblick

Drei Zugangswege vom Windows-PC zum PV-Config-Tool auf dem Pi4:

| Methode | Aufwand | Komfort |
|---------|---------|---------|
| **Windows Terminal Profil** | Setup-Script einmalig | ⭐⭐⭐ Dropdown → Klick |
| **pv-config.bat** | Doppelklick | ⭐⭐ Desktop-Shortcut |
| **pv-config.ps1** | PowerShell | ⭐⭐ Flexibel mit Parametern |

---

## Schnellstart (empfohlen)

### 1. Setup-Script ausführen (einmalig)

PowerShell öffnen und ausführen:

```powershell
# Script aus dem Repo holen (USB-Stick, Netzlaufwerk oder Git Clone)
cd pfad\zu\pv-system\scripts\windows

# Alles einrichten (SSH-Key + Terminal-Profil)
.\setup-terminal-profile.ps1
```

Das Script erledigt automatisch:
- SSH-Key generieren (Ed25519) — falls noch keiner vorhanden
- Public Key auf den Pi4 kopieren (Passwort wird **einmalig** abgefragt)
- SSH-Config Eintrag `pv-pi4` anlegen
- Windows Terminal Profil "PV-Config" hinzufügen

### 2. Nutzen

**Windows Terminal** → Dropdown-Pfeil (▼) neben dem Tab → **PV-Config**

→ Verbindet automatisch zum Pi4 und startet das Konfigurations-Menü.

---

## Manuelles Setup

Falls das automatische Setup nicht gewünscht ist:

### SSH-Key einrichten

```powershell
# 1. Key generieren
ssh-keygen -t ed25519 -C "pv-config@MEIN-PC"

# 2. Key auf Pi4 kopieren (einmalig Passwort eingeben)
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh admin@192.168.2.181 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

# 3. Test (kein Passwort mehr nötig)
ssh admin@192.168.2.181 "hostname && date"
```

### SSH-Config Eintrag

Datei `%USERPROFILE%\.ssh\config` — hinzufügen:

```
Host pv-pi4
    HostName 192.168.2.181
    User admin
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ConnectTimeout 10
    RequestTTY yes
```

### Windows Terminal Profil manuell

Windows Terminal → Einstellungen → JSON öffnen → in `profiles.list` einfügen:

```json
{
    "name": "PV-Config",
    "guid": "{e7a1b3c4-5d6f-4a8b-9c0e-1f2a3b4c5d6e}",
    "commandline": "ssh -t pv-pi4 \"cd '/home/admin/Dokumente/PVAnlage/pv-system' && python3 pv-config.py; exec bash --login\"",
    "icon": "ms-appx:///ProfileIcons/{9acb9455-ca41-5af7-950f-6bca1bc9722f}.png",
    "colorScheme": "One Half Dark",
    "startingDirectory": "%USERPROFILE%",
    "hidden": false,
    "tabTitle": "PV-Config (Pi4)"
}
```

---

## Varianten

### Nur Shell (ohne Config-Tool)

```powershell
# PowerShell-Script
.\pv-config.ps1 -ShellOnly

# Oder direkt
ssh -t pv-pi4 "cd '/home/admin/Dokumente/PVAnlage/pv-system' && exec bash --login"
```

### Failover-Pi statt Primary

```powershell
.\pv-config.ps1 -Host 192.168.2.105 -User jk
```

### Zweites Profil für Failover (Windows Terminal JSON)

```json
{
    "name": "PV-Config (Failover)",
    "guid": "{f8b2c4d5-6e7f-5b9c-0d1e-2f3a4b5c6d7f}",
    "commandline": "ssh -t jk@192.168.2.105 \"cd '/home/jk/Dokumente/PVAnlage/pv-system' && python3 pv-config.py; exec bash --login\"",
    "icon": "ms-appx:///ProfileIcons/{9acb9455-ca41-5af7-950f-6bca1bc9722f}.png",
    "colorScheme": "One Half Dark",
    "hidden": false,
    "tabTitle": "PV-Config (Failover)"
}
```

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| `ssh: connect to host ... Connection refused` | Pi4 aus? `ping 192.168.2.181` |
| `Permission denied (publickey,password)` | SSH-Key nicht kopiert → `setup-terminal-profile.ps1` nochmal |
| `whiptail: not found` | Auf Pi: `sudo apt install whiptail` |
| Terminal-Fenster zu klein für whiptail | Fenster auf mind. 80×24 Zeichen vergrößern |
| `TERM environment variable not set` | `-t` Flag fehlt → Script nutzen |
| Umlaute/Sonderzeichen kaputt | Windows Terminal → Profil → UTF-8 Encoding aktivieren |

---

## Sicherheit

- **Kein offener Port** auf dem Pi — nur SSH (Port 22)
- **Config-Tool** schreibt nur JSON-Dateien — kein Modbus/DB-Zugriff
- **SSH-Key** kann jederzeit widerrufen werden: auf dem Pi die Zeile aus `~/.ssh/authorized_keys` entfernen
- Siehe: [AUTOMATION_ARCHITEKTUR.md](../../doc/AUTOMATION_ARCHITEKTUR.md) §3 (S1 Config-Schicht)
