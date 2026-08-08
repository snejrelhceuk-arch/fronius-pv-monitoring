"""nq.transfer.nq_energy_recompute — Rückwirkende Korrektur der PAC-Energie-Fixpunkte (Rolle N).

**Warum:** Die frühere Tages-Differenz ``delta = letzter − erster Snapshot INNERHALB
des Tages`` (``compute_daily``) verliert die Energie in der Lücke zwischen dem
letzten Snapshot eines Tages und dem ersten des Folgetages. Bei 5-min-Takt (und
erst recht bei Collector-Ausfall über Mitternacht) ist das ein **systematischer
Verlust** — z. B. 2026-07-13: within-day 883 Wh, real (aus den Zählerständen)
2357 Wh → 1474 Wh verloren.

**Korrektur (produktionskonform, wie ``energy_checkpoints`` der Kern-DB):**
aufeinanderfolgende **day_start-Fixpunkte** differenzieren:

    delta(D) = start(D+1) − start(D) ,  end(D) = start(D+1)

Das teleskopiert über einen zusammenhängenden Lauf → Lauf-Summe = Zähler-
fortschritt end(Dn) − start(D0) (**energieerhaltend**, kein Verlust mehr). Die
``*_start``-Spalten (= near-Mitternacht-Zählerstände) bleiben unangetastet; nur
``*_end``/``*_delta``/``src`` werden neu gesetzt. Danach Monats-/Jahres-Fixpunkte
neu rollen.

Invarianten:
- **Nur PAC-Zählerzeilen** (``src`` ≠ ``pv_backfill``). Backfill-Tage aus der
  Produktion bleiben unberührt (anderer Zähler, autoritativ).
- **Keine Differenz über einen Zähler-/Meter-Wechsel** (Reset-/Skalensprung-Guard).
- **Letzter Tag eines Laufs** (kein Folge-Fixpunkt) behält die within-day-Differenz,
  ``src='partial'`` (kann noch nicht randscharf geschlossen werden).
- Idempotent (Differenz aus unveränderten ``*_start`` → wiederholter Lauf stabil).
- Schreibt ausschließlich in ``nq/db/`` (Rolle N), niemals ``data.db``.

Start:  python3 -m nq.transfer.nq_energy_recompute            # Dry-Run (Report)
        python3 -m nq.transfer.nq_energy_recompute --apply    # schreibt zurück
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from glob import glob

from nq.nq_common import open_db, PRIMARY_SCHEMA
from nq.collector.nq_energy import COUNTERS
from nq.transfer.nq_energy_rollup import rollup_month, rollup_year

_MIN_DELTA = 1.0  # Wh: darunter kein signifikanter Unterschied (wie nq_energy)


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _next_day(day: str) -> str:
    t = time.strptime(day, "%Y-%m-%d")
    return time.strftime("%Y-%m-%d", time.localtime(time.mktime(
        (t.tm_year, t.tm_mon, t.tm_mday, 12, 0, 0, 0, 0, -1)) + 86400))


def _load_all_daily() -> dict:
    """Liest alle nq_energy_daily-Zeilen über die Monats-DBs. Returns day -> row-dict."""
    cols = ["day"] + [f"{c}_{k}" for c in COUNTERS for k in ("start", "end", "delta")] \
        + ["src", "n_samples"]
    sel = ",".join(cols)
    out: dict = {}
    for db_path in sorted(glob(os.path.join(_db_dir(), "nq_*.db"))):
        try:
            c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            rows = c.execute(f"SELECT {sel} FROM nq_energy_daily").fetchall()
            c.close()
        except Exception:
            continue
        for r in rows:
            d = dict(zip(cols, r))
            d["_db"] = db_path
            out[d["day"]] = d
    return out


def _corrected(day_row: dict, next_row: dict | None) -> dict:
    """Neue end/delta je Zähler + src. Differenziert einen Zähler nur gegen den
    Folge-Fixpunkt, wenn **beide Randstände gültige kumulative Basen** sind
    (> _MIN_DELTA) und **kein Reset** vorliegt — sonst bleibt der within-day-Wert
    erhalten (schützt vor Artefakten aus früher Register-Fehllesung, z. B.
    Export=0 in der Anlaufphase 2026-07-12/13).

    Idempotent: geschlossene Zähler leiten sich nur aus den unveränderlichen
    ``*_start`` ab; ungültige/offene Zähler werden **nicht** angefasst.
    """
    res = {}
    any_reset = False
    imp_closed = False
    for c in COUNTERS:
        s = day_row.get(f"{c}_start")
        e_old = day_row.get(f"{c}_end")
        s_next = next_row.get(f"{c}_start") if next_row else None
        valid_base = s is not None and s > _MIN_DELTA
        valid_next = s_next is not None and s_next > _MIN_DELTA
        if valid_base and s_next is not None and s_next < s - _MIN_DELTA:
            any_reset = True
        if valid_base and valid_next and s_next >= s - _MIN_DELTA:
            res[f"{c}_end"] = s_next
            res[f"{c}_delta"] = round(s_next - s, 3)
            if c == "wh_imp":
                imp_closed = True
        else:
            # Reset, ungültige Basis (0-Register) oder letzter Tag → within-day behalten
            res[f"{c}_end"] = e_old
            res[f"{c}_delta"] = (round(e_old - s, 3) if (e_old is not None and s is not None)
                                 else day_row.get(f"{c}_delta"))
    if any_reset:
        res["src"] = "reset_fallback"
    elif imp_closed:
        res["src"] = "counter"          # Bezugszähler randscharf geschlossen
    else:
        res["src"] = "partial"          # letzter Tag im Lauf / offene Basis
    return res


def recompute(apply: bool = False) -> dict:
    daily = _load_all_daily()
    counter_days = sorted(d for d, r in daily.items() if (r.get("src") or "") != "pv_backfill")
    report = []
    writes: dict = {}   # db_path -> list of (day, corrected)
    months_touched: set[str] = set()
    for day in counter_days:
        row = daily[day]
        nxt = daily.get(_next_day(day))
        # Folge-Fixpunkt nur nutzen, wenn er selbst ein PAC-Zählertag ist
        if nxt is not None and (nxt.get("src") or "") == "pv_backfill":
            nxt = None
        corr = _corrected(row, nxt)
        old_imp = row.get("wh_imp_delta")
        new_imp = corr.get("wh_imp_delta")
        old_exp = row.get("wh_exp_delta")
        new_exp = corr.get("wh_exp_delta")
        changed = (old_imp != new_imp) or (old_exp != new_exp) or ((row.get("src") or "") != corr["src"])
        report.append({
            "day": day, "n_samples": row.get("n_samples"),
            "src_old": row.get("src"), "src_new": corr["src"],
            "imp_old_wh": old_imp, "imp_new_wh": new_imp,
            "exp_old_wh": old_exp, "exp_new_wh": new_exp,
            "d_imp_wh": (round((new_imp or 0) - (old_imp or 0), 1)),
            "changed": changed,
        })
        if changed:
            writes.setdefault(row["_db"], []).append((day, corr))
            months_touched.add(day[:7])

    if apply and writes:
        now = int(time.time())
        for db_path, items in writes.items():
            conn = open_db(db_path, PRIMARY_SCHEMA)
            for day, corr in items:
                sets = []
                vals = []
                for c in COUNTERS:
                    sets += [f"{c}_end=?", f"{c}_delta=?"]
                    vals += [corr.get(f"{c}_end"), corr.get(f"{c}_delta")]
                sets += ["src=?", "created_ts=?"]
                vals += [corr["src"], now]
                vals.append(day)
                conn.execute(f"UPDATE nq_energy_daily SET {','.join(sets)} WHERE day=?", vals)
            conn.commit()
            conn.close()
        # Monats-/Jahres-Fixpunkte neu rollen
        for m in sorted(months_touched):
            rollup_month(m)
        for y in sorted({m[:4] for m in months_touched}):
            rollup_year(y)

    n_changed = sum(1 for r in report if r["changed"])
    return {
        "apply": apply, "days_total": len(counter_days), "days_changed": n_changed,
        "months_touched": sorted(months_touched), "report": report,
    }


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Energie-Fixpunkte rückwirkend korrigieren (Randwert/Checkpoint-Differenz)")
    ap.add_argument("--apply", action="store_true", help="Änderungen schreiben (Default: Dry-Run)")
    ap.add_argument("--json", action="store_true", help="Vollen Report als JSON ausgeben")
    a = ap.parse_args()
    res = recompute(apply=a.apply)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    mode = "APPLY" if a.apply else "DRY-RUN"
    print(f"[{mode}] PAC-Zählertage={res['days_total']} geändert={res['days_changed']} "
          f"Monate={','.join(res['months_touched']) or '—'}")
    print(f"{'Tag':<12}{'n':>5} {'src':>16} {'Imp alt→neu Wh':>26} {'ΔImp':>8}")
    for r in res["report"]:
        if not r["changed"]:
            continue
        print(f"{r['day']:<12}{(r['n_samples'] or 0):>5} "
              f"{(r['src_old'] or '')+'→'+r['src_new']:>16} "
              f"{str(r['imp_old_wh'])+' → '+str(r['imp_new_wh']):>26} {r['d_imp_wh']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
