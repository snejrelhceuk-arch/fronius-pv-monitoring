"""System-Info- und Ticker-Endpunkte des system-Blueprints."""
import os

from flask import jsonify

from routes.helpers import api_error_response
from routes.system import bp


@bp.route('/api/system_info')
def api_system_info():
    """Live-Systeminfos: CPU, RAM, Temp, Uptime, DB-Größe."""
    import platform
    result = {}
    try:
        # CPU-Auslastung (1-min Load Average)
        load1, load5, load15 = os.getloadavg()
        result['cpu_load'] = {'1min': round(load1, 2), '5min': round(load5, 2), '15min': round(load15, 2)}

        # CPU-Cores
        result['cpu_cores'] = os.cpu_count() or 1

        # RAM
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem = {}
            for line in lines:
                parts = line.split()
                if parts[0] in ('MemTotal:', 'MemAvailable:', 'MemFree:'):
                    mem[parts[0].rstrip(':')] = int(parts[1])  # kB
            total_mb = mem.get('MemTotal', 0) / 1024
            avail_mb = mem.get('MemAvailable', mem.get('MemFree', 0)) / 1024
            used_mb = total_mb - avail_mb
            result['ram'] = {
                'total_mb': round(total_mb),
                'used_mb': round(used_mb),
                'avail_mb': round(avail_mb),
                'percent': round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0
            }
        except Exception:
            result['ram'] = None

        # CPU-Temperatur
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_mc = int(f.read().strip())
            result['cpu_temp_c'] = round(temp_mc / 1000, 1)
        except Exception:
            result['cpu_temp_c'] = None

        # Uptime
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_s = float(f.read().split()[0])
            days = int(uptime_s // 86400)
            hours = int((uptime_s % 86400) // 3600)
            mins = int((uptime_s % 3600) // 60)
            result['uptime'] = f"{days}d {hours}h {mins}m"
            result['uptime_seconds'] = round(uptime_s)
        except Exception:
            result['uptime'] = None

        # Hostname + Modell
        result['hostname'] = platform.node()
        try:
            with open('/proc/device-tree/model', 'r') as f:
                result['model'] = f.read().strip().rstrip('\x00')
        except Exception:
            result['model'] = platform.machine()

        # Python Version
        result['python'] = platform.python_version()

        # DB-Größe (tmpfs)
        try:
            db_path = '/dev/shm/fronius_data.db'
            if os.path.exists(db_path):
                size_bytes = os.path.getsize(db_path)
                result['db_size_mb'] = round(size_bytes / 1024 / 1024, 1)
            else:
                result['db_size_mb'] = None
        except Exception:
            result['db_size_mb'] = None

        # Disk (SD-Card / Root)
        try:
            st = os.statvfs('/')
            total_gb = (st.f_frsize * st.f_blocks) / (1024**3)
            free_gb = (st.f_frsize * st.f_bavail) / (1024**3)
            result['disk'] = {
                'total_gb': round(total_gb, 1),
                'free_gb': round(free_gb, 1),
                'percent': round((1 - free_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            }
        except Exception:
            result['disk'] = None

    except Exception as e:
        return api_error_response(e, "System Info")

    return jsonify(result)


@bp.route('/api/ticker', methods=['GET'])
def get_ticker():
    """Holt die Ticker-Nachrichten vom Microservice (mit Fallback)"""
    import requests
    from config import load_local_setting

    ticker_url = load_local_setting('PV_TICKER_API_ENDPOINT', 'http://127.0.0.1:8050/ticker')
    try:
        # Aggressiver Timeout, um pv-system nicht zu blockieren, falls Pi5 offline
        resp = requests.get(ticker_url, timeout=1.0)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({
            "status": "error",
            "text": "Ticker derzeit nicht erreichbar.",
            "detail": str(e)
        })
