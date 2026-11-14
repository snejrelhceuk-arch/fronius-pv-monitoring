#!/usr/bin/env python3
"""scripts/solarweb_compare.py — Abgleich Solarweb <-> eigene DB-Tagesdaten.

Erzeugt/aktualisiert ``doc/csv/abgleich_YYYY-MM_daily_vs_pvsystem.csv`` aus der
Solarweb-Arbeits-CSV (``doc/csv/solarweb_daily_YYYY-MM_working.csv``) und den
Tageswerten aus ``daily_data`` (``config.DB_PATH``). Vergleicht die fuenf
Energie-Leitgroessen PV/Netzbezug/Einspeisung/Batterie-Laden/Verbrauch und
meldet die groessten Abweichungen per Mail.

Kein Live-Abruf standardmaessig — arbeitet auf vorhandenen Solarweb-CSVs. Mit
``--fetch`` wird vorab ``fetch_solarweb_daily.py`` versucht (nur wenn Credentials
hinterlegt; sonst uebersprungen). So bleibt der Timer auch nach Entfernen der
Solarweb-Credentials lauffaehig (self-checking).

Spalten der Abgleich-CSV (Bestandsformat, `;`-getrennt):
  date; sw_pv; lo_pv; delta_pv; delta_pv_pct; sw_bezug; lo_bezug; delta_bezug;
  sw_einsp; lo_einsp; delta_einsp; sw_batt_in; lo_batt_in; delta_batt_in;
  sw_verbr; lo_verbr; delta_verbr        (delta = lokal - solarweb)

Neustart-fest/defensiv: fehlende CSV/DB -> Meldung, kein Fehler. Exit immer 0.

Nutzung:
  .venv/bin/python scripts/solarweb_compare.py [--month YYYY-MM] [--fetch]
                                               [--no-mail] [--threshold 2.0]
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pv_notify import host_label, send_mail  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

CSV_DIR = os.path.join(REPO_ROOT, "doc", "csv")

# solarweb-CSV-Feld -> (daily_data-Spalte, abgleich-Praefix)
METRICS = [
    ("gesamt_prod_kwh", "W_PV_total", "pv"),
    ("netzbezug_kwh", "W_Imp_Netz_total", "bezug"),
    ("einspeisung_kwh", "W_Exp_Netz_total", "einsp"),
    ("in_batt_kwh", "W_Batt_Charge_total", "batt_in"),
    ("verbrauch_kwh", "W_Consumption_total", "verbr"),
]


def _ts_for(day: str) -> int:
    dt = datetime.strptime(day, "%Y-%m-%d").replace(
        hour=0, minute=0, second=0, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _try_fetch(month: str) -> str:
    fetch = os.path.join(SCRIPTS_DIR, "fetch_solarweb_daily.py")
    secrets = os.path.join(REPO_ROOT, ".secrets")
    if not os.path.exists(fetch) or not os.path.exists(secrets):
        return "Fetch uebersprungen (Skript oder .secrets fehlt)."
    y, m = month.split("-")
    try:
        p = subprocess.run([sys.executable, fetch, "--year", y, "--month", str(int(m))],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
        return f"Fetch rc={p.returncode}: {(p.stdout or p.stderr).strip()[-200:]}"
    except Exception as e:  # noqa: BLE001
        return f"Fetch-Fehler: {e}"


def _load_solarweb(month: str) -> dict[str, dict]:
    path = os.path.join(CSV_DIR, f"solarweb_daily_{month}_working.csv")
    rows: dict[str, dict] = {}
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            d = (r.get("date") or "").strip()
            if d:
                rows[d] = r
    return rows


def _load_db(days: list[str]) -> dict[str, dict]:
    import config
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(config.DB_PATH)
        cols = ", ".join(m[1] for m in METRICS)
        for day in days:
            row = con.execute(
                f"SELECT {cols} FROM daily_data WHERE ts=?", (_ts_for(day),)
            ).fetchone()
            if row:
                out[day] = {METRICS[i][1]: row[i] for i in range(len(METRICS))}
        con.close()
    except Exception as e:  # noqa: BLE001
        print(f"DB-Fehler: {e}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM (Default: aktueller Monat)")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--threshold", type=float, default=2.0,
                    help="Melde-Schwelle |delta%%| je Tag/Metrik")
    args = ap.parse_args()

    month = args.month or date.today().strftime("%Y-%m")
    host = host_label()
    notes = []
    if args.fetch:
        notes.append(_try_fetch(month))

    sw = _load_solarweb(month)
    if not sw:
        body = (f"Solarweb-Abgleich {month} — keine Solarweb-CSV gefunden "
                f"(doc/csv/solarweb_daily_{month}_working.csv).\n"
                "Nichts zu vergleichen (kein Fehler).\n" + "\n".join(notes))
        print(body)
        if not args.no_mail:
            send_mail(f"[PV-Solarweb-Abgleich] {host}: {month} keine Daten",
                      body, event="solarweb_compare")
        return 0

    days = sorted(sw.keys())
    db = _load_db(days)

    out_path = os.path.join(CSV_DIR, f"abgleich_{month}_daily_vs_pvsystem.csv")
    header = ["date"]
    for _sw, _db, pref in METRICS:
        header += [f"sw_{pref}", f"lo_{pref}", f"delta_{pref}"]
        if pref == "pv":
            header.insert(header.index("delta_pv") + 1, "delta_pv_pct")

    flagged: list[str] = []
    max_abs_pct = {pref: 0.0 for *_, pref in METRICS}
    n_cmp = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        for day in days:
            if day not in db:
                continue
            n_cmp += 1
            line = [day]
            for sw_field, db_col, pref in METRICS:
                try:
                    sw_v = round(float(sw[day].get(sw_field) or 0), 3)
                except ValueError:
                    sw_v = 0.0
                lo_v = round((db[day].get(db_col) or 0) / 1000.0, 3)
                delta = round(lo_v - sw_v, 3)
                pct = round(delta / sw_v * 100, 2) if sw_v else 0.0
                max_abs_pct[pref] = max(max_abs_pct[pref], abs(pct))
                if abs(pct) >= args.threshold:
                    flagged.append(f"{day} {pref}: sw={sw_v} lo={lo_v} Δ={delta} ({pct:+.2f}%)")
                line += [sw_v, lo_v, delta]
                if pref == "pv":
                    line.append(pct)
            w.writerow(line)

    lines = [
        f"PV-System Solarweb-Abgleich — {host}",
        f"Monat: {month}   verglichene Tage: {n_cmp}/{len(days)}",
        f"Ausgabe: doc/csv/abgleich_{month}_daily_vs_pvsystem.csv",
        "",
        "Groesste |Abweichung| je Metrik (lokal vs. Solarweb):",
    ] + [f"  {pref}: {max_abs_pct[pref]:.2f}%" for *_, pref in METRICS] + [
        "",
        f"Auffaellige Tage (|Δ| >= {args.threshold}%): {len(flagged)}",
    ] + [f"  {x}" for x in flagged[:50]]
    if len(flagged) > 50:
        lines.append(f"  ... (+{len(flagged) - 50} weitere)")
    if notes:
        lines += ["", *notes]
    body = "\n".join(lines)
    print(body)

    if not args.no_mail:
        send_mail(f"[PV-Solarweb-Abgleich] {host}: {month} — {len(flagged)} Auffaelligkeiten",
                  body, event="solarweb_compare")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Unerwarteter Fehler (defensiv geschluckt): {e}")
        sys.exit(0)
