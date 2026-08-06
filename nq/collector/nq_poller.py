"""nq.collector.nq_poller — Dual-Rate-Poller für PAC4200 (Rolle N, Tech).

**NQ2-Tier-Benennung** (vereinheitlicht 2026-07-14):
- **fast** (200 ms, Main-Thread): Block A + Block B Skalare (U, I, P, Q, S,
  cos φ, THD, Unsymmetrie) via ``pac_live.read_fast_snapshot``.
- **medium** (1 s, Hintergrund-Thread): Harmonische (@9001/@11001/@22001) via
  ``pac_live.read_harm_snapshot`` **plus** die Netzfrequenz (real ~10 s
  Refresh, daher im 1-s-Tier statt redundant im 200-ms-Tier).
- **slow** (energy_s, eigener Dienst ``nq_energy``): kumulative Energiezähler.

**Fast-Loop schreibt:**
- ``nq_raw_fast``   — Block-A-Rohwerte (ts_ms PK, 200-ms-Raster)
- ``nq_raw_medium`` — Block-B-Rohwerte + Frequenz ``f`` (ts_ms PK)
- ``nq_5min``       — Skalare min/avg/max/std im 5-min-Raster (35 Größen)

**Medium-Loop schreibt:**
- ``nq_raw_slow``   — Harmonische RAW (ts, meas, phase, ord, value) bei 1 s
  meas: 'U_LN' | 'U_LL' | 'I', ord: 1,3,5,...,31

**Grenzwert-Monitor (WP1):** ``LimitMonitor`` wertet die Fast-Skalare gegen
``config/nq_config.json`` → ``grenzwerte`` aus; bei dauerhafter Überschreitung
(>``limit_window_s``) → Zeile in ``nq_limit_alerts`` + best-effort Sofort-Mail.

**Härtung (keine Interferenz):**
- Zwei getrennte Threads mit je eigenem DB-Handle — langsame Harm-Reads blockieren
  nie den 200-ms-Fast-Loop.
- Fast-Timeout 0.5 s: Bei PAC-Ausfall max. 0.5 s Blocking im Fast-Thread.
- Medium-Timeout 1.5 s: Harm-Reads können bei >1.5 s PAC-Latenz ausgelassen werden.

**RAM-Schätzung 12 h:** fast ~33 MB + medium ~38 MB + slow ~230 MB + agg ~8 MB = ~310 MB
→ weit unter tmpfs-Cap 1 200 MB.

Start (Tech):  python3 -m nq.collector.nq_poller
Doku: doc/netzqualitaet/NQ_MODUL.md §4/§5, doc/netzqualitaet/MESSTECHNIK.md.
"""
from __future__ import annotations

import argparse
import math
import signal
import threading
import time

from nq.nq_common import open_db, load_config, TECH_SCHEMA
from nq.pac_live import read_fast_snapshot, read_harm_snapshot, read_max_snapshot
from nq.collector.nq_capping import enforce_retention
# ---------------------------------------------------------------------------
# Skalare Charting-/Analyse-Größen → nq_5min (5-min-Bucket, meas=''/phase=0/ord=0)
# ---------------------------------------------------------------------------
AGG_QUANTITIES = [
    "U_L1N", "U_L2N", "U_L3N", "U_L12", "U_L23", "U_L31",
    "Is_L1", "Is_L2", "Is_L3", "I_N",
    "P_L1", "P_L2", "P_L3", "P_tot", "Q_tot", "S_tot",
    "PF_L1", "PF_L2", "PF_L3", "PF_tot",
    "cosphi_L1", "cosphi_L2", "cosphi_L3",
    "THDu_L1", "THDu_L2", "THDu_L3", "THDi_L1", "THDi_L2", "THDi_L3",
    "THDu_L12", "THDu_L23", "THDu_L31",
    "FREQ", "Unbal_U", "Unbal_I",
]

