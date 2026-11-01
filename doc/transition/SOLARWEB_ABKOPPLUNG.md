# Solarweb-Abkopplung — Transition zum eigenständigen Monitoring

**Hintergrund:** Ab 26.11.2026 schränkt Fronius den API-Zugang zu Solarweb ein.
Langzeit-Daten (Jahreswerte, historische Tagesreihen) werden ohne Premium-Abo
nicht mehr abrufbar sein. Dieser Wechsel war konzeptionell bereits geplant
(lokales Monitoring als primäre Datenquelle). Dieses Dokument fixiert die
Entscheidung und die daraus folgenden Maßnahmen.

---

## 1. Entscheidung: Eigenständiges Monitoring ohne Solarweb

### Argumente für die Trennung

| Argument | Gewicht |
|---|---|
| Datenqualität lokal bestätigt: PV-Δ < 0,4 % gegen Solarweb (H1 2026) | ✅ hoch |
| Lokales System misst vollständiger (Wattpilot-Netzanteil, Grid-Charging) | ✅ hoch |
| Keine Cloud-Abhängigkeit für den Anlagenbetrieb | ✅ hoch |
| Backup-Kette (FB + Küche) sichert Langzeit-Daten redundant | ✅ hoch |
| Solarweb-Abo kostet Geld, Mehrwert nach Trennung minimal | ✅ mittel |
| iMSys dient weiterhin als eichrechtliche Referenz, nicht Solarweb | ✅ mittel |
| Solarweb-Daten als CSV bis 26.11. vollständig gesichert (2021–2026) | ✅ hoch |

### Argumente gegen die Trennung (entkräftet)

| Gegenargument | Entkräftung |
|---|---|
| Solarweb als externe Kontrollinstanz | Ersatz: iMSys (eichrechtlich), PAC4200, monatliche Abgleich-Matrix |
| Historische Langzeitdaten gehen verloren | Solarweb-CSVs 2021–2026 vollständig archiviert in `doc/csv/` |
| Fronius-Cloud liefert PV-Prognose-Daten | Prognose läuft über lokale Forecast-Pipeline (nicht Solarweb) |

**Entscheidung: Solarweb wird abgekoppelt. Kein Premium-Abo ab 26.11.2026.**

---

## 2. Datenlage vor der Abkopplung (Sicherung bis 26.11.2026)

### Was bereits gesichert ist

- Solarweb-Tagesdaten **2021-11 bis 2026-10** vollständig als CSV in `doc/csv/`
- Abgleich-Matrizen für H1 2026 (Jan–Jun, Okt)
- Monatssummen und Jahreswerte

### Was vor dem 26.11. noch gesichert werden muss

- [ ] Solarweb-Tagesdaten November 2026 — fetch am 01.12.2026 oder während der
  Zugriffs-Übergangszeit noch möglich: `python3 scripts/fetch_solarweb_daily.py --year 2026 --month 11`
- [ ] Solarweb-Jahressummen 2026 final — fetch am 02.01.2027 (falls noch zugänglich)
  oder Fallback: aus Tagesdaten-CSVs aggregieren
- [ ] Solarweb-Monatssummen-CSV aktualisieren (derzeit bis Jun 2026)

### Was nach der Abkopplung wegfällt (akzeptiert)

- Live-Ansicht im Solarweb-Portal
- Fronius-Push-Benachrichtigungen via Solarweb
- Update-Erinnerungen (Firmware) via Solarweb-Portal
- Historische Solarweb-Vergleichsansicht > 1 Jahr zurück

---

## 3. Eigenständige Monitoring-Architektur (IST-Zustand)

Das lokale Monitoring ist vollständig funktionsfähig ohne Solarweb:

```
Messung                Aggregation              Anzeige / Auswertung
───────────────────────────────────────────────────────────────────────
raw_data (3s)          data_1min (1min)          Web-UI (Flow, Tag, Monat, Jahr)
                       data_15min/hourly         Tages-/Monats-Mail (diagnos)
                       daily_data                monthly/yearly_statistics
                       monthly_statistics        CSV-Export (doc/csv/)
                                                 PAC4200 Fixpunkte (NQ-DB)
                                                 iMSys-Gegencheck (nq_ims_reading)
```

