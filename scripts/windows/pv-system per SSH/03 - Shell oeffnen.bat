@echo off
title PV-System Shell
color 0A

echo.
echo  =========================================================
echo   PV-System Erlau - Shell (Kommandozeile)
echo   Verbinde mit Pi4 (192.168.2.181)...
echo  =========================================================
echo.

where ssh >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [FEHLER] OpenSSH nicht gefunden!
    echo  Bitte zuerst "01 - SSH einrichten" starten.
    echo.
    pause
    exit /b 1
)

REM -- Shell im Projektverzeichnis oeffnen --
ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -t admin@192.168.2.181 "cd '/home/admin/Dokumente/PVAnlage/pv-system' && echo '  Projektverzeichnis: pv-system' && echo '  Befehle: python3 pv-config.py | htop | git log' && echo '' && exec bash --login"

if errorlevel 255 (
    echo.
    echo  Verbindung fehlgeschlagen! Siehe "01 - SSH einrichten".
    echo.
    pause
)