# ---------------------------------------------------------------------------
# Schreib-Seitige Plausibilität: finite-aber-absurde Modbus-Fehldekodierungen
# (z. B. 1e23, Register-Bleed FREQ=55.0 / U=419.197, FREQ=0.007) VOR dem
# Aggregieren verwerfen, damit nq_5min-min/max nicht korrumpiert werden.
# `_f32` filtert nur NaN/Inf; endliche Ausreißer passieren sonst ungeprüft.
# Korridore aus `config/nq_config.json:monitoring_filter.corridors` (dieselbe
# physikalische Quelle wie der Display-Filter), mit sicheren Defaults.
# ---------------------------------------------------------------------------
_PLAUSIBLE_DEFAULT = {
    "FREQ": (47.0, 53.0),
    "U_LN": (150.0, 300.0),
    "U_LL": (280.0, 520.0),
    "I":    (-3000.0, 3000.0),
    "P":    (-200000.0, 200000.0),
    "Q":    (-200000.0, 200000.0),
    "S":    (0.0, 250000.0),
    "THD":  (0.0, 100.0),
    "PF":   (-1.5, 1.5),
    "UNBAL": (0.0, 300.0),
}


def _quantity_class(q: str) -> str | None:
    qu = q.upper()
    if qu == "FREQ":
        return "FREQ"
    if qu.startswith("THD"):
        return "THD"
    if qu.startswith("UNBAL"):
        return "UNBAL"
    if qu.startswith("PF") or qu.startswith("COSPHI"):
        return "PF"
    if qu.startswith("U_"):
        return "U_LN" if qu.endswith("N") else "U_LL"
    if qu.startswith("I_") or qu.startswith("IS_"):
        return "I"
    if qu.startswith("P"):
        return "P"
    if qu.startswith("Q"):
        return "Q"
    if qu.startswith("S"):
        return "S"
    return None


def _build_plausible() -> dict[str, tuple]:
    corr: dict = {}
    try:
        corr = (load_config().get("monitoring_filter", {}) or {}).get("corridors", {}) or {}
    except Exception:
        corr = {}
    merged = dict(_PLAUSIBLE_DEFAULT)
    for k, v in corr.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                merged[k] = (float(v[0]), float(v[1]))
            except (TypeError, ValueError):
                pass
    out: dict[str, tuple] = {}
    for q in AGG_QUANTITIES:
        cls = _quantity_class(q)
        if cls and cls in merged:
            out[q] = merged[cls]
    return out


_PLAUSIBLE = _build_plausible()


def _is_plausible(q: str, v) -> bool:
    """True, wenn v endlich und im physikalischen Korridor von q liegt."""
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return False
    corr = _PLAUSIBLE.get(q)
    return not (corr and (v < corr[0] or v > corr[1]))


# ---------------------------------------------------------------------------
# Harmonische → nq_raw_slow (1-s-RAW, meas/phase/ord-Format)
# ---------------------------------------------------------------------------
_HARM_ORDERS_ALL = (1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31)
_HARM_PHASES: dict[str, tuple] = {
    'U_LN': (('L1N', 1), ('L2N', 2), ('L3N', 3)),
    'U_LL': (('L12', 1), ('L23', 2), ('L31', 3)),
    'I':    (('L1',  1), ('L2',  2), ('L3',  3)),
}
_HARM_PFX = {'U_LN': 'U', 'U_LL': 'U', 'I': 'I'}


def _harm_to_slow_rows(ts: int, vals: dict, event: int = 0) -> list:
    """Wandelt flat-key harm-Dict (z. B. 'H3_U_L1N': 0.38) in nq_raw_slow-Zeilen um."""
    rows = []
    for meas, phases in _HARM_PHASES.items():
        pfx = _HARM_PFX[meas]
        for ph_str, phase in phases:
            for ord_ in _HARM_ORDERS_ALL:
                v = vals.get(f"H{ord_}_{pfx}_{ph_str}")
                if v is None:
                    continue
                rows.append((ts, meas, phase, ord_, v, event))
    return rows


