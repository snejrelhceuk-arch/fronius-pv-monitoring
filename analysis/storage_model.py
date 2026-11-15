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


# Anlagen-Fertigstellung / aktuelle Haushalts-Aera (3 E-Autos). Mittelwerte vor
# diesem Monat sind NICHT repraesentativ (Lastprofil hat sich 2024/2025 geaendert)
# und werden fuer die Baseline bewusst ausgeschlossen.
ERA_START_YEAR = 2025
ERA_START_MONTH = 10


def _open_analysis_ro():
    """Read-only Verbindung zur permanenten Tages/Monats-DB (analysis.db, Fallback RAM-DB)."""
    import sqlite3
    path = getattr(config, 'ANALYSIS_DB_PATH', None)
    if not path or not os.path.exists(path):
        path = getattr(config, 'DB_PATH', None)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    try:
        conn.execute("PRAGMA query_only=ON")
    except Exception:
        pass
    return conn


def measured_profile() -> dict:
    """
    Gemessener Netzbezug/Verbrauch je Kalendermonat aus den letzten <=12
    *vollstaendigen* Monaten seit Anlagen-Fertigstellung (>= ERA_START). Der
    laufende (unvollstaendige) Monat wird ausgelassen; Jahre vor der aktuellen
    Haushalts-Aera (zusaetzliche E-Autos) bleiben bewusst aussen vor.

    Rueckgabe:
      import_by_month : {1..12: kWh}   (je Kalendermonat, aus dem juengsten Jahr)
      load_by_month   : {1..12: kWh}
      import_kwh_year : Summe Netzbezug  (annualer Baseline-Bezug)
      load_kwh_year   : Summe Verbrauch
      source          : {1..12: year}
      months          : Zahl einbezogener Monate (<=12)
    """
    today = date.today()
    cur_key = today.year * 12 + today.month
    min_key = ERA_START_YEAR * 12 + ERA_START_MONTH
    rows = []
    try:
        conn = _open_analysis_ro()
        try:
            rows = conn.execute(
                """SELECT year, month, netz_bezug_kwh, gesamt_verbrauch_kwh
                   FROM monthly_statistics
                   WHERE (year * 12 + month) >= ? AND netz_bezug_kwh IS NOT NULL
                   ORDER BY year, month""",
                (min_key,),
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - defensiv
        logger.warning("measured_profile: monthly_statistics nicht lesbar (%s)", exc)
    complete = [r for r in rows if (r[0] * 12 + r[1]) < cur_key][-12:]
    imp_by, load_by, source = {}, {}, {}
    for y, m, imp, load in complete:
        source[m] = y                       # juengeres Jahr ueberschreibt Kalendermonat
        imp_by[m] = float(imp or 0.0)
        load_by[m] = float(load or 0.0)
    return {
        'import_by_month': imp_by,
        'load_by_month': load_by,
        'import_kwh_year': round(sum(imp_by.values()), 1),
        'load_kwh_year': round(sum(load_by.values()), 1),
        'source': source,
        'months': len(complete),
    }


def autumn_comparison() -> dict:
    """
    Tag-genauer Gleichwochen-Vergleich Herbst 2025 vs. 2026 (Effekt der
    Speichererweiterung) aus den permanenten Tagesdaten (daily_data). Vergleicht
    nur Tage, die in beiden Jahren vorliegen (z. B. Nov 1..14), damit kein
    unvollstaendiger Monat das Bild verfaelscht.
    """
    def _window(conn, year, month, d0, d1):
        row = conn.execute(
            """SELECT COUNT(*),
                      SUM(W_Imp_Netz_total)/1000.0,
                      SUM(W_PV_total)/1000.0,
                      SUM(W_Consumption_total)/1000.0
               FROM daily_data
               WHERE strftime('%Y-%m', ts, 'unixepoch') = ?
                 AND CAST(strftime('%d', ts, 'unixepoch') AS INT) BETWEEN ? AND ?""",
            (f"{year:04d}-{month:02d}", d0, d1),
        ).fetchone()
        return row or (0, None, None, None)

    def _max_day(conn, year, month):
        row = conn.execute(
            """SELECT MAX(CAST(strftime('%d', ts, 'unixepoch') AS INT))
               FROM daily_data WHERE strftime('%Y-%m', ts, 'unixepoch') = ?""",
            (f"{year:04d}-{month:02d}",),
        ).fetchone()
        return int(row[0]) if row and row[0] else 0

    months = []
    try:
        conn = _open_analysis_ro()
        try:
            for month, label in ((10, 'Oktober'), (11, 'November')):
                d_old = _max_day(conn, ERA_START_YEAR, month)
                d_new = _max_day(conn, date.today().year, month)
                d_cmp = min(d_old, d_new)
                if d_cmp <= 0:
                    continue
                a = _window(conn, ERA_START_YEAR, month, 1, d_cmp)
                b = _window(conn, date.today().year, month, 1, d_cmp)
                if not a[1] and not b[1]:
                    continue
                months.append({
                    'month': month,
                    'label': label,
                    'days': d_cmp,
                    'year_old': ERA_START_YEAR,
                    'year_new': date.today().year,
                    'import_old_kwh': round(float(a[1] or 0.0), 1),
                    'import_new_kwh': round(float(b[1] or 0.0), 1),
                    'pv_old_kwh': round(float(a[2] or 0.0), 1),
                    'pv_new_kwh': round(float(b[2] or 0.0), 1),
                    'load_old_kwh': round(float(a[3] or 0.0), 1),
                    'load_new_kwh': round(float(b[3] or 0.0), 1),
                    'import_delta_kwh': round(float((b[1] or 0.0) - (a[1] or 0.0)), 1),
                })
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - defensiv
        logger.warning("autumn_comparison fehlgeschlagen: %s", exc)
    return {'ok': bool(months), 'months': months}


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
    cal_month = np.empty(n, dtype=np.int64)   # Kalendermonat 0..11 (saisonale Annualisierung)
    minute_maps: dict[str, dict] = {}
    day0 = None
    for i in range(n):
        lt = time.localtime(int(ts[i]))
        cal_month[i] = lt.tm_mon - 1
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
        'cal_month': cal_month,
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
              p_charge_w: float, p_discharge_w: float,
              month_of_row: np.ndarray | None = None) -> dict:
    """
    Simuliert je Kapazitaet K einen Zusatzspeicher. Rueckgabe: avoided_wh[K],
    discharge_wh[K] (== avoided_wh), throughput fuer Zyklen. Mit month_of_row
    zusaetzlich avoided_by_month[K, 12] (Kalendermonat) fuer die saisonale
    Annualisierung.
    """
    K = caps_usable_wh.size
    n = surplus_wh.size
    soc = np.zeros(K)
    avoided = np.zeros(K)
    by_month = np.zeros((K, 12)) if month_of_row is not None else None
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
            if by_month is not None:
                by_month[:, int(month_of_row[i])] += supplied
    return {'avoided_wh': avoided, 'discharge_wh': avoided, 'avoided_by_month': by_month}


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


