# Single-Instance Schutz für collector.py

**Status**: ✅ Aktiv seit 07.02.2026

## Problem

Nach Stromausfall oder manuellen Eingriffen könnten **mehrere collector.py Prozesse** gleichzeitig laufen:
- Konkurrenzkampf um Modbus-Bus (blockiert WR-Kommunikation F1↔F2↔F3)
- Doppelte DB-Schreibzugriffe
- Hohe CPU-Last (20% statt 0.2%)
- Verfälschte Performance-Messung (587ms statt 191ms)

## Implementierte Schutz-Mechanismen

### 1. PID-File (Python-seitig)

**Datei**: `/srv/pv-system/collector.pid`

**Funktionsweise**:
```python
# modbus_v3.py, Zeile 47-89
def create_pid_file():
    - Prüft ob collector.pid existiert
    - Liest PID und prüft ob Prozess läuft (os.kill(pid, 0))
    - Falls läuft: sys.exit(1) mit Fehlermeldung
    - Falls stale (Prozess tot): Entfernt altes PID-File
    - Erstellt neues PID-File mit aktueller PID
    - Registriert atexit-Handler für Cleanup
```

**Test**:
```bash
# OK: Einzelner Prozess
$ python3 collector.py
[INFO] Poller gestartet
[OK] PID-File erstellt: ...

# BLOCKIERT: Zweiter Versuch
$ python3 collector.py
[ERROR] collector.py laeuft bereits (PID 177707)
   Beenden Sie den Prozess mit: kill 177707
   Oder erzwingen Sie Start mit: rm .../collector.pid
```

### 2. Monitoring-Script

**Datei**: `check_single_instance.sh`

```bash
./check_single_instance.sh
# ✓ Einzelner collector.py Prozess läuft
# PID, CPU%, MEM angezeigt

./check_single_instance.sh --kill-duplicates
# Stoppt ALLE collector.py, systemd startet neu
```

### 3. Automated Monitoring (Cron)

**Datei**: `monitor_collector.sh`

**Installation**:
```bash
crontab -e
# Füge hinzu:
*/5 * * * * /srv/pv-system/monitor_collector.sh
```

**Verhalten**:
- **Alle 5 Minuten**: Prüft Prozess-Anzahl
- **> 1 Prozess**: Stoppt alle, lässt systemd neu starten, loggt Alarm
- **0 Prozesse**: Warnt, systemd-Restart abwarten
- **1 Prozess**: Normal, kein Log-Eintrag

**Log**: `collector_monitor.log` (auto-rotation bei 100 Zeilen)

## Nach Stromausfall

**Automatischer Recovery**:
1. System bootet → systemd startet pv-collector.service
2. Python prüft PID-File (nicht vorhanden nach Reboot)
3. Neues PID-File wird erstellt
4. Cron-Monitoring prüft nach 0-5min
5. Falls Duplikate: Auto-Cleanup

**Manueller Check**:
```bash
# Status prüfen
systemctl status pv-collector
./check_single_instance.sh

# Falls Duplikate
./check_single_instance.sh --kill-duplicates
```

## Systemd-Integration (Optional)

**Könnte hinzugefügt werden** in `/etc/systemd/system/pv-collector.service`:
```ini
[Service]
ExecStartPre=/srv/pv-system/check_single_instance.sh --kill-duplicates
RuntimeDirectory=pv-system
PIDFile=/srv/pv-system/collector.pid
```

**Aktuell NICHT aktiviert** - Python-seitiger Schutz ist ausreichend!

## Verifizierung

```bash
# 1. PID-File existiert
cat /srv/pv-system/collector.pid
# → Zeigt PID

# 2. Prozess läuft mit dieser PID
ps aux | grep "python3.*collector.py"
# → PID muss übereinstimmen

# 3. Duplikat-Versuch blockiert
python3 /srv/pv-system/collector.py
# → [ERROR] collector.py laeuft bereits

# 4. Monitoring-Test
./monitor_collector.sh
# → Kein Alarm im Log

# 5. Performance-Check
sqlite3 data.db "SELECT AVG(t_poll_ms) FROM raw_data WHERE ts >= strftime('%s', 'now', '-10 min')"
# → ~190ms (nicht 587ms!)
```

## Wartung

**PID-File manuell entfernen** (nur bei Problemen):
```bash
# WARNUNG: Nur wenn collector WIRKLICH nicht läuft!
rm /srv/pv-system/collector.pid
sudo systemctl restart modbus-collector
```

**Monitoring-Log prüfen**:
```bash
tail -50 /srv/pv-system/collector_monitor.log
```

## Performance-Vergleich

| Zustand             | Prozesse | CPU   | t_poll_ms | Interval |
|---------------------|----------|-------|-----------|----------|
| **VOR Schutz**      | 2        | ~20%  | 587ms avg | 3.6s     |
| **NACH Schutz**     | 1        | 0.2%  | 191ms avg | 3.5s     |
| **Verbesserung**    | -50%     | -99%  | -68%      | +3%      |

## Zusammenfassung

✅ **3-stufiger Schutz**:
1. PID-File (sofortige Duplikat-Verhinderung)
2. check_single_instance.sh (manuelles Debugging)
3. monitor_collector.sh (Cron 5min, Auto-Cleanup)

✅ **Nach Stromausfall**: Automatischer sauberer Start

✅ **Performance**: 68% schneller durch Single-Process

✅ **WR-Kommunikation**: Modbus-Bus frei für F1↔F2↔F3