# ---------------------------------------------------------------------------
# Spalten-Maps für RAW-Tabellen (Block A → fast, Block B → medium)
# ---------------------------------------------------------------------------
_FAST_COLS = {
    "u_l1": "U_L1N", "u_l2": "U_L2N", "u_l3": "U_L3N",
    "u_l12": "U_L12", "u_l23": "U_L23", "u_l31": "U_L31",
    "i_l1": "Is_L1", "i_l2": "Is_L2", "i_l3": "Is_L3",
    "s_l1": "S_L1", "s_l2": "S_L2", "s_l3": "S_L3",
    "p_l1": "P_L1", "p_l2": "P_L2", "p_l3": "P_L3",
    "q_l1": "Q_L1", "q_l2": "Q_L2", "q_l3": "Q_L3",
    "p_tot": "P_tot", "q_tot": "Q_tot", "s_tot": "S_tot",
    "pf_l1": "PF_L1", "pf_l2": "PF_L2", "pf_l3": "PF_L3",
    "pf": "PF_tot",
    "uavg_ln": "Uavg_LN", "uavg_ll": "Uavg_LL", "isum": "Isum",
    "f": "FREQ",
}
_MED_COLS = {
    "cosphi_l1": "cosphi_L1", "cosphi_l2": "cosphi_L2", "cosphi_l3": "cosphi_L3",
    "ang_l1": "ang_L1", "ang_l2": "ang_L2", "ang_l3": "ang_L3",
    "thd_u_l1": "THDu_L1", "thd_u_l2": "THDu_L2", "thd_u_l3": "THDu_L3",
    "thd_u_l12": "THDu_L12", "thd_u_l23": "THDu_L23", "thd_u_l31": "THDu_L31",
    "thd_i_l1": "THDi_L1", "thd_i_l2": "THDi_L2", "thd_i_l3": "THDi_L3",
    "idist_l1": "Idist_L1", "idist_l2": "Idist_L2", "idist_l3": "Idist_L3",
    "i_n": "I_N",
    "unbal_u": "Unbal_U", "unbal_i": "Unbal_I",
    "f": "FREQ",
}

_STOP = False


def _handle_stop(_sig, _frm):
    global _STOP
    _STOP = True


# ---------------------------------------------------------------------------
# 5-min-Bucket: nur Skalare (Block A+B). Harmonische gehen direkt in nq_raw_slow.
# ---------------------------------------------------------------------------
class _Bucket:
    def __init__(self):
        self.acc: dict[str, list] = {}  # key -> [min, sum, max, n, sumsq]

    def add(self, vals: dict) -> None:
        for q in AGG_QUANTITIES:
            v = vals.get(q)
            if v is None:
                continue
            if not _is_plausible(q, v):
                continue  # Schreib-Seite: absurde Fehldekodierung verwerfen
            a = self.acc.get(q)
            if a is None:
                self.acc[q] = [v, v, v, 1, v * v]
            else:
                if v < a[0]:
                    a[0] = v
                a[1] += v
                if v > a[2]:
                    a[2] = v
                a[3] += 1
                a[4] += v * v

    def rows(self, ts_bucket: int) -> list:
        out = []
        for q, (vmin, vsum, vmax, n, sumsq) in self.acc.items():
            vavg = vsum / n
            vstd = (max(0.0, (sumsq / n) - (vavg * vavg))) ** 0.5 if n > 1 else 0.0
            out.append((ts_bucket, q, "", 0, 0, vmin, vavg, vmax, vstd, n))
        return out


def _detect_event(prev: dict, cur: dict, ef: dict) -> str | None:
    if not prev:
        return None
    du = ef.get("du_step_v", 3.0)
    df = ef.get("df_step_hz", 0.02)
    thd = ef.get("thd_u_pct", 5.0)
    di = ef.get("di_step_a", 5.0)
    for ph in ("U_L1N", "U_L2N", "U_L3N"):
        if prev.get(ph) is not None and cur.get(ph) is not None \
                and abs(cur[ph] - prev[ph]) >= du:
            return "du_step"
    if prev.get("FREQ") is not None and cur.get("FREQ") is not None \
            and abs(cur["FREQ"] - prev["FREQ"]) >= df:
        return "df_step"
    for q in ("THDu_L1", "THDu_L2", "THDu_L3"):
        if cur.get(q) is not None and cur[q] >= thd:
            return "thd_u"
    for q in ("Is_L1", "Is_L2", "Is_L3"):
        if prev.get(q) is not None and cur.get(q) is not None \
                and abs(cur[q] - prev[q]) >= di:
            return "di_step"
    return None


