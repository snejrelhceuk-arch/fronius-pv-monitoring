#!/usr/bin/env python3
"""tools/generate_volkszaehlung.py — erzeugt doc/volkszaehlung.md (Workspace-Statistik).

Auto-maintained: wird vom pre-commit-Hook aufgerufen, wenn Code-/Doku-Dateien
staged sind. Zaehlt Dateien + Zeilen je Sprache/Typ, Python nach ABCDEN-Rollen und
die groessten Python-Dateien. Deterministisch (kein Zeitstempel im Rumpf ausser Stand),
damit ein Commit ohne echte Aenderung keinen Diff erzeugt.

Aufruf:  python3 tools/generate_volkszaehlung.py [--check]
  --check: schreibt NICHT, gibt Exit 1 wenn die Datei veraltet waere.
"""
from __future__ import annotations

import os
import sys
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, 'doc', 'volkszaehlung.md')

EXCLUDE_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.mypy_cache',
                '.pytest_cache', '.ruff_cache'}

# Endung -> (Label, Bemerkung)
EXT_LANG = {
    '.py': 'Python', '.md': 'Markdown', '.csv': 'CSV', '.html': 'HTML',
    '.sh': 'Shell', '.json': 'JSON', '.txt': 'TXT', '.sql': 'SQL',
    '.js': 'JavaScript', '.css': 'CSS', '.yaml': 'YAML', '.yml': 'YAML',
    '.toml': 'TOML', '.conf': 'CONF', '.service': 'systemd', '.timer': 'systemd',
}

ROLE_DIRS = [
    ('C', 'Automation', 'automation/'),
    ('A', 'Collector', 'collector/'),
    ('B', 'Web-API', 'routes/'),
    ('D', 'Diagnos', 'diagnos/'),
    ('E', 'Steuerbox', 'steuerbox/'),
    ('N', 'Netzqualität', 'nq/'),
    ('N', 'Netzqualität (Legacy)', 'netzqualitaet/'),
]


def _count_lines(path: str) -> int:
    try:
        with open(path, 'rb') as f:
            return f.read().count(b'\n') + 1
    except OSError:
        return 0


def collect():
    lang_files: dict[str, int] = {}
    lang_lines: dict[str, int] = {}
    py_files: list[tuple[str, int]] = []
    excluded_dirs = 0
    total_bytes = 0

    for root, dirs, files in os.walk(REPO_ROOT):
        pruned = [d for d in dirs if d in EXCLUDE_DIRS]
        excluded_dirs += len(pruned)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            path = os.path.join(root, fn)
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass
            lang = EXT_LANG.get(ext)
            if not lang:
                continue
            lines = _count_lines(path)
            lang_files[lang] = lang_files.get(lang, 0) + 1
            lang_lines[lang] = lang_lines.get(lang, 0) + lines
            if ext == '.py':
                py_files.append((os.path.relpath(path, REPO_ROOT), lines))

    return lang_files, lang_lines, py_files, excluded_dirs, total_bytes


def _de(n: int) -> str:
    return f'{n:,}'.replace(',', '.')


def render() -> str:
    lang_files, lang_lines, py_files, excluded_dirs, total_bytes = collect()
    total_files = sum(lang_files.values())
    total_lines = sum(lang_lines.values())

    lines = []
    lines.append('# Volkszählung — PV-System Workspace')
    lines.append('')
    lines.append(f'> Stand: {date.today().isoformat()} · auto-generiert von '
                 '`tools/generate_volkszaehlung.py` (pre-commit).')
    lines.append('')
    lines.append('## Übersicht')
    lines.append('')
    lines.append(f'**Gesamtgröße (Textdateien gezählt):** {total_bytes // (1024 * 1024)} MB  ')
    lines.append(f'**Gesamtzeilen (Code/Doku/Daten):** {_de(total_lines)} Zeilen  ')
    lines.append(f'**Gezählte Dateien:** {_de(total_files)}  ')
    lines.append(f'**Ausgeschlossene Verzeichnisse:** {_de(excluded_dirs)} '
                 '(.venv, __pycache__, node_modules, .git …)')
    lines.append('')
    lines.append('## Nach Sprache/Typ')
    lines.append('')
    lines.append('| Sprache/Typ | Dateien | Zeilen | Anteil |')
    lines.append('|---|---|---|---|')
    for lang in sorted(lang_lines, key=lambda k: lang_lines[k], reverse=True):
        share = (lang_lines[lang] / total_lines * 100) if total_lines else 0
        lines.append(f'| **{lang}** | {_de(lang_files[lang])} | '
                     f'{_de(lang_lines[lang])} | {share:.1f}% |')
    lines.append(f'| **Total** | {_de(total_files)} | {_de(total_lines)} | 100% |')
    lines.append('')
    lines.append('## Python-Code nach ABCDEN-Rollen')
    lines.append('')
    lines.append('| Rolle | Verzeichnis | .py-Dateien | Zeilen |')
    lines.append('|---|---|---|---|')
    for role, name, d in ROLE_DIRS:
        base = os.path.join(REPO_ROOT, d)
        if not os.path.isdir(base):
            continue
        nf = nl = 0
        for r, ds, fs in os.walk(base):
            ds[:] = [x for x in ds if x not in EXCLUDE_DIRS]
            for f in fs:
                if f.endswith('.py'):
                    nf += 1
                    nl += _count_lines(os.path.join(r, f))
        if nf:
            lines.append(f'| **{role}** {name} | `{d}` | {_de(nf)} | {_de(nl)} |')
    lines.append('')
    lines.append('## Größte Python-Dateien (Top 10)')
    lines.append('')
    for path, n in sorted(py_files, key=lambda t: t[1], reverse=True)[:10]:
        lines.append(f'1. `{path}` — {_de(n)} Zeilen')
    lines.append('')
    lines.append('## Ausgeschlossene Bereiche')
    lines.append('')
    lines.append('`.git/`, `.venv/`, `__pycache__/`, `node_modules/`, Cache-Verzeichnisse '
                 'sowie Binärdateien (nur Text-/Code-Endungen werden gezählt).')
    lines.append('')
    return '\n'.join(lines) + '\n'


def main() -> int:
    check = '--check' in sys.argv[1:]
    new = render()
    old = ''
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            old = f.read()
    if new == old:
        return 0
    if check:
        print('doc/volkszaehlung.md ist veraltet (tools/generate_volkszaehlung.py)')
        return 1
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(new)
    print('doc/volkszaehlung.md aktualisiert.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
