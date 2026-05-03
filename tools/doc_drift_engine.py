#!/usr/bin/env python3
"""Doku-Drift-Engine (Schicht 2 + 3 der Doku-Engine).

Laeuft autonom (z. B. als Pi5-Cron) und erkennt Drift zwischen Code und
LLM-Cards. Schreibt fuer jeden Befund eine Markdown-Task-Datei nach
``doc/llm/_drift/tasks/`` (LLM-agnostisches Format).

Erkannte Drift-Klassen:
  D1  ANCHOR_GONE       Code-Anchor in Card existiert nicht mehr
  D2  REVIEW_STALE      Card-`last_review` > REVIEW_MAX_DAYS und
                        applyTo-Dateien wurden danach geaendert (git mtime)
  D3  INDEX_ORPHAN      INDEX referenziert Card, die nicht existiert
  D4  INDEX_MISSING     Card existiert, ist aber nicht im INDEX gelistet

Aufruf:
  python3 tools/doc_drift_engine.py [--write] [--cleanup]

Ohne ``--write`` werden Befunde nur auf stdout gemeldet (Dry-Run).
Mit ``--cleanup`` werden veraltete Tasks (Befund nicht mehr aktuell) aus
``_drift/tasks/`` entfernt.

Der optionale Ollama-Pfad (``_drift/proposed/``) ist hier nicht
implementiert; die Engine bleibt LLM-frei. Cloud-LLM (z. B. Doc-Maintainer-
Chatmode) verarbeitet die Tasks im Doc-Maintainer-Modus.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "doc" / "llm" / "cards"
INDEX_FILE = REPO_ROOT / "doc" / "llm" / "INDEX.md"
TASKS_DIR = REPO_ROOT / "doc" / "llm" / "_drift" / "tasks"

REVIEW_MAX_DAYS = 30

CODE_ANCHOR_RE = re.compile(r"`([^`]+\.(?:py|json|md|sh|service|timer|yaml|yml))(?::([\w_][\w\d_]*))?`")


# ----------------------- Helpers ----------------------- #

def _git_mtime(path: Path) -> _dt.date | None:
    """Letzter Commit-Zeitstempel der Datei (Datum)."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(path)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        s = out.stdout.strip()
        if not s:
            return None
        return _dt.date.fromisoformat(s)
    except Exception:
        return None


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    fm: dict[str, str] = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([\w_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def _iter_cards() -> list[Path]:
    if not CARDS_DIR.exists():
        return []
    return sorted(CARDS_DIR.glob("*.card.md"))


def _glob_apply_to(pattern: str) -> list[Path]:
    """`applyTo`-Pattern (glob) zu konkreten Dateien aufloesen."""
    if not pattern:
        return []
    return [p for p in REPO_ROOT.glob(pattern) if p.is_file()]


# ----------------------- Drift-Checks ----------------------- #

def check_anchor_gone(card: Path) -> list[tuple[str, str]]:
    """D1: Code-Anchor zeigt auf nicht-existierende Datei."""
    text = card.read_text(encoding="utf-8")
    findings: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in CODE_ANCHOR_RE.finditer(text):
        path_part = m.group(1)
        if "/" not in path_part or "*" in path_part or "<" in path_part:
            continue
        if path_part in seen:
            continue
        seen.add(path_part)
        if not (REPO_ROOT / path_part).exists():
            findings.append(("D1", f"Code-Anchor `{path_part}` existiert nicht mehr"))
    return findings


def check_review_stale(card: Path) -> list[tuple[str, str]]:
    """D2: Review-Datum alt UND applyTo-Dateien danach geaendert."""
    fm = _parse_frontmatter(card.read_text(encoding="utf-8"))
    review_str = fm.get("last_review", "")
    apply_to = fm.get("applyTo", "").strip().strip('"').strip("'")
    if not review_str or not apply_to:
        return []
    try:
        review = _dt.date.fromisoformat(review_str)
    except ValueError:
        return [("D2", f"`last_review` unparsebar: '{review_str}'")]
    age = (_dt.date.today() - review).days
    if age <= REVIEW_MAX_DAYS:
        return []
    files = _glob_apply_to(apply_to)
    if not files:
        return []
    newer: list[Path] = []
    for f in files:
        m = _git_mtime(f)
        if m and m > review:
            newer.append(f)
    if not newer:
        return []
    rel = ", ".join(str(p.relative_to(REPO_ROOT)) for p in newer[:5])
    suffix = f" (+{len(newer) - 5} weitere)" if len(newer) > 5 else ""
    return [("D2", f"`last_review`={review} (Alter {age}d) — applyTo-Dateien danach geaendert: {rel}{suffix}")]


def check_index_consistency() -> list[tuple[str, str, str]]:
    """D3/D4: INDEX-Konsistenz. Liefert (klasse, scope, msg)."""
    if not INDEX_FILE.exists() or not CARDS_DIR.exists():
        return []
    text = INDEX_FILE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"([\w-]+\.card\.md)", text))
    existing = {p.name for p in CARDS_DIR.glob("*.card.md")}
    findings: list[tuple[str, str, str]] = []
    for orphan in sorted(referenced - existing):
        findings.append(("D3", "INDEX.md", f"INDEX referenziert nicht existierende Card: {orphan}"))
    for missing in sorted(existing - referenced):
        findings.append(("D4", missing, f"Card {missing} ist nicht im INDEX gelistet"))
    return findings


