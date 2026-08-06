# Copilot-Instructions — PV-System

**Erstes Pflichtdokument:** [`AGENTS.md`](../AGENTS.md) im Repository-Root. Lies das vollständig, bevor du irgendetwas anderes tust. Es enthält ABCDE-Rollenmodell, No-Gos, Hosts und die Lade-Hierarchie.

**Danach:** je nach Aufgabe weiterladen wie in `AGENTS.md` beschrieben — `doc/llm/INDEX.md` → konkrete Card.

## VS-Code-spezifisch

- Beim Editieren auf den **Pre-commit-Hook** achten: Code-Änderungen in `automation/`, `collector/`, `diagnos/`, `steuerbox/`, `nq/` (inkl. `nq/legacy/`), `routes/`, `web_api.py` erfordern eine begleitende Card-Aktualisierung in `doc/llm/cards/`.
- Bei Unsicherheit über Konzepte/Module: zuerst `doc/llm/INDEX.md` durchsuchen, nicht direkt in den Quellcode springen.
- File-Refs in deinen Antworten als Markdown-Links: `[file.py](file.py#L42)`.
- Lokale Web-/Smoke-Tests immer gegen **Port 8000** durchführen (z. B. `http://127.0.0.1:8000/...`), nicht gegen Port 5000.

## Knappheit

Antworten kompakt halten. Keine zusätzlichen Docstrings, Type-Hints oder „Verbesserungen" in Code, der nicht Teil der Aufgabe ist.