# ---------------------------------------------------------------------------
# Hintergrund-Thread (NQ2 Medium-Tier): Harmonische bei 1 s (vollständig
# entkoppelt vom Fast-Loop). Liest medium_ms (Fallback slow_ms für Kompat).
# ---------------------------------------------------------------------------
_MEDIUM_SQL = (
    "INSERT OR REPLACE INTO nq_raw_slow (ts,meas,phase,ord,value,event) "
    "VALUES (?,?,?,?,?,?)"
)
_MEDIUM_FLUSH = 1440   # ~10 Harm-Polls × 144 rows/Poll = 1440 Zeilen

# Max-Werte (Block C) → nq_raw_max, 300-s-Slow-Poll (DB-Spalte → PAC-Key)
_MAX_COLS = {
    "umax_l1n": "Umax_L1N", "umax_l2n": "Umax_L2N", "umax_l3n": "Umax_L3N",
    "umax_l12": "Umax_L12", "umax_l23": "Umax_L23", "umax_l31": "Umax_L31",
    "imax_l1": "Imax_L1", "imax_l2": "Imax_L2", "imax_l3": "Imax_L3",
    "pmax_l1": "Pmax_L1", "pmax_l2": "Pmax_L2", "pmax_l3": "Pmax_L3",
    "freqmax": "FREQmax",
    "smax_tot": "Smax_tot", "pmax_tot": "Pmax_tot", "qmax_tot": "Qmax_tot",
}
_MAX_SQL = ("INSERT OR REPLACE INTO nq_raw_max (ts,%s) VALUES (%s)"
            % (",".join(_MAX_COLS), ",".join(["?"] * (len(_MAX_COLS) + 1))))
_MAX_PERIOD_S = 300.0


def _medium_ms(cfg: dict) -> int:
    pol = cfg.get("polling", {})
    return int(pol.get("medium_ms", pol.get("slow_ms", 1000)))


def _medium_thread(db_path: str, cfg: dict, stop_event: threading.Event) -> None:
    """Liest Harmonische jede medium_s und schreibt in nq_raw_slow (eigene DB-Verbindung)."""
    conn = open_db(db_path, TECH_SCHEMA)
    medium_s = _medium_ms(cfg) / 1000.0
    last_harm = 0.0
    last_max = 0.0
    buf: list = []
    errs = polls = 0

    print(f"[nq_poller/medium] gestartet medium={medium_s*1000:.0f}ms → nq_raw_slow (Harmonik)")
    while not stop_event.wait(0.01):
        now = time.time()
        if now - last_harm >= medium_s:
            last_harm = now
            try:
                hsnap = read_harm_snapshot(timeout=1.5)
                if hsnap.get("ok"):
                    polls += 1
                    rows = _harm_to_slow_rows(int(now), hsnap["values"])
                    buf.extend(rows)
                else:
                    errs += 1
            except Exception as e:
                errs += 1
                print(f"[nq_poller/medium] Harm-Fehler: {e}")

        # Max-Werte (Block C) alle 300 s → nq_raw_max
        if now - last_max >= _MAX_PERIOD_S:
            last_max = now
            try:
                msnap = read_max_snapshot(timeout=1.5)
                if msnap.get("ok"):
                    mv = msnap["values"]
                    conn.execute(_MAX_SQL, [int(now)]
                                 + [mv.get(k) for k in _MAX_COLS.values()])
                    conn.commit()
            except Exception as e:
                print(f"[nq_poller/medium] Max-Fehler: {e}")

        if len(buf) >= _MEDIUM_FLUSH:
            try:
                conn.executemany(_MEDIUM_SQL, buf)
                conn.commit()
                buf.clear()
            except Exception as e:
                print(f"[nq_poller/medium] DB-Fehler: {e}")

    # Final-Flush
    if buf:
        try:
            conn.executemany(_MEDIUM_SQL, buf)
            conn.commit()
        except Exception:
            pass
    conn.close()
    print(f"[nq_poller/medium] Ende. polls={polls} errs={errs}")


