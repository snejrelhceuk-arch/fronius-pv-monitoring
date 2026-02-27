#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Richtet das Windows Terminal Profil "PV-Config" automatisch ein.
.DESCRIPTION
    Fügt in die Windows Terminal settings.json ein neues Profil hinzu,
    das per SSH direkt pv-config.py auf dem Pi4 startet.

    Außerdem wird (optional) ein SSH-Key generiert und auf den Pi kopiert.
.NOTES
    Einmalig als Administrator ODER normaler User ausführen.
    Erstellt: 2026-02-27
#>

param(
    [switch]$SkipSshKey,
    [string]$PiHost = "192.168.2.181",
    [string]$PiUser = "admin"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  PV-System — Windows Terminal Setup" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 1. SSH-Key einrichten ───────────────────────────────────
$keyPath = "$env:USERPROFILE\.ssh\id_ed25519"

if (-not $SkipSshKey) {
    if (Test-Path $keyPath) {
        Write-Host "[OK] SSH-Key existiert bereits: $keyPath" -ForegroundColor Green
    } else {
        Write-Host "[SETUP] Generiere SSH-Key (Ed25519)..." -ForegroundColor Yellow
        ssh-keygen -t ed25519 -f $keyPath -N '""' -C "pv-config@$env:COMPUTERNAME"
        Write-Host "[OK] Key generiert." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Kopiere Public Key auf Pi4 ($PiUser@$PiHost)..." -ForegroundColor Yellow
    Write-Host "  (Passwort wird einmalig abgefragt)" -ForegroundColor DarkGray
    Write-Host ""

    # ssh-copy-id existiert nicht nativ unter Windows → manuell
    $pubKey = Get-Content "$keyPath.pub" -Raw
    $pubKey = $pubKey.Trim()
    $cmd = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Key installiert!'"
    ssh -o ConnectTimeout=10 "${PiUser}@${PiHost}" $cmd

    Write-Host ""
    Write-Host "[OK] SSH-Key auf Pi4 installiert. Passwortloser Zugang aktiv." -ForegroundColor Green
}

# ── 2. SSH Config Eintrag ───────────────────────────────────
$sshConfigPath = "$env:USERPROFILE\.ssh\config"
$sshEntry = @"

# PV-System Pi4 Primary
Host pv-pi4
    HostName $PiHost
    User $PiUser
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ConnectTimeout 10
    RequestTTY yes
"@

if (Test-Path $sshConfigPath) {
    $existing = Get-Content $sshConfigPath -Raw
    if ($existing -match "pv-pi4") {
        Write-Host "[OK] SSH-Config Eintrag 'pv-pi4' existiert bereits." -ForegroundColor Green
    } else {
        Add-Content -Path $sshConfigPath -Value $sshEntry
        Write-Host "[OK] SSH-Config Eintrag 'pv-pi4' hinzugefügt." -ForegroundColor Green
    }
} else {
    New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
    Set-Content -Path $sshConfigPath -Value $sshEntry.TrimStart()
    Write-Host "[OK] SSH-Config erstellt mit Eintrag 'pv-pi4'." -ForegroundColor Green
}

# ── 3. Windows Terminal Profil ──────────────────────────────
$wtSettingsLocations = @(
    "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json",
    "$env:LOCALAPPDATA\Microsoft\Windows Terminal\settings.json"
)

$wtSettingsPath = $null
foreach ($loc in $wtSettingsLocations) {
    if (Test-Path $loc) {
        $wtSettingsPath = $loc
        break
    }
}

if (-not $wtSettingsPath) {
    Write-Host ""
    Write-Host "[WARNUNG] Windows Terminal settings.json nicht gefunden." -ForegroundColor Yellow
    Write-Host "  Manuelles Profil-Setup nötig (siehe README)." -ForegroundColor Yellow
    Write-Host ""
} else {
    # settings.json lesen (Kommentare entfernen für JSON-Parse)
    $rawJson = Get-Content $wtSettingsPath -Raw
    # Einfacher Regex für einzeilige Kommentare
    $cleanJson = $rawJson -replace '(?m)^\s*//.*$', '' -replace ',\s*}', '}' -replace ',\s*]', ']'

    try {
        $settings = $cleanJson | ConvertFrom-Json

        # Prüfen ob Profil schon existiert
        $profileExists = $settings.profiles.list | Where-Object { $_.name -eq "PV-Config" }

        if ($profileExists) {
            Write-Host "[OK] Windows Terminal Profil 'PV-Config' existiert bereits." -ForegroundColor Green
        } else {
            $pvDir = "/home/$PiUser/Dokumente/PVAnlage/pv-system"

            $newProfile = [PSCustomObject]@{
                name             = "PV-Config"
                guid             = "{e7a1b3c4-5d6f-4a8b-9c0e-1f2a3b4c5d6e}"
                commandline      = "ssh -t pv-pi4 `"cd '$pvDir' && python3 pv-config.py; exec bash --login`""
                icon             = "ms-appx:///ProfileIcons/{9acb9455-ca41-5af7-950f-6bca1bc9722f}.png"
                colorScheme      = "One Half Dark"
                startingDirectory = "%USERPROFILE%"
                hidden           = $false
                tabTitle         = "PV-Config (Pi4)"
            }

            $settings.profiles.list += $newProfile
            $settings | ConvertTo-Json -Depth 10 | Set-Content $wtSettingsPath -Encoding UTF8

            Write-Host "[OK] Windows Terminal Profil 'PV-Config' hinzugefügt!" -ForegroundColor Green
        }
    } catch {
        Write-Host "[WARNUNG] settings.json konnte nicht geparst werden: $_" -ForegroundColor Yellow
        Write-Host "  Bitte manuell ein Profil hinzufügen (siehe README)." -ForegroundColor Yellow
    }
}

# ── 4. Zusammenfassung ──────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Setup abgeschlossen!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Nutzung:" -ForegroundColor White
Write-Host "    • Windows Terminal → Dropdown → 'PV-Config'" -ForegroundColor White
Write-Host "    • Oder: ssh -t pv-pi4 ""cd .../pv-system && python3 pv-config.py""" -ForegroundColor DarkGray
Write-Host "    • Oder: Doppelklick auf pv-config.bat" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  SSH-Verbindungstest:" -ForegroundColor White
Write-Host "    ssh pv-pi4 'hostname && date'" -ForegroundColor Cyan
Write-Host ""
