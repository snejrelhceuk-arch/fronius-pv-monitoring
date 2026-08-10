#!/usr/bin/env python3
"""
diagnos/log_health.py — Read-only Ueberlaufwache fuer persistente Logs.

Schicht D prueft die Groesse der Wartungs-/Diagnose-Logs unter ``logs/`` und
meldet einen Ueberlauf (z. B. haengende Rotation). Bewusst endlos gefuehrte
Nachweisdateien (``wp_netzbetreiber_leistung.csv`` — rechtlicher Langzeit-
nachweis) werden nur berichtet, nie alarmiert.

Rotierende Laufzeit-Logs auf ``/tmp`` (tmpfs) verschwinden beim Reboot und
werden von ``scripts/logrotate.sh`` bewirtschaftet — sie sind hier nicht
Gegenstand der Pruefung.
"""

import os
from typing import List

from diagnos.config import (
    CRIT, FAIL, OK, WARN,
    LOG_DIR, LOG_OVERFLOW_WARN_MB, LOG_OVERFLOW_CRIT_MB, LOG_ENDLESS_FILES,
)

_SEV_ORDER = {OK: 0, WARN: 1, CRIT: 2, FAIL: 3}


def _walk_logs() -> List[dict]:
    entries = []
    for root, _dirs, files in os.walk(LOG_DIR):
        for name in files:
            path = os.path.join(root, name)
            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
            except OSError:
                continue
            rel = os.path.relpath(path, LOG_DIR)
            entries.append({
                'name': rel,
                'size_mb': round(size_mb, 2),
                'endless': name in LOG_ENDLESS_FILES,
            })
    return entries


def check_log_health() -> dict:
    """Groessen-/Ueberlaufcheck fuer persistente Logs unter logs/."""
    if not os.path.isdir(LOG_DIR):
        return {'check': 'log_health', 'severity': OK, 'skipped': True,
                'detail': 'kein logs/-Verzeichnis'}
    try:
        entries = _walk_logs()
    except OSError as exc:
        return {'check': 'log_health', 'severity': FAIL, 'error': str(exc)}

    severity = OK
    problems = []
    for e in entries:
        if e['endless']:
            continue
        if e['size_mb'] >= LOG_OVERFLOW_CRIT_MB:
            sev = CRIT
        elif e['size_mb'] >= LOG_OVERFLOW_WARN_MB:
            sev = WARN
        else:
            continue
        if _SEV_ORDER[sev] > _SEV_ORDER[severity]:
            severity = sev
        problems.append(f"{e['name']} {e['size_mb']:.0f} MB")

    entries.sort(key=lambda x: x['size_mb'], reverse=True)
    out = {
        'check': 'log_health',
        'severity': severity,
        'file_count': len(entries),
        'total_mb': round(sum(e['size_mb'] for e in entries), 1),
        'files': entries[:12],
    }
    if problems:
        out['error'] = 'Log-Ueberlauf (Rotation pruefen): ' + ', '.join(problems)
    return out
