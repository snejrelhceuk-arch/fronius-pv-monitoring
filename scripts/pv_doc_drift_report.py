#!/usr/bin/env python3
"""scripts/pv_doc_drift_report.py — Doku-Drift-Pruefung + Mail-Report (Intervall 20 Tage).

Faehrt die vorhandene LLM-freie ``tools/doc_drift_engine.py`` (Schicht 2/3 der
Doku-Engine), die Code<->Card-Drift (D1 Anchor weg, D2 Review veraltet,
D3/D4 INDEX-Inkonsistenz, D5 Firmware-Versionsdrift) erkennt und als Task-Dateien
nach ``doc/llm/_drift/tasks/`` schreibt. Dieses Skript:

  1. ruft die Engine mit ``--write --cleanup`` (schreibt neue Tasks, raeumt
     veraltete weg — das ist die automatisierte "Korrektur"-Stufe, die ohne LLM
     sicher moeglich ist),
  2. zaehlt/gruppiert die offenen Drift-Tasks und
  3. verschickt eine Zusammenfassung per Mail.

Inhaltliche Card-Korrekturen bleiben bewusst ein Mensch/LLM-Schritt (die Engine
ist LLM-frei) — die Mail ist der Handlungs-Trigger.

Neustart-fest/selbstpruefend: fehlende Engine/Pfade werden gemeldet, nie als
Fehler gewertet. Jeder Fehler -> Exit 0 (Oneshot-Timer nie "failed").

Nutzung: ``.venv/bin/python scripts/pv_doc_drift_report.py [--no-mail] [--no-write]``
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date

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

ENGINE = os.path.join(REPO_ROOT, "tools", "doc_drift_engine.py")
TASKS_DIR = os.path.join(REPO_ROOT, "doc", "llm", "_drift", "tasks")
CARDS_DIR = os.path.join(REPO_ROOT, "doc", "llm", "cards")
DRIFT_CLASS_RE = re.compile(r"^(D[1-5])_")


def _run_engine(write: bool) -> str:
    if not os.path.exists(ENGINE):
        return "(doc_drift_engine.py nicht gefunden)"
    cmd = [sys.executable, ENGINE] + (["--write", "--cleanup"] if write else [])
    try:
        p = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=600)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return f"(Engine-Fehler: {e})"


def _open_tasks() -> list[str]:
    try:
        return sorted(f for f in os.listdir(TASKS_DIR) if f.endswith(".md"))
    except FileNotFoundError:
        return []


def _count_cards() -> int:
    try:
        return len([f for f in os.listdir(CARDS_DIR) if f.endswith(".card.md")])
    except FileNotFoundError:
        return 0


def main() -> int:
    args = sys.argv[1:]
    engine_out = _run_engine(write="--no-write" not in args)
    tasks = _open_tasks()
    by_class: Counter[str] = Counter()
    for t in tasks:
        m = DRIFT_CLASS_RE.match(t)
        by_class[m.group(1) if m else "D?"] += 1

    host = host_label()
    lines = [
        f"PV-System Doku-Drift-Report — {host}",
        f"Datum: {date.today().isoformat()}  (Intervall 20 Tage)",
        "",
        f"Cards gesamt: {_count_cards()}",
        f"Offene Drift-Tasks: {len(tasks)}",
    ]
    if by_class:
        lines.append("  nach Klasse: " + ", ".join(
            f"{k}={by_class[k]}" for k in sorted(by_class)))
    if tasks:
        lines += ["", "Tasks (doc/llm/_drift/tasks/):"] + [f"  {t}" for t in tasks[:40]]
        if len(tasks) > 40:
            lines.append(f"  ... (+{len(tasks) - 40} weitere)")
    lines += [
        "",
        "Klassen: D1=Anchor weg, D2=Review veraltet, D3/D4=INDEX-Inkonsistenz, "
        "D5=Firmware-Versionsdrift.",
        "Inhaltliche Card-Korrektur = Doc-Maintainer-/LLM-Schritt (Engine ist LLM-frei).",
        "",
        "--- Engine-Ausgabe (gekuerzt) ---",
        "\n".join(engine_out.splitlines()[-40:]),
    ]
    body = "\n".join(lines)
    print(body)

    if "--no-mail" not in args:
        subject = f"[PV-Doku-Drift] {host}: {len(tasks)} offene Drift-Task(s)"
        if send_mail(subject, body, event="doc_drift_report"):
            print("\nMail versendet.")
        else:
            print("\nMail NICHT versendet (SMTP n/a) — Report nur im Log.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Unerwarteter Fehler (defensiv geschluckt): {e}")
        sys.exit(0)
