"""nq — Netzqualität (Rolle N), PAC4200 am PCC.

Zwei-Host-Modul:
- collector/  → Tech (Pi4-Tech), RAM-first PAC4200-Erfassung im tmpfs
- transfer/   → Tech-Export (3–10 s + Event-RAW) und Primary-Ingest
- aggregate/  → Primary, Aggregationskaskade (3–10 s → 5 min → hourly → daily)
- analysis/   → Primary, Netzereignis-Analyse (HF/NF/VLF)

Rolle N ist read-only gegenüber der Produktion: kein Schreibpfad in data.db
oder Aktoren. Siehe doc/netzqualitaet/NQ_MODUL.md und
doc/system/ABCDEN_ROLLENMODELL.md.
"""
