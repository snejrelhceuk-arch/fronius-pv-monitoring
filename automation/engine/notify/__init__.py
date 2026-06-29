"""automation.engine.notify — fokussierte Helfer für den EventNotifier.

Aus event_notifier.py ausgelagert (Architektur-Refactor 2026-06-29):
  dedup      — persistenter 1×/Tag-Versandzustand (JSON)
  thresholds — reine Schwellwert-Auswertung gegen ObsState
  mail       — SMTP-Transport (zuvor 3× dupliziert)
"""
