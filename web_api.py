#!/usr/bin/env python3
"""
Flask Web API - NUR Visualisierung & API
Separater Prozess: Liest DB, serviert tag_view.html und API-Endpoints

tmpfs-Architektur: DB lebt in /dev/shm (RAM) — Echtzeit-Zugriff ohne Disk-I/O.
Persist-Thread sichert zeitbasiert auf SD-Card.

Modulare Blueprint-Architektur:
  routes/helpers.py       — Shared DB, Caches, Forecast-Persistierung
  routes/pages.py         — HTML-Seitenrouten (/, /flow, /monitoring, ...)
  routes/data.py          — Aggregierte Daten-APIs (/api/15min, /api/daily, ...)
  routes/realtime.py      — Echtzeit-/Zoom-APIs (/api/zoom, /api/realtime_smart, ...)
  routes/visualization.py — Visualisierungs-APIs (Tag/Monat/Jahr/Gesamt)
  routes/verbraucher.py   — Verbraucher-APIs (WP, Wattpilot, Haushalt)
  routes/erzeuger.py      — Erzeuger-APIs (F1/F2/F3 Strings)
  routes/system.py        — System-/Batterie-/Wattpilot-Status
  routes/forecast.py      — Prognose-APIs (Clear-Sky, Forecast)
"""
from flask import Flask, jsonify, request, send_from_directory
from markupsafe import escape as _html_escape
import logging
import os
import time
from datetime import datetime
import config
import db_init
import socket as _socket

# ─── Flask App ──────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/x-icon')

# ─── Mirror/Entwicklungs-Modus ─────────────────────────────────────
# Wenn PV_MIRROR_MODE=1: Read-Only Spiegel, keine externen Zugriffe.
# DB wird per sync_db.sh kopiert, kein Collector aktiv.
MIRROR_MODE = os.environ.get('PV_MIRROR_MODE', '0') == '1'
MIRROR_SOURCE = os.environ.get('PV_MIRROR_SOURCE', 'lokaler Spiegel')

if MIRROR_MODE:
    logging.info(f"=== MIRROR-MODUS aktiv === Quelle: {MIRROR_SOURCE}")

@app.context_processor
def inject_mirror_info():
    """Stellt Mirror-Info in allen Templates bereit."""
    return {
        'mirror_mode': MIRROR_MODE,
        'mirror_source': MIRROR_SOURCE,
        'local_hostname': _socket.gethostname(),
        'local_ip': os.environ.get('PV_LOCAL_IP', '127.0.0.1'),
        'api_base_url': os.environ.get('PV_API_BASE_URL', ''),
    }

@app.after_request
def add_cors_headers(response):
    """Erlaubt API-Aufrufe von konfigurierten Origins (Standard: nur Same-Origin)."""
    if request.path.startswith('/api/'):
        allow = os.environ.get('PV_API_CORS_ORIGINS', '')
        origin = request.headers.get('Origin')
        if not allow or not origin:
            # Kein CORS-Header → nur Same-Origin erlaubt
            pass
        elif allow == '*':
            response.headers['Access-Control-Allow-Origin'] = '*'
        else:
            allowed = [o.strip() for o in allow.split(',') if o.strip()]
            if origin in allowed:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Vary'] = 'Origin'
        if 'Access-Control-Allow-Origin' in response.headers:
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

@app.after_request
def add_mirror_banner(response):
    """Fügt ein sichtbares Banner in HTML-Seiten ein (nur im Mirror-Modus)."""
    if not MIRROR_MODE:
        return response
    if response.content_type and 'text/html' in response.content_type:
        banner = (
            '<div id="mirror-banner" style="position:fixed;top:0;left:0;right:0;'
            'background:linear-gradient(90deg,#ff6b00,#ff9500);color:#fff;'
            'text-align:center;padding:6px 12px;font-size:13px;font-weight:600;'
            'z-index:99999;box-shadow:0 2px 8px rgba(0,0,0,0.3);">'
            f'&#x1F50D; SPIEGEL-MODUS &mdash; Datenquelle: {_html_escape(MIRROR_SOURCE)} '
            f'| Letzte Sync: <span id="mirror-sync-age">?</span>'
            '<button onclick="this.parentElement.style.display=\'none\'" '
            'style="margin-left:16px;background:rgba(255,255,255,0.3);border:none;'
            'color:#fff;cursor:pointer;padding:2px 8px;border-radius:3px;">&#x2715;</button>'
            '</div>'
            '<script>fetch("/api/mirror_status").then(r=>r.json()).then(d=>{'
            'document.getElementById("mirror-sync-age").textContent=d.sync_age_text||"?"'
            '}).catch(()=>{})</script>'
            '<style>body{padding-top:36px !important}</style>'
        )
        data = response.get_data(as_text=True)
        data = data.replace('<body', banner + '<body', 1)
        response.set_data(data)
    return response

