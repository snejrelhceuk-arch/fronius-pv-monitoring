# Git Workflow & Development Guide

## Branch-Übersicht

```
master (v1.0-production)
  └─ development (HEAD)
       └─ Refactoring + Optimierungen
```

## Produktionsversion sichern/wiederherstellen

```bash
# Zur Production zurück
git checkout v1.0-production

# Oder zum master-Branch
git checkout master

# Zurück zu Development
git checkout development
```

## Development-Workflow

```bash
# Status prüfen
git status

# Änderungen committen
git add <files>
git commit -m "Beschreibung"

# Alle Commits anzeigen
git log --oneline --graph --all

# Unterschied zwischen Branches
git diff master development
```

## Neue Features testen

```bash
# Aktuell: development-Branch
git branch --show-current

# Produktions-System läuft weiter auf modbus_v3.py (v1.0)
# Development-Änderungen sind NUR im Git-Commit, nicht im laufenden Code!
```

## Code-Module (Development)

### Neue Dateien:
1. **modbus_client.py** (355 Zeilen)
   - RawModbusClient Klasse
   - SunSpec Parser
   - Batch-Read-Optimierung
   
2. **data_processing.py** (240 Zeilen)
   - Energie-Akkumulatoren
   - Float-Formatierung
   - Battery-Berechnungen
   
3. **flask_api.py** (280 Zeilen)
   - Flask-Routen
   - API-Endpoints
   - HTML-Templates

### Utilities:
4. **monitor.sh**
   - System Health Check
   - Prozess/DB/API-Monitoring
   
5. **logrotate.sh**
   - Automatische Log-Bereinigung
   - Komprimierung alter Logs

### Dokumentation:
6. **README.md**
   - Schnellstart-Guide
   - API-Übersicht
   - Troubleshooting

## Nächste Schritte

### Morgen (31.12.2025):
- [ ] Tests der neuen Module
- [ ] Modbus-Batch-Read-Strategie validieren
- [ ] Produktionssystem beobachten

### Optional:
- [ ] modbus_v3.py refactoren (zu modular)
- [ ] Unit Tests schreiben
- [ ] Grafana-Integration

## Automatisierung

```bash
# Monitoring alle 60 Minuten (optional)
# Crontab-Eintrag:
0 * * * * /srv/pv-system/monitor.sh >> /tmp/health_check.log 2>&1

# Log-Rotation täglich um 3 Uhr (optional)
0 3 * * * /srv/pv-system/logrotate.sh
```

## Wichtig

⚠️ **PRODUKTIONS-SYSTEM UNBERÜHRT!**

Die laufende modbus_v3.py ist die v1.0-production Version.
Alle Änderungen sind nur im development-Branch.

Um Änderungen zu aktivieren:
1. Tests durchführen
2. Bei Erfolg: Code in modbus_v3.py integrieren
3. Produktionssystem neu starten

## Dateien-Übersicht

```
PRODUKTIV (läuft):
  ✅ modbus_v3.py (v1.0-production)
  ✅ aggregate.py
  ✅ db_schema_v4_tech.sql
  ✅ modbus_quellen.py
  ✅ data.db

DEVELOPMENT (neu):
  🔧 modbus_client.py
  🔧 data_processing.py
  🔧 flask_api.py
  📊 monitor.sh
  🗑️ logrotate.sh
  📖 README.md
```
