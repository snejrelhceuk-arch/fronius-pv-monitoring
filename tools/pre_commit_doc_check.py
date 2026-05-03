#!/usr/bin/env python3
"""Pre-commit Doc-Check (Schicht 1 der Doku-Engine).

Prueft:
  1. Frontmatter-Schema in geaenderten doc/llm/cards/*.md
  2. Code-Anchors in geaenderten Cards zeigen auf existierende Dateien
  3. doc/llm/INDEX.md referenziert keine nicht-existenten Cards (Karteileichen)
  4. Geaenderte Cards haben last_review = heute

Wird vom Git pre-commit-Hook aufgerufen (siehe Setup unten). Exitet 0 bei OK,
1 bei Fehlern.

Setup als Hook (manuell, einmalig):
  echo '#!/bin/sh' > .git/hooks/pre-commit
  echo 'exec python3 tools/pre_commit_doc_check.py' >> .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit

Domain<->Pfad-Mapping (Card-Pflicht bei Code-Aenderung) folgt in Phase 4.
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "doc" / "llm" / "cards"
INDEX_FILE = REPO_ROOT / "doc" / "llm" / "INDEX.md"

REQUIRED_FRONTMATTER = {"title", "domain", "role", "status", "last_review"}
ALLOWED_STATUS = {"stable", "experimental", "deprecated"}
ALLOWED_DOMAIN = {
    "automation",
    "collector",
    "diagnos",
    "steuerbox",
    "netzqualitaet",
    "system",
    "web",
    "meta",
}

CODE_ANCHOR_RE = re.compile(r"`([^`]+\.(?:py|json|md|sh|service|timer|yaml|yml))(?::([\w_][\w\d_]*))?`")


def _staged_files() -> list[Path]:
    """Liste aller fuer Commit gestagten Dateien, relativ zum Repo-Root."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line]


def _parse_frontmatter(text: str) -> tuple[dict[str, str], int] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    block = text[4:end]
    fm: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([\w_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm, end + 5


def _check_card(card_path: Path, errors: list[str]) -> None:
    rel = card_path.relative_to(REPO_ROOT)
    text = card_path.read_text(encoding="utf-8")
    parsed = _parse_frontmatter(text)
    if parsed is None:
        errors.append(f"{rel}: kein YAML-Frontmatter")
        return
    fm, body_offset = parsed
    missing = REQUIRED_FRONTMATTER - fm.keys()
    if missing:
        errors.append(f"{rel}: Frontmatter fehlt: {sorted(missing)}")
    if "status" in fm and fm["status"] not in ALLOWED_STATUS:
        errors.append(f"{rel}: status='{fm['status']}' ungueltig (erlaubt: {sorted(ALLOWED_STATUS)})")
    if "domain" in fm and fm["domain"] not in ALLOWED_DOMAIN:
        errors.append(f"{rel}: domain='{fm['domain']}' ungueltig (erlaubt: {sorted(ALLOWED_DOMAIN)})")
    if "last_review" in fm:
        try:
            d = _dt.date.fromisoformat(fm["last_review"])
        except ValueError:
            errors.append(f"{rel}: last_review='{fm['last_review']}' kein ISO-Datum")
        else:
            today = _dt.date.today()
            if d > today:
                errors.append(f"{rel}: last_review={d} liegt in der Zukunft")
            if d != today:
                errors.append(
                    f"{rel}: last_review={d} != heute ({today}) "
                    "- Card geaendert ohne last_review-Update"
                )
    body = text[body_offset:]
    seen: set[str] = set()
    for m in CODE_ANCHOR_RE.finditer(body):
        path_part = m.group(1)
        # Nur explizite Repo-Pfade pruefen (mit `/`). Reine Dateinamen sind
        # Symbol-/Modulerwaehnungen, deren voller Pfad woanders steht.
        if "/" not in path_part:
            continue
        # Glob-Pattern und Platzhalter ueberspringen
        if "*" in path_part or "<" in path_part:
            continue
        if path_part in seen:
            continue
        seen.add(path_part)
        candidate = REPO_ROOT / path_part
        if not candidate.exists():
            errors.append(f"{rel}: Code-Anchor zeigt auf nicht existierende Datei: {path_part}")


def _check_index_consistency(errors: list[str]) -> None:
    if not INDEX_FILE.exists() or not CARDS_DIR.exists():
        return
    text = INDEX_FILE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"([\w-]+\.card\.md)", text))
    existing = {p.name for p in CARDS_DIR.glob("*.card.md")}
    karteileichen = referenced - existing
    if karteileichen:
        errors.append(
            f"doc/llm/INDEX.md referenziert nicht existierende Cards: {sorted(karteileichen)}"
        )


def main() -> int:
    staged = _staged_files()
    changed_cards = [
        p for p in staged
        if p.is_file() and p.is_relative_to(CARDS_DIR) and p.name.endswith(".card.md")
    ]

    errors: list[str] = []
    for card in changed_cards:
        _check_card(card, errors)
    if any(p.is_relative_to(REPO_ROOT / "doc" / "llm") for p in staged):
        _check_index_consistency(errors)

    if errors:
        print("Doc-Check FEHLER:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("\nUmgehung (mit Bedacht): git commit --no-verify", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
