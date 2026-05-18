# Standalone Ticker Microservice

Dieser Dienst ist ein leichtgewichtiger, entkoppelter Service für das PV-System. Er holt standardmaessig alle 5 Minuten RSS-Nachrichten (z.B. Tagesschau, Heise), erkennt neue Meldungen seit dem letzten Lauf und stellt sie im Ticker vorne an. Nur diese neuen Meldungen werden fuer die optionale zweite Zeile via Ollama erklaert. Falls Ollama beim Start oder zwischendurch offline ist, bleiben die Rohmeldungen sichtbar; fehlende Erklaerungen fuer bereits laufende Meldungen werden nachgezogen, sobald Ollama wieder erreichbar ist.

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

## Konfiguration & Rollback

Die Ticker-Konfiguration wird aus `~/.infra.local` geladen:

```bash
# Erklaerungsmodell waehlen:
PV_TICKER_EXPLAIN_MODEL=mi24ins8:latest    # Experimental (Mistral 25GB)
# PV_TICKER_EXPLAIN_MODEL=qwen2.5:7b       # Fallback (wenn Mistral zu langsam)

# Timeout fuer Modell-Generierung:
PV_TICKER_EXPLAIN_TIMEOUT_SEC=25           # Fuer mi24ins8 (groesseres Modell)

# Ollama-URL (Beispiel):
PV_TICKER_EXPLAIN_OLLAMA_URL=http://192.0.2.116:11434/api/generate
```

### Systemsicheres Rollback (bei Performance-Problemen)

Wenn `mi24ins8:latest` zu viele Timeouts erzeugt:

1. **In `.infra.local` aendern:**
   ```bash
   PV_TICKER_EXPLAIN_MODEL=qwen2.5:7b
   PV_TICKER_EXPLAIN_TIMEOUT_SEC=15
   ```

2. **Ticker-Service neu starten:**
   ```bash
   sudo systemctl restart pv-ticker
   ```

3. **Logs prüfen** (um Performance zu vergleichen):
   ```bash
   journalctl -u pv-ticker -n 50 -f
   ```

   Timeouts erscheinen als: `Ollama TIMEOUT nach 25s (Modell: mi24ins8:latest)`

## Modellwechsel mit Reset der Erklaerungszeile

Wenn du zu einem neuen Modell wechselst und die zweite Tickerzeile cleanly leer starten möchtest:

1. **In `.infra.local` uncomment:**
   ```bash
   # Diese Zeile hinzufügen oder uncomment:
   TICKER_RESET_EXPLANATIONS_ONCE=1
   
   # Auch das neue Modell setzen:
   PV_TICKER_EXPLAIN_MODEL=mi24ins8:latest
   ```

2. **Service neu starten:**
   ```bash
   sudo systemctl restart pv-ticker
   ```

3. **Verhalten beim Start:**
   - Der Service liest `TICKER_RESET_EXPLANATIONS_ONCE=1`
   - Loescht alle bestehenden Erklaerungen → zweite Zeile wird leer
   - Logs zeigen: `[RESET] Alle X Erklaerungszeilen geloescht (Modellwechsel). Zweite Tickerzeile ist jetzt leer.`
   - `[INIT] ... Zweite Zeile wird jetzt vom neuen Modell (mi24ins8:latest) gefüllt.`
   - Ab dem nächsten RSS-Fetch generiert das neue Modell frische Erklaerungen