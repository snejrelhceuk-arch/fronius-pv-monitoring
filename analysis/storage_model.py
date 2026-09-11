"""
storage_model — Speicherausbau-Simulation (read-only Entscheidungsmodell).

Backtestet die historischen 5-Minuten-Energiedaten (data_5min_permanent) durch
ein *inkrementelles* Batteriemodell: ein virtueller Zusatzspeicher variabler
Groesse (plus optionaler PV-Zubau) laedt aus dem heute ungenutzten Ueberschuss
und deckt damit den gemessenen Netzbezug. Ergebnis: wie viel Netzbezug ein
groesserer Speicher zusaetzlich vermeidet und ob sich der Ausbau amortisiert.

Kernidee (robust, ohne Baseline-Kalibrierung):
  available_surplus_i = curtailed_i + W_Einspeis_i   (heute ungenutzter Ueberschuss)
  residual_deficit_i  = W_Bezug_i                     (heute aus dem Netz gedeckt)
  avoided(A) = Sigma der aus dem Zusatzspeicher gedeckten Defizite.
  avoided(0) = 0, monoton steigend, saettigend -> Optimum ueber Amortisationsgrenze.

Nulleinspeiser: ueberschuessige PV wird bei vollem Bestandsspeicher abgeregelt
(SOC-Deckel ~75 %). Diese Abregelung (curtailed_i) ist im Messwert W_Ertrag NICHT
enthalten und wird gegen eine selbstkalibrierte Clear-Sky-Prognose rekonstruiert
(alpha_day = realisierte/Clear-Sky-Erzeugung in nicht gedeckelten Tagesstunden).
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta

import numpy as np

import config

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(_REPO_ROOT, 'config', 'storage_expansion.json')
CLEARSKY_CACHE_DIR = os.path.join(_REPO_ROOT, 'tmp', 'clearsky_cache')

# Reconstructed-series memo (schwerer Teil: Clear-Sky + Rekonstruktion). Wird bei
# neuen Daten oder geaenderten Rekonstruktions-Parametern invalidiert.
_SERIES_CACHE: dict = {}
_SERIES_TTL_S = 3600


# ─────────────────────────────────────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    """Laedt config/storage_expansion.json (mit robusten Defaults)."""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception as exc:  # pragma: no cover - defensiv
        logger.warning("storage_expansion.json nicht lesbar (%s) - Defaults", exc)
        return {}


def default_price_eur_kwh(cfg: dict) -> float:
    """Aktueller Bezugspreis: bevorzugt config.get_strompreis(heute), sonst Fallback."""
    try:
        today = date.today()
        price = float(config.get_strompreis(today.year, today.month))
        if price > 0:
            return round(price, 4)
    except Exception:
        pass
    return float(cfg.get('wirtschaft', {}).get('strompreis_eur_kwh', 0.30))


# ─────────────────────────────────────────────────────────────────────────────
# Clear-Sky-Tagescache (deterministisch pro Datum, gitignored unter tmp/)
# ─────────────────────────────────────────────────────────────────────────────
def _clearsky_minute_map(day: date) -> dict[int, float] | None:
    """
    Liefert {minute_of_day: total_ac_W} der Clear-Sky-AC-Leistung fuer den Tag,
    5-Minuten-Raster. Disk-gecacht. None wenn solar_geometry nicht verfuegbar.
    """
    os.makedirs(CLEARSKY_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CLEARSKY_CACHE_DIR, f"{day.isoformat()}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            return {int(k): float(v) for k, v in raw.items()}
        except Exception:
            pass
    try:
        import solar_geometry as sg
    except Exception:
        return None
    try:
        curve = sg.get_clearsky_day_curve(day, interval_min=5)
    except Exception as exc:
        logger.debug("Clear-Sky %s fehlgeschlagen: %s", day, exc)
        return None
    minute_map: dict[int, float] = {}
    for point in curve:
        ts = point.get('timestamp')
        ac = point.get('total_ac', 0.0)
        if ts is None:
            continue
        lt = time.localtime(int(ts))
        minute_map[lt.tm_hour * 60 + lt.tm_min] = float(ac or 0.0)
    try:
        with open(cache_file, 'w', encoding='utf-8') as fh:
            json.dump(minute_map, fh)
    except Exception:
        pass
    return minute_map


# ─────────────────────────────────────────────────────────────────────────────
# Datenzugriff (read-only)
# ─────────────────────────────────────────────────────────────────────────────
def _open_ro():
    import sqlite3
    stats = getattr(config, 'STATS_DB_PATH', None)
    if stats and os.path.exists(stats):
        conn = sqlite3.connect(f"file:{stats}?mode=ro", uri=True, timeout=10.0)
        conn.execute("PRAGMA query_only=ON")
        return conn, 'data_5min_permanent'
    # Fallback: RAM-DB (nur juengste Retention, aber besser als nichts)
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=10.0)
    return conn, 'data_1min'


def _load_raw_series(start_ts: int, end_ts: int) -> dict:
    """Laedt die 5-min-Reihe (ts, soc, W_Ertrag, W_Verbrauch, W_Einspeis, W_Bezug)."""
    conn, table = _open_ro()
    try:
        rows = conn.execute(
            f"""SELECT ts, SOC_Batt_avg, W_Ertrag, W_Verbrauch, W_Einspeis, W_Bezug
                FROM {table}
                WHERE ts >= ? AND ts < ?
                  AND W_Ertrag IS NOT NULL AND W_Verbrauch IS NOT NULL
                ORDER BY ts""",
            (start_ts, end_ts),
        ).fetchall()
    finally:
        conn.close()
    n = len(rows)
    out = {
        'ts': np.empty(n, dtype=np.int64),
        'soc': np.zeros(n),
        'pv': np.zeros(n),
        'load': np.zeros(n),
        'exp': np.zeros(n),
        'imp': np.zeros(n),
    }
    for i, r in enumerate(rows):
        out['ts'][i] = r[0]
        out['soc'][i] = r[1] if r[1] is not None else 0.0
        out['pv'][i] = r[2] or 0.0
        out['load'][i] = r[3] or 0.0
        out['exp'][i] = r[4] or 0.0
        out['imp'][i] = r[5] or 0.0
    return out


def data_window() -> tuple[int, int, int]:
    """(start_ts, end_ts, n_days) der verfuegbaren 5-min-Permanentdaten."""
    conn, table = _open_ro()
    try:
        row = conn.execute(f"SELECT MIN(ts), MAX(ts) FROM {table}").fetchone()
    finally:
        conn.close()
    if not row or row[0] is None:
        now = int(time.time())
        return now - 86400, now, 1
    start_ts, end_ts = int(row[0]), int(row[1])
    n_days = max(1, round((end_ts - start_ts) / 86400))
    return start_ts, end_ts, n_days


def measured_annual_import_kwh() -> float:
    """Gemessener Netzbezug der letzten 12 Monate (monthly_statistics) fuer Annualisierung."""
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=10.0)
        try:
            row = conn.execute(
                """SELECT SUM(netz_bezug_kwh) FROM monthly_statistics
                   WHERE (year * 12 + month) >= (
                       SELECT MAX(year * 12 + month) - 11 FROM monthly_statistics)"""
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return float(row[0])
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Potenzial-Rekonstruktion (Abregelung via Clear-Sky) + Ueberschuss/Defizit
# ─────────────────────────────────────────────────────────────────────────────
def _reconstruct(start_ts: int, end_ts: int, soc_cap_pct: float,
                 pv_kwp: float, use_curtailment: bool) -> dict:
    """
    Baut die kapazitaets-unabhaengigen Reihen fuer die Dispatch-Simulation:
      available_surplus (Wh), residual_deficit (Wh), curtailed (Wh),
      clearsky_norm (Wh je kWp, fuer PV-Zubau), alpha_day, ts.
    """
    raw = _load_raw_series(start_ts, end_ts)
    n = len(raw['ts'])
    if n == 0:
        return {'n': 0}

    ts = raw['ts']
    dt_h = np.full(n, 5.0 / 60.0)
    if n > 1:
        diffs = np.diff(ts) / 3600.0
        dt_h[1:] = np.clip(diffs, 1.0 / 60.0, 1.0)  # Luecken kappen

    # Clear-Sky-AC (W) je Intervall aus dem Tages-Minutenraster.
    cs_w = np.zeros(n)
    have_cs = False
    day_index = np.empty(n, dtype=np.int64)
    minute_maps: dict[str, dict] = {}
    day0 = None
    for i in range(n):
        lt = time.localtime(int(ts[i]))
        dkey = f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"
        if dkey not in minute_maps:
            minute_maps[dkey] = _clearsky_minute_map(date(lt.tm_year, lt.tm_mon, lt.tm_mday)) or {}
        mm = minute_maps[dkey]
        if mm:
            have_cs = True
            mod = lt.tm_hour * 60 + lt.tm_min
            cs_w[i] = mm.get(mod, mm.get(mod - mod % 5, 0.0))
        d_ord = datetime(lt.tm_year, lt.tm_mon, lt.tm_mday).toordinal()
        if day0 is None:
            day0 = d_ord
        day_index[i] = d_ord - day0

    cs_wh = cs_w * dt_h                     # Clear-Sky-Energie je Intervall (Wh, ganze Anlage)
    cs_norm_wh = cs_wh / max(pv_kwp, 1e-6)  # je kWp (fuer PV-Zubau)

    # Tages-Kalibrierung alpha_day = realisierte / Clear-Sky-Erzeugung in
    # nicht-gedeckelten Tagesstunden (soc < cap, Clear-Sky > Schwelle).
    n_days = int(day_index.max()) + 1 if n else 0
    cs_thresh_w = 300.0
    free = (cs_w > cs_thresh_w) & (raw['soc'] < soc_cap_pct)
    sum_pv = np.bincount(day_index, weights=raw['pv'] * free, minlength=n_days)
    sum_cs = np.bincount(day_index, weights=cs_wh * free, minlength=n_days)
    alpha_day = np.divide(sum_pv, sum_cs, out=np.zeros(n_days), where=sum_cs > 500.0)
    valid = alpha_day[(alpha_day > 0.05) & (alpha_day < 1.2)]
    alpha_global = float(np.median(valid)) if valid.size else 0.0
    alpha_day[(alpha_day <= 0.05) | (alpha_day >= 1.2)] = alpha_global
    alpha_per_row = alpha_day[day_index]

    # Abregelung: nur wenn Bestandsspeicher gedeckelt (soc >= cap) und Tag.
    curtailed = np.zeros(n)
    if use_curtailment and have_cs and alpha_global > 0:
        capped = (raw['soc'] >= soc_cap_pct) & (cs_w > cs_thresh_w)
        potential = cs_wh * alpha_per_row
        curtailed = np.where(capped, np.maximum(potential - raw['pv'], 0.0), 0.0)

    available_surplus = curtailed + raw['exp']
    residual_deficit = raw['imp'].copy()

    return {
        'n': n,
        'ts': ts,
        'day_index': day_index,
        'n_days': n_days,
        'dt_h': dt_h,
        'available_surplus': available_surplus,
        'residual_deficit': residual_deficit,
        'curtailed': curtailed,
        'exp': raw['exp'],
        'cs_norm_wh': cs_norm_wh,
        'alpha_per_row': alpha_per_row,
        'have_clearsky': have_cs,
        'load_total_wh': float(raw['load'].sum()),
        'pv_total_wh': float(raw['pv'].sum()),
    }


def get_series(soc_cap_pct: float, pv_kwp: float, use_curtailment: bool) -> dict:
    """Gecachte Rekonstruktion ueber das volle verfuegbare Datenfenster."""
    start_ts, end_ts, n_days = data_window()
    key = (start_ts, end_ts, round(soc_cap_pct, 1), round(pv_kwp, 2), bool(use_curtailment))
    hit = _SERIES_CACHE.get(key)
    if hit and (time.time() - hit['_built']) < _SERIES_TTL_S:
        return hit
    series = _reconstruct(start_ts, end_ts, soc_cap_pct, pv_kwp, use_curtailment)
    series['_built'] = time.time()
    series['window'] = (start_ts, end_ts, n_days)
    _SERIES_CACHE[key] = series
    return series


# ─────────────────────────────────────────────────────────────────────────────
# Inkrementeller Batterie-Dispatch (vektorisiert ueber Kapazitaeten)
# ─────────────────────────────────────────────────────────────────────────────
def _dispatch(surplus_wh: np.ndarray, deficit_wh: np.ndarray, dt_h: np.ndarray,
              caps_usable_wh: np.ndarray, rt_eff: float,
              p_charge_w: float, p_discharge_w: float) -> dict:
    """
    Simuliert je Kapazitaet K einen Zusatzspeicher. Rueckgabe: avoided_wh[K],
    discharge_wh[K] (== avoided_wh), throughput fuer Zyklen.
    """
    K = caps_usable_wh.size
    n = surplus_wh.size
    soc = np.zeros(K)
    avoided = np.zeros(K)
    eta = math.sqrt(max(rt_eff, 1e-6))
    caps = caps_usable_wh
    for i in range(n):
        s = surplus_wh[i]
        if s > 0.0:
            room = caps - soc
            max_in = p_charge_w * dt_h[i] * eta
            stored = np.minimum(np.minimum(s * eta, room), max_in)
            soc += stored
        d = deficit_wh[i]
        if d > 0.0:
            max_out = p_discharge_w * dt_h[i] * eta
            avail = np.minimum(soc * eta, max_out)
            supplied = np.minimum(d, avail)
            soc -= supplied / eta
            avoided += supplied
    return {'avoided_wh': avoided, 'discharge_wh': avoided}


# ─────────────────────────────────────────────────────────────────────────────
# Oeffentliche Analyse-Entrypoints
# ─────────────────────────────────────────────────────────────────────────────
def _tech(cfg: dict) -> dict:
    t = cfg.get('technik', {})
    return {
        'usable_fraction': float(t.get('usable_fraction', 0.90)),
        'rt_efficiency': float(t.get('rt_efficiency', 0.90)),
        'soc_cap_detect_pct': float(t.get('soc_cap_detect_pct', 73)),
        'max_zubau_batt_kwh': float(t.get('max_zubau_batt_kwh', 55)),
        'max_zubau_pv_kwp': float(t.get('max_zubau_pv_kwp', 20)),
        'kalender_jahre': float(t.get('batt_kalender_jahre', 15)),
        'zyklen_lebensdauer': float(t.get('batt_zyklen_lebensdauer', 6000)),
        'wr_leistung_kw': float(t.get('wr_leistung_kw', 50)),
        'mppt_frei': int(t.get('mppt_frei', 4)),
    }


def run_sweep(add_pv_kwp: float = 0.0, use_curtailment: bool = True,
              steps: int = 46) -> dict:
    """
    Hauptanalyse: Kapazitaets-Sweep (nominal 0..max) fuer gegebenen PV-Zubau.
    Liefert Kurven (vermiedener Netzbezug, Autarkie, Zyklen) + Wirtschaft +
    Optimum. Preis/Kosten werden im Frontend live variiert; hier Default-Wirtschaft.
    """
    cfg = load_config()
    tech = _tech(cfg)
    bestand = cfg.get('bestand', {})
    pv_kwp = float(bestand.get('pv_kwp', getattr(config, 'PV_KWP_TOTAL', 37.59)))

    series = get_series(tech['soc_cap_detect_pct'], pv_kwp, use_curtailment)
    if series.get('n', 0) == 0:
        return {'error': 'Keine Daten im Zeitfenster'}

    dt_h = series['dt_h']
    surplus = series['available_surplus'].copy()
    if add_pv_kwp > 0:
        surplus = surplus + series['cs_norm_wh'] * add_pv_kwp * series['alpha_per_row']
    deficit = series['residual_deficit']

    start_ts, end_ts, n_days = series['window']
    annual_factor = 365.0 / max(n_days, 1)

    # Kapazitaets-Gitter (nominal kWh) -> nutzbar Wh.
    max_batt = tech['max_zubau_batt_kwh']
    caps_nom = np.linspace(0.0, max_batt, steps)
    caps_usable_wh = caps_nom * tech['usable_fraction'] * 1000.0

    p_charge_w = tech['wr_leistung_kw'] * 1000.0
    disp = _dispatch(surplus, deficit, dt_h, caps_usable_wh,
                     tech['rt_efficiency'], p_charge_w, p_charge_w)

    avoided_kwh_win = disp['avoided_wh'] / 1000.0
    avoided_kwh_year = avoided_kwh_win * annual_factor
    discharge_kwh_year = disp['discharge_wh'] / 1000.0 * annual_factor

    # Kennzahlen
    total_load_kwh_year = series['load_total_wh'] / 1000.0 * annual_factor
    measured_import_win = float(deficit.sum()) / 1000.0
    measured_import_year = measured_import_win * annual_factor
    curtailed_kwh_year = float(series['curtailed'].sum()) / 1000.0 * annual_factor
    export_kwh_year = float(series['exp'].sum()) / 1000.0 * annual_factor
    surplus_kwh_year = float(surplus.sum()) / 1000.0 * annual_factor

    # Autarkie-Basis: heutiger Bezug / Verbrauch.
    base_import = measured_import_year
    autarky_base = (1.0 - base_import / total_load_kwh_year) * 100.0 if total_load_kwh_year else 0.0

    caps_usable_kwh = caps_usable_wh / 1000.0
    # Vollzyklen/Jahr des Zusatzspeichers (0 bei Kapazitaet 0).
    with np.errstate(divide='ignore', invalid='ignore'):
        cycles_year = np.where(caps_usable_kwh > 0.01,
                               discharge_kwh_year / np.maximum(caps_usable_kwh, 1e-6), 0.0)

    curve = []
    for i in range(steps):
        rest_import = max(base_import - avoided_kwh_year[i], 0.0)
        autarky = (1.0 - rest_import / total_load_kwh_year) * 100.0 if total_load_kwh_year else 0.0
        curve.append({
            'batt_nom_kwh': round(float(caps_nom[i]), 2),
            'batt_usable_kwh': round(float(caps_usable_kwh[i]), 2),
            'avoided_kwh_year': round(float(avoided_kwh_year[i]), 1),
            'rest_import_kwh_year': round(rest_import, 1),
            'autarky_pct': round(autarky, 1),
            'cycles_year': round(float(cycles_year[i]), 1),
        })

    return {
        'ok': True,
        'add_pv_kwp': add_pv_kwp,
        'use_curtailment': use_curtailment,
        'period': {
            'start': datetime.fromtimestamp(start_ts).strftime('%Y-%m-%d'),
            'end': datetime.fromtimestamp(end_ts).strftime('%Y-%m-%d'),
            'days': n_days,
            'annual_factor': round(annual_factor, 3),
            'have_clearsky': bool(series['have_clearsky']),
        },
        'baseline': {
            'import_kwh_year': round(base_import, 0),
            'load_kwh_year': round(total_load_kwh_year, 0),
            'autarky_pct': round(autarky_base, 1),
            'curtailed_kwh_year': round(curtailed_kwh_year, 0),
            'export_kwh_year': round(export_kwh_year, 0),
            'surplus_kwh_year': round(surplus_kwh_year, 0),
            'pv_kwp': pv_kwp,
            'batt_bestand_kwh': float(bestand.get('batt_kwh_nominal', getattr(config, 'PV_BATTERY_KWH', 20.48))),
        },
        'tech': tech,
        'econ_defaults': {
            'strompreis_eur_kwh': default_price_eur_kwh(cfg),
            'einspeiseverguetung_eur_kwh': float(cfg.get('wirtschaft', {}).get('einspeiseverguetung_eur_kwh', 0.0)),
            'strompreis_steigerung_pct_a': float(cfg.get('wirtschaft', {}).get('strompreis_steigerung_pct_a', 3.0)),
            'payback_grenze_jahre': float(cfg.get('wirtschaft', {}).get('payback_grenze_jahre', 10.0)),
            'wr_fix_eur': float(cfg.get('kosten', {}).get('wr_fix_eur', 4000)),
            'batt_eur_pro_kwh_nominal': float(cfg.get('kosten', {}).get('batt_eur_pro_kwh_nominal', 160)),
            'pv_eur_pro_kwp': float(cfg.get('kosten', {}).get('pv_eur_pro_kwp', 250)),
        },
        'presets': cfg.get('presets', []),
        'curve': curve,
    }


def run_detail(add_pv_kwp: float, batt_nom_kwh: float,
               use_curtailment: bool = True) -> dict:
    """Monatsaufschluesselung + Kennzahlen fuer *ein* Szenario (Slider-Release)."""
    cfg = load_config()
    tech = _tech(cfg)
    pv_kwp = float(cfg.get('bestand', {}).get('pv_kwp', getattr(config, 'PV_KWP_TOTAL', 37.59)))
    series = get_series(tech['soc_cap_detect_pct'], pv_kwp, use_curtailment)
    if series.get('n', 0) == 0:
        return {'error': 'Keine Daten'}

    dt_h = series['dt_h']
    surplus = series['available_surplus'].copy()
    if add_pv_kwp > 0:
        surplus = surplus + series['cs_norm_wh'] * add_pv_kwp * series['alpha_per_row']
    deficit = series['residual_deficit']
    ts = series['ts']

    cap_usable_wh = np.array([batt_nom_kwh * tech['usable_fraction'] * 1000.0])
    # Zeitaufgeloester Einzel-Dispatch fuer die Monatszuordnung.
    soc = 0.0
    eta = math.sqrt(max(tech['rt_efficiency'], 1e-6))
    cap = float(cap_usable_wh[0])
    p_w = tech['wr_leistung_kw'] * 1000.0
    months: dict[str, dict] = {}
    for i in range(series['n']):
        s = surplus[i]
        if s > 0.0 and cap > 0.0:
            stored = min(min(s * eta, cap - soc), p_w * dt_h[i] * eta)
            soc += stored
        avoided_i = 0.0
        d = deficit[i]
        if d > 0.0 and soc > 0.0:
            avail = min(soc * eta, p_w * dt_h[i] * eta)
            supplied = min(d, avail)
            soc -= supplied / eta
            avoided_i = supplied
        lt = time.localtime(int(ts[i]))
        mkey = f"{lt.tm_year:04d}-{lt.tm_mon:02d}"
        m = months.setdefault(mkey, {'import': 0.0, 'avoided': 0.0, 'curtailed': 0.0})
        m['import'] += deficit[i]
        m['avoided'] += avoided_i
        m['curtailed'] += series['curtailed'][i]

    monthly = []
    for mkey in sorted(months):
        m = months[mkey]
        monthly.append({
            'month': mkey,
            'import_kwh': round(m['import'] / 1000.0, 1),
            'avoided_kwh': round(m['avoided'] / 1000.0, 1),
            'rest_kwh': round(max(m['import'] - m['avoided'], 0.0) / 1000.0, 1),
            'curtailed_kwh': round(m['curtailed'] / 1000.0, 1),
        })

    _, _, n_days = series['window']
    annual_factor = 365.0 / max(n_days, 1)
    avoided_year = sum(x['avoided_kwh'] for x in monthly) * annual_factor
    cap_usable_kwh = batt_nom_kwh * tech['usable_fraction']
    cycles_year = (avoided_year / cap_usable_kwh) if cap_usable_kwh > 0.01 else 0.0
    return {
        'ok': True,
        'batt_nom_kwh': batt_nom_kwh,
        'add_pv_kwp': add_pv_kwp,
        'avoided_kwh_year': round(avoided_year, 1),
        'cycles_year': round(cycles_year, 1),
        'monthly': monthly,
    }
