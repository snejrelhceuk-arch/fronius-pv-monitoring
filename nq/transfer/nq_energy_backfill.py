#!/usr/bin/env python3
"""nq.transfer.nq_energy_backfill — Einmaliger rückwirkender Fixpunkt-Backfill (Rolle N).

Für den Zeitraum VOR PAC-Start existieren keine PAC-Energie-Fixpunkte. Dieses
Skript füllt die NQ-Energie-Fixpunkte (``nq_energy_daily`` + Monats-/Jahres-Rollup
über ``nq_energy_rollup``) **einmalig** read-only aus der Produktions-DB
(``daily_data``: ``W_Imp_Netz_*``/``W_Exp_Netz_*``), damit die NQ-Werte in den
Tooltip-Klammern anfangs ≈ den PV-Werten entsprechen. Mit der Zeit dürfen die
echten PAC-Werte davon divergieren.

Eigenschaften:
- **Read-only** auf die Produktions-DB (``config.DB_PATH``).
- Schreibt in ``nq/db/nq_YYYY-MM.db`` mit ``src='pv_backfill'``.
- **Idempotent** & schonend: echte PAC-Zeilen (``src`` = ``counter`` /
  ``reset_fallback`` / ``partial``) werden **nie** überschrieben; nur Tage ohne
  echte PAC-Daten (und nur vor PAC-Start) werden gefüllt.
- **Dry-Run per Default**; tatsächliche Schreibvorgänge nur mit ``--commit``.

Reactive-/Apparent-Energie (varh/vah) kennt die Produktions-DB nicht → bleibt für
Backfill-Zeilen NULL (nur wh_imp/wh_exp aus dem Fronius-Primär-SM).

Start:  python3 -m nq.transfer.nq_energy_backfill [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--commit]
Doku:   doc/netzqualitaet/NQ_TESTS_UND_DB.md §5.
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import time

from nq.nq_common import open_db, PRIMARY_SCHEMA
from nq.collector.nq_energy import COUNTERS
from nq.transfer import nq_energy_rollup

try:
    import config as _pvconfig
except Exception:  # pragma: no cover
    _pvconfig = None

BACKFILL_SRC = "pv_backfill"
REAL_SRC = {"counter", "reset_fallback", "partial"}


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _day_start_ts(day: str) -> int:
    t = time.strptime(day, "%Y-%m-%d")
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def _first_real_pac_day() -> str | None:
    """Frühester Tag mit echten PAC-Daten (src != pv_backfill) über alle NQ-Monats-DBs."""
    best: str | None = None
    for db_path in sorted(glob.glob(os.path.join(_db_dir(), "nq_*.db"))):
        try:
            c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            row = c.execute(
                "SELECT MIN(day) FROM nq_energy_daily WHERE src IS NULL OR src != ?",
                (BACKFILL_SRC,),
            ).fetchone()
            c.close()
        except Exception:
            continue
        if row and row[0] and (best is None or row[0] < best):
            best = row[0]
    return best


def _pv_daily_rows(from_day: str, to_day: str) -> list[dict]:
    """Read-only Tages-Energie (Netz Bezug/Einspeisung) aus der Produktions-``daily_data``."""
    if _pvconfig is None:
        raise RuntimeError("config nicht importierbar — Produktions-DB unbekannt")
    db = getattr(_pvconfig, "DB_PATH", None)
    if not db or not os.path.exists(db):
        raise RuntimeError(f"Produktions-DB nicht gefunden: {db}")
    t0 = _day_start_ts(from_day)
    t1 = _day_start_ts(to_day) + 86400  # inklusive to_day
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
    try:
        rows = c.execute(
            "SELECT date(ts,'unixepoch','localtime') AS d, "
            "W_Imp_Netz_start, W_Imp_Netz_end, W_Imp_Netz_total, "
            "W_Exp_Netz_start, W_Exp_Netz_end, W_Exp_Netz_total "
            "FROM daily_data WHERE ts >= ? AND ts < ? ORDER BY ts",
            (t0, t1),
        ).fetchall()
    finally:
        c.close()
    out = []
    for d, imp_s, imp_e, imp_t, exp_s, exp_e, exp_t in rows:
        out.append({
            "day": d,
            "wh_imp_start": imp_s, "wh_imp_end": imp_e, "wh_imp_delta": imp_t,
            "wh_exp_start": exp_s, "wh_exp_end": exp_e, "wh_exp_delta": exp_t,
        })
    return out


def _existing_src(conn: sqlite3.Connection, day: str) -> str | None:
    row = conn.execute("SELECT src FROM nq_energy_daily WHERE day=?", (day,)).fetchone()
    return row[0] if row else None


def _write_daily(conn: sqlite3.Connection, rec: dict, now: int) -> None:
    cols = ["day"]
    vals = [rec["day"]]
    for c in COUNTERS:
        cols += [f"{c}_start", f"{c}_end", f"{c}_delta"]
        vals += [rec.get(f"{c}_start"), rec.get(f"{c}_end"), rec.get(f"{c}_delta")]
    cols += ["src", "n_samples", "created_ts"]
    vals += [BACKFILL_SRC, 0, now]
    ph = ",".join(["?"] * len(vals))
    conn.execute(f"INSERT OR REPLACE INTO nq_energy_daily ({','.join(cols)}) VALUES ({ph})", vals)
    # Fixpunkt (Tagesanfang, kumulativ) — nur wenn Startstand vorhanden.
    if rec.get("wh_imp_start") is not None or rec.get("wh_exp_start") is not None:
        conn.execute(
            "INSERT OR REPLACE INTO nq_energy_checkpoint "
            "(ts, day, wh_imp, wh_exp, varh_imp, varh_exp, vah) VALUES (?,?,?,?,?,?,?)",
            [_day_start_ts(rec["day"]), rec["day"],
             rec.get("wh_imp_start"), rec.get("wh_exp_start"), None, None, None],
        )


def backfill(from_day: str | None, to_day: str | None, commit: bool) -> dict:
    first_pac = _first_real_pac_day()
    # Standard-Ende: Tag vor PAC-Start (echte PAC-Tage nie berühren).
    if to_day is None:
        if first_pac:
            t = time.strptime(first_pac, "%Y-%m-%d")
            to_day = time.strftime("%Y-%m-%d", time.localtime(time.mktime(
                (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) - 86400))
        else:
            to_day = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    if from_day is None:
        from_day = "2000-01-01"  # _pv_daily_rows begrenzt ohnehin auf vorhandene Tage

    pv_rows = _pv_daily_rows(from_day, to_day)
    now = int(time.time())
    written = 0
    skipped_real = 0
    months: set[str] = set()
    years: set[str] = set()
    conns: dict[str, sqlite3.Connection] = {}

    def _conn_for(month: str) -> sqlite3.Connection:
        if month not in conns:
            conns[month] = open_db(os.path.join(_db_dir(), f"nq_{month}.db"), PRIMARY_SCHEMA)
        return conns[month]

    try:
        for rec in pv_rows:
            day = rec["day"]
            if first_pac and day >= first_pac:
                continue  # Sicherheitsnetz: nie in die PAC-Ära schreiben
            month = day[:7]
            conn = _conn_for(month)
            src = _existing_src(conn, day)
            if src in REAL_SRC:
                skipped_real += 1
                continue
            if commit:
                _write_daily(conn, rec, now)
            written += 1
            months.add(month)
            years.add(day[:4])
        if commit:
            for conn in conns.values():
                conn.commit()
    finally:
        for conn in conns.values():
            conn.close()

    # Monats-/Jahres-Fixpunkte aus den (jetzt gefüllten) Tagesdaten neu rollen.
    rolled_months, rolled_years = [], []
    if commit:
        for m in sorted(months):
            rolled_months.append(nq_energy_rollup.rollup_month(m))
        for y in sorted(years):
            rolled_years.append(nq_energy_rollup.rollup_year(y))

    return {
        "commit": commit,
        "range": [pv_rows[0]["day"] if pv_rows else None,
                  pv_rows[-1]["day"] if pv_rows else None],
        "first_pac_day": first_pac,
        "pv_days_found": len(pv_rows),
        "days_written": written,
        "days_skipped_real": skipped_real,
        "months_affected": sorted(months),
        "years_affected": sorted(years),
        "rolled_months": rolled_months,
        "rolled_years": rolled_years,
    }


def main() -> int:
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Energie-Fixpunkt-Backfill aus PV-DB (einmalig)")
    ap.add_argument("--from", dest="from_day", default=None, help="Start YYYY-MM-DD (Default: früheste daily_data)")
    ap.add_argument("--to", dest="to_day", default=None, help="Ende YYYY-MM-DD (Default: Tag vor PAC-Start)")
    ap.add_argument("--commit", action="store_true", help="Tatsächlich schreiben (Default: Dry-Run)")
    a = ap.parse_args()
    res = backfill(a.from_day, a.to_day, a.commit)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not a.commit:
        print("\n[DRY-RUN] Nichts geschrieben. Mit --commit ausführen.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
