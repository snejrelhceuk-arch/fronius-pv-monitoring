@echo off
chcp 65001 >nul 2>&1
title PV-System — SSH einrichten
color 0E

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  PV-System Erlau — SSH-Zugang einrichten                  ║
echo  ║  (einmalig pro PC)                                        ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

REM ── 1. OpenSSH prüfen ────────────────────────────────────────
where ssh >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [FEHLER] OpenSSH ist nicht installiert!
    echo.
    echo  So aktivieren Sie OpenSSH:
    echo    1. Einstellungen öffnen  (Win+I)
    echo    2. System → Optionale Features
    echo    3. "Feature hinzufügen" → "OpenSSH-Client" suchen
    echo    4. Installieren und PC neu starten
    echo.
    pause
    exit /b 1
)
echo  [OK] OpenSSH gefunden: 
where ssh
echo.

REM ── 2. SSH-Key prüfen/erstellen ──────────────────────────────
set "KEYFILE=%USERPROFILE%\.ssh\id_ed25519"

if exist "%KEYFILE%" (
    echo  [OK] SSH-Key existiert bereits: %KEYFILE%
    echo.
) else (
    echo  Generiere SSH-Key (Ed25519)...
    echo  (Einfach 3x Enter drücken — kein Passwort nötig)
    echo.
    ssh-keygen -t ed25519 -C "pv-config@%COMPUTERNAME%" -f "%KEYFILE%"
    echo.
    if exist "%KEYFILE%" (
        echo  [OK] Key generiert.
    ) else (
        echo  [FEHLER] Key konnte nicht erstellt werden.
        pause
        exit /b 1
    )
)

REM ── 3. Key auf Pi4 kopieren ──────────────────────────────────
echo  ────────────────────────────────────────────────────────
echo  Kopiere Public Key auf Pi4 (192.168.2.181)...
echo  Das Pi4-Passwort wird EINMALIG abgefragt.
echo  (Danach nie wieder — der SSH-Key übernimmt.)
echo  ────────────────────────────────────────────────────────
echo.

REM ssh-copy-id gibt es unter Windows nicht → manuell
set /p PUBKEY=<"%KEYFILE%.pub"
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new admin@192.168.2.181 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '%COMPUTERNAME%' ~/.ssh/authorized_keys 2>/dev/null || echo '%PUBKEY%' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Key erfolgreich installiert!'"

if errorlevel 1 (
    echo.
    echo  [WARNUNG] Key-Transfer fehlgeschlagen.
    echo  Ist der Pi4 erreichbar? Prüfen: ping 192.168.2.181
    echo.
) else (
    echo.
    echo  ════════════════════════════════════════════════════
    echo  [OK] SSH-Zugang eingerichtet!
    echo  ════════════════════════════════════════════════════
    echo.
    echo  Test — Verbindung ohne Passwort:
    echo.
    ssh -o ConnectTimeout=5 admin@192.168.2.181 "echo '  Verbunden mit:' && hostname && echo '  Datum:' && date"
    echo.
    echo  Ab jetzt: "PV-Config starten.bat" doppelklicken.
)

echo.
pause
