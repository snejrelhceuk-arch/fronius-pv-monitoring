"""
nq_notifier.py — Mail-Skelett für Netzqualitäts-Befunde (Schicht D, Mai 2026).

Status: SKELETT — Versandlogik produktiv, NQ-Detektoren stehen erst mit
PAC4200-Inbetriebnahme im Mai 2026 zur Verfügung. Wird vom
``automation_daemon`` aktuell nicht aufgerufen (siehe ``ENABLED``).

Architektur
-----------
NQ-Befunde werden vom ``netzqualitaet``-Subsystem als Liste von Check-
Dicts geliefert (gleiches Schema wie diagnos.health/integrity):

    {
        'check': 'nq:flicker_pst10',  # eindeutiger Schlüssel je Bucket/Phasen-Kombo
        'severity': 'warn'|'crit'|'fail'|'ok',
        # checkspezifische Felder:
        'pst_max': 1.42,
        'phase': 'L1',
        'bucket': '5m',
        ...
    }

Pfade
-----
- **Sunset-Mail-Anteil** (NQ in Tagesbericht): über ``filter_reportable``
  + eigenem State-File ``config/nq_alert_state.json``. Stabile Befunde
  werden unterdrückt, Reminder nach 7 Tagen, Heilung automatisch.
- **Sofortpfad**: Trade-Switch-Detektion oder THD-Hard-Crit (Brand-/
  Geräteschutz) → ``pruefe_nq_sofortalarme()`` ruft den generischen
  ``EventNotifier._sende_diagnos_alarm`` auf.

Aktivierung
-----------
Wenn die NQ-Sammlung produktiv ist, ``ENABLED = True`` setzen und
``automation_daemon`` einklinken (bevorzugt im 10-min-Slot neben
Integrity/Health).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from automation.engine import diagnos_alert_state

LOG = logging.getLogger('nq_notifier')

# Solange das NQ-Subsystem nicht produktiv läuft, bleibt der Notifier
# inaktiv. Schalter zentral, damit der Daemon das defensiv prüfen kann.
ENABLED = False

# Eigener State-File-Pfad (separates Namespacing zu Diagnos).
NQ_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config',
    'nq_alert_state.json',
)

# Severities, die für die NQ-Sunset-Sektion akzeptiert werden.
_REPORT_SEVERITIES = {'warn', 'crit', 'fail'}

# Sofortpfad: nur fachlich begründete Trigger. Erweiterbar, sobald die
# konkreten Schwellen aus der PAC4200-Auswertung feststehen.
_SOFORT_TRIGGER_PREFIXES = (
    'nq:trade_switch',         # Trade-Switch-Erkennung
    'nq:thdu_hard',            # Verzerrungs-CRIT (Brandgefahr / Geräteschutz)
    'nq:asymmetrie_hard',      # extreme Asymmetrie
)


class NQNotifier:
    """Mail-Adapter für Netzqualitäts-Befunde.

    Bewusst getrennt von ``EventNotifier``: NQ ist ein eigenes Subsystem
    mit eigenem State-File, eigenem Lebenszyklus und eigener Aktivierung.
    Versand selbst läuft jedoch über die generischen Helper im
    EventNotifier (gleicher SMTP-Pfad, gleiche persistente Dedup).
    """

    def __init__(self, event_notifier):
        # Wir borgen uns den Versandweg vom EventNotifier — so haben wir
        # nur EINEN SMTP-Pfad, eine Credential-Quelle und eine
        # Sofort-Dedup-Datei.
        self._evn = event_notifier

    # ── Sunset-Anteil (gefiltert, nur Diff) ────────────────
    def diff_nq_befunde(self, nq_checks: list) -> tuple[set[str], dict, dict]:
        """Filtere NQ-Checks gegen ``config/nq_alert_state.json``.

        Returns:
            (reportable_check_names, summary, severity_counts)
        """
        if not nq_checks:
            return set(), {'new': 0, 'changed': 0, 'reminder': 0,
                           'suppressed': 0, 'healed': 0}, \
                          {'warn': 0, 'crit': 0, 'fail': 0}

        try:
            state = diagnos_alert_state.load_state(NQ_STATE_PATH)
        except Exception as exc:
            LOG.warning(f"NQ-State Laden fehlgeschlagen: {exc}")
            state = {}

        try:
            reportable, new_state, summary = diagnos_alert_state.filter_reportable(
                nq_checks, state
            )
        except Exception as exc:
            LOG.error(f"NQ-Filter fehlgeschlagen: {exc}")
            return set(), {'new': 0, 'changed': 0, 'reminder': 0,
                           'suppressed': 0, 'healed': 0}, \
                          {'warn': 0, 'crit': 0, 'fail': 0}

        try:
            diagnos_alert_state.save_state(new_state, NQ_STATE_PATH)
        except Exception as exc:
            LOG.warning(f"NQ-State Speichern fehlgeschlagen: {exc}")

        names = {c.get('check') for c in reportable if c.get('check')}
        sev_counts = diagnos_alert_state.severity_counts(reportable)
        return names, summary, sev_counts

    @staticmethod
    def format_nq_summary(
        nq_checks: list,
        reportable_names: Optional[set] = None,
        summary: Optional[dict] = None,
    ) -> list[str]:
        """Formatiere NQ-Sektion für die Sunset-Mail (Skelett).

        Wird vom ``EventNotifier`` über einen optionalen Hook eingebunden,
        sobald NQ produktiv ist. Aktuell nur Demonstrationsformat.
        """
        if not nq_checks:
            return [
                '',
                'Netzqualitaet (PAC4200)',
                '  Snapshot:            keine NQ-Daten verfuegbar',
            ]

        severity_map = {'ok': 'OK', 'warn': 'WARN', 'crit': 'KRIT', 'fail': 'FAIL'}
        bad = [c for c in nq_checks if (c.get('severity') or '').lower() in _REPORT_SEVERITIES]
        if reportable_names is not None:
            shown = [c for c in bad if c.get('check') in reportable_names]
            stale = len(bad) - len(shown)
        else:
            shown = bad
            stale = 0

        lines = [
            '',
            'Netzqualitaet (PAC4200)',
            f'  Befunde gesamt:      {len(bad)}'
            f' (neu/eskaliert: {len(shown)}, stabil unterdrueckt: {stale})',
        ]

        for check in shown[:8]:
            sev = severity_map.get(check.get('severity'), '—')
            reason = check.get('_alert_reason') or 'new'
            tag = f' [{reason}]' if reason and reason != 'new' else ''
            lines.append(f'  [{sev}] {check.get("check")}{tag}')

        if stale > 0:
            lines.append(
                f'  ({stale} stabile NQ-Befund(e) unterdrueckt — siehe netzqualitaet/nq_analysis.py)'
            )

        return lines

    # ── Sofortpfad (über generischen EventNotifier-Helper) ──
    def pruefe_nq_sofortalarme(self, nq_checks: list) -> list[str]:
        """Reagiere auf akute NQ-Befunde mit eigener Sofortmail.

        Akzeptiert nur Checks, deren Name mit einem ``_SOFORT_TRIGGER_PREFIXES``
        beginnt UND severity ∈ {crit, fail}. Die Versand-Dedup kommt aus
        dem EventNotifier (gleiche persistente JSON-Datei).
        """
        if not ENABLED:
            return []
        if not nq_checks:
            return []
        if self._evn is None or not getattr(self._evn, '_email', ''):
            return []

        ausgeloest: list[str] = []
        akute = {'crit', 'fail'}
        for check in nq_checks:
            name = check.get('check') or ''
            sev = (check.get('severity') or '').lower()
            if sev not in akute:
                continue
            if not any(name.startswith(p) for p in _SOFORT_TRIGGER_PREFIXES):
                continue

            alarm_key = f'{name}:{sev}'
            text = f"{name} {sev.upper()}"
            details = {k: v for k, v in check.items() if k != 'check'}
            sent = self._evn._sende_diagnos_alarm(  # noqa: SLF001
                alarm_key, text, details, kategorie='NQ'
            )
            if sent:
                ausgeloest.append(alarm_key)

        return ausgeloest