@app.route('/api/mirror_status')
def api_mirror_status():
    """Status des Mirror-Modus (für Banner und Monitoring)."""
    sync_age = None
    sync_age_text = "unbekannt"
    last_sync = None

    # Prüfe Alter der lokalen DB
    db_path = config.DB_PERSIST_PATH
    if os.path.exists(db_path):
        mtime = os.path.getmtime(db_path)
        age_s = time.time() - mtime
        sync_age = int(age_s)
        if age_s < 60:
            sync_age_text = f"{int(age_s)}s"
        elif age_s < 3600:
            sync_age_text = f"{int(age_s/60)}min"
        else:
            sync_age_text = f"{int(age_s/3600)}h {int((age_s%3600)/60)}min"
        last_sync = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({
        'mirror_mode': MIRROR_MODE,
        'source': MIRROR_SOURCE,
        'local_ip': os.environ.get('PV_LOCAL_IP', '127.0.0.1'),
        'last_sync': last_sync,
        'sync_age_seconds': sync_age,
        'sync_age_text': sync_age_text,
    })


# ═══════════════════════════════════════════════════════════════
# BLUEPRINT-REGISTRIERUNG
# ═══════════════════════════════════════════════════════════════
from routes.pages import bp as pages_bp
from routes.data import bp as data_bp
from routes.realtime import bp as realtime_bp
from routes.visualization import bp as visualization_bp
from routes.verbraucher import bp as verbraucher_bp
from routes.erzeuger import bp as erzeuger_bp
from routes.system import bp as system_bp
from routes.forecast import bp as forecast_bp

app.register_blueprint(pages_bp)
app.register_blueprint(data_bp)
app.register_blueprint(realtime_bp)
app.register_blueprint(visualization_bp)
app.register_blueprint(verbraucher_bp)
app.register_blueprint(erzeuger_bp)
app.register_blueprint(system_bp)
app.register_blueprint(forecast_bp)

# Forecast-Tabelle sicherstellen (idempotent)
from routes.helpers import ensure_forecast_table
ensure_forecast_table()


# ═══════════════════════════════════════════════════════════════
# STANDALONE-START
# ═══════════════════════════════════════════════════════════════

def _check_port_available(host, port):
    """Prüft ob der Port frei ist — verhindert Konflikt mit systemd-Service"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # SO_REUSEADDR erlauben für TIME_WAIT sockets (schnellerer Restart)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False

if __name__ == '__main__':
    print("=== PV-System Web API ===")
    print(f"URL: http://localhost:{config.WEB_API_PORT}")
    print("Datensammlung läuft separat in collector.py")
    print("")

    # Port-Konflikt-Schutz: Verhindert doppelten Start (z.B. manuell + systemd)
    if not _check_port_available(config.WEB_API_HOST, config.WEB_API_PORT):
        print(f"FEHLER: Port {config.WEB_API_PORT} ist bereits belegt!")
        print("  Vermutlich läuft pv-web.service bereits.")
        print("  Prüfen:  sudo systemctl status pv-web.service")
        print("  Stoppen: sudo systemctl stop pv-web.service")
        import sys
        sys.exit(1)

    # tmpfs-DB initialisieren (NVMe → RAM beim Boot)
    if db_init.ensure_tmpfs_db():
        size_mb = os.path.getsize(config.DB_PATH) / 1e6 if os.path.exists(config.DB_PATH) else 0
        print(f"OK tmpfs-DB bereit: {config.DB_PATH} ({size_mb:.1f} MB)")
    else:
        print("FEHLER: tmpfs-DB konnte nicht initialisiert werden!")
        import sys
        sys.exit(1)

    # Persist-Thread: tmpfs → SD-Card (zeitbasiert)
    db_init.start_persist_thread()
    schedule = db_init.describe_persist_schedule()
    print(f"OK Persist-Thread: {config.DB_PATH} -> {config.DB_PERSIST_PATH} | {schedule}")

    print("")
    print("Architektur: tmpfs (RAM-Dateisystem)")
    print(f"  - Primaere DB:  {config.DB_PATH} (Echtzeit, <3s)")
    print(f"  - Persist-Kopie: {config.DB_PERSIST_PATH} ({schedule})")
    print("  => Null Disk-I/O fuer Reads, 1 Schicht, Echtzeit-Daten")
    print("")

    app.run(host=config.WEB_API_HOST, port=config.WEB_API_PORT, debug=False, threaded=True, use_reloader=False)
