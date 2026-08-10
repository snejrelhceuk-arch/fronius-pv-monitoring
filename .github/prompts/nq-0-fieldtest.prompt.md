---
mode: agent
description: "NQ Phase 0 — 48h-Read-Only-Feldtest PAC4200 (Refresh-Raten messen, nichts speichern)"
---

# NQ Phase 0 — PAC4200 Read-Only-Feldtest (Tech)

Du bist Senior-Entwickler am **PV-System**, Rolle **N (Netzqualität)**.

## Pflichtlektüre zuerst (in dieser Reihenfolge)
1. [`AGENTS.md`](../../AGENTS.md) — Rollenmodell, No-Gos (v. a. „Rolle N ist read-only gegenüber Produktion").
2. [`doc/netzqualitaet/NQ_MODUL.md`](../../doc/netzqualitaet/NQ_MODUL.md) — §3 (RAM-Budget), §4 (Blöcke), §7 (Feldtest-Vorbedingung).
3. [`doc/netzqualitaet/MESSTECHNIK.md`](../../doc/netzqualitaet/MESSTECHNIK.md) — PAC4200-Fakten, Registerblöcke, offene Refresh-Fragen.

## Ziel
Ein **kleines, eigenständiges Read-Only-Skript**, das den PAC4200 mit Profil 1
(Fast 500 ms / Medium 1 s / Slow 1 s) pollt und **nur misst, ob und wann sich
Registerwerte real ändern**. Es **speichert nichts persistent** (kein DB-Write,
kein SD-Write). Erkenntnisziel: reale interne Refresh-Rate je Block — besonders
der Harmonischen (bis 64. Ordnung). Ergebnis legt die endgültigen Poll-Raten fest.

## Harte Vorgaben (No-Gos)
- **Nur Modbus TCP `read`.** Niemals in den PAC4200 schreiben. Niemals in `data.db`/Aktoren.
- **Kein persistenter Speicher.** Ausgabe nur nach stdout / optional Ausgabe in `tmpfs` (`/dev/shm`), niemals auf SD.
- **Registeradressen NICHT erfinden.** Verwende ausschließlich Adressen aus der verifizierten Siemens-PAC4200-Modbus-Map. Fehlt sie, halte inne und fordere sie an — rate nicht.
- Kein Refactor am bestehenden Produktions-Collector.

## Aufgaben
1. Lege `nq/fieldtest/pac_refresh_probe.py` an (neues Unterpaket `nq/fieldtest/` mit `__init__.py`).
2. Nutze `pymodbus` (prüfe Version im Repo: [`requirements.txt`](../../requirements.txt)) analog zum Stil in [`collector/modbus_client.py`](../../collector/modbus_client.py) und [`collector/sunspec.py`](../../collector/sunspec.py). FLOAT32 = 2 Register, Byte-/Word-Order gemäß Siemens-Doku.
3. Konfig aus [`config/nq_config.json`](../../config/nq_config.json) laden (`pac.host/port/unit_id`), Registeradressen aus einer **separaten, klar markierten Map** (Platzhalter, bis Siemens-Map vorliegt).
4. Polle je Block im vorgegebenen Takt, halte den letzten Wert je Register, zähle **Change-Events** und miss die **realen Änderungsintervalle** (Median/Min/Max) über den Testzeitraum.
5. Ausgabe periodisch: je Block „X von N Registern geändert, mediane Änderungsperiode Y s". Am Ende Zusammenfassung + Empfehlung je Block.
6. Optionaler Parameter `--duration-h` (Default kurz für Smoke-Test; 48 h für Volltest). Sauberes SIGINT-Handling.

## Definition of Done
- Skript läuft read-only, ohne persistenten Write, sauber startbar auf Tech.
- Es liefert je Block eine belastbare Aussage zur realen Refresh-Rate.
- Kurzer Ergebnisvermerk (Empfehlung Poll-Raten) wird in [`doc/netzqualitaet/MESSTECHNIK.md`](../../doc/netzqualitaet/MESSTECHNIK.md) unter „Pflege-Regel" nachgetragen.
- Card [`doc/llm/cards/netzqualitaet-nq-collector.card.md`](../../doc/llm/cards/netzqualitaet-nq-collector.card.md): `last_review` auf heute; Feldtest-Erkenntnis kurz vermerken.

## Danach
Ergebnisse fließen in **Phase 1** ([`nq-1-tech-collector.prompt.md`](nq-1-tech-collector.prompt.md)): die dort verwendeten Poll-Raten in [`config/nq_config.json`](../../config/nq_config.json) werden auf die gemessenen Werte gesetzt.
