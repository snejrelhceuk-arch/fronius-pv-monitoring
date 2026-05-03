# Standalone Ticker Microservice

Dieser Dienst ist ein leichtgewichtiger, entkoppelter Service für das PV-System. Er holt zyklisch RSS-Nachrichten (z.B. Tagesschau, Heise), fasst diese via lokaler KI (Ollama) zusammen und stellt sie als Text-Stream (JSON) zur Verfügung.

## Architektur & Sicherheit
* **Separation of Concerns:** Durch die Auslagerung auf z.B. den Pi5 (Backup-Host) wird der Primary-Host entlastet.
* **Fallbacks:** Fällt der Ticker-Server.oder Ollama aus, fallbacked der Code sauber auf Roh-RSS-Titel oder gibt dem Primary signal, dass der Ticker nicht verfügbar ist.
* **Port-Hygiene:** Ollama lauscht nur auf `127.0.0.1:11434`. Ausschließlich Port `8050` (für Abfrage der generierten Headlines) ist dem internen Netzwerk zugänglich.

## Deployment auf Pi5 (Micro-LLM-Host)
Dieser Service erfordert **keinen** Code/Datenbank-Clone des Haupt-Repos.

1. **Dateien kopieren:**
   ```bash
   scp tools/ticker_service/ticker_server.py admin@192.0.2.195:/home/user/ticker_server.py
   ```

2. **Systemd-Service einrichten:**
   Wir binden den Dienst stark ein (Nice=19), um sicherzustellen, dass die gegenseitige Server-Überwachung oder Backup-Tasks **niemals** von der KI verdrängt werden können.

   Auf dem Pi5 `/etc/systemd/system/pv-ticker.service` erstellen:
   ```ini
   [Unit]
   Description=PV Dashboard Ticker Microservice
   After=network.target

   [Service]
   Type=simple
   User=admin
   ExecStart=/usr/bin/python3 /home/user/ticker_server.py
   Environment="TICKER_PORT=8050"
   Restart=always
   RestartSec=30
   
   # Schutz vor System-Auslastung durch KI:
   Nice=19
   CPUSchedulingPolicy=idle
   IOSchedulingClass=idle

   [Install]
   WantedBy=multi-user.target
   ```

3. **Starten:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable pv-ticker --now
   ```