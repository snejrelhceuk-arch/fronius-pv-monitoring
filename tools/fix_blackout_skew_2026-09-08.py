#!/usr/bin/env python3
"""Einmal-Korrektur: Uhr-Skew des Blackouts 2026-09-08 zeitrichtig ruecken.

Hintergrund (s. doc/audit/2026-09-08-blackout.md): Nach dem Netzausfall bootete
der Host 10:38 mit zurueckgestellter Uhr (08:03). Alle real 10:38-13:42 erfassten
Messsaetze tragen deshalb FALSCHE Zeitstempel 08:04-11:07. Diese Insel-Phase
(Ueberfrequenz) erscheint dadurch morgens 08-11 Uhr und verfaelscht saemtliche
Tages-Charts. Der echte Total-Blackout 08:03-10:38 ist als 4-min-Luecke getarnt.

Korrektur: die verschobenen Zeilen um +OFFSET Sekunden nach vorn schieben. Damit
sitzt die Insel-Phase auf der echten Zeit (10:39-13:42) und zwischen 07:59 und
10:39 entsteht die echte (leere) Blackout-Luecke.

OFFSET = 9300 s (2 h 35 min) = reale Bootzeit (monotonic 10:38:22) minus
Dienst-Start-Wallclock (skewed 08:03:22). Kollisionsmarge zur ersten echten
Zeile nach dem NTP-Sprung (13:42:17): ~18 s -> sicher.

Idempotenz-Schutz: laeuft nur, solange verschobene Zeilen im Skew-Fenster liegen.
Reversibel: --revert schiebt exakt zurueck. Standard = Dry-Run (--apply noetig).
"""
import argparse
import sqlite3
import sys

OFFSET_S = 9300  # 2h35m
# Zwischen-Offset: schiebt den Block zunaechst in einen garantiert LEEREN
# Zukunftsbereich (10 Tage), damit der Vorwaerts-Shift trotz PK-Ueberlappung
# kollisionsfrei bleibt (Ziel- und Quellfenster ueberlappen sonst).
BIG_S = 864000
DATE = "2026-09-08"
# Lokalzeit-Fenster, das AUSSCHLIESSLICH den Skew-Block umfasst
# (pre-Blackout endet 07:59:52, post-NTP beginnt 13:42:17 -> Fenster dazwischen).
WIN_START = f"{DATE} 08:00:00"
WIN_END = f"{DATE} 11:10:00"
# Nach dem Ruecken belegte Zeilen dieses Fenster (fuer --revert / Idempotenz).
# Obergrenze EXKLUSIV vor der ersten echten Post-NTP-Zeile (raw 13:42:17,
# data_1min-Bucket 13:42:00) -> Revert fasst nur den verschobenen Insel-Block.
SHIFTED_START = f"{DATE} 10:38:00"
SHIFTED_END = f"{DATE} 13:42:00"

PRIMARY_TABLES = ["raw_data", "data_1min", "data_15min", "hourly_data"]


def _count(cur, table, ts_col, scale, lo, hi):
    cur.execute(
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE datetime({ts_col}/{scale},'unixepoch','localtime') >= ? "
        f"AND datetime({ts_col}/{scale},'unixepoch','localtime') < ?",
        (lo, hi),
    )
    return cur.fetchone()[0]


def run(db_path, tables, ts_col, unit, apply, revert):
    offset = -OFFSET_S if revert else OFFSET_S
    scale = 1000 if unit == "ms" else 1
    off_native = offset * scale
    big_native = BIG_S * scale
    src_lo, src_hi = (SHIFTED_START, SHIFTED_END) if revert else (WIN_START, WIN_END)

    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    print(f"== {db_path} ({'REVERT' if revert else 'SHIFT'} {offset:+d}s) ==")
    plan = []
    for t in tables:
        try:
            n_src = _count(cur, t, ts_col, scale, src_lo, src_hi)
        except sqlite3.OperationalError as e:
            print(f"  {t}: uebersprungen ({e})")
            continue
        print(f"  {t}: {n_src} Zeilen im Quellfenster")
        if n_src:
            plan.append(t)

    if not plan:
        print("  Nichts zu tun (bereits korrigiert oder kein Skew-Block).")
        conn.close()
        return 0

    if not apply:
        print(f"DRY-RUN: {len(plan)} Tabellen wuerden {offset:+d}s verschoben. Mit --apply ausfuehren.")
        conn.close()
        return 0

    try:
        cur.execute("BEGIN")
        for t in plan:
            # Exakte epoch-Grenzen des Quellblocks bestimmen.
            cur.execute(
                f"SELECT MIN({ts_col}), MAX({ts_col}) FROM {t} "
                f"WHERE datetime({ts_col}/{scale},'unixepoch','localtime') >= ? "
                f"AND datetime({ts_col}/{scale},'unixepoch','localtime') < ?",
                (src_lo, src_hi),
            )
            lo, hi = cur.fetchone()
            # Phase 1: in leeren Zukunftsbereich (kollisionsfrei).
            cur.execute(
                f"UPDATE {t} SET {ts_col} = {ts_col} + ? "
                f"WHERE {ts_col} >= ? AND {ts_col} <= ?",
                (big_native, lo, hi),
            )
            n1 = cur.rowcount
            # Phase 2: von dort auf die Zielposition (offset - big).
            cur.execute(
                f"UPDATE {t} SET {ts_col} = {ts_col} + ? "
                f"WHERE {ts_col} >= ? AND {ts_col} <= ?",
                (off_native - big_native, lo + big_native, hi + big_native),
            )
            n2 = cur.rowcount
            if n1 != n2:
                raise sqlite3.IntegrityError(
                    f"{t}: Phasen-Zeilenzahl divergiert ({n1} vs {n2})")
            print(f"  {t}: {n2} Zeilen {offset:+d}s verschoben")
        conn.commit()
        print(f"OK: {len(plan)} Tabellen {offset:+d}s verschoben, committed.")
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"ABBRUCH (Kollision/Divergenz) -> rollback: {e}", file=sys.stderr)
        conn.close()
        return 2
    conn.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--tables", default=",".join(PRIMARY_TABLES),
                    help="Kommaliste; Default = Primary-Tabellen")
    ap.add_argument("--ts-col", default="ts")
    ap.add_argument("--unit", choices=["s", "ms"], default="s")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    tables = [t.strip() for t in a.tables.split(",") if t.strip()]
    sys.exit(run(a.db, tables, a.ts_col, a.unit, a.apply, a.revert))


if __name__ == "__main__":
    main()
