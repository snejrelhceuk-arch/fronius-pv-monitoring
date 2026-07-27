# Standalone Ticker Microservice

Dieser Dienst ist ein leichtgewichtiger, entkoppelter Service für das PV-System. Er holt standardmaessig alle 5 Minuten RSS-Nachrichten (z.B. Tagesschau, Heise), erkennt neue Meldungen seit dem letzten Lauf und stellt sie im Ticker vorne an. Nur diese neuen Meldungen werden fuer die optionale zweite Zeile via Ollama erklaert. Falls Ollama beim Start oder zwischendurch offline ist, bleiben die Rohmeldungen sichtbar; fehlende Erklaerungen fuer bereits laufende Meldungen werden nachgezogen, sobald Ollama wieder erreichbar ist.

> **Zweite Tickerzeile — Resilienz (2026-07-25):** Ist Ollama nicht erreichbar oder das Modell nicht geladen, faellt die zweite Zeile als self-contained Fallback auf die RSS-Detailzusammenfassung zurueck (`TICKER_EXPLAIN_FALLBACK_DETAILS=1`, Default an) und bleibt damit **nie leer**. Das Feld `explain` bleibt intern leer, sodass der Backfill die Zeile automatisch auf echte KI-Erklaerungen aufwertet, sobald Ollama wieder antwortet. Aktives Modell: **`qwen2.5:7b`** (Q4_K_M, ~4.7 GB) — passt in die 8 GB VRAM der RTX 3070 (~0.6 s/Satz). Das frühere `mi24ins8:latest` (Mistral 25 GB) war CPU-gebunden/fragil.

## Feeds und Verhaeltnis (API/Flow-Ticker)

- ARD-Quelle ist weiterhin aktiv: `https://www.tagesschau.de/xml/rss2/`
- Heise-Quelle: `https://www.heise.de/rss/heise-atom.xml`
- Geplantes Mischverhaeltnis in der Anzeige: **12:3 (ARD:Heise)**
- Der Server begrenzt die laufende Tickerliste pro Quelle auf dieses Kontingent,
  damit Heise bei hoeherer Update-Frequenz nicht den gesamten Lauftext dominiert.

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

Die Ticker-Konfiguration wird aus `~/.infra.local` geladen. **Auf dem Backup-Host (.195) ist die systemd-Drop-in `/etc/systemd/system/pv-ticker.service.d/override.conf` massgeblich** (Env-Vars haben im Code Vorrang vor `.infra.local`); die Repo-Referenz dieser Datei liegt unter `config/systemd/pv-ticker.override.conf`.

```bash
# Erklaerungsmodell (nachhaltig, passt in RTX-3070-VRAM):
PV_TICKER_EXPLAIN_MODEL=qwen2.5:7b
PV_TICKER_EXPLAIN_MODEL_FALLBACK=qwen2.5:7b

# Timeout fuer Modell-Generierung:
PV_TICKER_EXPLAIN_TIMEOUT_SEC=90
PV_TICKER_EXPLAIN_TIMEOUT_FALLBACK_SEC=30

# Ollama-URL:
PV_TICKER_EXPLAIN_OLLAMA_URL=http://192.0.2.116:11434/api/generate

# Resilienz: leere KI-Zeile -> Fallback auf RSS-Details (self-contained). 1=an (Default).
TICKER_EXPLAIN_FALLBACK_DETAILS=1
```

### Modell auf dem Ollama-Host wiederherstellen

Fehlt das Modell (Ollama meldet `model '...' not found`, `GET /api/tags` zeigt `{"models":[]}`), per HTTP-API neu ziehen — **kein SSH noetig**:

```bash
curl -s http://192.0.2.116:11434/api/pull -d '{"model":"qwen2.5:7b"}'
curl -s http://192.0.2.116:11434/api/tags   # Verifikation
sudo systemctl restart pv-ticker            # auf .195
```

### Systemsicheres Rollback (bei Performance-Problemen)

Wenn `mi24ins8:latest` zu viele Timeouts erzeugt:

1. **Timeout erhöhen:** Setze in `.infra.local` `PV_TICKER_EXPLAIN_TIMEOUT_SEC` auf einen höheren Wert (z.B. `180`) und starte den Dienst neu.

2. **Model vorladen / prüfen:** Stelle sicher, dass `mi24ins8:latest` auf dem Ollama-Host vorab geladen ist (siehe `http://<ollama-host>:11434/api/ps`).

3. **Bei akuten Problemen (Notfall):** Deaktiviere kurzzeitig Erklärungen durch Entfernen der `PV_TICKER_EXPLAIN_OLLAMA_URL`-Zeile oder setze in der Systemd-Unit `TICKER_EXPLAIN_ENABLE=0`, dann `sudo systemctl restart pv-ticker`.

4. **Logs prüfen:**
   ```bash
   journalctl -u pv-ticker -n 50 -f
   ```

   Timeouts erscheinen als: `Ollama TIMEOUT nach <N>s (Modell: mi24ins8:latest)`

## Modellwechsel mit Reset der Erklaerungszeile

Wenn du zu einem neuen Modell wechselst und die zweite Tickerzeile cleanly leer starten möchtest:

1. **In `.infra.local` uncomment:**
   ```bash
   # Diese Zeile hinzufügen oder uncomment:
   TICKER_RESET_EXPLANATIONS_ONCE=1
   
   # Auch das neue Modell setzen:
   PV_TICKER_EXPLAIN_MODEL=mi24ins8:latest
   ```

   # Optional: Sofortiges Backfill nach Reset (neue Erklaerungen sofort erzeugen)
   # Setze diese Variable nur, wenn Ollama erreichbar und leistungsfähig ist:
   # TICKER_RESET_BACKFILL_IMMEDIATELY=1

2. **Service neu starten:**
   ```bash
   sudo systemctl restart pv-ticker
   ```

3. **Verhalten beim Start:**
   - Der Service liest `TICKER_RESET_EXPLANATIONS_ONCE=1`
   - Loescht alle bestehenden Erklaerungen → zweite Zeile wird leer
   - Bereits vorhandene Meldungen werden danach **nicht** sofort wieder via Backfill erklaert
   - Erklaerungen werden wieder nur fuer neu eintreffende Meldungen erzeugt
   - Logs zeigen: `[RESET] Alle X Erklaerungszeilen geloescht (Modellwechsel). Zweite Tickerzeile ist jetzt leer.`
   - `[INIT] ... Zweite Zeile wird jetzt vom neuen Modell (mi24ins8:latest) gefüllt.`
   - Ab dem nächsten RSS-Fetch generiert das neue Modell frische Erklaerungen

   Hinweis: Wenn `TICKER_RESET_BACKFILL_IMMEDIATELY=1` gesetzt ist, versucht der Dienst
   direkt nach dem Reset, alle fehlenden Erklärungen einmalig per LLM zu erzeugen.
   Ohne diese Option bleiben alte Einträge nach Reset leer und werden erst für neu
   eingehende Meldungen wieder erläutert (sicherer Modus).
