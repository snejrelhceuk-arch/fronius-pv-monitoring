"""nq.tech_read — Primary-seitiges read-only Lesen der NQ-Zeitreihen von Tech.

Liefert das 10-s-Aggregat (``nq_agg_10s``) aus Techs tmpfs im **Wide-Format**
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

from nq.nq_common import load_config, BASE_DIR


def _tech_host(cfg: dict) -> str:
    host = os.environ.get("PV_TECH_IP")
    if not host:
        try:
            import config
            host = getattr(config, "NQ_TECH_IP", None)
        except Exception:
            host = None
    return host or cfg.get("transfer", {}).get("tech_host") or "192.0.2.181"


def fetch_agg(start: int, end: int, resolution: int = 10) -> dict:
    """Holt nq_agg_10s [start,end] von Tech, auf ``resolution`` (s) verdichtet.

    Returns dict: ``{"data": [...wide rows...], "quantities": [...], "source": ..,
    "points": n, "start": start, "end": end}``. Bei Fehler ``error`` gesetzt.
    """
    cfg = load_config()
    host = _tech_host(cfg)
    tmpfs_db = cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db")
    res = max(int(resolution), 10)

    remote_code = (
        "import sqlite3,json\n"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True)\n"
        f"r=c.execute(\"SELECT CAST(ts/{res} AS INT)*{res} tb, quantity, "
        f"AVG(vavg), MIN(vmin), MAX(vmax) FROM nq_agg_10s "
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
        if out.returncode != 0:
            return {"data": [], "quantities": [], "source": "nq_tech_agg10s",
                    "points": 0, "start": start, "end": end,
                    "error": out.stderr.strip()[:200] or "Tech nicht erreichbar"}
        triples = json.loads(out.stdout.strip() or "[]")
    except Exception as exc:  # pragma: no cover
        return {"data": [], "quantities": [], "source": "nq_tech_agg10s",
                "points": 0, "start": start, "end": end, "error": str(exc)}

    # Pivot long -> wide
    buckets: dict[int, dict] = {}
    quantities: set[str] = set()
    for tb, q, vavg, vmin, vmax in triples:
        row = buckets.setdefault(tb, {"ts": tb})
        row[q] = vavg
        quantities.add(q)
    data = [buckets[k] for k in sorted(buckets)]
    return {"data": data, "quantities": sorted(quantities),
            "source": "nq_tech_agg10s", "points": len(data),
            "start": start, "end": end}