**Redundanz-Kette:** Primary → FB-Mirror (10 min) → FB-GFS (tägl./wöch./mon./jährl.)
→ Küche-Archiv (monthly/yearly, permanent). Details: `doc/system/BACKUP_STRATEGY.md`.

---

## 4. Qualitätssicherung ohne Solarweb

### Ersetzte Solarweb-Kontrollpfade

| Bisheriger Solarweb-Check | Lokale Ersatz-Methode |
|---|---|
| PV-Jahresertrag vs. Erwartung | `yearly_statistics.W_PV_total_kwh` + Tages-Mail |
| Netzbezug monatlich | `monthly_statistics` + Abgleich `nq_energy_daily` (PAC) |
| Batterie-Zyklen | `battery_health_daily.full_cycles` |
| Einspeisung Jahressumme | `W_Exp_Netz_total` + iMSys-Fixpunkt |

### Neue Kontrollpfade (einzurichten, s. TODO.md)

- **SM-LCD Fixpunkt** (`enwitec`-Anzeige): unregelmäßige Stichproben,
  LCD-Ablesung gegen `raw_data.W_Imp_Netz` zum selben Zeitstempel
- **Dimplex WP-Zähler** gegen DB-Summe `heizpatrone_daily` (aktuell) /
  zukünftig eigene `wp_daily`-Tabelle mit COP-Tracking
- **Monatliche Abgleich-Matrix** lokal vs. PAC4200 (bereits implementiert)

---

## 5. CSV-Archivierung als Langzeit-Lesbarkeit

CSVs sind das menschenlesbare Langzeit-Format. Strategie:

- **Tages-CSVs:** `tools/export_daily_csv.py` → `doc/csv/daily_YYYY.csv` (volle Historie; laufendes Jahr täglich per Cron)
- **Monats-CSVs:** Monatlich als `abgleich_YYYY-MM_daily_vs_pvsystem.csv` in `doc/csv/`
- **Jahres-CSVs:** `data_YYYY.csv` aus `yearly_statistics` (4 Jahreswerte bereits vorhanden)
- **Solarweb-CSVs:** Weiterführung bis Nov 2026, dann einfrieren

Für eine vollständige Tag-genaue Analyse des gesamten Betriebs ab 2026 reicht
die lokale `daily_data`-DB. Der Export nach CSV ist auf Abruf möglich, muss aber
nicht täglich automatisch laufen (DB-Backup ist zuverlässiger als CSV-Redundanz).

---

## 6. Checkliste Abkopplung

- [x] Solarweb-Tagesdaten 2021-11 bis 2026-10 in `doc/csv/` gesichert
- [x] Abgleich-Matrizen H1 + Oktober 2026 abgeschlossen
- [x] Tages-Export-Script `tools/export_daily_csv.py` angelegt (→ `doc/csv/daily_YYYY.csv`, täglicher Cron fürs laufende Jahr)
- [ ] November 2026 Solarweb-Daten fetchen (nach Monatswechsel)
- [ ] Jahres-Abschluss 2026 sichern (Januar 2027)
- [ ] Solarweb-Credentials nach Abkopplung aus `.secrets` entfernen

---

## 7. Verwandte Dokumentation

- [`doc/csv/README.md`](../csv/README.md) — CSV-Archivübersicht
- [`doc/audit/SOLARWEB_ABGLEICH.md`](../audit/SOLARWEB_ABGLEICH.md) — Abgleich-Methodik und Protokoll
- [`doc/system/BACKUP_STRATEGY.md`](../system/BACKUP_STRATEGY.md) — Backup-Kette
- [`doc/MESSSYSTEM_FIXPUNKTE.md`](../MESSSYSTEM_FIXPUNKTE.md) — iMSys/SM/PAC Fixpunkte
