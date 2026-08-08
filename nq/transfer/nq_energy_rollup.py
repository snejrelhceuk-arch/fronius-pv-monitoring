"""nq.transfer.nq_energy_rollup — Primary-Tages-Rollup der PAC-Energiezähler (Rolle N).

Läuft **1×/Tag auf Primary** (SD, selten schreiben). Holt die Energiezähler-
Snapshots **read-only von Tech** (tmpfs via SSH), berechnet per Differenzmethode
das Tages-Delta + day_start-Checkpoint und schreibt in die Primary-Monats-DB
``nq/db/nq_YYYY-MM.db``. Zusätzlich Vergleich gegen den **Master-SM** (Fronius
Primär-SM, read-only aus der Produktions-DB) — ``nq_energy_compare``.

Robust gegen Tech-Reboot: die tmpfs-Snapshots sind volatil, aber die PAC-Zähler
sind kumulativ. Das Tages-Delta wird aus start/end der Tages-Snapshots gebildet
(``compute_daily`` mit Reset-Erkennung); der day_start-Checkpoint fixiert den
Anfangsstand dauerhaft auf Primary-SD.

Start:  python3 -m nq.transfer.nq_energy_rollup [--day YYYY-MM-DD]
Doku:   doc/netzqualitaet/NQ_TESTS_UND_DB.md §4/§5.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

from nq.nq_common import load_config, open_db, PRIMARY_SCHEMA, BASE_DIR
from nq.collector.nq_energy import compute_daily_boundary, COUNTERS

try:
    import config as _pvconfig
except Exception:  # pragma: no cover
    _pvconfig = None


def _tech_host(cfg: dict) -> str:
    host = os.environ.get("PV_TECH_IP")
    if not host:
        try:
            import config
            host = getattr(config, "NQ_TECH_IP", None)
        except Exception:
            host = None
    return (host
            or cfg.get("transfer", {}).get("tech_host")
            or "192.0.2.181")


def _day_bounds(day: str) -> tuple[int, int]:
    """localtime-Tagesgrenzen (wie Produktion) für 'YYYY-MM-DD'."""
    t = time.strptime(day, "%Y-%m-%d")
    t0 = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def fetch_tech_rows(host: str, tmpfs_db: str, t0: int, t1: int,
                    margin_s: int = 0) -> list[tuple]:
    """Holt read-only die Energiezähler-Snapshots von Tech (SSH+Python).

    Fenster ``[t0 - margin_s, t1 + margin_s)`` — der Rand über die Tagesgrenzen
    hinaus ist nötig, damit die Mitternachts-Randwerte **bracketiert** und linear
    interpoliert werden können (energieerhaltend, siehe compute_daily_boundary).
    """
    cols = ", ".join(["ts"] + COUNTERS)
    lo, hi = t0 - int(margin_s), t1 + int(margin_s)
    remote = (
        "import sqlite3,json,sys;"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True);"
        f"print(json.dumps(c.execute('SELECT {cols} FROM nq_energy_raw "
        f"WHERE ts>=? AND ts<? ORDER BY ts',({lo},{hi})).fetchall()))"
    )
    # Remote-Repo-Pfad zur Laufzeit (gleicher Pfad auf beiden Hosts; via
    # PV_REPO_DIR überschreibbar) — kein hostspezifischer Literal im Code.
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
         "cd %s && python3 -c \"%s\"" % (remote_dir, remote)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"Tech-Fetch fehlgeschlagen: {out.stderr.strip()[:200]}")
    return [tuple(r) for r in json.loads(out.stdout.strip() or "[]")]


def master_sm_day(t0: int, t1: int) -> dict | None:
    """Best-effort: Master-SM (Fronius Primär-SM) Tages-Bezug/Lieferung in kWh aus
    dem **autoritativen Tages-Fixpunkt** ``daily_data`` (read-only, W_Imp/Exp_Netz
    _start/_end = Zählerstand an den Tagesgrenzen). Fällt bei fehlenden Fixpunkten
    auf die 1-min-Delta-Summe zurück. None bei Nichtverfügbarkeit."""
    if _pvconfig is None:
        return None
    db = getattr(_pvconfig, "DB_PATH", None)
    if not db or not os.path.exists(db):
        return None
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        row = c.execute(
            "SELECT W_Imp_Netz_start, W_Imp_Netz_end, W_Exp_Netz_start, W_Exp_Netz_end "
            "FROM daily_data WHERE ts>=? AND ts<? ORDER BY ts LIMIT 1", (t0, t1)
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            c.close()
            imp = (row[1] - row[0]) / 1000.0
            exp = abs((row[3] or 0.0) - (row[2] or 0.0)) / 1000.0
            return {"imp_kwh": round(imp, 3), "exp_kwh": round(exp, 3)}
        # Fallback: 1-min-Deltas summieren (weniger genau als die Fixpunkte)
        row = c.execute(
            "SELECT SUM(W_Imp_Netz_delta), SUM(W_Exp_Netz_delta) "
            "FROM data_1min WHERE ts>=? AND ts<?", (t0, t1)
        ).fetchone()
        c.close()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    imp = (row[0] or 0.0) / 1000.0
    exp = abs(row[1] or 0.0) / 1000.0   # Exp-Delta ist negativ
    return {"imp_kwh": round(imp, 3), "exp_kwh": round(exp, 3)}


def rollup(day: str) -> dict:
    cfg = load_config()
    host = _tech_host(cfg)
    ecfg = cfg.get("energy", {})
    margin = int(ecfg.get("boundary_margin_s", 7200))
    max_gap = float(ecfg.get("boundary_max_gap_s", 1800))
    min_ok = int(ecfg.get("min_samples_ok", 200))
    t0, t1 = _day_bounds(day)
    rows = fetch_tech_rows(host, cfg["tmpfs"]["db_path"], t0, t1, margin_s=margin)
    daily = compute_daily_boundary(rows, t0, t1, max_gap_s=max_gap, min_samples_ok=min_ok)
    if daily is None:
        return {"day": day, "written": False, "reason": "keine Tech-Snapshots"}

    db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "db")
    month = day[:7]
    conn = open_db(os.path.join(db_dir, f"nq_{month}.db"), PRIMARY_SCHEMA)
    now = int(time.time())

    # nq_energy_daily (start/end/delta je Zähler + src)
    cols = ["day"]
    vals = [day]
    for c in COUNTERS:
        cols += [f"{c}_start", f"{c}_end", f"{c}_delta"]
        vals += [daily.get(f"{c}_start"), daily.get(f"{c}_end"), daily.get(f"{c}_delta")]
    cols += ["src", "n_samples", "created_ts"]
    vals += [daily.get("src"), daily.get("n_samples"), now]
    ph = ",".join(["?"] * len(vals))
    conn.execute(f"INSERT OR REPLACE INTO nq_energy_daily ({','.join(cols)}) VALUES ({ph})", vals)

    # Checkpoint = day_start-Stand (erster Snapshot des Tages)
    conn.execute(
        "INSERT OR REPLACE INTO nq_energy_checkpoint "
        "(ts, day, wh_imp, wh_exp, varh_imp, varh_exp, vah) VALUES (?,?,?,?,?,?,?)",
        [t0, day] + [daily.get(f"{c}_start") for c in COUNTERS],
    )

    # Vergleich PAC vs Master-SM (iMS bleibt NULL -> manuelle Ablesung)
    pac_imp = (daily.get("wh_imp_delta") or 0.0) / 1000.0
    pac_exp = (daily.get("wh_exp_delta") or 0.0) / 1000.0
    msm = master_sm_day(t0, t1)
    msm_imp = msm["imp_kwh"] if msm else None
    msm_exp = msm["exp_kwh"] if msm else None
    d_imp = round(pac_imp - msm_imp, 3) if msm_imp is not None else None
    d_exp = round(pac_exp - msm_exp, 3) if msm_exp is not None else None
    conn.execute(
        "INSERT OR REPLACE INTO nq_energy_compare "
        "(day, pac_imp_kwh, pac_exp_kwh, msm_imp_kwh, msm_exp_kwh, "
        " ims_imp_kwh, ims_exp_kwh, d_pac_msm_imp, d_pac_msm_exp, "
        " d_pac_ims_imp, d_pac_ims_exp, note, created_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [day, round(pac_imp, 3), round(pac_exp, 3), msm_imp, msm_exp,
         None, None, d_imp, d_exp, None, None, None, now],
    )
    conn.commit()
    conn.close()
    return {"day": day, "written": True, "src": daily.get("src"),
            "n_samples": daily.get("n_samples"),
            "pac_imp_kwh": round(pac_imp, 3), "pac_exp_kwh": round(pac_exp, 3),
            "msm_imp_kwh": msm_imp, "msm_exp_kwh": msm_exp}


# ---------------------------------------------------------------------------
# NQ2 WP2: Fixpunkt-Rollup Monat / Jahr (aus nq_energy_daily aggregiert)
# ---------------------------------------------------------------------------
def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _month_db_path(month: str) -> str:
    return os.path.join(_db_dir(), f"nq_{month}.db")


def _prev_month() -> str:
    lt = time.localtime()
    y, m = lt.tm_year, lt.tm_mon - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def _prev_year() -> str:
    return str(time.localtime().tm_year - 1)


def _rollup_from_daily(db_paths: list, day_like: str) -> dict | None:
    """Aggregiert nq_energy_daily über db_paths (day LIKE day_like) zu Fixpunkten.

    start = erster Tag *_start; end = letzter Tag *_end; delta = Σ Tages-Deltas
    (reset-aware bereits je Tag angewandt). db_paths müssen sortiert sein.
    """
    import sqlite3
    per = {c: {"start": None, "end": None, "delta": 0.0, "any": False} for c in COUNTERS}
    src_overall = "counter"
    n_total = 0
    days_seen = 0
    col_expr = ",".join(f"{c}_start,{c}_end,{c}_delta" for c in COUNTERS)
    nc = len(COUNTERS)
    for db_path in db_paths:
        if not os.path.exists(db_path):
            continue
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            rows = c.execute(
                f"SELECT day,{col_expr},src,n_samples FROM nq_energy_daily "
                "WHERE day LIKE ? ORDER BY day", (day_like,)).fetchall()
        except Exception:
            rows = []
        finally:
            c.close()
        for row in rows:
            days_seen += 1
            vals = row[1:1 + 3 * nc]
            src = row[1 + 3 * nc]
            n = row[2 + 3 * nc]
            n_total += (n or 0)
            if src and src != "counter":
                src_overall = src
            for i, cc in enumerate(COUNTERS):
                s, e, d = vals[i * 3], vals[i * 3 + 1], vals[i * 3 + 2]
                p = per[cc]
                if s is not None and p["start"] is None:
                    p["start"] = s
                if e is not None:
                    p["end"] = e
                if d is not None:
                    p["delta"] += d
                    p["any"] = True
    if not days_seen:
        return None
    out: dict = {"n_samples": n_total, "src": src_overall, "n_days": days_seen}
    for cc in COUNTERS:
        p = per[cc]
        out[f"{cc}_start"] = p["start"]
        out[f"{cc}_end"] = p["end"] if p["end"] is not None else p["start"]
        out[f"{cc}_delta"] = round(p["delta"], 3) if p["any"] else None
    return out


def _write_fixpoint(conn, table: str, keycol: str, keyval: str, agg: dict) -> None:
    now = int(time.time())
    cols = [keycol]
    vals = [keyval]
    for c in COUNTERS:
        cols += [f"{c}_start", f"{c}_end", f"{c}_delta"]
        vals += [agg.get(f"{c}_start"), agg.get(f"{c}_end"), agg.get(f"{c}_delta")]
    cols += ["src", "n_samples", "created_ts"]
    vals += [agg.get("src"), agg.get("n_samples"), now]
    ph = ",".join(["?"] * len(vals))
    conn.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({ph})", vals)
    conn.commit()


def rollup_month(month: str) -> dict:
    """Monats-Fixpunkt (YYYY-MM) aus den Tages-Deltas des Monats. Idempotent."""
    db_path = _month_db_path(month)
    agg = _rollup_from_daily([db_path], f"{month}-%")
    if agg is None:
        return {"month": month, "written": False, "reason": "keine Tagesdaten"}
    conn = open_db(db_path, PRIMARY_SCHEMA)
    _write_fixpoint(conn, "nq_energy_monthly", "month", month, agg)
    conn.close()
    return {"month": month, "written": True, "src": agg["src"], "n_days": agg["n_days"],
            "wh_imp_kwh": round((agg.get("wh_imp_delta") or 0.0) / 1000.0, 3),
            "wh_exp_kwh": round((agg.get("wh_exp_delta") or 0.0) / 1000.0, 3)}


def rollup_year(year: str) -> dict:
    """Jahres-Fixpunkt (YYYY) aus den 12 Monats-DBs. Ablage in nq_{year}-01.db."""
    db_paths = [os.path.join(_db_dir(), f"nq_{year}-{m:02d}.db") for m in range(1, 13)]
    agg = _rollup_from_daily(db_paths, f"{year}-%")
    if agg is None:
        return {"year": year, "written": False, "reason": "keine Tagesdaten"}
    conn = open_db(os.path.join(_db_dir(), f"nq_{year}-01.db"), PRIMARY_SCHEMA)
    _write_fixpoint(conn, "nq_energy_yearly", "year", year, agg)
    conn.close()
    return {"year": year, "written": True, "src": agg["src"], "n_days": agg["n_days"],
            "wh_imp_kwh": round((agg.get("wh_imp_delta") or 0.0) / 1000.0, 3),
            "wh_exp_kwh": round((agg.get("wh_exp_delta") or 0.0) / 1000.0, 3)}


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Energie-Rollup (Primary)")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD Tages-Rollup (Default: gestern)")
    ap.add_argument("--month", default=None, help="YYYY-MM Monats-Rollup (Default: Vormonat)")
    ap.add_argument("--year", default=None, help="YYYY Jahres-Rollup (Default: Vorjahr)")
    ap.add_argument("--auto-month", action="store_true",
                    help="Vormonat rollen (für Timer am Monatsersten)")
    ap.add_argument("--auto-year", action="store_true",
                    help="Vorjahr rollen (für Timer am 1.1.)")
    a = ap.parse_args()
    if a.month or a.auto_month:
        month = a.month or _prev_month()
        print(json.dumps(rollup_month(month), ensure_ascii=False))
        return 0
    if a.year or a.auto_year:
        year = a.year or _prev_year()
        print(json.dumps(rollup_year(year), ensure_ascii=False))
        return 0
    day = a.day or time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    print(json.dumps(rollup(day), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