# ---------------------------------------------------------------------------
# WP1: Software-Grenzwertüberwachung (LimitMonitor)
# Wertet die verifiziert gelesenen Fast-Skalare gegen config 'grenzwerte' aus.
# KEINE erfundenen PAC-Status-Register (No-Go). Auschöpfung = % der Spanne
# nominal→boundary; Alarm bei >=crit_pct dauerhaft (>limit_window_s).
# ---------------------------------------------------------------------------
def _limit_specs(gw: dict) -> list:
    """Baut Grenz-Spezifikationen (name, value_key, kind, nominal, boundary)."""
    if not gw:
        return []
    specs: list = []
    lo, hi = gw.get("u_ln_min_v"), gw.get("u_ln_max_v")
    if lo and hi:
        nom = (lo + hi) / 2.0
        for ph, key in (("l1", "U_L1N"), ("l2", "U_L2N"), ("l3", "U_L3N")):
            specs.append((f"u_ln_max_{ph}", key, "hi", nom, hi))
            specs.append((f"u_ln_min_{ph}", key, "lo", nom, lo))
    lo, hi = gw.get("u_ll_min_v"), gw.get("u_ll_max_v")
    if lo and hi:
        nom = (lo + hi) / 2.0
        for ph, key in (("l12", "U_L12"), ("l23", "U_L23"), ("l31", "U_L31")):
            specs.append((f"u_ll_max_{ph}", key, "hi", nom, hi))
            specs.append((f"u_ll_min_{ph}", key, "lo", nom, lo))
    i_max = gw.get("i_max_a")
    if i_max:
        for ph, key in (("l1", "I_L1"), ("l2", "I_L2"), ("l3", "I_L3")):
            specs.append((f"i_max_{ph}", key, "hi", 0.0, i_max))
    p_max = gw.get("p_max_w")
    if p_max:
        # Anschlussleistung (Betrag P_tot, Bezug wie Einspeisung) — Anschlussgröße.
        specs.append(("p_max_tot", "P_tot", "hi", 0.0, p_max))
    lo, hi = gw.get("freq_min_hz"), gw.get("freq_max_hz")
    if lo and hi:
        nom = (lo + hi) / 2.0
        specs.append(("freq_max", "FREQ", "hi", nom, hi))
        specs.append(("freq_min", "FREQ", "lo", nom, lo))
    thd_hi = gw.get("thd_u_max_pct")
    if thd_hi:
        for ph, key in (("l1", "THDu_L1"), ("l2", "THDu_L2"), ("l3", "THDu_L3")):
            specs.append((f"thd_u_max_{ph}", key, "hi", 0.0, thd_hi))
    return specs


def _pct_toward(value: float, kind: str, nominal: float, boundary: float):
    """Ausschöpfung in % der Spanne nominal→boundary (None wenn Spanne <=0)."""
    if kind == "hi":
        span = boundary - nominal
        return (value - nominal) / span * 100.0 if span > 0 else None
    span = nominal - boundary
    return (nominal - value) / span * 100.0 if span > 0 else None


def _evaluate_limits(vals: dict, specs: list, crit_pct: float) -> list:
    """Liste aktuell verletzter Grenzen (>=crit_pct)."""
    out = []
    for name, key, kind, nominal, boundary in specs:
        v = vals.get(key)
        if v is None:
            continue
        if kind == "hi" and nominal == 0.0:
            v = abs(v)
        pct = _pct_toward(v, kind, nominal, boundary)
        if pct is not None and pct >= crit_pct:
            out.append((name, key, float(v), float(boundary), float(pct)))
    return out


