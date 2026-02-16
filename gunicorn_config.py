"""
Gunicorn-Konfiguration für PV-System Web-API
Produktions-Setup: Multi-Worker, Timeouts, Logging

Nutzung:
  gunicorn -c gunicorn_config.py web_api:app
"""
import multiprocessing
import os

# --- Binding ---
bind = "0.0.0.0:8000"

# --- Workers ---
# Pi4 hat 4 Kerne, aber auch andere Prozesse → 3 Worker reichen
workers = 3
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
    """Wird einmal beim Gunicorn-Master-Start ausgeführt."""
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
