"""
nq_notifier.py — Diff-Filter + Sofortpfad für Netzqualitäts-Befunde (Schicht D).

NQ-Befunde (Rolle N) liefert ``diagnos.nq_health.run_all()`` als Liste von
Check-Dicts (gleiches Schema wie diagnos.health/integrity):

    {'check': 'nq:pipeline_freshness', 'severity': 'ok'|'warn'|'crit'|'fail', ...}

Zwei Pfade, beide über den SMTP-/Dedup-Weg des ``EventNotifier``:

- **Sunset-Mail-Anteil:** ``diff_nq_befunde()`` filtert die Befunde gegen den
  eigenen State ``config/nq_alert_state.json`` (stabile unterdrücken, Reminder
  nach 7 Tagen, Heilung automatisch). Die Textzeilen baut
  ``notify/report_format.nq_summary``; die Detailtabelle steht in
  ``logs/diagnos/Netz-Status.md``.
- **Sofortpfad:** ``pruefe_nq_sofortalarme()`` reagiert auf fachlich harte
  Trigger (Trade-Switch, THD-Hard-Crit) künftiger Analyse-Detektoren.
  ``diagnos.nq_health`` selbst löst diese nicht aus — der Pfad bleibt für die
  Ereignis-Analyse reserviert.
"""

from __future__ import annotations

import logging
import os

from automation.engine import diagnos_alert_state

LOG = logging.getLogger('nq_notifier')

# Sofortpfad-Schalter (zentral). Der Sunset-Diff (diff_nq_befunde) laeuft
# unabhaengig davon; ENABLED steuert nur die harten Sofort-Trigger unten.
ENABLED = True

# Eigener State-File-Pfad (separates Namespacing zu Diagnos).
NQ_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config',
    'nq_alert_state.json',
)

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