class LimitMonitor:
    """Zustandsmaschine: Alarm bei dauerhafter (>window_s) Grenzausschöpfung."""

    def __init__(self, cfg: dict):
        gw = cfg.get("grenzwerte", {})
        an = cfg.get("analysis", {})
        self.enabled = bool(an.get("limit_mail_enabled", True))
        self.window_s = float(an.get("limit_window_s", 10))
        self.cooldown_s = float(an.get("limit_mail_cooldown_s", 300))
        self.crit_pct = float(gw.get("warning_levels", {}).get("crit_pct", 90))
        self.specs = _limit_specs(gw)
        self._since: dict[str, float] = {}
        self._last_mail: dict[str, float] = {}

    def check(self, conn, vals: dict, ts: float) -> str | None:
        """Prüft Grenzen; mailt bei dauerhafter Ausschöpfung. Gibt den Namen einer
        NEU aktiv gewordenen Grenze zurück (für Event-Schnipsel-Markierung), sonst None."""
        if not self.specs:
            return None
        active = _evaluate_limits(vals, self.specs, self.crit_pct)
        active_names = {a[0] for a in active}
        for name in list(self._since):
            if name not in active_names:
                self._since.pop(name, None)
        newly = None
        for name, qty, value, threshold, pct in active:
            since = self._since.get(name)
            if since is None:
                self._since[name] = ts
                if newly is None:
                    newly = name  # neue Grenzausschöpfung -> Event-Schnipsel
            elif ts - since >= self.window_s:
                self._raise(conn, name, qty, value, threshold, pct, ts)
        return newly

    def _raise(self, conn, name, qty, value, threshold, pct, ts) -> None:
        if ts - self._last_mail.get(name, 0.0) < self.cooldown_s:
            return
        self._last_mail[name] = ts
        mailed = 0
        if self.enabled:
            try:
                from nq.collector.nq_limit_mail import send_limit_mail
                subj = f"[NQ] Grenzwert {name}: {value:.2f} ({pct:.0f}% der Spanne)"
                body = (f"Netzqualitaet-Grenzwertueberschreitung (PAC4200)\n\n"
                        f"Grenze:    {name}\nGroesse:   {qty}\n"
                        f"Messwert:  {value:.3f}\nGrenze:    {threshold:.3f}\n"
                        f"Ausschoepfung: {pct:.1f}%\n"
                        f"Dauerhaft >= {self.window_s:.0f}s.\n")
                mailed = 1 if send_limit_mail(subj, body) else 0
            except Exception:
                mailed = 0
        try:
            conn.execute(
                "INSERT INTO nq_limit_alerts "
                "(ts,limit_name,quantity,value,threshold,pct,mailed) VALUES (?,?,?,?,?,?,?)",
                (int(ts), name, qty, value, threshold, round(pct, 1), mailed))
            conn.commit()
        except Exception as e:
            print(f"[nq_poller/limit] DB-Fehler: {e}")


