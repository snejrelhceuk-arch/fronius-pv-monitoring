"""
Blueprint: Speicherausbau-Amortisationsanalyse (Rolle B, read-only).

Vorwaerts gerichtetes Entscheidungsmodell im Analyse-Bereich:
  /analyse/speicherausbau           HTML-Ansicht (Schieber + ECharts)
  /api/analyse/speicher/sweep       Kapazitaets-Sweep (Kurve + Wirtschaft)
  /api/analyse/speicher/detail      Monatsaufschluesselung fuer ein Szenario

Kein Hardware-Zugriff, kein DB-Write. Rechnet auf den permanenten 5-min-Daten.
"""
import logging
from urllib.parse import urlencode

from flask import Blueprint, jsonify, render_template, request

from analysis import storage_model
from routes.helpers import api_error_response

logger = logging.getLogger(__name__)

bp = Blueprint('analyse_speicher', __name__)


def _nav_query():
    try:
        from routes.pages import _get_nav_context
        return urlencode(_get_nav_context(request.args))
    except Exception:
        return ''


@bp.route('/analyse/speicherausbau')
def speicherausbau_page():
    """Ansicht: Nachweis vermeidbarer Netzbezug via Speicherausbau + PV-Zubau."""
    nav_query = _nav_query()
    return render_template('analyse_speicherausbau_view.html',
                           nav_query=('?' + nav_query) if nav_query else '')


@bp.route('/api/analyse/speicher/sweep')
def api_sweep():
    """Kapazitaets-Sweep fuer gegebenen PV-Zubau + Abregelungs-Modus."""
    try:
        add_pv = request.args.get('add_pv', 0.0, type=float) or 0.0
        curtail = request.args.get('curtail', '1') != '0'
        add_pv = max(0.0, min(add_pv, 40.0))
        result = storage_model.run_sweep(add_pv_kwp=add_pv, use_curtailment=curtail)
        return jsonify(result)
    except Exception as exc:  # pragma: no cover - defensiv
        return api_error_response(exc, "Speicher-Sweep")


@bp.route('/api/analyse/speicher/detail')
def api_detail():
    """Monatsaufschluesselung + Kennzahlen fuer ein konkretes Szenario."""
    try:
        add_pv = request.args.get('add_pv', 0.0, type=float) or 0.0
        batt = request.args.get('batt', 25.0, type=float) or 0.0
        curtail = request.args.get('curtail', '1') != '0'
        add_pv = max(0.0, min(add_pv, 40.0))
        batt = max(0.0, min(batt, 60.0))
        result = storage_model.run_detail(add_pv_kwp=add_pv, batt_nom_kwh=batt,
                                          use_curtailment=curtail)
        return jsonify(result)
    except Exception as exc:  # pragma: no cover - defensiv
        return api_error_response(exc, "Speicher-Detail")
