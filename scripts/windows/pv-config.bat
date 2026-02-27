@echo off
REM ──────────────────────────────────────────────────────────
REM  PV-System Konfiguration — Desktop-Verknüpfung
REM  Doppelklick → SSH → pv-config.py auf Pi4 Primary
REM ──────────────────────────────────────────────────────────
REM  Nutzt OpenSSH (in Windows 10/11 integriert)
REM  Für passwortlosen Zugang: SSH-Key einrichten (siehe README)
REM ──────────────────────────────────────────────────────────

set PI_HOST=192.168.2.181
set PI_USER=admin
set PV_DIR=/home/admin/Dokumente/PVAnlage/pv-system

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  PV-System Erlau — Konfigurationszugang                  ║
echo  ║  Ziel: %PI_USER%@%PI_HOST%                                        ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 -t %PI_USER%@%PI_HOST% "cd '%PV_DIR%' && python3 pv-config.py; exec bash --login"

if errorlevel 1 (
    echo.
    echo  Verbindung fehlgeschlagen!
    echo  Pi erreichbar?  ping %PI_HOST%
    echo  SSH-Key noetig?  ssh-keygen -t ed25519
    echo.
    pause
)
