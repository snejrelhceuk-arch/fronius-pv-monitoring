#!/usr/bin/env python3
"""IST-Zustand-Cleaner fuer die Doku (Gegenstueck zum Pre-commit-Hook).

Entfernt Changelog-/Historie-Konstrukte aus Cards und Human-Docs, damit die
Doku ausschliesslich den aktuellen Stand beschreibt (Historie lebt in git):

  - `changes:`-Block im YAML-Frontmatter von Cards
  - Body-Sektionen `## Changes` / `## Historie` / `## Aenderungshistorie` u. ae.
  - `last_review:` wird bei veraenderten Cards auf heute gesetzt

Ausnahme (nie angefasst): doc/meta/KI_BEITRAGSANALYSE.md.

Aufruf:
  python3 tools/strip_doc_history.py           # Dry-Run (zeigt nur an)
  python3 tools/strip_doc_history.py --apply    # schreibt
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "doc" / "llm" / "cards"
DOC_DIR = REPO_ROOT / "doc"
TODAY = _dt.date.today().isoformat()

ALLOWED = {"doc/meta/KI_BEITRAGSANALYSE.md"}

_HEADING = re.compile(
    r"^(#{2,6})\s+(changes|changelog|change[-\s]?log|\u00e4nderungshistorie|"
    r"versionshistorie|revision history|historie|history)\b",
    re.IGNORECASE,
)


def _strip_body_history(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    changed = False
    while i < len(lines):
        m = _HEADING.match(lines[i])
        if m:
            changed = True
            level = len(m.group(1))
            i += 1
            while i < len(lines):
                nxt = re.match(r"^(#{1,6})\s+\S", lines[i])
                if nxt and len(nxt.group(1)) <= level:
                    break
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if not changed:
        return text, False
    res = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return res, changed


def _strip_frontmatter_changes(text: str) -> tuple[str, bool]:
    if not text.startswith("---\n"):
        return text, False
    end = text.find("\n---\n", 4)
    if end < 0:
        return text, False
    fm_lines = text[4:end].split("\n")
    body = text[end + 5:]
    out: list[str] = []
    i = 0
    changed = False
    while i < len(fm_lines):
        if re.match(r"^changes:\s*$", fm_lines[i]):
            changed = True
            i += 1
            while i < len(fm_lines) and (fm_lines[i].startswith("\t") or fm_lines[i].startswith(" ")):
                i += 1
            continue
        out.append(fm_lines[i])
        i += 1
    return "---\n" + "\n".join(out) + "\n---\n" + body, changed


def _bump_last_review(text: str) -> str:
    return re.sub(
        r"(?m)^last_review:\s*\d{4}-\d{2}-\d{2}\s*$",
        f"last_review: {TODAY}",
        text,
        count=1,
    )


def _process(path: Path, is_card: bool) -> tuple[bool, str]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel in ALLOWED:
        return False, f"skip (Ausnahme): {rel}"
    text = path.read_text(encoding="utf-8")
    new = text
    notes = []
    if is_card:
        new, fm_changed = _strip_frontmatter_changes(new)
        if fm_changed:
            notes.append("changes:-Frontmatter")
    new, body_changed = _strip_body_history(new)
    if body_changed:
        notes.append("Historie-Sektion")
    if (is_card and (notes)) and new != text:
        new = _bump_last_review(new)
    if new != text:
        delta = text.count("\n") - new.count("\n")
        return True, f"CLEAN {rel}: {', '.join(notes)} (-{delta} Zeilen)"
    return False, f"ok    {rel}: nichts zu tun"


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    targets = [(p, True) for p in sorted(CARDS_DIR.glob("*.card.md"))]
    targets += [(p, False) for p in sorted(DOC_DIR.rglob("*.md"))
                if not p.is_relative_to(CARDS_DIR)]
    any_change = False
    for path, is_card in targets:
        changed, msg = _process(path, is_card)
        if changed:
            any_change = True
            print(msg)
            if apply:
                text = path.read_text(encoding="utf-8")
                new = text
                if is_card:
                    new, _ = _strip_frontmatter_changes(new)
                new, _ = _strip_body_history(new)
                if is_card:
                    new = _bump_last_review(new)
                path.write_text(new, encoding="utf-8")
    if not any_change:
        print("Nichts zu bereinigen.")
    elif not apply:
        print("\n(Dry-Run — mit --apply schreiben.)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
