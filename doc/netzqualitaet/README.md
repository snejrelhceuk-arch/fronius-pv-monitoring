# Netzqualitaet — Dokumentationsstart

**Stand:** 2026-08-08
**Aktueller Schwerpunkt:** Rolle-N-PAC4200-Modul, nicht mehr die alte reine
Smart-Meter-Auswertung.

Netzqualitaet ist ein eigenstaendiges Teilprojekt im PV-System. Es misst und
analysiert die Netzqualitaet am PCC mit dem PAC4200, bleibt aber strikt von
Produktionsdaten und Aktorik getrennt: Rolle N schreibt nur in `nq/db/` bzw.
Tech-tmpfs und niemals in `data.db` oder Aktoren.

## Inhalt

1. [Schnellwahl](#schnellwahl)
2. [Aktuelle Architektur](#aktuelle-architektur)
3. [Leseordnung fuer Menschen](#leseordnung-fuer-menschen)
4. [Leseordnung fuer LLMs](#leseordnung-fuer-llms)
5. [Legacy und Archiv](#legacy-und-archiv)

## Schnellwahl

| Frage | Lesen |
|---|---|
| Wie ist Rolle N aufgebaut? | [`NQ_MODUL.md`](NQ_MODUL.md) |
| Welche PAC4200-Register sind verifiziert? | [`MESSTECHNIK.md`](MESSTECHNIK.md), [`PAC4200-Modbus.md`](PAC4200-Modbus.md) |
| Wie laufen Tech-Collector, Transfer und Aggregation? | [`../llm/cards/netzqualitaet-nq-collector.card.md`](../llm/cards/netzqualitaet-nq-collector.card.md), [`../llm/cards/netzqualitaet-nq-aggregation.card.md`](../llm/cards/netzqualitaet-nq-aggregation.card.md) |
| Wie funktioniert Spektralanalyse/THD/HF-NF-VLF? | [`../llm/cards/netzqualitaet-nq-analysis-events.card.md`](../llm/cards/netzqualitaet-nq-analysis-events.card.md) |
| Warum sind PAC-Energiewerte randscharf? | [`ENERGIE_FEHLERANALYSE_2026-08-08.md`](ENERGIE_FEHLERANALYSE_2026-08-08.md), [`ENERGIE_ABLESEMETHODE.md`](ENERGIE_ABLESEMETHODE.md) |
| Welche alten NQ-Phasen sind nur noch Historie? | [`migration/`](migration/), [`NQ2_ROADMAP.md`](NQ2_ROADMAP.md) |

## Aktuelle Architektur

| Ebene | Host | Aufgabe | Ablage |
|---|---|---|---|
| Tech | Pi4-Tech | PAC4200 lesen, Fast/Medium/Slow-RAW, LimitMonitor, Event-Schnipsel | tmpfs `/dev/shm/nq_cache.db` |
| Primary | Pi5-Primary | Transfer, 5min/hourly/daily, Energie-Fixpunkte, Spektralanalyse | `nq/db/nq_YYYY-MM.db` |
| Web | Pi5-Primary | Read-only Anzeige/API, PAC-Clone, Charts, Spektralanalyse | `routes/pac4200.py`, Templates |

Wichtig: Web/API (Rolle B) liest nur. Hardwarezugriff auf den PAC4200 passiert
im NQ-Collector; Produktionsdaten bleiben read-only.

## Leseordnung fuer Menschen

1. **Ueberblick:** [`NQ_MODUL.md`](NQ_MODUL.md) fuer Ziele, Host-Schnitt,
   RAM-first-Entscheidung, Retention und Betriebsregeln.
2. **Messtechnik:** [`MESSTECHNIK.md`](MESSTECHNIK.md) fuer verifizierte
   Messgroessen; [`PAC4200-Modbus.md`](PAC4200-Modbus.md) nur bei Registerarbeit.
3. **Energie:** [`ENERGIE_FEHLERANALYSE_2026-08-08.md`](ENERGIE_FEHLERANALYSE_2026-08-08.md)
   zuerst, danach [`ENERGIE_ABLESEMETHODE.md`](ENERGIE_ABLESEMETHODE.md).
4. **Betrieb/Tools:** [`TOOLS.md`](TOOLS.md) nur fuer Offline-/Analysewerkzeuge,
   nicht fuer den heissen Collector-Pfad.
5. **Historie:** [`NQ2_ROADMAP.md`](NQ2_ROADMAP.md) und Tiefenpruefungen nur
   zur Nachverfolgung erledigter Work-Packages lesen.

## Leseordnung fuer LLMs

LLMs starten nicht hier, sondern ueber [`../llm/INDEX.md`](../llm/INDEX.md).
Die relevanten Cards sind bewusst kurz und fuehren direkt zu Code-Ankern:

- Collector/Tech: [`../llm/cards/netzqualitaet-nq-collector.card.md`](../llm/cards/netzqualitaet-nq-collector.card.md)
- Transfer/Aggregation/Energie: [`../llm/cards/netzqualitaet-nq-aggregation.card.md`](../llm/cards/netzqualitaet-nq-aggregation.card.md)
- Analyse/Spektrik: [`../llm/cards/netzqualitaet-nq-analysis-events.card.md`](../llm/cards/netzqualitaet-nq-analysis-events.card.md)
- Web/API: [`../llm/cards/web-display-api.card.md`](../llm/cards/web-display-api.card.md)

Wenn eine Card die Invarianten klaert, keine langen Human-Dokus nachladen.
Human-Dokus sind fuer Methodik, Betrieb und historische Begruendung da.

## Legacy und Archiv

`nq/legacy/` und [`METHODEN.md`](METHODEN.md) beschreiben die fruehere
Smart-Meter-basierte NQ-Auswertung. Diese Inhalte sind fachlich nuetzlich fuer
DFD und Boundary-Analyse, aber nicht mehr der aktuelle Architekturpfad.

Historische Zwischenstaende liegen unter [`migration/`](migration/). Neue offene
Aufgaben gehoeren nach [`../TODO.md`](../TODO.md), nicht in Unterordner-TODOs.
