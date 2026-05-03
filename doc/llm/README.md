# `doc/llm/` — Die LLM-Bibliothek (Erläuterung für Menschen)

**Zielgruppe dieser Datei:** Du, der Betreiber. Erklärt, warum es diese Bibliothek gibt, wie sie funktioniert und wie sie gepflegt wird.

## Zweck

Trennung der Doku in zwei klar adressierte Tracks:

- **Human-Track** (`doc/<bereich>/…`, `doc/SYSTEM_BRIEFING.md`, `doc/TODO.md`): ausführliche Manuals, Architektur-Entscheidungen, Begründungen, Diagramme. Für dich (heute / in zwei Jahren) und neue Mitleser.
- **LLM-Track** (`doc/llm/` + `AGENTS.md` + `.github/copilot-instructions.md`): kompakte Module-Cards (≤150 Zeilen, einheitliches Schema, YAML-Frontmatter). Für Agenten, die Code schreiben sollen — schnell scannbar, hohe Lenkungsdichte, zuverlässig auffindbar.

Beide Tracks laufen parallel, keiner ersetzt den anderen.

## Lade-Hierarchie für LLMs

| Stufe | Datei | Wann geladen |
|---|---|---|
| 1 | `AGENTS.md` (Repo-Root), `.github/copilot-instructions.md` | Tool-Auto-Load (Copilot, Claude, Cursor, …) |
| 2 | `doc/SYSTEM_BRIEFING.md` | bei jeder fachlichen Aufgabe |
| 3 | `doc/llm/INDEX.md` | wenn Aufgabe konkret wird |
| 4 | `doc/llm/cards/<…>.card.md` | gezielt, on demand |

## Card-Schema

Vorlage: `doc/llm/_TEMPLATE.md`. Pflicht-Sektionen:

- YAML-Frontmatter (`title`, `domain`, `role`, `status`, `last_review`)
- Zweck (1–3 Sätze)
- Code-Anchor (Datei:Symbol + zugehörige DBs/Configs)
- Inputs / Outputs
- Invarianten (was MUSS gelten)
- No-Gos
- Häufige Aufgaben
- Bekannte Fallstricke
- Verwandte Cards
- Human-Doku (Verweis auf Manual)

## Verzeichnisstruktur

```
doc/llm/
├── README.md          ← diese Datei
├── _TEMPLATE.md       ← Vorlage für neue Cards
├── INDEX.md           ← Trigger→Card-Mapping (Stufe 3)
├── cards/             ← die Bibliothek selbst (Stufe 4)
│   ├── automation-engine.card.md
│   ├── collector-db-schema.card.md
│   └── …
└── _drift/            ← Output der Drift-Engine (Phase 5+)
    ├── tasks/         ← offene Doku-Aufgaben
    ├── proposed/      ← Ollama-Diff-Vorschläge (optional)
    ├── done/          ← erledigte Aufgaben (Archiv)
    ├── state.json     ← interner Zustand der Engine
    └── latest.json    ← Reportgröße für Mail-Trigger
```

## Pflege-Mechanik (Doku-Engine)

Vier Schichten, die zusammen verhindern, dass die Doku vom Code abdriftet:

1. **Pre-commit-Hook** (`tools/pre_commit_doc_check.py`)
   Code-Änderung in einer Domain → Card-Update in derselben Commit erforderlich. Frontmatter und Code-Anchors werden validiert.
2. **Drift-Engine** (`tools/doc_drift_engine.py`, systemd-Timer auf Pi5)
   Vergleicht täglich Cards gegen Code-Realität (Anchors, Signaturen, `git log`-Datum). Schreibt Drift-Report.
3. **Task-Generator + optionaler Ollama-Vorschlag**
   Pro Drift ein Task-Paket in `_drift/tasks/`. Wenn lokales Ollama erreichbar und Modelfile-Hash stimmt: zusätzlicher Diff-Vorschlag in `_drift/proposed/`. Engine ist auch ohne Ollama voll funktional.
4. **Doc-Maintainer-Chatmode** (`.github/chatmodes/doc-maintainer.chatmode.md`)
   Du startest ihn in VS-Code; er liest `_drift/tasks/`, arbeitet sie mit Cloud-LLM (Copilot/Claude) ab, präsentiert Diffs zur Approval. Tool-Restriction: schreibt nur in `doc/llm/`.

## Wann neue Card schreiben?

Faustregel: jede Domäne, die in `AGENTS.md`/`SYSTEM_BRIEFING` als ABCDE-Rolle oder Submodul namentlich erscheint, bekommt mindestens eine Card. Cards bleiben ≤150 Zeilen — wenn länger, splitten.

## Wann ins Manual statt in Card?

| Card-Track | Manual-Track (`doc/<bereich>/`) |
|---|---|
| Was tun, was nicht tun, wo finden | Warum so entschieden, Hintergrund, Diagramme |
| Code-Anchors, Invarianten | Architektur-Begründungen |
| Häufige Aufgaben (3–6) | Designhistorie, Audit-Befunde |
| ≤150 Zeilen | beliebig lang |

Cards sind für **„Mach X jetzt"**. Manuals sind für **„Verstehe, warum"**.

## Aktueller Stand

- **2026-05-03:** Phase 1 (Cleanup) abgeschlossen. Phase 2 (Skelett) abgeschlossen. Phase 3 (Pilot automation + collector) folgt.

## Plan-Quelle

Der vollständige Refactor-Plan liegt in der Session-Memory des Doku-Refactor-Vorgangs. Wesentliche Entscheidungen sind in dieser Datei zusammengefasst.
