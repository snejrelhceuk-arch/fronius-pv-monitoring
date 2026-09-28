"""pac4200-Submodul: Seiten-Routen + Live-Snapshot (Rolle B, read-only).

Aufgeteilt aus ``routes/pac4200.py`` (2026-09-28). Reine Template-Seiten der
PAC4200-/NQ-Ansichten sowie die Live-Snapshot-/Realtime-APIs (aus Tech-tmpfs,
kein PAC-Direktzugriff im Normalbetrieb).
"""
import logging
import os
import time as _time

from flask import jsonify, render_template, request

import config
from nq import pac_live
from nq import tech_read

from routes.pac4200 import bp


# ---------------------------------------------------------------------------
# Seiten-Routen
# ---------------------------------------------------------------------------

@bp.route('/pac4200')
def pac4200_page():
    return render_template('pac4200_view.html')


@bp.route('/netzqualitaet/live')
def nq_live_page():
    return render_template('nq_live_view.html')


@bp.route('/netzqualitaet/analyse')
def nq_analyse_page():
    """NQ-Spektralanalyse — Übersicht/Hub. Auf Einzelseiten verteilt:
    Oberschwingungen, Lomb-Scargle-Periodogramm, Welch-PSD, Transienten-
    Spektrogramm (STFT/Morlet-CWT) und Reflexionen. Rechenkern
    nq.analysis.nq_spectral (+ nq.analysis.nq_reflection)."""
    return render_template('nq_analyse_view.html', active='hub')


@bp.route('/netzqualitaet/analyse/harmonische')
def nq_analyse_harmonische_page():
    """Oberschwingungs-Linienspektrum (geräteinterne FFT) + THD-Korrelation."""
    return render_template('nq_spec_harmonische.html', active='harmonische')


@bp.route('/netzqualitaet/analyse/periodogramm')
def nq_analyse_periodogramm_page():
    """Lomb-Scargle-Periodogramm (VLF/eVLF, lückenrobust)."""
    return render_template('nq_spec_periodogramm.html', active='periodogramm')


@bp.route('/netzqualitaet/analyse/psd')
def nq_analyse_psd_page():
    """Welch-PSD (LF/VLF, log-log)."""
    return render_template('nq_spec_psd.html', active='psd')


@bp.route('/netzqualitaet/analyse/spektrogramm')
def nq_analyse_spektrogramm_page():
    """Transienten-Spektrogramm (STFT / Morlet-CWT)."""
    return render_template('nq_spec_spektrogramm.html', active='spektrogramm')


@bp.route('/netzqualitaet/analyse/reflexion')
def nq_analyse_reflexion_page():
    """Reflexions-/Laufwellen-Analyse (Versuch) — stilisierte Europakarte,
    Δt→Distanz→Reflexionsstelle. Rechenkern nq.analysis.nq_reflection."""
    return render_template('nq_reflexion.html', active='reflexion')


# ---------------------------------------------------------------------------
# Live-API (PAC4200)
# ---------------------------------------------------------------------------

@bp.route('/api/pac4200/live')
def api_pac4200_live():
    """NQ2 WP1: Live-Snapshot **indirekt aus Tech-tmpfs** (Tech = einziger PAC-Leser).

    Kein PAC-Direktzugriff im Normalbetrieb (Clients pollen den Tech-Puffer).
    ``?direct=1`` liest ausnahmsweise direkt vom PAC — nur für Offline-Feldtests
    und nur wenn per ENV ``PV_PAC_ALLOW_DIRECT=1`` freigegeben.
    """
    allow_direct = os.environ.get('PV_PAC_ALLOW_DIRECT', '0') == '1'
    if allow_direct and request.args.get('direct') == '1':
        try:
            snap = pac_live.read_snapshot(host=config.PAC_IP,
                                          port=config.PAC_MODBUS_PORT,
                                          unit_id=config.PAC_UNIT_ID,
                                          timeout=3.0)
            snap.setdefault('host', config.PAC_IP)
            return jsonify(snap), (200 if snap.get('ok') else 503)
        except Exception as exc:
            logging.exception("PAC4200 direct snapshot failed")
            return jsonify({"ok": False, "error": str(exc), "screens": []}), 503
    try:
        snap = tech_read.fetch_tech_snapshot()
        return jsonify(snap), (200 if snap.get('ok') else 503)
    except Exception as exc:
        logging.exception("PAC4200 tech snapshot failed")
        return jsonify({"ok": False, "error": str(exc), "screens": []}), 503


@bp.route('/api/nq/realtime_smart')
def api_nq_realtime_smart():
    """NQ-Zeitreihe (PAC4200) fuer Maschinenraum-Chart.

    resolution>=300 s -> nq_5min (Tagesraster). resolution<300 s -> Hochaufloesung
    aus Techs RAW-RAM (nur die letzten ~12 h; aeltere Buckets im Fenster bleiben 5 min).
    """
    try:
        resolution = max(request.args.get('resolution', type=int, default=300), 5)
        start_ts = request.args.get('start', type=int)
        end_ts = request.args.get('end', type=int)
        end = end_ts if end_ts else int(_time.time())
        if start_ts and end_ts and start_ts < end_ts:
            start = start_ts
        else:
            hours = min(max(request.args.get('hours', type=float, default=24.0), 0.001), 168)
            start = end - int(hours * 3600)
        res = tech_read.fetch_agg(start, end, resolution)
        res["resolution"] = f"{resolution}s"
        return jsonify(res), (200 if not res.get("error") else 503)
    except Exception as exc:
        logging.exception("NQ realtime_smart failed")
        return jsonify({"data": [], "error": str(exc), "source": "nq_tech_5min"}), 503
