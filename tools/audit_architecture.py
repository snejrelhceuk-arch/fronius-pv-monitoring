#!/usr/bin/env python3
"""Architektur-Audit fuer das PV-System.

Read-only. Erzeugt einen kompakten Bericht ueber:
  1. Top-N laengste .py-Dateien (Hotspot-Liste).
  2. ABCDE-Grenz-Check: importiert Web/Diagnos heimlich Schreib-APIs?
  3. Dupletten-Suche fuer ausgewaehlte Helper-Namen.
    4. Registry-Safety, Aktorimport- und systemd-Pfadbefunde.
    5. Root-vs-Subordner-Inventur (Verteilung der A-Module).

Aufruf: python3 tools/audit_architecture.py
Optional: --json fuer maschinenlesbare Ausgabe.

Befindet sich aus Audit 2026-05-16. Siehe doc/TODO.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".venv", "backup", "imports", "__pycache__", ".git", "reports", "logs"}

# ABCDE-Grenzen: Was darf wer NICHT importieren?
# B (Web) und D (Diagnos) duerfen keine Schreib-APIs anziehen.
WRITE_API_MARKERS = [
    "BatteryConfig(",  # fronius_api: enthaelt .write()
    "set_soc_min(",
    "set_soc_max(",
    "fritz_set_state(",
    "wp_modbus.write",
]
# Schichten an Pfaden ablesen
LAYER_BY_PATH = [
    ("steuerbox/", "E"),
    ("diagnos/", "D"),
    ("automation/", "C"),
    ("routes/", "B"),
    ("web_api.py", "B"),
]
HELPER_DUPLICATE_NAMES = [
    "safe_float", "safe_int", "to_bool", "parse_ts", "as_local",
    "now_local", "iso_now", "get_db", "get_db_connection", "db_connect",
]
HARD_SAFETY_RULES = {"sls_schutz", "einspeise_schutz", "wattpilot_battschutz"}
HARD_SAFETY_AKTOREN = {"batterie", "wattpilot", "fritzdect"}
ACTOR_IMPORT_ALLOWED_PREFIXES = (
    "automation/engine/",
    "tests/",
    "tools/",
)
WRITE_CLIENT_ALLOWED_PREFIXES = (
    "automation/",
    "tests/",
    "tools/",
)
WRITE_CLIENT_ALLOWED_FILES = {
    "wattpilot_read_api.py",
}
LEGACY_SYSTEMD_PATHS = ("/srv/pv-system", "/opt/pv-system")


def iter_py_files():
    for p in REPO.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        yield p


def file_len(p: Path) -> int:
    try:
        return sum(1 for _ in p.open("rb"))
    except OSError:
        return 0


def detect_layer(rel: str) -> str | None:
    for marker, layer in LAYER_BY_PATH:
        if rel.startswith(marker) or rel == marker:
            return layer
    return None


def hotspots(top_n: int = 15):
    files = [(p, file_len(p)) for p in iter_py_files()]
    files.sort(key=lambda x: x[1], reverse=True)
    return [
        {"path": str(p.relative_to(REPO)), "lines": n}
        for p, n in files[:top_n]
    ]


def boundary_violations():
    findings = []
    for p in iter_py_files():
        rel = str(p.relative_to(REPO))
        layer = detect_layer(rel)
        if layer not in ("B", "D"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for marker in WRITE_API_MARKERS:
            for m in re.finditer(re.escape(marker), text):
                # Zeile ermitteln und Kommentare/Strings ignorieren (heuristisch)
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                if line_end == -1:
                    line_end = len(text)
                line_text = text[line_start:line_end]
                stripped = line_text.lstrip()
                if stripped.startswith("#"):
                    continue
                # Marker links vom '#' liegen? Wenn '#' vor Marker, ist Marker im Kommentar.
                pre = text[line_start:m.start()]
                if "#" in pre:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                findings.append({
                    "layer": layer,
                    "path": rel,
                    "line": line,
                    "marker": marker,
                })
    return findings


def helper_duplicates():
    out = defaultdict(list)
    pattern = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(")
    for p in iter_py_files():
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    m = pattern.match(line)
                    if not m:
                        continue
                    name = m.group(1)
                    if name in HELPER_DUPLICATE_NAMES:
                        out[name].append({
                            "path": str(p.relative_to(REPO)),
                            "line": i,
                        })
        except OSError:
            continue
    # Nur echte Dupletten
    return {n: locs for n, locs in out.items() if len(locs) > 1}


def safety_registry_violations():
    path = REPO / "config" / "engine_registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return [{"path": str(path.relative_to(REPO)), "name": "<missing>", "kind": "registry", "reason": "not readable"}]
    except json.JSONDecodeError as ex:
        return [{"path": str(path.relative_to(REPO)), "name": "<json>", "kind": "registry", "reason": str(ex)}]

    findings = []
    for key, hard_names in (("regeln", HARD_SAFETY_RULES), ("aktoren", HARD_SAFETY_AKTOREN)):
        seen = set()
        for entry in data.get(key, []):
            name = entry.get("name")
            if name in hard_names:
                seen.add(name)
                if entry.get("aktiv", True) is False:
                    findings.append({
                        "path": str(path.relative_to(REPO)),
                        "kind": key,
                        "name": name,
                        "reason": "hard safety entry has aktiv=false",
                    })
        for missing in sorted(hard_names - seen):
            findings.append({
                "path": str(path.relative_to(REPO)),
                "kind": key,
                "name": missing,
                "reason": "hard safety entry missing",
            })
    return findings


def actor_import_violations():
    findings = []
    pattern = re.compile(r"^\s*(?:from|import)\s+automation\.engine\.aktoren")
    for p in iter_py_files():
        rel = str(p.relative_to(REPO))
        if rel.startswith(ACTOR_IMPORT_ALLOWED_PREFIXES):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                findings.append({"path": rel, "line": line_no, "line_text": stripped})
    return findings


def writable_client_findings():
    findings = []
    patterns = (
        "from wattpilot_api import WattpilotClient",
        "import wattpilot_api",
        "WattpilotClient(",
    )
    for p in iter_py_files():
        rel = str(p.relative_to(REPO))
        if rel == "wattpilot_api.py":
            continue
        if rel in WRITE_CLIENT_ALLOWED_FILES:
            continue
        if rel.startswith(WRITE_CLIENT_ALLOWED_PREFIXES):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if any(marker in line for marker in patterns):
                findings.append({"path": rel, "line": line_no, "line_text": stripped})
    return findings


def web_sql_write_findings():
    findings = []
    pattern = re.compile(
        r"(?:\.execute(?:many)?\(\s*)?[\"']\s*(INSERT|UPDATE|DELETE|REPLACE)\b",
        re.IGNORECASE,
    )
    for p in iter_py_files():
        rel = str(p.relative_to(REPO))
        if not (rel.startswith("routes/") or rel == "web_api.py"):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if ".execute" not in line and ".executemany" not in line and not stripped.startswith(("'", '"')):
                continue
            if pattern.search(line):
                findings.append({"path": rel, "line": line_no, "line_text": stripped[:120]})
    return findings


def systemd_path_findings():
    findings = []
    systemd_dir = REPO / "config" / "systemd"
    if not systemd_dir.exists():
        return findings
    for p in sorted(systemd_dir.glob("*.service")):
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            if any(old in line for old in LEGACY_SYSTEMD_PATHS):
                findings.append({
                    "path": str(p.relative_to(REPO)),
                    "line": line_no,
                    "line_text": line.strip(),
                })
    return findings


def root_inventory():
    out = {"root_py": [], "by_layer": defaultdict(list)}
    for p in REPO.glob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        out["root_py"].append({"path": p.name, "lines": file_len(p)})
    for p in iter_py_files():
        rel = str(p.relative_to(REPO))
        layer = detect_layer(rel)
        if layer:
            out["by_layer"][layer].append(rel)
    out["by_layer"] = {k: sorted(v) for k, v in out["by_layer"].items()}
    out["root_py"].sort(key=lambda x: x["lines"], reverse=True)
    return out


def format_text(report: dict) -> str:
    lines = []
    lines.append("# Architektur-Audit PV-System")
    lines.append("")
    lines.append("## Hotspots (Top 15)")
    for h in report["hotspots"]:
        mark = " HOT" if h["lines"] >= 800 else ""
        lines.append(f"  {h['lines']:5d}  {h['path']}{mark}")
    lines.append("")
    lines.append("## ABCDE-Grenzverletzungen (B/D ziehen Schreib-API)")
    if not report["boundary_violations"]:
        lines.append("  keine")
    else:
        for v in report["boundary_violations"]:
            lines.append(f"  [{v['layer']}] {v['path']}:{v['line']}  {v['marker']}")
    lines.append("")
    lines.append("## Helper-Dupletten (Top-Kandidaten)")
    if not report["helper_duplicates"]:
        lines.append("  keine")
    else:
        for name, locs in report["helper_duplicates"].items():
            lines.append(f"  {name}:")
            for loc in locs:
                lines.append(f"    - {loc['path']}:{loc['line']}")
    lines.append("")
    lines.append("## Safety-Registry")
    if not report["safety_registry_violations"]:
        lines.append("  keine")
    else:
        for v in report["safety_registry_violations"]:
            lines.append(f"  {v['path']} [{v['kind']}] {v['name']}: {v['reason']}")
    lines.append("")
    lines.append("## Aktorimporte ausserhalb C")
    if not report["actor_import_violations"]:
        lines.append("  keine")
    else:
        for v in report["actor_import_violations"]:
            lines.append(f"  {v['path']}:{v['line']}  {v['line_text']}")
    lines.append("")
    lines.append("## Schreibfaehige Client-Imports ausserhalb C")
    if not report["writable_client_findings"]:
        lines.append("  keine")
    else:
        for v in report["writable_client_findings"]:
            lines.append(f"  {v['path']}:{v['line']}  {v['line_text']}")
    lines.append("")
    lines.append("## Web-SQL-Schreibmarker")
    if not report["web_sql_write_findings"]:
        lines.append("  keine")
    else:
        for v in report["web_sql_write_findings"]:
            lines.append(f"  {v['path']}:{v['line']}  {v['line_text']}")
    lines.append("")
    lines.append("## systemd-Pfade mit Alt-Workspace")
    if not report["systemd_path_findings"]:
        lines.append("  keine")
    else:
        for v in report["systemd_path_findings"]:
            lines.append(f"  {v['path']}:{v['line']}  {v['line_text']}")
    lines.append("")
    lines.append("## Root-Inventar")
    lines.append("  .py-Dateien im Repo-Root (sortiert nach Laenge):")
    for f in report["root_inventory"]["root_py"]:
        lines.append(f"    {f['lines']:5d}  {f['path']}")
    lines.append("")
    lines.append("  Layer-Verteilung (Anzahl Dateien):")
    for layer in sorted(report["root_inventory"]["by_layer"]):
        files = report["root_inventory"]["by_layer"][layer]
        lines.append(f"    {layer}: {len(files)}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="JSON-Output statt Text")
    ap.add_argument("--top", type=int, default=15, help="Anzahl Hotspots (Default 15)")
    args = ap.parse_args()

    report = {
        "hotspots": hotspots(args.top),
        "boundary_violations": boundary_violations(),
        "helper_duplicates": helper_duplicates(),
        "safety_registry_violations": safety_registry_violations(),
        "actor_import_violations": actor_import_violations(),
        "writable_client_findings": writable_client_findings(),
        "web_sql_write_findings": web_sql_write_findings(),
        "systemd_path_findings": systemd_path_findings(),
        "root_inventory": root_inventory(),
    }
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_text(report))
    # Exit-Code: 1 bei harten Grenzverletzungen, sonst 0. Bekannte technische
    # Schulden (Aktorimporte/Systemd-Altpfade) bleiben Berichtsbefunde.
    return 1 if report["boundary_violations"] or report["safety_registry_violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
