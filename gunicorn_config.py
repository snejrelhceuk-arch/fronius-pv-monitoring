"""
Gunicorn-Konfiguration für PV-System Web-API
Produktions-Setup: Multi-Worker, Timeouts, Logging

WICHTIG: Nur via systemd starten (pv-web.service)!
  sudo systemctl restart pv-web.service
  ./restart_webserver.sh

Manueller Start (nohup gunicorn ...) ist NICHT erlaubt —
führt zu Port-Konflikten mit dem systemd-Service.
"""
import os
from host_role import is_failover

# --- Binding ---
bind = "0.0.0.0:8000"

# --- Workers ---
# Primary (Pi4): 3 Worker (4 Kerne, aber auch andere Prozesse)
# Failover: 1 Worker reicht (nur read-only Zugriffe)
workers = 1 if is_failover() else 3
worker_class = "sync"  # Einfacher, stabiler als gthread
# threads = 2  # nur bei gthread relevant

# --- Timeouts ---
timeout = 120          # Manche Analyse-Queries dauern länger
graceful_timeout = 30
keepalive = 5

# --- Logging ---
accesslog = "/tmp/pv_web_access.log"
errorlog = "/tmp/pv_web_error.log"
loglevel = "info"

# --- Process ---
pidfile = "/tmp/pv_web.pid"
daemon = False  # systemd managt den Lifecycle

# --- Startup Hook: tmpfs-DB initialisieren ---
def on_starting(server):
    """Wird einmal beim Gunicorn-Master-Start ausgeführt.
    
    Guard: Blockiert Start wenn nicht via systemd gestartet —
    verhindert Port-Konflikte durch manuelle nohup-Starts.
    
    Primary: Kopiert data.db (SD) → tmpfs falls tmpfs leer (nach Reboot).
    Failover: tmpfs wird per Mirror-Sync befüllt — hier nur prüfen ob da.
              Falls tmpfs noch leer (erster Start nach Reboot), einmalig
              aus SD-Kopie (data.db) laden als Fallback.
    """
    
    # --- Guard: Nur systemd darf Gunicorn starten ---
    if not os.environ.get("INVOCATION_ID"):
        # INVOCATION_ID wird von systemd automatisch gesetzt
        server.log.error(
            "⚠ ABBRUCH: Gunicorn darf nur via systemd gestartet werden!\n"
            "  Korrekt:  sudo systemctl restart pv-web.service\n"
            "  Oder:     ./restart_webserver.sh\n"
            "  Manueller Start (nohup gunicorn ...) ist nicht erlaubt."
        )
        raise SystemExit(1)
    
    import db_init
    import config
    
    if db_init.ensure_tmpfs_db():
        size_mb = os.path.getsize(config.DB_PATH) / 1e6 if os.path.exists(config.DB_PATH) else 0
        server.log.info(f"tmpfs-DB bereit: {config.DB_PATH} ({size_mb:.1f} MB)")
    else:
        server.log.error("tmpfs-DB konnte nicht initialisiert werden!")
        raise SystemExit(1)

def post_fork(server, worker):
    """Nach Worker-Fork: keine Persist-Threads starten (DB kommt per Sync)."""
    server.log.info(f"Worker {worker.pid} gestartet (read-only Modus)")
