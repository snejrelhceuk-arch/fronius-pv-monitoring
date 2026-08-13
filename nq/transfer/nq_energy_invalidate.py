"""nq.transfer.nq_energy_invalidate — Ungültige PAC-Tage an SM angleichen (Rolle N).

**Zweck:** Für Tage **ohne gültige PAC-Messung** (Zählerunterbrechung, Anlaufphase,
zu wenige Snapshots) den PAC-Tageswert durch den autoritativen Fronius-SM-Wert
ersetzen, damit die **kumulativen Statistiken** (Monats-/Jahres-Fixpunkte, Tooltip-
Klammerwerte) nicht durch Startup-Artefakte verfälscht werden.

**Abgrenzung zur früheren Automatik:** Dieses Werkzeug ersetzt **nur explizit
benannte Tage** (``--day`` bzw. ``--before``). Es gibt **keine** Schwellen-
Automatik, die gültige Messtage überschreiben und reale Abweichungen verschleiern
könnte. Gültige PAC-Tage (ab 2026-08-05) bleiben unangetastet.

**Mechanik:**
- Setzt ``wh_imp_delta`` / ``wh_exp_delta`` auf den SM-Tageswert (``master_sm_day``),
  ``src='sm_substitute'``. Die ``*_start``/``*_end``-Fixpunkte (echte PAC-Zählerstände)
  bleiben unverändert.
- ``sm_substitute`` wird von ``nq_energy_recompute`` übersprungen (bleibt stabil).
- Rollt Monats-/Jahres-Fixpunkte neu.
- Rührt ``pv_backfill``-Tage nicht an.

Start:  python3 -m nq.transfer.nq_energy_invalidate --before 2026-08-05          # Dry-Run
        python3 -m nq.transfer.nq_energy_invalidate --before 2026-08-05 --apply
        python3 -m nq.transfer.nq_energy_invalidate --day 2026-08-04 --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from glob import glob

from nq.nq_common import open_db, PRIMARY_SCHEMA
from nq.transfer.nq_energy_rollup import master_sm_day, rollup_month, rollup_year

SRC_SUBSTITUTE = "sm_substitute"


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _day_bounds(day: str) -> tuple[int, int]:
    t = time.strptime(day, "%Y-%m-%d")
    t0 = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def _select_days(before: str | None, days: list[str]) -> dict:
    """PAC-Zählertage (src != pv_backfill), gefiltert auf < ``before`` bzw. die
    explizite ``days``-Liste. Returns day -> {src, _db}."""
    out: dict = {}
    for db_path in sorted(glob(os.path.join(_db_dir(), "nq_*.db"))):
        try:
            c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            rows = c.execute(
                "SELECT day, src FROM nq_energy_daily WHERE src != 'pv_backfill'"
            ).fetchall()
            c.close()
        except Exception:
            continue
        for day, src in rows:
            if days and day not in days:
                continue
            if before and not (day < before):
                continue
            out[day] = {"src": src, "_db": db_path}
    return out


def invalidate(before: str | None = None, days: list[str] | None = None,
               apply: bool = False) -> dict:
    days = days or []
    sel = _select_days(before, days)
    report = []
    writes: dict = {}
    months_touched: set[str] = set()

    for day in sorted(sel):
        t0, t1 = _day_bounds(day)
        sm = master_sm_day(t0, t1)
        if not sm:
            report.append({"day": day, "skipped": "kein SM-Wert", "src_old": sel[day]["src"]})
            continue
        report.append({
            "day": day, "src_old": sel[day]["src"], "src_new": SRC_SUBSTITUTE,
            "sm_imp_kwh": sm["imp_kwh"], "sm_exp_kwh": sm["exp_kwh"],
        })
        writes.setdefault(sel[day]["_db"], []).append(
            (day, sm["imp_kwh"], sm["exp_kwh"]))
        months_touched.add(day[:7])

    if apply and writes:
        now = int(time.time())
        for db_path, items in writes.items():
            conn = open_db(db_path, PRIMARY_SCHEMA)
            for day, sm_imp, sm_exp in items:
                conn.execute(
                    "UPDATE nq_energy_daily SET "
                    "wh_imp_delta=?, wh_exp_delta=?, src=?, created_ts=? WHERE day=?",
                    [round(sm_imp * 1000, 3), round(sm_exp * 1000, 3),
                     SRC_SUBSTITUTE, now, day],
                )
            conn.commit()
            conn.close()
        for m in sorted(months_touched):
            rollup_month(m)
        for y in sorted({m[:4] for m in months_touched}):
            rollup_year(y)

    return {"apply": apply, "before": before, "days": days,
            "n": len(sel), "months_touched": sorted(months_touched), "report": report}


def main() -> int:
    import sys, json
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Ungültige PAC-Tage an SM angleichen (explizit)")
    ap.add_argument("--before", help="Alle PAC-Tage vor diesem Datum (YYYY-MM-DD)")
    ap.add_argument("--day", action="append", default=[], help="Expliziter Tag (wiederholbar)")
    ap.add_argument("--apply", action="store_true", help="Schreiben (Default: Dry-Run)")
    ap.add_argument("--json", action="store_true", help="Report als JSON")
    a = ap.parse_args()
    if not a.before and not a.day:
        ap.error("--before oder --day angeben")
    res = invalidate(before=a.before, days=a.day, apply=a.apply)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    mode = "APPLY" if a.apply else "DRY-RUN"
    print(f"[{mode}] before={a.before or '—'} days={a.day or '—'} "
          f"betroffen={res['n']} Monate={','.join(res['months_touched']) or '—'}")
    for r in res["report"]:
        if r.get("skipped"):
            print(f"  {r['day']}  ÜBERSPRUNGEN ({r['skipped']})")
        else:
            print(f"  {r['day']}  {r['src_old']} -> {r['src_new']}  "
                  f"SM imp={r['sm_imp_kwh']} exp={r['sm_exp_kwh']} kWh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
