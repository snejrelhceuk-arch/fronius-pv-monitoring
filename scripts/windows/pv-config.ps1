#!/usr/bin/env pwsh
<#
.SYNOPSIS
    PV-System Konfigurations-Terminal — Direktzugang vom Windows-PC
.DESCRIPTION
    Verbindet per SSH zum Pi4 Primary und startet pv-config.py.
    Für Windows Terminal Profile: siehe setup-terminal-profile.ps1
.NOTES
    Voraussetzung: OpenSSH-Client (in Windows 10/11 enthalten)
    Erstellt: 2026-02-27
#>

param(
    [string]$Host = "192.168.2.181",
    [string]$User = "admin",
    [string]$PvDir = "/home/admin/Dokumente/PVAnlage/pv-system",
    [switch]$ShellOnly   # Nur Shell statt pv-config.py starten
)

$ErrorActionPreference = "Stop"

# ── Banner ──────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  PV-System Erlau — Konfigurationszugang                  ║" -ForegroundColor Cyan
Write-Host "║  Ziel: ${User}@${Host}                                   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── SSH-Verbindung ──────────────────────────────────────────
$sshArgs = @(
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-t",                              # TTY anfordern (nötig für whiptail)
    "${User}@${Host}"
)

if ($ShellOnly) {
    # Nur ins Verzeichnis wechseln
    $sshArgs += "cd '$PvDir' && exec bash --login"
} else {
    # pv-config.py starten, bei Beenden → Shell im Projektverzeichnis
    $sshArgs += "cd '$PvDir' && python3 pv-config.py; exec bash --login"
}

try {
    & ssh @sshArgs
} catch {
    Write-Host ""
    Write-Host "Verbindung fehlgeschlagen: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Prüfen Sie:" -ForegroundColor Yellow
    Write-Host "  1. Ist der Pi4 erreichbar?  ping $Host" -ForegroundColor Yellow
    Write-Host "  2. SSH-Key eingerichtet?     ssh-keygen -t ed25519" -ForegroundColor Yellow
    Write-Host "  3. Key kopiert?              ssh-copy-id ${User}@${Host}" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Enter zum Schließen"
}
