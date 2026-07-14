"""nq.transfer.nq_event_transfer — Sofort-Transfer & Katalogisierung von Event-Schnipseln (Rolle N).

NQ2 WP4: Beim Event-Trigger markiert der Poller einen 200-ms-Sample (``event=1``)
in ``nq_raw_fast``. Dieses Modul baut daraus **sofort** (nicht erst beim
Tages-Transfer) einen Schnipsel: es holt das Umfeld ``[ts-pre_window, ts+post_window]``
(gekappt auf ``max_duration_s`` = 300 s) aus Tech-tmpfs, leitet Trigger/Peak/Severity
ab, entdoppelt (Cooldown 120 s + Ähnlichkeit ±30 % Amplitude / ±10 % Zeit / ≥24 h)
und schreibt ``nq_events`` (Katalog) + ``nq_event_fast``/``nq_event_medium`` (RAW)
auf Primary. Event-Log wird auf ``event_max_count`` (10000) gekappt.

Rollen-Reinheit: read-only ggü. Produktion; schreibt nur NQ-DBs.

Start:  python3 -m nq.transfer.nq_event_transfer [--hours N]
Timer:  in pv-nq-agg-transfer integrierbar oder pv-nq-event-transfer.
Doku:   doc/netzqualitaet/NQ_MODUL.md §7, doc/dev_prompt/EVENT/prompt.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

from nq.nq_common import load_config, open_db, PRIMARY_SCHEMA, BASE_DIR

# nq_raw_fast-Spaltenreihenfolge (ohne event) = nq_event_fast (ohne event_id)
_FAST_COLS = ["u_l1", "u_l2", "u_l3", "u_l12", "u_l23", "u_l31",
              "i_l1", "i_l2", "i_l3", "p_tot", "q_tot", "s_tot", "pf", "f"]
_MED_COLS = ["thd_u_l1", "thd_u_l2", "thd_u_l3", "thd_i_l1", "thd_i_l2", "thd_i_l3"]


def _tech_host(cfg: dict) -> str:
    host = os.environ.get("PV_TECH_IP")
    if not host:
        try:
            import config
            host = getattr(config, "NQ_TECH_IP", None)
        except Exception:
            host = None
    return host or cfg.get("transfer", {}).get("tech_host") or "192.0.2.181"


def _primary_db(ts: int) -> str:
    month = time.strftime("%Y-%m", time.localtime(ts))
    return os.path.join(BASE_DIR, "nq", "db", f"nq_{month}.db")


# ---------------------------------------------------------------------------
# Reine Ableitungs-/Dedup-Logik (testbar, ohne SSH/DB)
# ---------------------------------------------------------------------------
def derive_event(fast_rows: list, cfg: dict) -> dict | None:
    """Leitet aus einem Schnipsel (fast_rows: dicts mit ts_ms + Skalaren) die
    Event-Kennzahlen ab: ts_start/end, duration_s, trigger, kind, band,
    peak_quantity, peak_value, severity, dedup_key."""
    if not fast_rows:
        return None
    ts0 = fast_rows[0]["ts_ms"] // 1000
    ts1 = fast_rows[-1]["ts_ms"] // 1000
    gw = cfg.get("grenzwerte", {})

    # Kandidaten: größte normierte Abweichung bestimmt Trigger + Peak
    def _series(key):
        return [r[key] for r in fast_rows if r.get(key) is not None]

    best = None  # (norm, quantity, value, trigger, band)
    # Spannung L-N (Sprung + Bandverletzung)
    for key in ("u_l1", "u_l2", "u_l3"):
        s = _series(key)
        if not s:
            continue
        vmax, vmin = max(s), min(s)
        span = max(abs(vmax - 230.0), abs(vmin - 230.0))
        peak = vmax if abs(vmax - 230.0) >= abs(vmin - 230.0) else vmin
        norm = span / max(gw.get("u_ln_max_v", 253.0) - 230.0, 1.0)
        if best is None or norm > best[0]:
            best = (norm, key, peak, "du_step", "HF_local")
    # Strom-Sprung
    for key in ("i_l1", "i_l2", "i_l3"):
        s = [abs(v) for v in _series(key)]
        if not s:
            continue
        peak = max(s)
        norm = peak / max(gw.get("i_max_a", 35.0), 1.0)
        if best is None or norm > best[0]:
            best = (norm, key, peak, "di_step", "HF_local")
    # Frequenz
    s = _series("f")
    if s:
        dev = max(abs(max(s) - 50.0), abs(min(s) - 50.0))
        peak = max(s) if abs(max(s) - 50.0) >= abs(min(s) - 50.0) else min(s)
        norm = dev / max(gw.get("freq_max_hz", 52.0) - 50.0, 0.5)
        if best is None or norm > best[0]:
            best = (norm, "f", peak, "df_step", "NF_global")

    if best is None:
        return None
    norm, qty, peak, trigger, band = best
    kind = {"du_step": "u_step", "di_step": "i_step", "df_step": "freq_dev"}.get(trigger, trigger)
    return {
        "ts_start": ts0, "ts_end": ts1, "duration_s": max(ts1 - ts0, 0),
        "trigger": trigger, "kind": kind, "band": band,
        "peak_quantity": qty, "peak_value": round(float(peak), 3),
        "severity": round(min(max(norm, 0.0), 1.0), 3),
        "n_samples": len(fast_rows),
        "dedup_key": f"{trigger}:{qty}",
    }


def is_similar(ev: dict, prev: dict, cfg: dict) -> bool:
    """Ähnlichkeit: gleicher Trigger+Größe, Amplitude ±amp%, Zeit-Abstand < min_hours."""
    ef = cfg.get("event_filter", {})
    if ev["dedup_key"] != prev["dedup_key"]:
        return False
    amp = ef.get("dedup_amplitude_pct", 30) / 100.0
    min_h = ef.get("dedup_min_hours_apart", 24)
    pv, cv = prev.get("peak_value") or 0.0, ev.get("peak_value") or 0.0
    if abs(pv) > 1e-9 and abs(cv - pv) / abs(pv) > amp:
        return False
    hours_apart = abs(ev["ts_start"] - prev["ts_start"]) / 3600.0
    return hours_apart < min_h


def ingest_snippets(conn, snippets: list, cfg: dict) -> dict:
    """Schreibt Schnipsel idempotent nach Primary. snippets: Liste von
    ``{fast:[dict...], medium:[dict...]}``. Dedup + Cap. Returns Summary."""
    ef = cfg.get("event_filter", {})
    cooldown = ef.get("cooldown_s", 120)
    max_dur = ef.get("max_duration_s", 300)
    kept = skipped = 0
    last_kept: dict = {}   # dedup_key -> event dict

    for snip in snippets:
        fast = sorted(snip.get("fast", []), key=lambda r: r["ts_ms"])
        med = sorted(snip.get("medium", []), key=lambda r: r["ts_ms"])
        # Kappung auf max_duration_s
        if fast:
            t_lo = fast[0]["ts_ms"]
            fast = [r for r in fast if r["ts_ms"] - t_lo <= max_dur * 1000]
            med = [r for r in med if r["ts_ms"] - t_lo <= max_dur * 1000]
        ev = derive_event(fast, cfg)
        if ev is None:
            continue
        prev = last_kept.get(ev["dedup_key"])
        has_snippet = 1
        # Cooldown (120 s): kein neuer Schnipsel für denselben Trigger
        if prev and (ev["ts_start"] - prev["ts_start"]) < cooldown:
            skipped += 1
            continue
        # Ähnlichkeit (≥24 h): nur Beschreibung, kein Snippet
        if prev and is_similar(ev, prev, cfg):
            has_snippet = 0

        now = int(time.time())
        cur = conn.execute(
            "INSERT INTO nq_events (ts_start, ts_end, duration_s, band, kind, trigger, "
            "severity, peak_quantity, peak_value, origin, dedup_key, n_samples, "
            "has_snippet, metrics, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ev["ts_start"], ev["ts_end"], ev["duration_s"], ev["band"], ev["kind"],
             ev["trigger"], ev["severity"], ev["peak_quantity"], ev["peak_value"],
             "unklar", ev["dedup_key"], ev["n_samples"], has_snippet,
             json.dumps({"norm": ev["severity"]}), now),
        )
        eid = cur.lastrowid
        if has_snippet:
            conn.executemany(
                "INSERT OR REPLACE INTO nq_event_fast "
                "(ts_ms, event_id, " + ",".join(_FAST_COLS) + ") VALUES ("
                + ",".join(["?"] * (len(_FAST_COLS) + 2)) + ")",
                [[r["ts_ms"], eid] + [r.get(c) for c in _FAST_COLS] for r in fast],
            )
            if med:
                conn.executemany(
                    "INSERT OR REPLACE INTO nq_event_medium "
                    "(ts, event_id, " + ",".join(_MED_COLS) + ") VALUES ("
                    + ",".join(["?"] * (len(_MED_COLS) + 2)) + ")",
                    [[r["ts_ms"] // 1000, eid] + [r.get(c) for c in _MED_COLS] for r in med],
                )
        last_kept[ev["dedup_key"]] = ev
        kept += 1

    conn.commit()
    _cap_event_log(conn, cfg)
    return {"kept": kept, "skipped": skipped}


def _cap_event_log(conn, cfg: dict) -> int:
    """Behält höchstens event_max_count Events (älteste + Snippets löschen)."""
    cap = cfg.get("retention", {}).get("event_max_count", 10000)
    n = conn.execute("SELECT COUNT(*) FROM nq_events").fetchone()[0]
    if n <= cap:
        return 0
    over = n - cap
    ids = [r[0] for r in conn.execute(
        "SELECT event_id FROM nq_events ORDER BY created_ts ASC, event_id ASC LIMIT ?",
        (over,)).fetchall()]
    if not ids:
        return 0
    ph = ",".join(["?"] * len(ids))
    conn.execute(f"DELETE FROM nq_event_fast WHERE event_id IN ({ph})", ids)
    conn.execute(f"DELETE FROM nq_event_medium WHERE event_id IN ({ph})", ids)
    conn.execute(f"DELETE FROM nq_events WHERE event_id IN ({ph})", ids)
    conn.commit()
    return len(ids)


# ---------------------------------------------------------------------------
# SSH-Orchestrierung (Tech → Primary)
# ---------------------------------------------------------------------------
def _ssh_json(host: str, code: str, timeout: int = 60) -> str:
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
         "cd %s && python3 -" % remote_dir],
        input=code, capture_output=True, text=True, timeout=timeout, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200] or "Tech nicht erreichbar")
    return out.stdout.strip()


def transfer_events(hours: float = 5.0) -> dict:
    """Holt Event-Marker der letzten ``hours`` h von Tech, baut Schnipsel, schreibt Primary."""
    cfg = load_config()
    host = _tech_host(cfg)
    tmpfs_db = cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db")
    ef = cfg.get("event_filter", {})
    pre = ef.get("pre_window_s", 30)
    post = ef.get("post_window_s", 30)
    now = int(time.time())
    t0 = now - int(hours * 3600)

    fcols = ",".join(["ts_ms"] + _FAST_COLS)
    mcols = ",".join(["ts_ms"] + _MED_COLS)
    code = (
        "import sqlite3,json\n"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True)\n"
        f"mk=[r[0] for r in c.execute('SELECT ts_ms FROM nq_raw_fast WHERE event=1 AND ts_ms>=? ORDER BY ts_ms',({t0*1000},)).fetchall()]\n"
        "snips=[]\n"
        "for ts in mk:\n"
        f" lo=ts-{pre*1000}; hi=ts+{post*1000}\n"
        f" fr=[dict(zip([d[0] for d in cur.description],row)) for cur in [c.execute('SELECT {fcols} FROM nq_raw_fast WHERE ts_ms>=? AND ts_ms<=? ORDER BY ts_ms',(lo,hi))] for row in cur.fetchall()]\n"
        f" mr=[dict(zip([d[0] for d in cur.description],row)) for cur in [c.execute('SELECT {mcols} FROM nq_raw_medium WHERE ts_ms>=? AND ts_ms<=? ORDER BY ts_ms',(lo,hi))] for row in cur.fetchall()]\n"
        " snips.append({'fast':fr,'medium':mr})\n"
        "print(json.dumps({'markers':mk,'snippets':snips}))\n"
    )
    payload = json.loads(_ssh_json(host, code) or "{}")
    snippets = payload.get("snippets", [])
    markers = payload.get("markers", [])
    if not snippets:
        return {"markers": 0, "kept": 0, "skipped": 0}

    conn = open_db(_primary_db(t0), PRIMARY_SCHEMA)
    summary = ingest_snippets(conn, snippets, cfg)
    conn.close()

    # Marker auf Tech quittieren (event=0 setzen), damit sie nicht erneut transferiert werden
    if markers:
        ids = ",".join(str(int(m)) for m in markers)
        ack = (
            "import sqlite3\n"
            f"c=sqlite3.connect('{tmpfs_db}')\n"
            f"c.execute('UPDATE nq_raw_fast SET event=0 WHERE ts_ms IN ({ids})')\n"
            "c.commit()\n"
        )
        try:
            _ssh_json(host, ack, timeout=30)
        except Exception as exc:  # pragma: no cover
            print(f"[nq_event_transfer] Ack fehlgeschlagen: {exc}")

    summary["markers"] = len(markers)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="NQ Event-Schnipsel-Transfer (Tech → Primary)")
    ap.add_argument("--hours", type=float, default=5.0)
    a = ap.parse_args()
    print(json.dumps(transfer_events(a.hours), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