def _month_geometry(series: dict, source: dict | None = None):
    """
    Pro-Kalendermonat-Geometrie des Datenfensters:
      present_days[12] : im Fenster real vorhandene Tage (fraktional, aus dt_h)
      full_days[12]    : Tage des vollen Kalendermonats
      present_mask[12] : True wenn der Monat ausreichend belegt ist (>=3 Tage)
    """
    import calendar as _calendar
    cal = series['cal_month']
    dt_h = series['dt_h']
    present_days = np.array([float(dt_h[cal == m].sum()) / 24.0 for m in range(12)])
    year_for = source or {}
    full_days = np.array([
        _calendar.monthrange(int(year_for.get(m + 1, date.today().year)), m + 1)[1]
        for m in range(12)
    ], dtype=float)
    return present_days, full_days, present_days >= 3.0


def _month_sum(values: np.ndarray, cal_month: np.ndarray) -> np.ndarray:
    """Summe einer Zeilenreihe je Kalendermonat -> (1,12)."""
    out = np.zeros((1, 12))
    for m in range(12):
        out[0, m] = float(values[cal_month == m].sum())
    return out


def _annualize_by_month(by_month_wh: np.ndarray, present_days: np.ndarray,
                        full_days: np.ndarray, present_mask: np.ndarray,
                        cap_wh: np.ndarray | None = None) -> np.ndarray:
    """
    Saisonale Annualisierung simulierter Monatswerte (K,12):
      - belegte Monate -> x full_days/present_days (Teilmonat auf Vollmonat)
      - fehlende Monate (z. B. Dezember, keine 5-min-Daten) -> aus den belegten
        Kalendernachbarn geschaetzt
      - optionale Deckelung je Monat (cap_wh[12], z. B. gemessener Netzbezug:
        es laesst sich nie mehr Bezug vermeiden als tatsaechlich bezogen wurde)
    Rueckgabe: annual_wh[K].
    """
    bm = np.atleast_2d(by_month_wh).astype(float)
    norm = np.where(present_mask, full_days / np.maximum(present_days, 1e-6), 0.0)
    val = bm * norm
    for m in range(12):
        if present_mask[m]:
            continue
        neigh = [k for k in ((m - 1) % 12, (m + 1) % 12) if present_mask[k]]
        if not neigh:
            neigh = [k for k in range(12) if present_mask[k]]
        if neigh:
            val[:, m] = val[:, neigh].mean(axis=1)
    if cap_wh is not None:
        cap = np.asarray(cap_wh, dtype=float)
        has_cap = cap > 0
        val = np.where(has_cap[None, :], np.minimum(val, cap[None, :]), val)
    return val.sum(axis=1)


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
    cal_month = series['cal_month']

    # Kapazitaets-Gitter in ganzen kWh (nominal) -> saubere X-Achse im Chart.
    max_batt = tech['max_zubau_batt_kwh']
    caps_nom = np.arange(0.0, max_batt + 1e-6, 1.0)
    if caps_nom.size == 0 or caps_nom[-1] < max_batt - 1e-6:
        caps_nom = np.append(caps_nom, max_batt)
    steps = caps_nom.size
    caps_usable_wh = caps_nom * tech['usable_fraction'] * 1000.0

    p_charge_w = tech['wr_leistung_kw'] * 1000.0
    disp = _dispatch(surplus, deficit, dt_h, caps_usable_wh,
                     tech['rt_efficiency'], p_charge_w, p_charge_w,
                     month_of_row=cal_month)

    # Gemessenes Baseline-Profil der aktuellen Haushalts-Aera (seit Okt 2025;
    # inkl. Dezember). Grundet Netzbezug/Verbrauch auf Messwerte statt auf eine
    # lineare x365/Tage-Hochrechnung des dezember-losen 5-min-Fensters.
    prof = measured_profile()
    present_days, full_days, present_mask = _month_geometry(series, prof.get('source'))
    imp_cap_wh = np.zeros(12)
    for m, kwh in prof.get('import_by_month', {}).items():
        imp_cap_wh[m - 1] = kwh * 1000.0
    have_measured = prof.get('months', 0) >= 6 and prof.get('import_kwh_year', 0) > 0

    if have_measured:
        # Vermiedener Bezug saisonal annualisiert + je Monat auf den gemessenen
        # Bezug gedeckelt; Baseline = gemessene Jahressumme.
        avoided_kwh_year = _annualize_by_month(
            disp['avoided_by_month'], present_days, full_days, present_mask,
            cap_wh=imp_cap_wh) / 1000.0
        base_import = float(prof['import_kwh_year'])
        total_load_kwh_year = float(prof['load_kwh_year'])
        baseline_source = 'measured'
    else:
        avoided_kwh_year = disp['avoided_wh'] / 1000.0 * annual_factor
        base_import = float(deficit.sum()) / 1000.0 * annual_factor
        total_load_kwh_year = series['load_total_wh'] / 1000.0 * annual_factor
        baseline_source = 'projected'

    discharge_kwh_year = avoided_kwh_year
    # Potenzial-Groessen saisonal annualisieren (Teilmonate/Dezember korrekt).
    curtailed_kwh_year = float(_annualize_by_month(
        _month_sum(series['curtailed'], cal_month),
        present_days, full_days, present_mask)[0]) / 1000.0
    export_kwh_year = float(_annualize_by_month(
        _month_sum(series['exp'], cal_month),
        present_days, full_days, present_mask)[0]) / 1000.0
    surplus_kwh_year = float(_annualize_by_month(
        _month_sum(surplus, cal_month),
        present_days, full_days, present_mask)[0]) / 1000.0

    # Autarkie-Basis: Bezug / Verbrauch.
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
            'baseline_source': baseline_source,
            'measured_months': int(prof.get('months', 0)),
        },
        'baseline': {
            'import_kwh_year': round(base_import, 0),
            'load_kwh_year': round(total_load_kwh_year, 0),
            'autarky_pct': round(autarky_base, 1),
            'curtailed_kwh_year': round(curtailed_kwh_year, 0),
            'export_kwh_year': round(export_kwh_year, 0),
            'surplus_kwh_year': round(surplus_kwh_year, 0),
            'pv_kwp': pv_kwp,
            'batt_bestand_kwh': float(bestand.get('batt_kwh_nominal', getattr(config, 'PV_BATTERY_KWH', 25.6))),
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
        'autumn': autumn_comparison(),
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
    cal_month = series['cal_month']
    surplus = series['available_surplus'].copy()
    if add_pv_kwp > 0:
        surplus = surplus + series['cs_norm_wh'] * add_pv_kwp * series['alpha_per_row']
    deficit = series['residual_deficit']

    cap = batt_nom_kwh * tech['usable_fraction'] * 1000.0
    eta = math.sqrt(max(tech['rt_efficiency'], 1e-6))
    p_w = tech['wr_leistung_kw'] * 1000.0
    # Zeitaufgeloester Einzel-Dispatch, Zuordnung je Kalendermonat (0..11).
    avoided_m = np.zeros(12)
    curtailed_m = np.zeros(12)
    soc = 0.0
    for i in range(series['n']):
        mo = int(cal_month[i])
        s = surplus[i]
        if s > 0.0 and cap > 0.0:
            soc += min(min(s * eta, cap - soc), p_w * dt_h[i] * eta)
        d = deficit[i]
        if d > 0.0 and soc > 0.0:
            supplied = min(d, min(soc * eta, p_w * dt_h[i] * eta))
            soc -= supplied / eta
            avoided_m[mo] += supplied
        curtailed_m[mo] += series['curtailed'][i]

    # Gemessenes Baseline-Profil (aktuelle Haushalts-Aera, inkl. Dezember) als
    # Netzbezug je Kalendermonat; simulierter vermiedener Bezug wird saisonal auf
    # den Vollmonat normalisiert (Teilmonate wie Nov) und je Monat gedeckelt.
    prof = measured_profile()
    present_days, full_days, present_mask = _month_geometry(series, prof.get('source'))
    imp_by = prof.get('import_by_month', {})
    imp_cap_wh = np.zeros(12)
    for m, kwh in imp_by.items():
        imp_cap_wh[m - 1] = kwh * 1000.0
    have_measured = prof.get('months', 0) >= 6 and imp_by

    avoided_norm = _annualize_by_month(avoided_m, present_days, full_days,
                                       present_mask, cap_wh=imp_cap_wh if have_measured else None)
    # Einzelmonate (ungesummt) fuer den Chart.
    norm = np.where(present_mask, full_days / np.maximum(present_days, 1e-6), 0.0)
    av_month = avoided_m * norm
    curt_month = curtailed_m * norm
    for m in range(12):          # fehlende Monate (Dezember) aus Nachbarn
        if present_mask[m]:
            continue
        neigh = [k for k in ((m - 1) % 12, (m + 1) % 12) if present_mask[k]] or \
                [k for k in range(12) if present_mask[k]]
        if neigh:
            av_month[m] = float(np.mean([av_month[k] for k in neigh]))
            curt_month[m] = float(np.mean([curt_month[k] for k in neigh]))
    if have_measured:
        av_month = np.minimum(av_month, imp_cap_wh)

    _MON = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
            'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
    source = prof.get('source', {})
    monthly = []
    month_order = sorted(imp_by) if have_measured else sorted(set(int(x) + 1 for x in cal_month))
    for m in month_order:
        idx = m - 1
        imp_kwh = (imp_cap_wh[idx] / 1000.0) if have_measured else \
            float(_month_sum(deficit, cal_month)[0, idx] * norm[idx]) / 1000.0
        av_kwh = av_month[idx] / 1000.0
        yr = source.get(m)
        monthly.append({
            'month': f"{_MON[idx]}{(' ' + str(yr)[2:]) if yr else ''}",
            'import_kwh': round(imp_kwh, 1),
            'avoided_kwh': round(av_kwh, 1),
            'rest_kwh': round(max(imp_kwh - av_kwh, 0.0), 1),
            'curtailed_kwh': round(curt_month[idx] / 1000.0, 1),
            'estimated': not bool(present_mask[idx]),
        })

    avoided_year = float(avoided_norm[0]) / 1000.0 if np.ndim(avoided_norm) else float(avoided_norm) / 1000.0
    cap_usable_kwh = batt_nom_kwh * tech['usable_fraction']
    cycles_year = (avoided_year / cap_usable_kwh) if cap_usable_kwh > 0.01 else 0.0
    return {
        'ok': True,
        'batt_nom_kwh': batt_nom_kwh,
        'add_pv_kwp': add_pv_kwp,
        'avoided_kwh_year': round(avoided_year, 1),
        'cycles_year': round(cycles_year, 1),
        'baseline_source': 'measured' if have_measured else 'projected',
        'monthly': monthly,
    }
