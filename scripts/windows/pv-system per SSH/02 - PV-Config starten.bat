@echo off
title PV-System Konfiguration
color 0B

echo.
echo  =========================================================
echo   PV-System Erlau - Konfiguration starten
echo   Verbinde mit Pi4 (192.168.2.181)...
echo  =========================================================
echo.

REM -- SSH pruefen --
where ssh >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [FEHLER] OpenSSH nicht gefunden!
    echo  Bitte zuerst "01 - SSH einrichten" starten.
    echo.
    pause
    exit /b 1
)

REM -- Verbinden und pv-config.py starten --
REM  -t = Terminal anfordern (noetig fuer whiptail-Menues)
REM  Nach Beenden von pv-config.py bleibt die Shell offen
ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -t admin@192.168.2.181 "cd '/home/admin/Dokumente/PVAnlage/pv-system' && python3 pv-config.py; exec bash --login"

if errorlevel 255 (
    echo.
    echo  ---------------------------------------------------------
    echo  Verbindung fehlgeschlagen!
    echo.
    echo  Pruefen:
    echo    - Pi4 erreichbar?     ping 192.168.2.181
    echo    - SSH eingerichtet?   "01 - SSH einrichten" starten
    echo    - Im richtigen Netz?  WLAN/LAN mit 192.168.2.x
    echo  ---------------------------------------------------------
    echo.
    pause
)
