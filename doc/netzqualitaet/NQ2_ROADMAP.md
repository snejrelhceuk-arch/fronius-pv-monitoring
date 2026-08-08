# NQ2-Roadmap — Status und Historie

**Stand:** 2026-08-08
**Status:** WP0-WP5 sind umgesetzt; WP6 ist durch die aktuelle
Spektralanalyse-/Ereignis-Pipeline abgeloest bzw. in laufende Analysearbeit
ueberfuehrt.

Dieses Dokument ist **kein aktiver Arbeitsplan** mehr. Es bleibt als kompakter
History-Index erhalten, damit alte Verweise auf die NQ2-Work-Packages nicht in
einen scheinbar offenen Plan fuehren.

## Inhalt

1. [Aktueller Einstieg](#aktueller-einstieg)
2. [Umgesetzte Work-Packages](#umgesetzte-work-packages)
3. [Offene Analysearbeit](#offene-analysearbeit)
4. [Historische Detailprompts](#historische-detailprompts)

## Aktueller Einstieg

| Thema | Massgebliche Quelle |
|---|---|
| Rolle-N-Architektur, Tech/Primary, RAM-first | [`NQ_MODUL.md`](NQ_MODUL.md) |
| Tech-Collector, LimitMonitor, PAC-Clone-Single-Reader | [`../llm/cards/netzqualitaet-nq-collector.card.md`](../llm/cards/netzqualitaet-nq-collector.card.md) |
| Transfer, Aggregation, Energie-Fixpunkte, Event-Schnipsel | [`../llm/cards/netzqualitaet-nq-aggregation.card.md`](../llm/cards/netzqualitaet-nq-aggregation.card.md) |
| HF/NF/VLF, Spektralanalyse, Harmonische/THD | [`../llm/cards/netzqualitaet-nq-analysis-events.card.md`](../llm/cards/netzqualitaet-nq-analysis-events.card.md) |
| Web/API/Chart | [`../llm/cards/web-display-api.card.md`](../llm/cards/web-display-api.card.md) |

## Umgesetzte Work-Packages

| WP | Ergebnis |
|---|---|
| WP0 Datenhygiene/Doku | Tote Stubs entfernt, Tier-Benennung fast/medium/slow konsolidiert, 12-h-Retention und NQ-Konfiguration nachgezogen. |
| WP1 PAC-Clone/LimitMonitor | Web liest den PAC-Clone indirekt ueber Tech; LimitMonitor prueft Spannung, Strom und Leistung aus verifizierten Skalaren. |
| WP2 Fixpunkte/Transienten | Tages-, Monats- und Jahres-Fixpunkte fuer PAC-Energie; Transientenpfad und Transfer/Aggregation angelegt. |
| WP3 Energie-Spiegelung | `/api/nq/energy*` und Monitoring-Tooltips spiegeln PAC-Werte additiv. |
| WP4 Event-Schnipsel | `nq_event_*`, Event-Dedup, Peak/Severity und `/api/nq/event/<id>` produktiv. |
| WP5 NQ-Chart | 5-min-Tag-Chart, Event-Drill-down, Langzeitaggregate und Zeitnavigation umgesetzt. |

## Offene Analysearbeit

WP6 ist nicht mehr als Monolith zu verfolgen. Aktuelle Analyseaufgaben werden
klein ueber die Analyse-Card und konkrete Code-Anker bearbeitet:

- Spektralanalyse: `nq/analysis/nq_spectral.py` und `/api/nq/spectral/*`.
- Ereigniskatalog: `nq/analysis/nq_events.py`, `nq_hf.py`, `nq_nf.py`, `nq_vlf.py`.
- Residual-/Netzsignal-Datensatz: `nq/analysis/nq_pattern.py` und `nq_pattern_5min`.
- Energie-Grenzwerte und Messmethodik: [`ENERGIE_FEHLERANALYSE_2026-08-08.md`](ENERGIE_FEHLERANALYSE_2026-08-08.md).

Neue offene Punkte gehoeren nach [`../TODO.md`](../TODO.md) oder in eine
zuständige LLM-Card, nicht in dieses History-Dokument.

## Historische Detailprompts

Die alten Work-Package-Prompts bleiben als Nachvollzug erhalten:

- `doc/dev_prompt/NQ2-WP0-Datenhygiene/prompt.md`
- `doc/dev_prompt/NQ2-WP1-PAC-Reader/prompt.md`
- `doc/dev_prompt/NQ2-WP2-Aggregation/prompt.md`
- `doc/dev_prompt/NQ2-WP3-Zaehler-Spiegelung/prompt.md`
- `doc/dev_prompt/NQ2-WP4-Events/prompt.md`
- `doc/dev_prompt/NQ2-WP5-Chart/prompt.md`
- `doc/dev_prompt/NQ2-WP6-Analyse/prompt.md`

Sie sind historische Umsetzungsunterlagen. Fuer neue Arbeit zaehlen die Cards in
[`../llm/INDEX.md`](../llm/INDEX.md).