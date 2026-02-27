# Ollama LLM-Server — 192.168.2.116 (Ubuntu)

## Hardware
- CPU: 24 Kerne
- RAM: 62 GB
- GPU: NVIDIA GeForce RTX 3070 (8 GB VRAM)
- Disk: 92 GB NVMe

## Ollama
- Version: 0.17.0
- Basis-Modell: qwen2.5-coder:7b-instruct-q4_K_M (4.7 GB)
- Embedding: nomic-embed-text (274 MB)
- API: http://localhost:11434

## Experten-Modelle (custom, via System-Prompt)

### pv-system-expert
- Projekt: Fronius PV-Monitoring (37,59 kWp), Erlau
- Quell-Host: Pi4 Primary (192.168.2.181, admin)
- Workspace: /home/admin/Dokumente/PVAnlage/pv-system
- Sync: Git post-commit Hook + Cron 04:00 täglich
- Sync-Script: pv-system/ollama/ollama_sync.py
- Kern-Wissen: pv-system/ollama/system_prompt_kern.md (~9 KB statisch)
- Dynamische Deltas: Config-Werte, Git-Commits, geänderte Module (~7 KB)
- Gesamt System-Prompt: ~16 KB

### ha-heizung-expert (geplant)
- Projekt: Home Assistant Heizungssteuerung
- Quell-Host: HA-Server (192.168.2.140)
- Status: Noch nicht eingerichtet

## SSH-Zugang
- User: zmithy
- Autorisierte Keys:
  - Pi4 Primary (admin@192.168.2.181) — id_ed25519_ollama

## Modell-Management

```bash
# Modelle auflisten
ollama list

# Modell testen
ollama run pv-system-expert "Wie berechne ich die PV-Erzeugung?"

# Modell löschen
ollama rm pv-system-expert

# Modell neu bauen (Modelfile muss in /tmp liegen)
ollama create pv-system-expert -f /tmp/Modelfile

# API-Aufruf
curl http://localhost:11434/api/generate -d '{
  "model": "pv-system-expert",
  "prompt": "Wie prüfe ich den Collector-Status?",
  "stream": false
}'
```

## Sync-Ablauf (automatisch vom Pi4)

```
Pi4 (181): git commit
  → post-commit Hook (.git/hooks/post-commit)
    → ollama/ollama_sync.py
      1. Scannt doc/*.md, config.py, Code-Docstrings, Git-Log
      2. Generiert Modelfile (statischer Kern + dynamische Deltas)
      3. Content-Hash-Vergleich mit .sync_state.json
      4. Bei Änderung: scp Modelfile → 116:/tmp/Modelfile
      5. ssh 116 "ollama create pv-system-expert -f /tmp/Modelfile"
      6. Speichert Hash + Timestamp in .sync_state.json
```

Zusätzlich läuft ein Cron-Job auf dem Pi4 (täglich 04:00) als Fallback.

## Manueller Rebuild

Falls auf dem Server selbst ein Rebuild nötig ist:

```bash
# Modelfile muss vorhanden sein (z.B. in /tmp/Modelfile)
ollama create pv-system-expert -f /tmp/Modelfile

# Oder vom Pi4 aus manuell triggern:
ssh admin@192.168.2.181 'cd /home/admin/Dokumente/PVAnlage/pv-system && python3 ollama/ollama_sync.py --force'
```

## Wartung & Diagnose

```bash
# Ollama-Service
systemctl status ollama
sudo systemctl restart ollama

# GPU-Status / VRAM-Auslastung
nvidia-smi

# Ollama-Logs
journalctl -u ollama -f

# Speicher
ollama list           # Modellgrößen
df -h /               # Disk-Nutzung
free -h               # RAM

# Modell im VRAM prüfen (läuft es?)
curl -s http://localhost:11434/api/ps | python3 -m json.tool
```

## Ressourcen-Limits
- RTX 3070 hat 8 GB VRAM → nur EIN 7B-Modell gleichzeitig im VRAM
- Ollama swappt automatisch zwischen Modellen (~2-3s Ladezeit bei RAM-Cache)
- System-Prompt-Budget: max ~20 KB pro Modell (32K Token Kontext gesamt)
- /tmp/Modelfile wird bei jedem Sync überschrieben (kein persistenter Pfad)

## Architektur-Übersicht

```
┌─────────────────────────────┐       ┌──────────────────────────┐
│  Pi4 Primary (.181)         │  SSH  │  Ollama-Server (.116)    │
│  ─────────────────────      │──────▶│  ──────────────────      │
│  pv-system Workspace        │       │  Ollama 0.17.0           │
│  ollama_sync.py             │  scp  │  qwen2.5-coder:7b Q4_KM │
│  system_prompt_kern.md      │──────▶│  pv-system-expert        │
│  Git post-commit Hook       │       │  (ha-heizung-expert)     │
│  Cron 04:00 Fallback        │       │  RTX 3070 · 62 GB RAM   │
└─────────────────────────────┘       └──────────────────────────┘
```
