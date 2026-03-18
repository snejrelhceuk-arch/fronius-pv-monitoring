#!/usr/bin/env python3
"""
ollama_sync.py — Automatischer Wissens-Sync zum Ollama PV-System-Experten
=========================================================================
Scannt Dokumentation, Config und Code-Docstrings, generiert ein aktuelles
Modelfile und aktualisiert das Modell auf dem Ollama-Host.

Aufruf:
  python3 ollama/ollama_sync.py                # Voll-Sync (Modelfile + Ollama-Update)
  python3 ollama/ollama_sync.py --dry-run      # Nur Modelfile generieren, kein Push
  python3 ollama/ollama_sync.py --diff          # Zeige Änderungen seit letztem Sync
  python3 ollama/ollama_sync.py --force         # Erzwinge Rebuild auch ohne Änderungen

Wird automatisch getriggert von:
  - Git post-commit Hook (nach jedem Commit)
  - Cron-Job (täglich 04:00, Fallback)

Architektur:
  1. Sammle Quellen: doc/*.md, config.py, Code-Docstrings, DB-Schema
  2. Extrahiere relevante Abschnitte (keine Rohdaten, nur Wissen)
  3. Generiere System-Prompt mit Versionierung + Checksumme
  4. Vergleiche mit letztem Stand → Skip wenn identisch
  5. Baue Modelfile → scp + ollama create auf Server
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config

# ── Pfade ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
OLLAMA_DIR = BASE_DIR / 'ollama'
MODELFILE_PATH = OLLAMA_DIR / 'Modelfile'
SYNC_STATE_PATH = OLLAMA_DIR / '.sync_state.json'
CHANGELOG_PATH = OLLAMA_DIR / 'CHANGELOG.md'

# ── Ollama-Host ────────────────────────────────────────────
OLLAMA_SSH_HOST = config.load_local_setting('PV_OLLAMA_SSH_HOST', 'ollama-host')
OLLAMA_MODEL_NAME = 'pv-system-expert'
OLLAMA_BASE_MODEL = 'qwen2.5-coder:7b-instruct-q4_K_M'

# ── Quell-Dateien für Wissens-Extraktion ─────────────────────
DOC_FILES = [
    'doc/SYSTEM_ARCHITECTURE.md',
    'doc/DB_SCHEMA.md',
    'doc/AGGREGATION_PIPELINE.md',
    'doc/FELDNAMEN_REFERENZ.md',
    'doc/SCHUTZREGELN.md',
    'doc/BATTERIE_STRATEGIEN.md',
]

CODE_FILES_DOCSTRINGS = [
    'config.py',
    'web_api.py',
    'modbus_v3.py',
    'fronius_api.py',
    'battery_control.py',
    'battery_scheduler.py',
    'solar_forecast.py',
    'wattpilot_collector.py',
    'host_role.py',
    'aggregate.py',
    'automation/engine/engine.py',
    'automation/engine/automation_daemon.py',
]

CONFIG_FILES = [
    'config.py',
    'requirements.txt',
    'README.md',
]


# ═════════════════════════════════════════════════════════════
# Wissens-Extraktion
# ═════════════════════════════════════════════════════════════

def extract_doc_summary(filepath: Path, max_lines: int = 40) -> str:
    """Extrahiere Dokumentation: Nur Überschriften, Tabellen und Kernaussagen.
    
    Strategie: Behalte Überschriften (#), Tabellen (|), Codeblöcke (```),
    wichtige Markierungen (⚠️, KRITISCH, WICHTIG) und kompakte Absätze.
    Filtere leere Zeilen und redundante Fülltext-Absätze.
    """
    if not filepath.exists():
        return ''
    lines = filepath.read_text(encoding='utf-8', errors='replace').splitlines()
    
    kept = []
    in_code_block = False
    code_lines = 0
    
    for line in lines:
        stripped = line.strip()
        
        # Code-Block Tracking (max 10 Zeilen pro Block)
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            code_lines = 0
            if len(kept) < max_lines:
                kept.append(line)
            continue
        
        if in_code_block:
            code_lines += 1
            if code_lines <= 8 and len(kept) < max_lines:
                kept.append(line)
            continue
        
        # Immer behalten: Überschriften, Tabellen, Warnungen
        if (stripped.startswith('#') or
            stripped.startswith('|') or
            stripped.startswith('- ') or
            stripped.startswith('* ') or
            '⚠️' in stripped or
            'KRITISCH' in stripped or
            'WICHTIG' in stripped or
            re.match(r'^\d+\.', stripped)):
            if len(kept) < max_lines:
                kept.append(line)
        # Kompakte Info-Zeilen (Zuweisungen, Definitionen)
        elif ':' in stripped and len(stripped) < 120 and len(stripped) > 5:
            if len(kept) < max_lines:
                kept.append(line)
    
    return '\n'.join(kept).strip()


def extract_module_docstring(filepath: Path) -> str:
    """Extrahiere den Modul-Docstring + öffentliche Funktionssignaturen."""
    if not filepath.exists():
        return ''
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''

    parts = []

    # Modul-Docstring extrahieren (nur erste 8 Zeilen)
    docstring_match = re.search(r'^"""(.*?)"""', text, re.DOTALL)
    if not docstring_match:
        docstring_match = re.search(r"^'''(.*?)'''", text, re.DOTALL)
    if docstring_match:
        doc_lines = docstring_match.group(1).strip().splitlines()
        parts.append('\n'.join(doc_lines[:8]))

    # Nur öffentliche Funktionen (keine _ prefix), max 10
    count = 0
    for match in re.finditer(
        r'^(class\s+\w+.*?:|def\s+(?!_)\w+\(.*?\).*?:)\s*\n\s*"""(.*?)"""',
        text, re.MULTILINE | re.DOTALL
    ):
        if count >= 10:
            break
        sig = match.group(1).strip()
        doc = match.group(2).strip().split('\n')[0]
        parts.append(f"  {sig}  # {doc}")
        count += 1

    return '\n'.join(parts[:15])


def extract_config_values(filepath: Path) -> str:
    """Extrahiere alle Konfigurationswerte aus config.py."""
    if not filepath.exists():
        return ''
    text = filepath.read_text(encoding='utf-8', errors='replace')
    # Alle Zuweisungen auf Modul-Ebene
    assignments = []
    for line in text.splitlines():
        line_s = line.strip()
        if (re.match(r'^[A-Z_]+\s*=', line_s) and
                'import' not in line_s and
                'def ' not in line_s):
            assignments.append(line_s)
    return '\n'.join(assignments)


def extract_route_endpoints(filepath: Path) -> str:
    """Extrahiere Flask-Route-Definitionen."""
    if not filepath.exists():
        return ''
    text = filepath.read_text(encoding='utf-8', errors='replace')
    routes = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "@bp.route(" in line or "@app.route(" in line:
            route_match = re.search(r"['\"]([^'\"]+)['\"]", line)
            if route_match:
                # Nächste def-Zeile finden
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip().startswith('def '):
                        func_name = re.search(r'def\s+(\w+)', lines[j])
                        # Docstring?
                        doc = ''
                        for k in range(j + 1, min(j + 3, len(lines))):
                            if '"""' in lines[k]:
                                doc = lines[k].strip().strip('"').strip("'")
                                break
                        routes.append(
                            f"  {route_match.group(1):30s} → {func_name.group(1) if func_name else '?'}"
                            + (f"  # {doc}" if doc else "")
                        )
                        break
    return '\n'.join(routes)


def get_git_recent_changes(n: int = 20) -> str:
    """Hole die letzten n Git-Commit-Messages."""
    try:
        result = subprocess.run(
            ['git', '--no-pager', 'log', f'--oneline', f'-{n}', '--no-decorate'],
            capture_output=True, text=True, cwd=str(BASE_DIR), timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ''


def get_file_tree() -> str:
    """Erstelle eine kompakte Dateiliste."""
    tree = []
    for root, dirs, files in os.walk(str(BASE_DIR)):
        # Skip uninteressante Ordner
        dirs[:] = [d for d in dirs if d not in {
            '__pycache__', '.git', 'node_modules', 'backup', 'imports',
            '.state', 'static', 'templates',
        }]
        level = root.replace(str(BASE_DIR), '').count(os.sep)
        indent = '  ' * level
        dirname = os.path.basename(root)
        if level > 0:
            tree.append(f"{indent}{dirname}/")
        for f in sorted(files):
            if f.endswith(('.py', '.md', '.json', '.sh', '.txt', '.html')):
                tree.append(f"{indent}  {f}")
    return '\n'.join(tree[:60])  # Max 60 Einträge


# ═════════════════════════════════════════════════════════════
# System-Prompt Generierung
# ═════════════════════════════════════════════════════════════

def build_system_prompt() -> str:
    """Baue den System-Prompt: statischer Kern + dynamische Updates.
    
    Architektur:
      1. Statischer Kern (~15 KB): Handgeschriebenes, kompaktes Systemwissen
         aus ollama/system_prompt_kern.md — wird manuell gepflegt
      2. Dynamische Deltas (~5 KB): Automatisch extrahiert aus Docs/Code/Git
         für aktuelle Änderungen und frische Commits
    
    Budget: ~20 KB gesamt (≈6000 Tokens bei Qwen2.5, lässt 26K für Fragen)
    """
    sections = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # ── Statischer Kern ──────────────────────────────────────
    kern_path = OLLAMA_DIR / 'system_prompt_kern.md'
    if kern_path.exists():
        kern = kern_path.read_text(encoding='utf-8', errors='replace')
        sections.append(kern)
    else:
        sections.append("FEHLER: system_prompt_kern.md nicht gefunden!")

    # ── Dynamischer Abschnitt ────────────────────────────────
    sections.append("\n" + "═" * 65)
    sections.append(f"DYNAMISCHE UPDATES (Stand: {now})")
    sections.append("═" * 65)

    # Konfigurationswerte (kompakt)
    config_content = extract_config_values(BASE_DIR / 'config.py')
    if config_content:
        sections.append("\n--- Aktuelle Config-Werte ---")
        sections.append(config_content)

    # Letzte Git-Commits (wichtig für Kontext)
    recent = get_git_recent_changes(10)
    if recent:
        sections.append("\n--- Letzte Git-Commits ---")
        sections.append(recent)

    # Geänderte Module: nur Docstrings der kürzlich geänderten Dateien
    changed = get_changed_source_files()
    if changed:
        sections.append(f"\n--- Kürzlich geänderte Module ({len(changed)}) ---")
        for code_file in changed[:8]:
            filepath = BASE_DIR / code_file
            if filepath.suffix == '.py':
                content = extract_module_docstring(filepath)
                if content:
                    sections.append(f"\n{code_file}:")
                    # Nur erste 3 Zeilen des Docstrings
                    sections.append('\n'.join(content.splitlines()[:3]))

    # API-Endpunkte (kompakt, nur Routen-Liste)
    sections.append("\n--- API-Endpunkte ---")
    for route_file in ['routes/pages.py', 'routes/data.py', 'routes/realtime.py',
                        'routes/forecast.py', 'routes/system.py']:
        filepath = BASE_DIR / route_file
        endpoints = extract_route_endpoints(filepath)
        if endpoints:
            sections.append(endpoints)

    return '\n'.join(sections)

    return '\n'.join(sections)


def build_modelfile(system_prompt: str) -> str:
    """Baue das komplette Ollama Modelfile."""
    return f"""FROM {OLLAMA_BASE_MODEL}

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_ctx 32768
PARAMETER repeat_penalty 1.1

SYSTEM \"\"\"
{system_prompt}
\"\"\"
"""


# ═════════════════════════════════════════════════════════════
# Sync-Logik
# ═════════════════════════════════════════════════════════════

def compute_content_hash(content: str) -> str:
    """SHA256-Hash des Inhalts."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


def load_sync_state() -> dict:
    """Lade letzten Sync-Status."""
    if SYNC_STATE_PATH.exists():
        try:
            return json.loads(SYNC_STATE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_sync_state(state: dict):
    """Speichere Sync-Status."""
    SYNC_STATE_PATH.write_text(json.dumps(state, indent=2))


def get_changed_source_files() -> list[str]:
    """Finde geänderte Dateien seit letztem Sync."""
    state = load_sync_state()
    last_sync = state.get('last_sync_ts', 0)

    changed = []
    all_files = DOC_FILES + CODE_FILES_DOCSTRINGS + CONFIG_FILES
    for f in set(all_files):
        filepath = BASE_DIR / f
        if filepath.exists():
            mtime = filepath.stat().st_mtime
            if mtime > last_sync:
                changed.append(f)
    return changed


def push_to_ollama(modelfile_path: Path) -> bool:
    """Kopiere Modelfile zum Ollama-Host und erstelle das Modell."""
    print(f"  → Kopiere Modelfile nach {OLLAMA_SSH_HOST}...")
    scp = subprocess.run(
        ['scp', '-o', 'ConnectTimeout=10', str(modelfile_path),
         f'{OLLAMA_SSH_HOST}:/tmp/Modelfile'],
        capture_output=True, text=True, timeout=30
    )
    if scp.returncode != 0:
        print(f"  ✗ SCP fehlgeschlagen: {scp.stderr}")
        return False

    # Persistente Kopie in ~/ollama-config/ ablegen
    subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=10', OLLAMA_SSH_HOST,
         'cp /tmp/Modelfile ~/ollama-config/Modelfile 2>/dev/null || true'],
        capture_output=True, text=True, timeout=15
    )

    print(f"  → Erstelle Modell '{OLLAMA_MODEL_NAME}' auf {OLLAMA_SSH_HOST}...")
    create = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=10', OLLAMA_SSH_HOST,
         f'ollama create {OLLAMA_MODEL_NAME} -f /tmp/Modelfile'],
        capture_output=True, text=True, timeout=120
    )
    if create.returncode != 0:
        print(f"  ✗ ollama create fehlgeschlagen: {create.stderr}")
        return False

    print(f"  ✓ Modell '{OLLAMA_MODEL_NAME}' erfolgreich aktualisiert")
    return True


def append_changelog(changed_files: list[str], content_hash: str):
    """Füge Eintrag zum Changelog hinzu."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f"\n## {now} (Hash: {content_hash})\n"
    entry += f"Geänderte Quellen: {', '.join(changed_files[:10])}\n"

    if CHANGELOG_PATH.exists():
        existing = CHANGELOG_PATH.read_text()
    else:
        existing = "# Ollama PV-System-Expert — Sync-Changelog\n"

    CHANGELOG_PATH.write_text(existing + entry)


# ═════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Ollama PV-System-Expert Sync')
    parser.add_argument('--dry-run', action='store_true',
                        help='Nur Modelfile generieren, nicht pushen')
    parser.add_argument('--diff', action='store_true',
                        help='Zeige Änderungen seit letztem Sync')
    parser.add_argument('--force', action='store_true',
                        help='Erzwinge Rebuild auch ohne Änderungen')
    parser.add_argument('--quiet', action='store_true',
                        help='Minimale Ausgabe (für Cron/Hooks)')
    args = parser.parse_args()

    # Diff-Modus
    if args.diff:
        changed = get_changed_source_files()
        if changed:
            print(f"Geänderte Dateien seit letztem Sync ({len(changed)}):")
            for f in sorted(changed):
                print(f"  • {f}")
        else:
            print("Keine Änderungen seit letztem Sync.")
        return

    # Generierung
    if not args.quiet:
        print("╔══════════════════════════════════════════════════════════╗")
        print("║  Ollama PV-System-Expert — Wissens-Sync                 ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()

    changed_files = get_changed_source_files()
    state = load_sync_state()
    old_hash = state.get('content_hash', '')

    if not changed_files and not args.force:
        if not args.quiet:
            print("  Keine Änderungen seit letztem Sync. (--force zum Erzwingen)")
        return

    if not args.quiet:
        print(f"  {len(changed_files)} geänderte Quelle(n) erkannt")
        for f in changed_files[:5]:
            print(f"    • {f}")
        if len(changed_files) > 5:
            print(f"    ... und {len(changed_files) - 5} weitere")
        print()

    # System-Prompt bauen
    if not args.quiet:
        print("  Generiere System-Prompt...")
    system_prompt = build_system_prompt()
    new_hash = compute_content_hash(system_prompt)

    if new_hash == old_hash and not args.force:
        if not args.quiet:
            print(f"  Inhalt unverändert (Hash: {new_hash}). Überspringe.")
        return

    # Modelfile schreiben
    modelfile_content = build_modelfile(system_prompt)
    MODELFILE_PATH.write_text(modelfile_content, encoding='utf-8')

    prompt_size_kb = len(system_prompt.encode('utf-8')) / 1024
    if not args.quiet:
        print(f"  Modelfile geschrieben: {MODELFILE_PATH}")
        print(f"  System-Prompt: {prompt_size_kb:.1f} KB, Hash: {new_hash}")
        print()

    # Push zum Server
    if args.dry_run:
        if not args.quiet:
            print("  --dry-run: Kein Push zum Server.")
        return

    success = push_to_ollama(MODELFILE_PATH)

    if success:
        # State speichern
        save_sync_state({
            'content_hash': new_hash,
            'last_sync_ts': time.time(),
            'last_sync_iso': datetime.now().isoformat(),
            'changed_files': changed_files[:20],
            'prompt_size_kb': round(prompt_size_kb, 1),
        })
        append_changelog(changed_files, new_hash)
        if not args.quiet:
            print(f"\n  ✓ Sync abgeschlossen ({datetime.now().strftime('%H:%M:%S')})")
    else:
        print("\n  ✗ Sync fehlgeschlagen — Server nicht erreichbar?")
        sys.exit(1)


if __name__ == '__main__':
    main()
