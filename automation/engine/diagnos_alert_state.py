"""
diagnos_alert_state.py — Persistenter Diff-Zustand für Diagnos-Mailmeldungen.

Hintergrund:
  Die Sunset-Mail enthielt bisher in jeder Mail erneut alle Diagnos-Checks
  mit Severity > ok. Wiederkehrende, aber stabile Befunde (z. B. eine alte
  RAW-Datenlücke, die nicht refilled wird) erzeugten dadurch jeden Tag
  dieselbe Warnung.

Vorgehen:
  - Pro Check wird ein Fingerprint (severity + checkspezifische Hauptfelder)
    gebildet.
  - State-Datei `config/diagnos_alert_state.json` speichert pro Check den
    zuletzt gemeldeten Fingerprint + Zeitstempel.
  - Ein Befund wird nur dann in die Mail aufgenommen, wenn:
      * der Fingerprint sich gegenüber dem letzten gemeldeten unterscheidet
        (= wirklich neuer/eskalierter Zustand), ODER
      * seit der letzten Meldung mehr als REMINDER_DAYS vergangen sind
        (Heartbeat: anhaltend kaputte Sachen werden nicht für immer
        verschwiegen).
  - Wenn ein Check wieder OK wird, verfällt sein Eintrag automatisch
    (Selbstheilung).

Datenfluss ist ausschließlich automation-intern — diagnos selbst bleibt
read-only und unangetastet.

Wiederverwendung (z. B. NQ-Befunde, geplant Mai 2026):
  Das Modul ist generisch. Aufrufer müssen nur eine Liste von Check-Dicts
  liefern, die je `check` (Name) und `severity` ('ok'|'warn'|'crit'|'fail')
  enthalten. Für check-typ-spezifische Fingerprints `_fingerprint_fields()`
  um den eigenen Namespace-Prefix erweitern (z. B. `nq:flicker_pst10`
  → eigene Felder wie `pst_max`, `bucket_count`).
  Eigener State-File über `path`-Argument:
      load_state(path='config/nq_alert_state.json')
      filter_reportable(checks, state)
      save_state(new_state, path='config/nq_alert_state.json')
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

LOG = logging.getLogger('diagnos_alert_state')

# Standardpfad: <repo>/config/diagnos_alert_state.json
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config',
    'diagnos_alert_state.json',
)

REMINDER_DAYS = 7
REMINDER_S = REMINDER_DAYS * 86400

# Severities, die als "Befund" gelten. 'ok' wird ignoriert / heilt den State.
_BAD_SEVERITIES = {'warn', 'crit', 'fail'}


def _round_or_none(value, step: float):
    """Diskretisiere einen Wert auf step-Buckets, None bleibt None."""
    if value is None:
        return None
    try:
        return int(float(value) // step)
    except (TypeError, ValueError):
        return None


def _fingerprint_fields(check: dict) -> tuple:
    """Wähle pro Check-Familie die relevanten Identitätsfelder.

    Ziel: stabile Fingerprints, die sich nur dann ändern, wenn sich der
    Befund inhaltlich verändert (neue Lücken, andere Tagesabweichung,
    eskalierte Severity, neuer Fehler-Text).
    """
    name = str(check.get('check') or '')
    sev = check.get('severity') or ''

    # Gap-Scans: Anzahl + maximale Lückenlänge identifizieren neue Lücken
    if name.startswith('integrity:gaps:'):
        return (
            sev,
            check.get('gap_count'),
            check.get('max_gap_s'),
            check.get('followup_assessment') or '',
        )

    if name == 'integrity:daily_energy_balance':
        return (sev, check.get('bad_days'), _round_or_none(check.get('max_diff_wh'), 100))

    if name in ('integrity:monthly_rollup', 'integrity:yearly_rollup'):
        return (sev, _round_or_none(check.get('max_diff_kwh'), 1))

    if name == 'integrity:fronius_attachment_state':
        return (sev, check.get('assessment') or '')

    if name == 'integrity:config_json_parse':
        return (sev, check.get('error') or '', check.get('failed_count'))

    if name == 'cpu_temp':
        return (sev, _round_or_none(check.get('value_c'), 5))

    if name in ('ram', 'disk_root'):
        return (sev, _round_or_none(check.get('used_pct'), 5))

    if name == 'throttle':
        return (sev, check.get('hex') or '')

    if name.startswith('freshness:'):
        return (sev, _round_or_none(check.get('age_s'), 3600))

    if name == 'mirror_sync_age':
        return (sev, _round_or_none(check.get('age_s'), 600))

    if name == 'backup_local_gfs_daily':
        return (sev, _round_or_none(check.get('age_h'), 12))

    if name.startswith('service:'):
        return (sev, check.get('active_state') or check.get('error') or '')

    # Generischer Fallback: severity + Fehlertext
    return (sev, check.get('error') or '')


def compute_fingerprint(check: dict) -> str:
    """Stabiler String-Fingerprint eines Check-Ergebnisses."""
    return json.dumps(_fingerprint_fields(check), sort_keys=True, default=str)


def load_state(path: Optional[str] = None) -> dict:
    p = path or _DEFAULT_PATH
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning(f"Alert-State nicht lesbar ({p}): {exc} → fresh start")
        return {}


def save_state(state: dict, path: Optional[str] = None) -> None:
    p = path or _DEFAULT_PATH
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except OSError as exc:
        LOG.error(f"Alert-State nicht schreibbar ({p}): {exc}")


def filter_reportable(
    checks: list,
    state: Optional[dict] = None,
    now_ts: Optional[float] = None,
    reminder_s: int = REMINDER_S,
) -> tuple[list, dict, dict]:
    """Bestimme, welche Checks in die Mail aufgenommen werden müssen.

    Rückgabe:
      - reportable: Liste der Checks, die diesmal gemeldet werden sollen.
      - new_state:  aktualisiertes State-Dict (zum Speichern).
      - summary:    {'new': n, 'changed': n, 'reminder': n,
                     'suppressed': n, 'healed': n}

    Heilung (severity zurück auf ok) entfernt den State-Eintrag — der nächste
    erneute Befund wird dann wieder gemeldet.
    """
    if state is None:
        state = {}
    if now_ts is None:
        now_ts = time.time()

    new_state = dict(state)  # Kopie für saubere Mutation
    reportable: list = []
    summary = {'new': 0, 'changed': 0, 'reminder': 0, 'suppressed': 0, 'healed': 0}

    seen_names = set()

    for check in checks:
        name = check.get('check')
        if not name:
            continue
        seen_names.add(name)

        sev = (check.get('severity') or '').lower()
        if sev not in _BAD_SEVERITIES:
            # OK → State heilen, sodass spätere Verschlechterung wieder meldet.
            if name in new_state:
                new_state.pop(name, None)
                summary['healed'] += 1
            continue

        fp = compute_fingerprint(check)
        prev = state.get(name) or {}
        prev_fp = prev.get('fingerprint')
        prev_last = prev.get('last_reported_ts') or 0

        if prev_fp is None:
            reason = 'new'
        elif prev_fp != fp:
            reason = 'changed'
        elif (now_ts - prev_last) >= reminder_s:
            reason = 'reminder'
        else:
            reason = None

        if reason is None:
            summary['suppressed'] += 1
            continue

        # Annotiere den Grund, damit die Mail das transparent zeigen kann.
        annotated = dict(check)
        annotated['_alert_reason'] = reason
        reportable.append(annotated)
        summary[reason] += 1

        new_state[name] = {
            'fingerprint': fp,
            'severity': sev,
            'first_seen_ts': prev.get('first_seen_ts') or now_ts,
            'last_reported_ts': now_ts,
        }

    # State-Einträge für Checks, die diesmal gar nicht mehr auftauchen,
    # bleiben stehen (kein false-heal). Sie laufen erst über die
    # Reminder-Logik wieder los, wenn der Check zurückkehrt.

    return reportable, new_state, summary


def severity_counts(checks: list) -> dict:
    """Zähle severity-Vorkommen (warn/crit/fail) in einer Check-Liste."""
    counts = {'warn': 0, 'crit': 0, 'fail': 0}
    for check in checks:
        sev = (check.get('severity') or '').lower()
        if sev in counts:
            counts[sev] += 1
    return counts
