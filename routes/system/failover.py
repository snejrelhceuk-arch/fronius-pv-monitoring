"""Failover- und Backup-Status-Endpunkte des system-Blueprints.

Prüfen entfernte Hosts read-only via SSH (Sync-Marker / Backup-DB-Alter).
Eigene Caches begrenzen die SSH-Aufrufe.
"""
import os
import time

from flask import jsonify

import config
from routes.system import bp

# ── Failover-/Backup-Status Caches ──────────────────────────────
_failover_cache = {'ts': 0, 'result': None}
_FAILOVER_CACHE_TTL = 60  # Sekunden (max. 1 SSH-Aufruf pro Minute)
_backup_cache = {'ts': 0, 'result': None}
_BACKUP_CACHE_TTL = 600  # Sekunden (10 Minuten)


@bp.route('/api/failover_status')
def api_failover_status():
    """
    Prüft den Failover-Host via SSH:
    Liest den Timestamp der Sync-Marker-Datei (.state/last_mirror_sync.ok).
    Wenn ≤ 15 Min alt → live, ≤ 30 Min → stale, sonst → down.
    Fallback: SSH-Connect prüfen (Host da, aber Sync kaputt).
    Cache: 60 Sekunden — max. 1 SSH-Aufruf pro Minute.
    """
    import subprocess

    now = time.time()
    if now - _failover_cache['ts'] < _FAILOVER_CACHE_TTL and _failover_cache['result'] is not None:
        return jsonify(_failover_cache['result'])

    failover_ip = getattr(config, 'FAILOVER_IP', None)
    failover_user = getattr(config, 'FAILOVER_USER', 'failover-user')
    failover_pv_base = getattr(config, 'FAILOVER_PV_BASE',
                               '/srv/pv-system')

    if not failover_ip:
        result = {'status': 'unknown', 'detail': 'FAILOVER_IP nicht konfiguriert'}
        _failover_cache.update(ts=now, result=result)
        return jsonify(result)

    marker = f'{failover_pv_base}/.state/last_mirror_sync.ok'
    ssh_target = f'{failover_user}@{failover_ip}'

    try:
        # SSH: Marker-Timestamp lesen (stat -c %Y = modtime als epoch).
        # Der Remote-Teil endet dank `|| echo 0` immer mit RC 0 — der
        # ssh-Return-Code spiegelt daher rein die Erreichbarkeit wider
        # (0 = verbunden, != 0 = Auth-/Verbindungsfehler).
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=3', '-o', 'BatchMode=yes',
             '-o', 'StrictHostKeyChecking=accept-new',
             ssh_target, f'stat -c %Y "{marker}" 2>/dev/null || echo 0'],
            capture_output=True, text=True, timeout=6
        )

        if proc.returncode != 0:
            # SSH-Verbindung selbst fehlgeschlagen → Host down (nicht "stale").
            result = {'status': 'down', 'age': None, 'host': ssh_target,
                      'detail': f'Failover-Host nicht erreichbar (ssh rc={proc.returncode})'}
        else:
            try:
                marker_ts = int((proc.stdout or '').strip() or '0')
            except ValueError:
                marker_ts = 0
            age_sec = int(now - marker_ts) if marker_ts > 0 else -1

            if age_sec < 0:
                result = {'status': 'stale', 'age': None, 'host': ssh_target,
                          'detail': 'Host erreichbar, aber Sync-Marker fehlt (kein Mirror-Lauf)'}
            elif age_sec <= 900:   # ≤ 15 Min
                result = {'status': 'live', 'age': age_sec, 'host': ssh_target,
                          'detail': f'Mirror OK ({age_sec // 60} Min)'}
            elif age_sec <= 1800:  # ≤ 30 Min
                result = {'status': 'stale', 'age': age_sec, 'host': ssh_target,
                          'detail': f'Mirror veraltet ({age_sec // 60} Min)'}
            else:
                result = {'status': 'stale', 'age': age_sec, 'host': ssh_target,
                          'detail': f'Mirror zu alt ({age_sec // 60} Min)'}

    except subprocess.TimeoutExpired:
        result = {'status': 'down', 'age': None, 'host': ssh_target,
                  'detail': 'SSH-Timeout (Failover-Host nicht erreichbar)'}
    except Exception as e:
        result = {'status': 'down', 'age': None, 'host': ssh_target,
                  'detail': f'Fehler: {e}'}

    _failover_cache.update(ts=now, result=result)
    return jsonify(result)


@bp.route('/api/backup_status')
def api_backup_status():
    """
    Prüft den Backup-Pfad auf Pi5 via SSH (Existenz Zielverzeichnis).

    Status:
      - up:   Zielverzeichnis vorhanden
      - down: Zielverzeichnis fehlt oder SSH-Fehler

    Cache: 10 Minuten (kein häufiger SSH-Check nötig).
    """
    import subprocess

    now = time.time()
    if now - _backup_cache['ts'] < _BACKUP_CACHE_TTL and _backup_cache['result'] is not None:
        return jsonify(_backup_cache['result'])

    pi5_host = getattr(config, 'PI5_BACKUP_HOST', None)
    pi5_db_path = getattr(config, 'PI5_BACKUP_DB_PATH', '/srv/pv-system/data.db')
    default_gfs_base = os.path.join(os.path.dirname(pi5_db_path), 'backup', 'db')
    target_dir = getattr(config, 'PI5_BACKUP_GFS_BASE', default_gfs_base)

    if not pi5_host:
        result = {'status': 'down', 'detail': 'PI5_BACKUP_HOST nicht konfiguriert', 'target_dir': target_dir}
        _backup_cache.update(ts=now, result=result)
        return jsonify(result)

    try:
        # Prüfe Erreichbarkeit UND Aktualität der Backup-DB
        proc = subprocess.run(
            [
                'ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=accept-new',
                pi5_host,
                f'test -d "{target_dir}" && stat -c%Y "{pi5_db_path}" 2>/dev/null || echo 0'
            ],
            capture_output=True, text=True, timeout=8
        )

        out = (proc.stdout or '').strip()
        try:
            remote_mtime = int(out)
        except ValueError:
            remote_mtime = 0

        if remote_mtime == 0:
            result = {
                'status': 'down',
                'detail': 'Zielverzeichnis oder DB fehlt/nicht erreichbar',
                'target_dir': target_dir,
                'checked_at': int(now),
            }
        else:
            age_h = (now - remote_mtime) / 3600
            if age_h <= 12:
                result = {
                    'status': 'up',
                    'detail': f'Backup aktuell (vor {age_h:.1f}h)',
                    'target_dir': target_dir,
                    'checked_at': int(now),
                    'backup_age_hours': round(age_h, 1),
                }
            else:
                result = {
                    'status': 'stale',
                    'detail': f'Backup veraltet! Letzte Aktualisierung vor {age_h:.0f}h',
                    'target_dir': target_dir,
                    'checked_at': int(now),
                    'backup_age_hours': round(age_h, 1),
                }
    except subprocess.TimeoutExpired:
        result = {
            'status': 'down',
            'detail': 'SSH-Timeout zu Pi5',
            'target_dir': target_dir,
            'checked_at': int(now),
        }
    except Exception as e:
        result = {
            'status': 'down',
            'detail': f'Fehler: {e}',
            'target_dir': target_dir,
            'checked_at': int(now),
        }

    _backup_cache.update(ts=now, result=result)
    return jsonify(result)