# ---------------------------------------------------------------------------
# Haupt-Loop: Fast-Pfad (200 ms, Main-Thread)
# ---------------------------------------------------------------------------
def poller_loop(db_path: str, cfg: dict) -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    conn = open_db(db_path, TECH_SCHEMA)

    poll_s = cfg.get("polling", {}).get("fast_ms", 200) / 1000.0
    grid_s = cfg.get("aggregate", {}).get("grid_s", 300)
    ef = cfg.get("event_filter", {})
    cooldown_s = ef.get("cooldown_s", 120)
    cap_every_s = 60

    # Hintergrund-Thread (Medium-Tier) für Harmonische starten
    stop_event = threading.Event()
    medium = threading.Thread(target=_medium_thread, args=(db_path, cfg, stop_event),
                              name="nq-medium", daemon=True)
    medium.start()

    limit_mon = LimitMonitor(cfg)

    bucket = _Bucket()
    cur_bucket = int(time.time() // grid_s) * grid_s  # Initialisiere mit aktuellem Bucket
    fast_buf: list = []
    med_buf: list = []
    prev_vals: dict = {}
    last_event_ts = 0.0
    last_cap = time.time()
    polls = errors = events = 0

    fast_sql = ("INSERT OR REPLACE INTO nq_raw_fast (ts_ms,%s,event) VALUES (%s)"
                % (",".join(_FAST_COLS), ",".join(["?"] * (len(_FAST_COLS) + 2))))
    med_sql = ("INSERT OR REPLACE INTO nq_raw_medium (ts_ms,%s,event) VALUES (%s)"
               % (",".join(_MED_COLS), ",".join(["?"] * (len(_MED_COLS) + 2))))

    print(f"[nq_poller] db={db_path} fast={poll_s*1000:.0f}ms grid={grid_s}s "
          f"| Block A+B fast-thread, Harmonische slow-thread (read-only PAC)")

    while not _STOP:
        t0 = time.time()
        try:
            snap = read_fast_snapshot(timeout=0.5)   # kurzer Timeout: max 0.5s blocking
            if snap.get("ok"):
                polls += 1
                v = snap["values"]
                now = snap["ts"]
                ts_ms = int(t0 * 1000)

                ev = 0
                trig = _detect_event(prev_vals, v, ef)
                if trig and (t0 - last_event_ts) >= cooldown_s:
                    ev = 1
                    events += 1
                    last_event_ts = t0
                prev_vals = v

                b = now - (now % grid_s)
                if cur_bucket is None:
                    cur_bucket = b
                elif b != cur_bucket:
                    conn.executemany(
                        "INSERT OR REPLACE INTO nq_5min "
                        "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", bucket.rows(cur_bucket))
                    conn.commit()
                    bucket = _Bucket()
                    cur_bucket = b
                bucket.add(v)

                # WP1: Grenzwertüberwachung (best-effort, non-blocking)
                try:
                    limit_trig = limit_mon.check(conn, v, now)
                    # 3e: Anschlussgrößen-Überschreitung -> Event-Schnipsel speichern.
                    if limit_trig and ev == 0 and (t0 - last_event_ts) >= cooldown_s:
                        ev = 1
                        events += 1
                        last_event_ts = t0
                except Exception as e:
                    print(f"[nq_poller/limit] Check-Fehler: {e}")

                fast_buf.append([ts_ms] + [v.get(k) for k in _FAST_COLS.values()] + [ev])
                med_buf.append([ts_ms] + [v.get(k) for k in _MED_COLS.values()] + [ev])
            else:
                errors += 1
        except Exception as e:
            errors += 1
            print(f"[nq_poller] Fast-Fehler: {e}")

        if len(fast_buf) >= 10:
            try:
                conn.executemany(fast_sql, fast_buf)
                conn.executemany(med_sql, med_buf)
                conn.commit()
                fast_buf.clear()
                med_buf.clear()
            except Exception as e:
                print(f"[nq_poller] DB-Fehler Fast: {e}")

        if (time.time() - last_cap) >= cap_every_s:
            try:
                enforce_retention(conn, cfg)
            except Exception as e:
                print(f"[nq_poller] Kappung-Fehler: {e}")
            last_cap = time.time()

        sleep = poll_s - (time.time() - t0)
        while sleep > 0 and not _STOP:
            time.sleep(min(0.02, sleep))
            sleep -= 0.02

    # Cleanup: Medium-Thread stoppen
    stop_event.set()
    medium.join(timeout=5.0)

    # Final-Flush Fast
    try:
        if fast_buf:
            conn.executemany(fast_sql, fast_buf)
            conn.executemany(med_sql, med_buf)
        if cur_bucket is not None and bucket.acc:
            conn.executemany(
                "INSERT OR REPLACE INTO nq_5min "
                "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
                bucket.rows(cur_bucket))
        conn.commit()
    except Exception as e:
        print(f"[nq_poller] Final-Flush-Fehler: {e}")
    conn.close()
    print(f"[nq_poller] Ende. polls={polls} errors={errors} events={events}")


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    cfg = load_config()
    ap = argparse.ArgumentParser(description="NQ Dual-Rate-Poller (Tech)")
    ap.add_argument("--db", default=cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db"))
    a = ap.parse_args()
    poller_loop(a.db, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
