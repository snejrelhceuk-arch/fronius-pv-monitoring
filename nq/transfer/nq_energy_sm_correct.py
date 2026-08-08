"""nq.transfer.nq_energy_sm_correct — SM-Korrektur für PAC-Problem-Tage (Rolle N).

**Zweck:** Überschreibt PAC-Energiewerte für Tage mit offensichtlichen PAC-Fehlern
(Anlaufphase, Collector-Ausfall, extreme Abweichungen) mit den autoritativen
Fronius Master-SM-Werten aus ``daily_data``. Nutzt dieselbe Quelle wie der
Energie-Vergleich.

**Strategie:**
- Identifiziert Tage mit großer Abweichung (>20% oder absolute Differenz >0.5 kWh)
- Überschreibt diese mit SM-Werten (``src='sm_corrected'``)
- Rollt Monats-/Jahres-Fixpunkte neu

**Sicherheit:**
- Dry-Run-Default (``--apply`` zum Schreiben)
- Schützt manuell korrigierte Tage (``src='manual'``)
- Protokolliert alle Änderungen

Start:  python3 -m nq.transfer.nq_energy_sm_correct [--apply] [--threshold-pct 20]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from glob import glob

from nq.nq_common import open_db, PRIMARY_SCHEMA
from nq.transfer.nq_energy_rollup import master_sm_day, rollup_month, rollup_year


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _day_bounds(day: str) -> tuple[int, int]:
    t = time.strptime(day, "%Y-%m-%d")
    t0 = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def _load_pac_days() -> dict:
    """Liest alle PAC-Zählertage (src != 'pv_backfill')."""
    out = {}
    for db_path in sorted(glob(os.path.join(_db_dir(), "nq_*.db"))):
        try:
            c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            rows = c.execute(
                "SELECT day, wh_imp_delta, wh_exp_delta, src "
                "FROM nq_energy_daily WHERE src != 'pv_backfill'"
            ).fetchall()
            c.close()
        except Exception:
            continue
        for day, imp, exp, src in rows:
            out[day] = {
                "day": day,
                "pac_imp_kwh": (imp / 1000.0) if imp else None,  # Wh -> kWh
                "pac_exp_kwh": (exp / 1000.0) if exp else None,  # Wh -> kWh
                "src": src, "_db": db_path
            }
    return out


def _needs_correction(pac_imp: float | None, pac_exp: float | None,
                     sm_imp: float | None, sm_exp: float | None,
                     threshold_pct: float, min_abs_kwh: float) -> tuple[bool, str]:
    """Prüft ob Korrektur nötig ist. Returns (needs, reason)."""
    if sm_imp is None or sm_exp is None:
        return False, ""
    
    # Import prüfen
    if pac_imp is None or pac_imp == 0:
        if sm_imp > min_abs_kwh:
            return True, "pac_imp=0_but_sm_has_data"
    elif sm_imp > 0:
        dev_pct = abs(100.0 * (pac_imp - sm_imp) / sm_imp)
        abs_diff = abs(pac_imp - sm_imp)
        if dev_pct > threshold_pct and abs_diff > min_abs_kwh:
            return True, f"imp_dev={dev_pct:.1f}%"
    
    # Export prüfen
    if pac_exp is None or pac_exp == 0:
        if sm_exp > min_abs_kwh:
            return True, "pac_exp=0_but_sm_has_data"
    elif sm_exp > 0:
        dev_pct = abs(100.0 * (pac_exp - sm_exp) / sm_exp)
        abs_diff = abs(pac_exp - sm_exp)
        if dev_pct > threshold_pct and abs_diff > min_abs_kwh:
            return True, f"exp_dev={dev_pct:.1f}%"
    
    return False, ""


def correct(apply: bool = False, threshold_pct: float = 20.0,
           min_abs_kwh: float = 0.5) -> dict:
    """Korrigiert Problem-Tage mit SM-Werten."""
    pac_days = _load_pac_days()
    report = []
    writes = {}
    months_touched = set()
    
    for day, pd in sorted(pac_days.items()):
        # Schütze manuell korrigierte Tage
        if pd["src"] == "manual":
            continue
        
        t0, t1 = _day_bounds(day)
        sm = master_sm_day(t0, t1)
        if not sm:
            continue
        
        sm_imp, sm_exp = sm["imp_kwh"], sm["exp_kwh"]
        needs, reason = _needs_correction(
            pd["pac_imp_kwh"], pd["pac_exp_kwh"], sm_imp, sm_exp,
            threshold_pct, min_abs_kwh
        )
        
        if needs:
            report.append({
                "day": day,
                "pac_imp_kwh": pd["pac_imp_kwh"],
                "pac_exp_kwh": pd["pac_exp_kwh"],
                "sm_imp_kwh": sm_imp,
                "sm_exp_kwh": sm_exp,
                "reason": reason,
                "src_old": pd["src"]
            })
            writes.setdefault(pd["_db"], []).append((day, sm_imp, sm_exp))
            months_touched.add(day[:7])
    
    if apply and writes:
        now = int(time.time())
        for db_path, items in writes.items():
            conn = open_db(db_path, PRIMARY_SCHEMA)
            for day, sm_imp, sm_exp in items:
                # Überschreibe mit SM-Werten, setze src='sm_corrected'
                conn.execute(
                    "UPDATE nq_energy_daily SET "
                    "wh_imp_delta=?, wh_exp_delta=?, src=?, created_ts=? "
                    "WHERE day=?",
                    [round(sm_imp * 1000, 3), round(sm_exp * 1000, 3),
                     "sm_corrected", now, day]
                )
            conn.commit()
            conn.close()
        
        # Rollup neu
        for m in sorted(months_touched):
            rollup_month(m)
        for y in sorted({m[:4] for m in months_touched}):
            rollup_year(y)
    
    return {
        "apply": apply,
        "threshold_pct": threshold_pct,
        "min_abs_kwh": min_abs_kwh,
        "days_total": len(pac_days),
        "days_corrected": len(report),
        "months_touched": sorted(months_touched),
        "report": report
    }


def main() -> int:
    import sys, json
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    
    ap = argparse.ArgumentParser(
        description="Korrigiert PAC-Problem-Tage mit SM-Werten"
    )
    ap.add_argument("--apply", action="store_true",
                   help="Änderungen schreiben (Default: Dry-Run)")
    ap.add_argument("--threshold-pct", type=float, default=20.0,
                   help="Abweichungs-Schwelle in Prozent (Default: 20)")
    ap.add_argument("--min-abs-kwh", type=float, default=0.5,
                   help="Minimale absolute Differenz in kWh (Default: 0.5)")
    ap.add_argument("--json", action="store_true",
                   help="Vollen Report als JSON ausgeben")
    a = ap.parse_args()
    
    res = correct(
        apply=a.apply,
        threshold_pct=a.threshold_pct,
        min_abs_kwh=a.min_abs_kwh
    )
    
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    
    mode = "APPLY" if a.apply else "DRY-RUN"
    print(f"[{mode}] Schwelle={res['threshold_pct']}%, min={res['min_abs_kwh']} kWh")
    print(f"PAC-Tage={res['days_total']} zu_korrigieren={res['days_corrected']} "
          f"Monate={','.join(res['months_touched']) or '—'}")
    
    if res['report']:
        print(f"\n{'Tag':<12} {'Grund':<25} {'PAC→SM Import':>20} {'PAC→SM Export':>20}")
        print("=" * 80)
        for r in res['report']:
            imp_str = f"{r['pac_imp_kwh'] or 0:.3f} → {r['sm_imp_kwh']:.3f}"
            exp_str = f"{r['pac_exp_kwh'] or 0:.3f} → {r['sm_exp_kwh']:.3f}"
            print(f"{r['day']:<12} {r['reason']:<25} {imp_str:>20} {exp_str:>20}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
