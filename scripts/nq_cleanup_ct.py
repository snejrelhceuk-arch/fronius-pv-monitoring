"""nq_cleanup_ct.py — Einmal-Bereinigung falsch gepolter CT-Daten (NQ2 WP0).

Am 2026-07-13 ~20:20 wurde die Stromwandler-Richtung im PAC4200 korrigiert. Alle
NQ-Daten **vor** diesem Zeitpunkt haben vertauschte Vorzeichen (Bezug ↔ Einspeisung).
Dieses Skript löscht die betroffenen Zeilen:
- **Tech (tmpfs)**: nq_raw_fast/medium (ts_ms < cutoff), nq_agg_10s (ts < cutoff) via SSH.
- **Primary (SD)**: nq_energy_daily + nq_energy_checkpoint des betroffenen Tages.

**Sicherheit:** Standard = **DRY-RUN** (zeigt nur, was gelöscht würde). Erst mit
``--commit`` wird tatsächlich gelöscht. Jede Löschung wird in ``nq_capping_log``
(trigger='ct_polarity_fix') protokolliert. Rolle N bleibt read-only ggü. Produktion
(nur NQ-DBs betroffen).

Aufruf (Dry-Run):   python3 scripts/nq_cleanup_ct.py
Aufruf (echt):      python3 scripts/nq_cleanup_ct.py --commit
Doku:  doc/netzqualitaet/NQ2_ROADMAP.md §6 (WP0), doc/dev_prompt/NQ2-WP0-Datenhygiene/prompt.md
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nq.nq_common import load_config, open_db, PRIMARY_SCHEMA, BASE_DIR  # noqa: E402

# Standard-Cutoff: 2026-07-13 20:20:00 localtime
_DEFAULT_CUTOFF = "2026-07-13 20:20:00"


def _cutoff_ts(cutoff: str) -> int:
    t = time.strptime(cutoff, "%Y-%m-%d %H:%M:%S")
    return int(time.mktime(t))


def _tech_host(cfg: dict) -> str:
    return (os.environ.get("PV_TECH_IP")
            or cfg.get("transfer", {}).get("tech_host") or "192.0.2.181")


def _ssh_python(host: str, code: str, timeout: int = 30) -> str:
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
         "cd %s && python3 -" % remote_dir],
        input=code, capture_output=True, text=True, timeout=timeout, check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200] or "Tech nicht erreichbar")
    return out.stdout.strip()


def cleanup_tech(cfg: dict, cutoff_ts: int, commit: bool) -> dict:
    """Löscht (oder zählt) pre-cutoff-Zeilen im Tech-tmpfs via SSH."""
    host = _tech_host(cfg)
    tmpfs = cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db")
    cut_ms = cutoff_ts * 1000
    mode = "delete" if commit else "count"
    code = (
        "import sqlite3,json\n"
        f"c=sqlite3.connect('{tmpfs}')\n"
        "res={}\n"
        f"for tbl,col,cut in [('nq_raw_fast','ts_ms',{cut_ms}),('nq_raw_medium','ts_ms',{cut_ms}),('nq_agg_10s','ts',{cutoff_ts})]:\n"
        "  n=c.execute('SELECT COUNT(*) FROM %s WHERE %s < ?'%(tbl,col),(cut,)).fetchone()[0]\n"
        f"  if '{mode}'=='delete' and n:\n"
        "    c.execute('DELETE FROM %s WHERE %s < ?'%(tbl,col),(cut,))\n"
        "  res[tbl]=n\n"
        f"if '{mode}'=='delete':\n"
        "  tot=sum(res.values())\n"
        "  if tot:\n"
        "    c.execute('INSERT INTO nq_capping_log(ts,trigger,table_name,rows_deleted,tmpfs_mb) VALUES(?,?,?,?,NULL)',(int(__import__('time').time()),'ct_polarity_fix','nq_raw_*',tot))\n"
        "  c.commit()\n"
        "print(json.dumps(res))\n"
    )
    try:
        import json
        counts = json.loads(_ssh_python(host, code) or "{}")
        return {"host": host, "counts": counts, "committed": commit}
    except Exception as exc:
        return {"host": host, "error": str(exc), "committed": False}


def cleanup_primary(cutoff_ts: int, commit: bool) -> dict:
    """Löscht (oder zählt) den betroffenen Tag in nq_energy_daily/checkpoint (Primary)."""
    day = time.strftime("%Y-%m-%d", time.localtime(cutoff_ts))
    month = day[:7]
    db_path = os.path.join(BASE_DIR, "nq", "db", f"nq_{month}.db")
    if not os.path.exists(db_path):
        return {"db": db_path, "note": "Monats-DB fehlt (nichts zu tun)", "committed": commit}
    conn = open_db(db_path, PRIMARY_SCHEMA)
    counts = {}
    for tbl in ("nq_energy_daily", "nq_energy_checkpoint"):
        counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE day = ?", (day,)).fetchone()[0]
    if commit:
        for tbl in ("nq_energy_daily", "nq_energy_checkpoint"):
            conn.execute(f"DELETE FROM {tbl} WHERE day = ?", (day,))
        conn.commit()
    conn.close()
    return {"db": db_path, "day": day, "counts": counts, "committed": commit}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ CT-Polarity-Datenbereinigung (WP0)")
    ap.add_argument("--cutoff", default=_DEFAULT_CUTOFF, help="localtime 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--commit", action="store_true", help="Tatsächlich löschen (sonst Dry-Run)")
    ap.add_argument("--skip-tech", action="store_true", help="Tech-Bereinigung überspringen")
    ap.add_argument("--skip-primary", action="store_true", help="Primary-Bereinigung überspringen")
    a = ap.parse_args()

    cfg = load_config()
    cut = _cutoff_ts(a.cutoff)
    if not a.commit:
        print("=== DRY-RUN (nichts wird gelöscht) — mit --commit ausführen ===")
    print(f"Cutoff: {a.cutoff} (ts={cut})")

    if not a.skip_tech:
        print("[Tech ] ", cleanup_tech(cfg, cut, a.commit))
    if not a.skip_primary:
        print("[Prim ] ", cleanup_primary(cut, a.commit))

    if not a.commit:
        print("=== Ende Dry-Run. Zum Löschen: --commit ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
