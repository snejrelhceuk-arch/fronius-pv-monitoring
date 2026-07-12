"""
Blueprint: PAC4200 Netzqualitäts-Messgerät (read-only Live-Anzeige).

Enthält: /pac4200 (Seite), /api/pac4200/live (JSON-Snapshot).

ABCD(EN)-Rollenmodell: Säule B (read-only Anzeige). Der Modbus-Zugriff selbst
liegt in Rolle N (`nq/pac_live.py`) und ist ausschliesslich lesend — analog zum
etablierten read-only `FroniusReadOnly`-Muster (nur GET/Read, kein Schreibpfad).
"""
import logging

from flask import Blueprint, jsonify, render_template

import config
from nq import pac_live

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
