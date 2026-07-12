"""
Blueprint: PAC4200 Netzqualitäts-Messgerät (read-only Live-Anzeige).

Enthält: /pac4200 (Seite), /api/pac4200/live (JSON-Snapshot).

ABCD(EN)-Rollenmodell: Säule B (read-only Anzeige). Der Modbus-Zugriff selbst
liegt in Rolle N (`nq/pac_live.py`) und ist ausschliesslich lesend — analog zum
etablierten read-only `FroniusReadOnly`-Muster (nur GET/Read, kein Schreibpfad).
"""
import logging

from flask import Blueprint, jsonify, render_template, request

import config
from nq import pac_live
from nq import tech_read

bp = Blueprint('pac4200', __name__)


@bp.route('/pac4200')
def pac4200_page():
    """PAC4200-Bedienoberfläche (nachgebildet) — Flow → Maschinenraum → PAC4200."""
    return render_template('pac4200_view.html')


@bp.route('/netzqualitaet/live')
def nq_live_page():
    """Netzqualität-Live-Tableau — alle PAC4200-Messwerte als Datentabelle
    (Pendant zu „Echtzeit", read-only). Erreichbar über den Maschinenraum."""
    return render_template('nq_live_view.html')


@bp.route('/api/pac4200/live')
def api_pac4200_live():
    """Read-only Live-Snapshot des PAC4200 (alle Mess-Bildschirme + Energie)."""
    try:
        snap = pac_live.read_snapshot(host=config.PAC_IP,
                                      port=config.PAC_MODBUS_PORT,
                                      unit_id=config.PAC_UNIT_ID,
                                      timeout=3.0)
        return jsonify(snap), (200 if snap.get('ok') else 503)
    except Exception as exc:  # pragma: no cover
        logging.exception("PAC4200 live snapshot failed")
        return jsonify({"ok": False, "error": str(exc), "screens": []}), 503


@bp.route('/api/nq/realtime_smart')
def api_nq_realtime_smart():
    """NQ-Zeitreihe (PAC4200 10-s-Aggregat) im gleichen Format wie
    /api/realtime_smart — Datenquelle für das DB-umschaltbare Maschinenraum-
    Charting („Netzqualität"-DB statt Kern-DB). Read-only von Tech."""
    import time as _t
    try:
        resolution = max(request.args.get('resolution', type=int, default=300), 10)
        start_ts = request.args.get('start', type=int)
        end_ts = request.args.get('end', type=int)
        end = end_ts if end_ts else int(_t.time())
        if start_ts and end_ts and start_ts < end_ts:
            start = start_ts
        else:
            hours = min(max(request.args.get('hours', type=float, default=24.0), 0.001), 168)
            start = end - int(hours * 3600)
        res = tech_read.fetch_agg(start, end, resolution)
        res["resolution"] = f"{resolution}s"
        return jsonify(res), (200 if not res.get("error") else 503)
    except Exception as exc:  # pragma: no cover
        logging.exception("NQ realtime_smart failed")
        return jsonify({"data": [], "error": str(exc), "source": "nq_tech_agg10s"}), 503
