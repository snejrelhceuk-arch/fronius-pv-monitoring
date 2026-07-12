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
from nq.collector.nq_energy import compute_daily, COUNTERS

try:
    import config as _pvconfig
except Exception:  # pragma: no cover
    _pvconfig = None


def _tech_host(cfg: dict) -> str:
    return (os.environ.get("PV_TECH_IP")
            or cfg.get("transfer", {}).get("tech_host")
            or "192.0.2.181")


def _day_bounds(day: str) -> tuple[int, int]:
    """localtime-Tagesgrenzen (wie Produktion) für 'YYYY-MM-DD'."""
    t = time.strptime(day, "%Y-%m-%d")
    t0 = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def fetch_tech_rows(host: str, tmpfs_db: str, t0: int, t1: int) -> list[tuple]:
    """Holt read-only die Energiezähler-Snapshots [t0,t1) von Tech (SSH+Python)."""
    cols = ", ".join(["ts"] + COUNTERS)
    remote = (
        "import sqlite3,json,sys;"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True);"
        f"print(json.dumps(c.execute('SELECT {cols} FROM nq_energy_raw "
        f"WHERE ts>=? AND ts<? ORDER BY ts',({t0},{t1})).fetchall()))"
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
    """Best-effort: Master-SM (Fronius Primär-SM) Tages-Bezug/Lieferung in kWh
    aus der Produktions-DB (read-only). None bei Nichtverfügbarkeit."""
    if _pvconfig is None:
        return None
    db = getattr(_pvconfig, "DB_PATH", None)
    if not db or not os.path.exists(db):
        return None
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
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
    t0, t1 = _day_bounds(day)
    rows = fetch_tech_rows(host, cfg["tmpfs"]["db_path"], t0, t1)
    daily = compute_daily(rows)
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


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Energie-Tages-Rollup (Primary)")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (Default: gestern)")
    a = ap.parse_args()
    day = a.day or time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    print(json.dumps(rollup(day), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
