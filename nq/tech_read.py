"""nq.tech_read — Primary-seitiges read-only Lesen der NQ-Zeitreihen von Tech.

Liefert das 5-min-Aggregat (``nq_5min``) aus Techs tmpfs im **Wide-Format**
(``[{ts, quantity1, quantity2, ...}]``) — identisch zum Format von
``/api/realtime_smart``, damit das bestehende Maschinenraum-Charting die NQ-DB
ohne Änderung darstellen kann.

Aktuell read-only via SSH (Tech tmpfs). Kann später transparent auf eine
Primary-lokale NQ-DB umgestellt werden. Rolle N, kein Schreibpfad.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from nq.nq_common import load_config, BASE_DIR


def _tech_host(cfg: dict) -> str:
    """Resolve Tech host: ENV > .infra.local > config > fallback."""
    host = os.environ.get("PV_TECH_IP")
    if not host:
        # Versuche .infra.local zu laden (EnvironmentFile in systemd)
        infra_file = os.path.join(BASE_DIR, ".infra.local")
        if os.path.exists(infra_file):
            try:
                with open(infra_file, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith("PV_TECH_IP="):
                            host = line.split("=", 1)[1].strip()
                            break
            except Exception:
                pass
    if not host:
        try:
            import config
            host = getattr(config, "NQ_TECH_IP", None)
        except Exception:
            host = None
    return host or cfg.get("transfer", {}).get("tech_host") or "192.0.2.181"


def _fetch_agg_primary(start: int, end: int, resolution: int = 300) -> dict | None:
    """Fallback: Liest nq_5min von lokalen Primary-DBs (nq/db/nq_YYYY-MM.db).
    
    Gibt None zurück, wenn keine DB vorhanden oder leer. Otherwise dict wie fetch_agg().
    """
    from datetime import datetime, timedelta
    from glob import glob
    
    res = max(int(resolution), 300)
    nq_dir = os.path.join(BASE_DIR, "nq", "db")
    if not os.path.isdir(nq_dir):
        return None
    
    # Sammle alle NQ-DBs im Fenster [start, end]
    db_paths = []
    d = datetime.fromtimestamp(start)
    end_d = datetime.fromtimestamp(end)
    while d <= end_d:
        db_path = os.path.join(nq_dir, f"nq_{d.strftime('%Y-%m')}.db")
        if os.path.exists(db_path):
            db_paths.append(db_path)
        d += timedelta(days=32)
    
    if not db_paths:
        return None
    
    try:
        import sqlite3
        buckets: dict[int, dict] = {}
        quantities: set[str] = set()
        
        for db_path in db_paths:
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
                rows = conn.execute(
                    f"SELECT CAST(ts/{res} AS INT)*{res} tb, quantity, "
                    f"AVG(vavg), MIN(vmin), MAX(vmax) FROM nq_5min "
                    f"WHERE ts>={int(start)} AND ts<={int(end)} AND meas='' "
                    f"GROUP BY tb,quantity ORDER BY tb"
                ).fetchall()
                conn.close()
                
                for tb, q, vavg, vmin, vmax in rows:
                    row = buckets.setdefault(tb, {"ts": tb})
                    row[q] = vavg
                    quantities.add(q)
            except Exception:
                continue
        
        if not buckets:
            return None
        
        data = [buckets[k] for k in sorted(buckets)]
        return {"data": data, "quantities": sorted(quantities),
                "source": "nq_primary_5min", "points": len(data),
                "start": start, "end": end}
    except Exception:
        return None


def fetch_agg(start: int, end: int, resolution: int = 300) -> dict:
    """Holt nq_5min [start,end] von Tech (SSH), mit Fallback auf Primary-DBs.

    Returns dict: ``{"data": [...wide rows...], "quantities": [...], "source": ..,
    "points": n, "start": start, "end": end}``. Bei Fehler ``error`` gesetzt.
    """
    cfg = load_config()
    host = _tech_host(cfg)
    tmpfs_db = cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db")
    res = max(int(resolution), 300)

    remote_code = (
        "import sqlite3,json\n"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True)\n"
        f"r=c.execute(\"SELECT CAST(ts/{res} AS INT)*{res} tb, quantity, "
        f"AVG(vavg), MIN(vmin), MAX(vmax) FROM nq_5min "
        f"WHERE ts>={int(start)} AND ts<={int(end)} AND meas='' "
        f"GROUP BY tb,quantity ORDER BY tb\").fetchall()\n"
        "print(json.dumps(r))\n"
    )
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    try:
        # Skript über stdin (python3 -), damit keine Shell die Anführungszeichen
        # im SQL zerlegt.
        out = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
             "cd %s && python3 -" % remote_dir],
            input=remote_code, capture_output=True, text=True, timeout=25, check=False,
        )
        if out.returncode == 0:
            triples = json.loads(out.stdout.strip() or "[]")
            # Pivot long -> wide
            buckets: dict[int, dict] = {}
            quantities: set[str] = set()
            for tb, q, vavg, vmin, vmax in triples:
                row = buckets.setdefault(tb, {"ts": tb})
                row[q] = vavg
                quantities.add(q)
            data = [buckets[k] for k in sorted(buckets)]
            return {"data": data, "quantities": sorted(quantities),
                    "source": "nq_tech_5min", "points": len(data),
                    "start": start, "end": end}
    except Exception as exc:  # pragma: no cover
        pass
    
    # Fallback auf Primary-DBs, wenn Tech nicht erreichbar/Fehler
    primary_res = _fetch_agg_primary(start, end, resolution)
    if primary_res:
        return primary_res
    
    # Kein Tech, kein Primary-Fallback
    return {"data": [], "quantities": [], "source": "nq_none",
            "points": 0, "start": start, "end": end,
            "error": "NQ-Daten nicht verfügbar (Tech/Primary nicht erreichbar)"}


# ---------------------------------------------------------------------------
# WP1: PAC-Clone Single-Reader — Live-Snapshot indirekt aus Tech-tmpfs.
# Tech ist einziger PAC-Leser; Clients pollen den Tech-Puffer (nicht den PAC).
# ---------------------------------------------------------------------------

def _ssh_python(host: str, code: str, timeout: int = 15) -> str:
    """Führt Python-Code read-only auf Tech via SSH aus (stdin), gibt stdout zurück."""
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
         "cd %s && python3 -" % remote_dir],
        input=code, capture_output=True, text=True, timeout=timeout, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200] or "Tech nicht erreichbar")
    return out.stdout.strip()


# Reverse-Maps RAW-Spalte → PAC-Snapshot-Key (Spiegel von nq_poller._FAST/_MED_COLS)
_FAST_REV = {
    "u_l1": "U_L1N", "u_l2": "U_L2N", "u_l3": "U_L3N",
    "u_l12": "U_L12", "u_l23": "U_L23", "u_l31": "U_L31",
    "i_l1": "Is_L1", "i_l2": "Is_L2", "i_l3": "Is_L3",
    "s_l1": "S_L1", "s_l2": "S_L2", "s_l3": "S_L3",
    "p_l1": "P_L1", "p_l2": "P_L2", "p_l3": "P_L3",
    "q_l1": "Q_L1", "q_l2": "Q_L2", "q_l3": "Q_L3",
    "p_tot": "P_tot", "q_tot": "Q_tot", "s_tot": "S_tot",
    "pf_l1": "PF_L1", "pf_l2": "PF_L2", "pf_l3": "PF_L3",
    "pf": "PF_tot",
    "uavg_ln": "Uavg_LN", "uavg_ll": "Uavg_LL", "isum": "Isum",
    "f": "FREQ",
}
_MED_REV = {
    "cosphi_l1": "cosphi_L1", "cosphi_l2": "cosphi_L2", "cosphi_l3": "cosphi_L3",
    "ang_l1": "ang_L1", "ang_l2": "ang_L2", "ang_l3": "ang_L3",
    "thd_u_l1": "THDu_L1", "thd_u_l2": "THDu_L2", "thd_u_l3": "THDu_L3",
    "thd_u_l12": "THDu_L12", "thd_u_l23": "THDu_L23", "thd_u_l31": "THDu_L31",
    "thd_i_l1": "THDi_L1", "thd_i_l2": "THDi_L2", "thd_i_l3": "THDi_L3",
    "idist_l1": "Idist_L1", "idist_l2": "Idist_L2", "idist_l3": "Idist_L3",
    "i_n": "I_N",
    "unbal_u": "Unbal_U", "unbal_i": "Unbal_I",
}
_ENERGY_REV = {"wh_imp": "Wh_imp", "wh_exp": "Wh_exp",
               "varh_imp": "varh_imp", "varh_exp": "varh_exp", "vah": "VAh"}
# Max-Werte (Block C) — Spiegel von nq_poller._MAX_COLS
_MAX_REV = {
    "umax_l1n": "Umax_L1N", "umax_l2n": "Umax_L2N", "umax_l3n": "Umax_L3N",
    "umax_l12": "Umax_L12", "umax_l23": "Umax_L23", "umax_l31": "Umax_L31",
    "imax_l1": "Imax_L1", "imax_l2": "Imax_L2", "imax_l3": "Imax_L3",
    "pmax_l1": "Pmax_L1", "pmax_l2": "Pmax_L2", "pmax_l3": "Pmax_L3",
    "freqmax": "FREQmax",
    "smax_tot": "Smax_tot", "pmax_tot": "Pmax_tot", "qmax_tot": "Qmax_tot",
}
# Harmonik meas/phase → Flat-Key-Bestandteile (Spiegel von nq_poller._HARM_PHASES)
_HARM_PH = {
    "U_LN": ("U", {1: "L1N", 2: "L2N", 3: "L3N"}),
    "U_LL": ("U", {1: "L12", 2: "L23", 3: "L31"}),
    "I": ("I", {1: "L1", 2: "L2", 3: "L3"}),
}


def _reconstruct_values(payload: dict) -> dict:
    """Baut den flachen PAC-``values``-Dict aus Tech-RAW-Zeilen zusammen."""
    vals: dict = {}
    fast = payload.get("fast") or {}
    for col, key in _FAST_REV.items():
        if col in fast and fast[col] is not None:
            vals[key] = fast[col]
    # abgeleitete Ströme (Betrag + Summe)
    isum, have = 0.0, False
    for ph in ("L1", "L2", "L3"):
        s = vals.get(f"Is_{ph}")
        if s is not None:
            vals[f"I_{ph}"] = abs(s)
            isum += s
            have = True
    if have:
        vals["Isum"] = isum
    med = payload.get("medium") or {}
    for col, key in _MED_REV.items():
        if col in med and med[col] is not None:
            vals[key] = med[col]
    en = payload.get("energy") or {}
    for col, key in _ENERGY_REV.items():
        if col in en and en[col] is not None:
            vals[key] = en[col]
    mx = payload.get("max") or {}
    for col, key in _MAX_REV.items():
        if col in mx and mx[col] is not None:
            vals[key] = mx[col]
    for meas, phase, ord_, value in (payload.get("harm") or []):
        spec = _HARM_PH.get(meas)
        if not spec or value is None:
            continue
        pfx, phmap = spec
        ph = phmap.get(phase)
        if ph:
            vals[f"H{ord_}_{pfx}_{ph}"] = value
    return vals


def fetch_tech_snapshot() -> dict:
    """Holt den letzten Fast/Medium/Slow/Energie-Stand von Tech und baut den
    PAC-Clone-Snapshot (values + screens) nach — **ohne** PAC-Direktzugriff.

    Returns ``{ok, ts, values, units, screens, source}`` (screens leer bei Fehler).
    """
    cfg = load_config()
    host = _tech_host(cfg)
    tmpfs_db = cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db")
    code = (
        "import sqlite3,json\n"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True)\n"
        "def r1(q):\n"
        " cur=c.execute(q); row=cur.fetchone()\n"
        " return dict(zip([d[0] for d in cur.description],row)) if row else None\n"
        "fast=r1('SELECT * FROM nq_raw_fast ORDER BY ts_ms DESC LIMIT 1')\n"
        "med=r1('SELECT * FROM nq_raw_medium ORDER BY ts_ms DESC LIMIT 1')\n"
        "en=r1('SELECT * FROM nq_energy_raw ORDER BY ts DESC LIMIT 1')\n"
        "mx=r1('SELECT * FROM nq_raw_max ORDER BY ts DESC LIMIT 1')\n"
        "hr=c.execute('SELECT ts FROM nq_raw_slow ORDER BY ts DESC LIMIT 1').fetchone()\n"
        "harm=c.execute('SELECT meas,phase,ord,value FROM nq_raw_slow WHERE ts=?',(hr[0],)).fetchall() if hr else []\n"
        "print(json.dumps({'fast':fast,'medium':med,'energy':en,'max':mx,'harm':harm,"
        "'ts':(fast.get('ts_ms') if fast else None)}))\n"
    )
    try:
        payload = json.loads(_ssh_python(host, code) or "{}")
    except Exception as exc:
        return {"ok": False, "ts": 0, "values": {}, "units": {}, "screens": [],
                "source": "nq_tech_tmpfs", "error": str(exc)}

    values = _reconstruct_values(payload)
    if not values:
        return {"ok": False, "ts": 0, "values": {}, "units": {}, "screens": [],
                "source": "nq_tech_tmpfs", "error": "keine Tech-Daten"}

    from nq import pac_live
    units: dict = {k: u for k, (_, u) in pac_live.FLOAT_MAP.items()}
    units.update({k: u for k, (_, u) in pac_live.FLOAT2_MAP.items()})
    units.update({k: u for k, (_, u) in pac_live.FLOAT3_MAP.items()})
    units.update({k: u for k, (_, u) in pac_live.DOUBLE_MAP.items()})
    ts_ms = payload.get("ts") or 0
    return {"ok": True, "ts": int((ts_ms or 0) / 1000) or int(time.time()),
            "values": values, "units": units,
            "screens": pac_live._build_screens(values),
            "source": "nq_tech_tmpfs"}


def fetch_tech_latest_fast() -> dict:
    """Nur der letzte Fast-Snapshot (Block-A-Skalare) von Tech — kompakt."""
    snap = fetch_tech_snapshot()
    if not snap.get("ok"):
        return snap
    return {"ok": True, "ts": snap["ts"], "values": snap["values"],
            "source": "nq_tech_tmpfs"}


# ---------------------------------------------------------------------------
# WP5: Langzeit-Aggregate aus der Primary-SD (nq_5min / nq_hourly / nq_daily).
# Läuft lokal auf Primary (kein SSH). Wide-Format wie fetch_agg.
# ---------------------------------------------------------------------------
def _primary_month_dbs(start: int, end: int) -> list:
    """Primary-Monats-DBs (nq_YYYY-MM.db), die [start,end] überlappen."""
    from datetime import datetime
    dbs, seen = [], set()
    d = datetime.fromtimestamp(start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_dt = datetime.fromtimestamp(end)
    guard = 0
    while d <= end_dt and guard < 130:
        guard += 1
        key = d.strftime("%Y-%m")
        if key not in seen:
            seen.add(key)
            p = os.path.join(BASE_DIR, "nq", "db", f"nq_{key}.db")
            if os.path.exists(p):
                dbs.append(p)
        d = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)
    return dbs


def fetch_aggregates(rng: str, start: int, end: int) -> dict:
    """Wide-Format-Aggregate der Primary-SD. rng ∈ {5min, hourly, daily}.

    Returns ``{data:[{ts, U_L1N, U_L1N_min, U_L1N_max, ...}], quantities, resolution,
    points, start, end, source}``. Nur Skalare (quantity != '').
    """
    import sqlite3
    from datetime import datetime
    table = {"5min": "nq_5min", "hourly": "nq_hourly", "daily": "nq_daily"}.get(rng)
    if not table:
        return {"data": [], "quantities": [], "error": "range muss 5min|hourly|daily sein",
                "resolution": rng, "points": 0, "start": start, "end": end}
    is_daily = rng == "daily"
    buckets: dict[int, dict] = {}
    quantities: set[str] = set()
    for db in _primary_month_dbs(start, end):
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
        except Exception:
            continue
        try:
            if is_daily:
                rows = conn.execute(
                    "SELECT day, quantity, vmin, vavg, vmax FROM nq_daily "
                    "WHERE quantity != '' ORDER BY day").fetchall()
                for day, q, vmin, vavg, vmax in rows:
                    try:
                        ts = int(datetime.strptime(day, "%Y-%m-%d").timestamp())
                    except Exception:
                        continue
                    if ts < start or ts >= end:
                        continue
                    r = buckets.setdefault(ts, {"ts": ts})
                    r[q], r[f"{q}_min"], r[f"{q}_max"] = vavg, vmin, vmax
                    quantities.add(q)
            else:
                rows = conn.execute(
                    f"SELECT ts, quantity, vmin, vavg, vmax FROM {table} "
                        "WHERE quantity != '' AND ts >= ? AND ts < ? ORDER BY ts",
                    (start, end)).fetchall()
                for ts, q, vmin, vavg, vmax in rows:
                    r = buckets.setdefault(ts, {"ts": ts})
                    r[q], r[f"{q}_min"], r[f"{q}_max"] = vavg, vmin, vmax
                    quantities.add(q)
        except Exception:
            pass
        finally:
            conn.close()
    data = [buckets[k] for k in sorted(buckets)]
    return {"data": data, "quantities": sorted(quantities), "resolution": rng,
            "points": len(data), "start": start, "end": end, "source": "nq_primary_agg"}