# ----------------------- Task-Output ----------------------- #

def _task_filename(klasse: str, scope: str, sig: str) -> str:
    safe_scope = scope.replace("/", "_").replace(" ", "_")
    return f"{klasse}_{safe_scope}_{sig}.md"


def _write_task(klasse: str, scope: str, msg: str, signature: str, write: bool) -> Path:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    fname = _task_filename(klasse, Path(scope).stem, signature)
    target = TASKS_DIR / fname
    body = (
        f"# Drift-Task {klasse} — {scope}\n\n"
        f"**Erkannt:** {_dt.date.today().isoformat()}\n"
        f"**Klasse:** {klasse}\n"
        f"**Scope:** `{scope}`\n\n"
        f"## Befund\n{msg}\n\n"
        f"## Aktion\n"
        f"- Card pruefen, anpassen, `last_review` auf heute setzen.\n"
        f"- Pre-commit-Hook validiert die Korrektur.\n"
        f"- Wenn Befund obsolet: Task-Datei manuell loeschen oder `--cleanup` laufen lassen.\n"
    )
    if write:
        target.write_text(body, encoding="utf-8")
    return target


def _signature(msg: str) -> str:
    """Stabile Kurz-Signatur fuer Task-Dateinamen (vermeidet Duplikate)."""
    return re.sub(r"[^a-z0-9]+", "-", msg.lower())[:40].strip("-")


# ----------------------- Main ----------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Tasks schreiben (sonst Dry-Run)")
    ap.add_argument("--cleanup", action="store_true", help="Veraltete Tasks entfernen")
    args = ap.parse_args()

    expected: set[Path] = set()
    findings: list[tuple[str, str, str]] = []  # (klasse, scope, msg)

    for card in _iter_cards():
        rel = str(card.relative_to(REPO_ROOT))
        for klasse, msg in check_anchor_gone(card):
            findings.append((klasse, rel, msg))
        for klasse, msg in check_review_stale(card):
            findings.append((klasse, rel, msg))

    findings.extend(check_index_consistency())

    for klasse, scope, msg in findings:
        sig = _signature(msg)
        target = _write_task(klasse, scope, msg, sig, write=args.write)
        expected.add(target)
        marker = "[would write]" if not args.write else "[wrote]"
        print(f"{marker} {klasse} {scope}: {msg}")

    if args.cleanup and TASKS_DIR.exists():
        for old in TASKS_DIR.glob("*.md"):
            if old not in expected:
                old.unlink()
                print(f"[removed] {old.relative_to(REPO_ROOT)}")

    print(f"\nGesamt: {len(findings)} Drift-Befunde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
