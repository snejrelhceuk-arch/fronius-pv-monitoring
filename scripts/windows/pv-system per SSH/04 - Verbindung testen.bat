@echo off
title PV-System - Verbindungstest
color 0E

echo.
echo  Teste Verbindung zu Pi4 (192.168.2.181)...
echo  ---------------------------------------------------------
echo.

REM -- Ping --
echo  [1/3] Ping...
ping -n 1 -w 3000 192.168.2.181 >nul 2>&1
if errorlevel 1 (
    echo        FEHLER - Pi4 nicht erreichbar!
    echo        Sind Sie im richtigen Netzwerk (192.168.2.x)?
    echo.
    pause
    exit /b 1
)
echo        OK - Pi4 antwortet
echo.

REM -- SSH --
echo  [2/3] SSH-Verbindung...
ssh -o ConnectTimeout=5 -o BatchMode=yes admin@192.168.2.181 "echo OK" >nul 2>&1
if errorlevel 1 (
    echo        FEHLER - SSH-Key nicht eingerichtet
    echo        Bitte "01 - SSH einrichten" starten.
    echo.
    pause
    exit /b 1
)
echo        OK - Passwortloser Zugang funktioniert
echo.

REM -- PV-System --
echo  [3/3] PV-System Status...
ssh -o ConnectTimeout=5 admin@192.168.2.181 "cd /home/admin/Dokumente/PVAnlage/pv-system && echo '  Host:     '$(hostname) && echo '  Rolle:    '$(cat .role 2>/dev/null || echo 'primary') && echo '  Python:   '$(python3 --version) && echo '  DB:       '$(ls -lh /dev/shm/fronius_data.db 2>/dev/null | awk '{print $5}' || echo 'nicht gefunden') && echo '  Uptime:   '$(uptime -p)"
echo.

echo  =========================================================
echo  Alles OK - "02 - PV-Config starten" verwenden.
echo  =========================================================
echo.
pause
