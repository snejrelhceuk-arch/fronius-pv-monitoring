# Steuerbox — Operator-Intent-API

**Status:** Planung (Stand 2026-04-11)

Eigener Flask-Dienst auf Nicht-Standard-Port mit eingeschraenkter Aktorik.
Siehe `doc/steuerbox/` fuer Architektur, Sicherheit, ToDo und LLM-Ausfuehrungsdatei.

## Kurzbeschreibung

Die Steuerbox ist das **Operator-Cockpit** fuer das PV-System. Sie nimmt
Bedienwuensche (Intents) entgegen, validiert sie gegen Hard Guards und
uebergibt sie an Schicht C (Automation) zur Ausfuehrung. Die Steuerbox
selbst schreibt **keine Aktoren direkt** — sie ist ein kontrollierter
Vermittler zwischen Mensch und Automation.

## Dateien (geplant)

```
steuerbox/
├── __init__.py           ← Modul-Marker
├── README.md             ← Dieses Dokument
├── steuerbox_api.py      ← Flask-Einstiegspunkt (separater Port)
├── validators.py         ← Hard Guards, IP-Allowlist, Timeout-Logik
├── intent_handler.py     ← Intent-Verarbeitung und Weiterleitung an C
└── enforcer.py           ← Safety Enforcer (Timeout-Ueberwachung, Norm-Reset)
```

## Verwandte Dokumente

- [doc/steuerbox/ARCHITEKTUR.md](../doc/steuerbox/ARCHITEKTUR.md)
- [doc/steuerbox/SICHERHEIT.md](../doc/steuerbox/SICHERHEIT.md)
- [doc/steuerbox/TODO.md](../doc/steuerbox/TODO.md)
- [doc/steuerbox/LLM_AUSFUEHRUNG.md](../doc/steuerbox/LLM_AUSFUEHRUNG.md)
