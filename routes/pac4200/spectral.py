"""pac4200-Submodul: Spektral-/Muster-/Reflexions-Analyse + Event-Drilldown.

Aufgeteilt aus ``routes/pac4200.py`` (2026-09-28). Read-only (Säule B):
Musteranalyse-Datensatz (nq_pattern_5min), Spektralanalyse (Harmonische,
Lomb-Scargle, Welch-PSD, STFT/Morlet-CWT), Reflexions-/Laufwellen-Analyse und
der Event-Schnipsel-Drilldown. Rechenkern: nq.analysis.nq_spectral / nq_reflection.
"""
import logging
import os
import time as _time
from glob import glob

from flask import jsonify, request

from routes.pac4200 import bp
from routes.pac4200._shared import _NQ_PRIMARY_DIR, _open_legacy, _nq_primary_db


# ---------------------------------------------------------------------------
# Musteranalyse-Datensatz (residual-bereinigt, nq_pattern_5min) — read-only
# ---------------------------------------------------------------------------

def _months_in_range(start, end):
    import datetime as _dt
    out = []
    d = _dt.date.fromtimestamp(start).replace(day=1)
    last = _dt.date.fromtimestamp(max(start, end - 1))
    while d <= last:
        out.append(d.strftime('%Y-%m'))
        d = (d.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    return out


@bp.route('/api/nq/pattern')
def api_nq_pattern():
    """Sauberer Musteranalyse-Datensatz (`nq_pattern_5min`): netzseitige U, f, PF, phi.

    Read-only. Parameter: ``?day=YYYY-MM-DD`` ODER ``?start=&end=`` (Unix-s).
    Interne (hinter dem PCC liegende) Lasteffekte sind residual-bereinigt.
    """
    day = request.args.get('day')
    if day:
        try:
            t = _time.strptime(day, '%Y-%m-%d')
            start = int(_time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
            end = start + 86400
        except Exception:
            return jsonify({'error': 'invalid day'}), 400
    else:
        end = request.args.get('end', type=int) or int(_time.time())
        start = request.args.get('start', type=int) or (end - 86400)
    cols = ['ts', 'u_clean_l1', 'u_clean_l2', 'u_clean_l3', 'u_meas_l1', 'u_meas_l2', 'u_meas_l3',
            'freq', 'pf_l1', 'pf_l2', 'pf_l3', 'phi_l1', 'phi_l2', 'phi_l3', 'du_int_max', 'origin']
    data = []
    for month in _months_in_range(start, end):
        conn = _open_legacy(_nq_primary_db(month))
        if not conn:
            continue
        try:
            rows = conn.execute(
                f"SELECT {','.join(cols)} FROM nq_pattern_5min WHERE ts >= ? AND ts < ? ORDER BY ts",
                (start, end)).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()
        for r in rows:
            data.append(dict(zip(cols, r)))
    return jsonify({'data': data, 'points': len(data), 'start': start, 'end': end,
                    'source': 'nq_pattern_5min', 'columns': cols})


# ---------------------------------------------------------------------------
# Spektralanalyse (ersetzt die Netzmusteranalyse) — read-only (Saeule B)
# Rechenkern: nq.analysis.nq_spectral (pure numpy). Siehe Card
# netzqualitaet-nq-analysis-events.card.md.
# ---------------------------------------------------------------------------

def _spec_window(default_days: int) -> tuple[int, int]:
    """Parst ?day / ?start&end -> (start, end) Unix-s."""
    day = request.args.get('day')
    if day:
        try:
            t = _time.strptime(day, '%Y-%m-%d')
            start = int(_time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
            return start, start + 86400
        except Exception:
            pass
    end = request.args.get('end', type=int) or int(_time.time())
    start = request.args.get('start', type=int) or (end - default_days * 86400)
    return start, end


def _nq_earliest_ts() -> int:
    """Frühester nq_5min-Zeitstempel über alle Monats-DBs (Messbeginn PAC4200).

    Für ``?range=all`` im Periodogramm: die Spanne (und damit die längste
    auflösbare Periode) verlängert sich mit jedem weiteren Messtag automatisch.
    """
    import glob
    from nq.analysis import nq_spectral as spec
    earliest = None
    for path in sorted(glob.glob(os.path.join(spec._DB_DIR, 'nq_2*.db'))):
        conn = spec._open_ro(path)
        if conn is None:
            continue
        try:
            row = conn.execute("SELECT MIN(ts) FROM nq_5min").fetchone()
            if row and row[0] is not None:
                earliest = row[0] if earliest is None else min(earliest, row[0])
        except Exception:
            pass
        finally:
            conn.close()
    return int(earliest) if earliest else int(_time.time() - 30 * 86400)


def _bounded_int_arg(name: str, default: int, lo: int, hi: int) -> int:
    value = request.args.get(name, type=int)
    if value is None:
        value = default
    return max(lo, min(int(value), hi))


def _series_pearson(a: dict, b: dict) -> float | None:
    """Pearson-Korrelation zweier {ts,values}-Serien ueber gemeinsame ts.

    Plausibilitaetspruefungen:
      - NaN/Inf werden ausgefiltert
      - Extreme Werte (>1e15 abs) werden verworfen
      - Ergebnis muss im gültigen Bereich [-1, 1] liegen
    """
    import numpy as _np
    ai = {int(t): float(v) for t, v in zip(a.get('ts', []), a.get('values', []))}
    bi = {int(t): float(v) for t, v in zip(b.get('ts', []), b.get('values', []))}
    common = sorted(set(ai) & set(bi))
    if len(common) < 5:
        return None
    x = _np.array([ai[t] for t in common]); y = _np.array([bi[t] for t in common])

    # Plausibilitätsprüfung: NaN/Inf/extreme Werte filtern
    mask = _np.isfinite(x) & _np.isfinite(y) & (_np.abs(x) < 1e15) & (_np.abs(y) < 1e15)
    if mask.sum() < 5:
        return None
    x = x[mask]; y = y[mask]

    if x.std() < 1e-12 or y.std() < 1e-12:
        return None

    try:
        r = float(_np.corrcoef(x, y)[0, 1])
        # Plausibilitätsprüfung des Ergebnisses
        if not _np.isfinite(r) or abs(r) > 1.0:
            return None
        return round(r, 4)
    except Exception:
        return None


def _downsample_matrix(mat, max_rows: int, max_cols: int):
    """Reduziert eine 2D-Matrix (fuer Transport) per Bin-Mittelung."""
    import numpy as _np
    m = _np.asarray(mat, dtype=float)
    if m.size == 0:
        return m, _np.array([]), _np.array([])
    r, c = m.shape
    out_rows = min(max_rows, r)
    out_cols = min(max_cols, c)
    if out_rows == r and out_cols == c:
        return m, _np.arange(r), _np.arange(c)

    row_edges = _np.linspace(0, r, out_rows + 1, dtype=int)
    col_edges = _np.linspace(0, c, out_cols + 1, dtype=int)
    out = _np.empty((out_rows, out_cols), dtype=float)
    ridx = _np.empty(out_rows, dtype=int)
    cidx = _np.empty(out_cols, dtype=int)

    for i in range(out_rows):
        rs, re = int(row_edges[i]), max(int(row_edges[i + 1]), int(row_edges[i]) + 1)
        ridx[i] = min(r - 1, (rs + re - 1) // 2)
        for j in range(out_cols):
            cs, ce = int(col_edges[j]), max(int(col_edges[j + 1]), int(col_edges[j]) + 1)
            if i == 0:
                cidx[j] = min(c - 1, (cs + ce - 1) // 2)
            block = m[rs:re, cs:ce]
            finite = block[_np.isfinite(block)]
            out[i, j] = float(finite.mean()) if finite.size else float('nan')
    return out, ridx, cidx


@bp.route('/api/nq/spectral/harmonics')
def api_nq_spectral_harmonics():
    """Oberschwingungs-Linienspektrum (PAC4200-Register) + THD-Korrelation.

    >50-Hz-Teil: geraeteinterne FFT (ungerade Ordnungen H1..H31 -> n*50 Hz).
    Vergleich berechnete THD (aus Harmonischen) gegen PAC4200-THD-Register.
    ``?start=&end=`` (Default 7 d) oder ``?day=``, ``?meas=U_LN|U_LL|I``.
    """
    from nq.analysis import nq_spectral as spec
    start, end = _spec_window(7)
    meas = request.args.get('meas', 'U_LN')
    if meas not in ('U_LN', 'U_LL', 'I'):
        meas = 'U_LN'
    try:
        harm = spec.load_harmonics(start, end, meas)
        thd_calc = spec.thd_from_harmonics(harm['orders'], harm['values'])
        thd_calc_series = spec.load_harmonic_thd_series(start, end, meas)
        pac_kind = 'i' if meas == 'I' else 'u'
        thd_pac_series = spec.load_thd_series(start, end, pac_kind)
        corr = _series_pearson(thd_calc_series, thd_pac_series)
    except Exception as exc:
        logging.exception("spectral/harmonics failed")
        return jsonify({'error': str(exc)}), 503
    return jsonify({
        'start': start, 'end': end, 'meas': meas,
        'spectrum': harm,
        'thd_calc_pct': thd_calc,
        'thd_calc_series': thd_calc_series,
        'thd_pac_series': thd_pac_series,
        'thd_correlation': corr,
        'note': ('THD aus ungeraden Einzelharmonischen (H1..H31) -> untere Schranke; '
                 'gerade Ordnungen (z.B. 100 Hz) fuehrt das PAC4200 nicht als Register. '
                 'Korrelation zum PAC-THD-Register ist deshalb erwartbar < 1,0.'),
    })


@bp.route('/api/nq/spectral/periodogram')
def api_nq_spectral_periodogram():
    """Lomb-Scargle-Periodogramm (VLF/eVLF), lückenrobust.

    ``?signal=freq|voltage``, ``?start=&end=`` (Default 30 d) oder ``?range=all``
    (seit Messbeginn PAC4200), ``?decimate=N``, ``?binning=1``. Die Auflösung
    wählt sich nach Spanne (5-min ≤ 75 d, sonst stündlich/täglich), damit die
    Periodenachse mit wachsender Messdauer immer weiter reicht (Woche → Saison
    → Jahr) und nicht an der 5-min-Retention (90 d) hängenbleibt.
    """
    from nq.analysis import nq_spectral as spec
    import numpy as _np
    if request.args.get('range') == 'all':
        start, end = _nq_earliest_ts(), int(_time.time())
    else:
        start, end = _spec_window(30)
    signal = request.args.get('signal', 'freq')
    dec = _bounded_int_arg('decimate', 1, 1, 10)
    do_bin = request.args.get('binning', type=int, default=0)
    # Auflösung nach Spanne wählen: 5-min bis 75 d, dann stündlich (bis ~2 a),
    # dann täglich — hält die Punktzahl für Lomb-Scargle beherrschbar und reicht
    # über die 5-min-Retention hinaus.
    span_days = max(0.0, (end - start) / 86400.0)
    source = '5min' if span_days <= 75 else ('hourly' if span_days <= 730 else 'daily')
    try:
        if source == '5min' and signal == 'voltage':
            ts, v = spec.load_clean_voltage(start, end, 1)
            x = v - (float(_np.nanmean(v)) if v.size else 0.0)
            unit = 'V'
        elif source == '5min':
            ts, v = spec.load_clean_freq(start, end)
            x = v - 50.0
            unit = 'Hz'
        else:
            _tab = 'nq_hourly' if source == 'hourly' else 'nq_daily'
            if signal == 'voltage':
                ts, v = spec.load_scalar_series('U_L1N', start, end, table=_tab)
                x = v - (float(_np.nanmean(v)) if v.size else 0.0)
                unit = 'V'
            else:
                ts, v = spec.load_scalar_series('FREQ', start, end, table=_tab)
                x = v - 50.0
                unit = 'Hz'
        if ts.size < 16:
            return jsonify({'error': 'insufficient data', 'n': int(ts.size),
                            'start': start, 'end': end}), 200
        t_used = ts.astype(float)
        dt = float(_np.median(_np.diff(_np.sort(ts))))
        if dec > 1:
            tu, xu, _fs = spec.resample_uniform(ts, x)
            xu = spec.decimate(xu, dec)
            t_used = tu[::dec][:xu.size]
            x = xu
            dt = dt * dec
        span = float(t_used[-1] - t_used[0])
        f_min = max(1.0 / span, 1e-9)
        f_max = 0.5 / dt
        fg = spec.log_freq_grid(f_min, f_max, 500)
        power = spec.lombscargle(t_used, x, fg)
        markers = []
        for m in spec.CYCLE_MARKERS:
            f = 1.0 / m['period_s']
            markers.append({**m, 'freq_hz': f,
                            'resolvable': bool(f_min <= f <= f_max)})
        resp = {
            'start': start, 'end': end, 'signal': signal, 'unit': unit,
            'n_samples': int(t_used.size), 'span_s': span,
            'source': source, 'decimate': dec, 'f_min_hz': f_min, 'f_max_hz': f_max,
            'freqs_hz': [round(float(f), 12) for f in fg],
            'power': [round(float(p), 6) for p in power],
            'markers': markers,
        }
        if do_bin:
            cf, cp, cc = spec.log_bin(fg, power, 12)
            resp['binned'] = {
                'freqs_hz': [round(float(f), 12) for f in cf],
                'power': [round(float(p), 6) for p in cp],
                'count': [int(c) for c in cc],
            }
        return jsonify(resp)
    except Exception as exc:
        logging.exception("spectral/periodogram failed")
        return jsonify({'error': str(exc)}), 503


@bp.route('/api/nq/spectral/psd')
def api_nq_spectral_psd():
    """Welch-PSD (log-log) der 5-min-Reihe. ``?signal=freq|voltage``,
    ``?window=hann|blackman``, ``?nperseg=``. 50-Hz-Split entfaellt (Nyquist
    << 50 Hz bei 5-min-Daten) -> hier LF/VLF-Leistungsdichte."""
    from nq.analysis import nq_spectral as spec
    import numpy as _np
    start, end = _spec_window(30)
    signal = request.args.get('signal', 'freq')
    window = request.args.get('window', 'hann')
    try:
        if signal == 'voltage':
            ts, v = spec.load_clean_voltage(start, end, 1)
            x = v - (float(_np.nanmean(v)) if v.size else 0.0)
            unit = 'V'
        else:
            ts, v = spec.load_clean_freq(start, end)
            x = v - 50.0
            unit = 'Hz'
        if ts.size < 32:
            return jsonify({'error': 'insufficient data', 'n': int(ts.size)}), 200
        tu, xu, fs = spec.resample_uniform(ts, x)
        default_nperseg = min(1024, xu.size // 4 * 2 or 8)
        nperseg = _bounded_int_arg('nperseg', default_nperseg, 16, min(8192, xu.size))
        f, p = spec.welch_psd(xu, fs, nperseg=nperseg, window=window)
        # log-log: DC-Bin (f=0) weglassen
        keep = f > 0
        return jsonify({
            'start': start, 'end': end, 'signal': signal, 'unit': unit,
            'fs_hz': fs, 'nperseg': nperseg, 'window': window,
            'freqs_hz': [round(float(x_), 12) for x_ in f[keep]],
            'psd': [round(float(y_), 9) for y_ in p[keep]],
            'psd_unit': f'{unit}^2/Hz',
            'note': ('50-Hz-Notch/Split nicht anwendbar: Abtastung 300 s '
                     '(Nyquist 1,667 mHz). Dargestellt ist die LF/VLF-Leistungsdichte.'),
        })
    except Exception as exc:
        logging.exception("spectral/psd failed")
        return jsonify({'error': str(exc)}), 503


@bp.route('/api/nq/spectral/spectrogram')
def api_nq_spectral_spectrogram():
    """Zeit-Frequenz-Analyse fuer Transienten (Verschiebungen/Aufschwingen).

    ``?method=cwt|stft`` (Default cwt, Morlet w0=6), ``?signal=freq|voltage``,
    ``?start=&end=`` (Default 7 d). Liefert eine kompakte 2D-Matrix (Heatmap).
    """
    from nq.analysis import nq_spectral as spec
    import numpy as _np
    start, end = _spec_window(7)
    method = request.args.get('method', 'cwt')
    signal = request.args.get('signal', 'freq')
    try:
        if signal == 'voltage':
            ts, v = spec.load_clean_voltage(start, end, 1)
            x = v - (float(_np.nanmean(v)) if v.size else 0.0)
            unit = 'V'
        else:
            ts, v = spec.load_clean_freq(start, end)
            x = v - 50.0
            unit = 'Hz'
        if ts.size < 32:
            return jsonify({'error': 'insufficient data', 'n': int(ts.size)}), 200
        tu, xu, fs = spec.resample_uniform(ts, x)
        t0 = float(tu[0])
        if method == 'stft':
            default_nperseg = min(128, xu.size // 4 or 8)
            nperseg = _bounded_int_arg('nperseg', default_nperseg, 16, min(4096, xu.size))
            freqs, times, Z = spec.stft(xu, fs, nperseg=nperseg)
            times_abs = t0 + times
        else:  # cwt (Morlet)
            f_hi = fs / 2.0
            f_lo = max(4.0 / (float(tu[-1] - tu[0])), f_hi / 1000.0)
            freqs = spec.log_freq_grid(f_lo, f_hi, 48)
            expected_bytes = len(freqs) * len(xu) * 8
            if expected_bytes > 50 * 1024 * 1024:
                return jsonify({'error': 'too much data for CWT; reduce timespan',
                                'estimated_mb': round(expected_bytes / (1024 * 1024), 1)}), 400
            Z = spec.morlet_cwt(xu, fs, freqs)
            times_abs = tu
        Zd, ridx, cidx = _downsample_matrix(Z, max_rows=64, max_cols=240)
        f_out = _np.asarray(freqs)[ridx] if len(ridx) else _np.asarray([])
        t_out = _np.asarray(times_abs)[cidx] if len(cidx) else _np.asarray([])
        return jsonify({
            'start': start, 'end': end, 'method': method, 'signal': signal, 'unit': unit,
            'fs_hz': fs,
            'freqs_hz': [round(float(f), 10) for f in f_out],
            'times': [int(t) for t in t_out],
            'z': [[round(float(val), 6) for val in row] for row in Zd],
            'shape': [int(Zd.shape[0]) if Zd.size else 0, int(Zd.shape[1]) if Zd.size else 0],
        })
    except Exception as exc:
        logging.exception("spectral/spectrogram failed")
        return jsonify({'error': str(exc)}), 503


@bp.route('/api/nq/reflection')
def api_nq_reflection():
    """Reflexions-/Laufwellen-Analyse: Netzgrenz-Geometrie + Schwingungspakete
    (5-min) + Event-Echo-Hypothesen (Δt→d=v·Δt/2→Reflexionsstelle).

    ``?start=&end=`` (Default 30 d) oder ``?day=``, ``?signal=freq|voltage``.
    Rechenkern nq.analysis.nq_reflection (read-only, Rolle N)."""
    from nq.analysis import nq_reflection as refl
    start, end = _spec_window(30)
    signal = request.args.get('signal', 'freq')
    try:
        return jsonify(refl.analyze(start, end, signal))
    except Exception as exc:
        logging.exception("nq/reflection failed")
        return jsonify({'error': str(exc)}), 503


@bp.route('/api/nq/reflection/geometry')
def api_nq_reflection_geometry():
    """Nur die Netzgrenz-Geometrie (Standort, Randpolygon, Grenzdistanzen) —
    schnelles Kartenrendern ohne Signalauswertung."""
    from nq.analysis import nq_reflection as refl
    try:
        return jsonify(refl.geometry())
    except Exception as exc:
        logging.exception("nq/reflection/geometry failed")
        return jsonify({'error': str(exc)}), 503


# ---------------------------------------------------------------------------
# NQ2 WP4: Event-Schnipsel-Drill-down (200-ms-RAW-Serie je Event)
# ---------------------------------------------------------------------------

@bp.route('/api/nq/event/<int:event_id>')
def api_nq_event(event_id):
    """RAW-Schnipsel (Wide-Format) eines Events. ?month=YYYY-MM engt die DB ein."""
    month = request.args.get('month')
    if month:
        candidates = [_nq_primary_db(month)]
    else:
        candidates = sorted(glob(os.path.join(_NQ_PRIMARY_DIR, 'nq_*.db')), reverse=True)[:6]

    for db_path in candidates:
        conn = _open_legacy(db_path)
        if not conn:
            continue
        try:
            ev = conn.execute(
                "SELECT event_id, ts_start, ts_end, duration_s, band, kind, trigger, "
                "severity, peak_quantity, peak_value, origin, has_snippet "
                "FROM nq_events WHERE event_id = ?", (event_id,)).fetchone()
            if not ev:
                continue
            fast = conn.execute(
                "SELECT ts_ms, u_l1, u_l2, u_l3, u_l12, u_l23, u_l31, "
                "i_l1, i_l2, i_l3, p_tot, q_tot, s_tot, pf, f "
                "FROM nq_event_fast WHERE event_id = ? ORDER BY ts_ms", (event_id,)).fetchall()
            med = conn.execute(
                "SELECT ts, thd_u_l1, thd_u_l2, thd_u_l3, thd_i_l1, thd_i_l2, thd_i_l3 "
                "FROM nq_event_medium WHERE event_id = ? ORDER BY ts", (event_id,)).fetchall()
        except Exception:
            conn.close()
            continue
        conn.close()

        fcols = ['ts_ms', 'u_l1', 'u_l2', 'u_l3', 'u_l12', 'u_l23', 'u_l31',
                 'i_l1', 'i_l2', 'i_l3', 'p_tot', 'q_tot', 's_tot', 'pf', 'f']
        mcols = ['ts', 'thd_u_l1', 'thd_u_l2', 'thd_u_l3', 'thd_i_l1', 'thd_i_l2', 'thd_i_l3']
        return jsonify({
            'event': {
                'event_id': ev[0], 'ts_start': ev[1], 'ts_end': ev[2],
                'duration_s': ev[3], 'band': ev[4], 'kind': ev[5], 'trigger': ev[6],
                'severity': ev[7], 'peak_quantity': ev[8], 'peak_value': ev[9],
                'origin': ev[10], 'has_snippet': ev[11],
            },
            'fast': [dict(zip(fcols, r)) for r in fast],
            'medium': [dict(zip(mcols, r)) for r in med],
            'count': len(fast),
        })
    return jsonify({'error': 'event not found', 'event_id': event_id}), 404
