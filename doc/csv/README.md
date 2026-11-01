# CSV-Archiv — Datenverwaltung & Monitoring

Stand: 01.11.2026
Quelle: Pi5-Backup-Archiv + lokaler Tages-Export

---

## 📋 Verzeichnisinhalt

### Tagegenaues Lokal-Archiv (Solarweb-unabhängig)

`daily_YYYY.csv` — tagegenaue Energiebilanz aus `daily_data` (eigenes Monitoring,
volle Historie 2021-11 bis laufend). **Ersetzt die Solarweb-Abhängigkeit** (s.
`doc/transition/SOLARWEB_ABKOPPLUNG.md`).

**Erzeugung:** `tools/export_daily_csv.py` (liest Shadow-Views → volle Historie).
Laufendes Jahr wird täglich 06:40 per Cron regeneriert; abgeschlossene Jahre sind stabil.

**Trennzeichen:** `;` · **Einheit:** kWh
**Felder:** date, pv, bezug, einsp, batt_in, batt_out, verbrauch, direktverbrauch, wp, wattpilot

### Historische Jahres-Backups (2022–2025)

| Datei | Größe | Beschreibung |
|---|---:|---|
| data_2022.csv | 884 B | Jahresarchiv 2022 (Monats-Aggregat) |
| data_2023.csv | 919 B | Jahresarchiv 2023 (Monats-Aggregat) |
| data_2024.csv | 949 B | Jahresarchiv 2024 (Monats-Aggregat) |
| data_2025.csv | 968 B | Jahresarchiv 2025 (Monats-Aggregat) |

**Zweck:** Langzeitarchiv für Aggregat-Statistiken (Monatsgranularität; die
tagegenauen `daily_YYYY.csv` sind der feinere, aktuelle Pool).

---

### Solarweb-Tagesdaten (Working-CSVs)

Tägliche Fronius-Solarweb-Energiewerte je Monat: `solarweb_daily_YYYY-MM_working.csv`.
Abgedeckt ist der gesamte Anlagenzeitraum **2021-11 bis laufender Monat** (Anlagenstart Nov 2021).
Monate vor Inbetriebnahme liefert Solarweb nicht — dafür existiert keine Datei.

**Feldtrennzeichen:** `;` (Semikolon)
**Felder:** date, einspeisung_kwh, in_batt_kwh, wattpilot_kwh, direkt_kwh, gesamt_prod_kwh, netzbezug_kwh, out_batt_kwh, verbrauch_kwh
**Quelle:** `scripts/fetch_solarweb_daily.py` (OAuth2-Login via `.secrets`, Chart-API je Monat)
**Abgleich:** Tagessummen decken sich je Monat mit `monthly_statistics` (PV nach Solarweb-Produktionsdefinition ~2–3 % höher; `wattpilot_kwh` = nur PV-Direkt-Anteil, lokale Messung vollständig).

---

### Solarweb-Validierungsdaten

| Datei | Größe | Beschreibung |
|---|---:|---|
| solarweb_daily_2026-01_reconciled_candidate.csv | 2,4 KB | Jan 2026 — validiert, Candidat für Import |
| solarweb_monthly_2026_reference.csv | ~0,5 KB | Monatssummen Jan–Jun 2026 (aus Tagesdaten aggregiert) |
| solarweb_yearly_2021-26_working.csv | 365 B | Jahresaggregate 2021–2026 (2026 = Jan–Jun-Ist) |

**Zweck:** QA und Referenzdaten für Konsistenzprüfung

---

### Vergleichsmatrizen (Abgleich Lokal ↔ Solarweb)

| Datei | Größe | Beschreibung |
|---|---:|---|
| abgleich_2026-01_matrix.csv | 556 B | Abweichungsmatrix Jan 2026 |
| abgleich_2026-02_daily_vs_pvsystem.csv | 3,1 KB | Detaillierter Abgleich Feb 2026 (lokal vs. Solarweb) |
| abgleich_2026-H1_monthly_solarweb_vs_lokal.csv | ~0,5 KB | Halbjahres-Monatsabgleich Jan–Jun 2026 (Solarweb vs. lokal) |

**Zweck:** Monitoring-Abweichungen, Fehleranalyse

**Inhalt abgleich_2026-02_daily_vs_pvsystem.csv (Beispiel):**
```
Tagesvergleich: lokale daily_data vs. Solarweb-Referenz
Felder: date, pv_lokal, pv_solarweb, delta_pv, import_lokal, import_solarweb, delta_import, ...
```

---

## 🔄 Verwendung in der Volkszählung (01.07.2026)

### Für KI-Beitragsanalyse
- Jahres-Archive (2022–2025) → Bestätigt stabiler Produktiveinsatz über 4 Jahre
- Solarweb-Daten (Jan–Jun 2026 vollständig) → Referenz für Datenqualität

### Für Solarweb-Abgleich (Q2 2026)
- **Vollständig:** Januar 2026 (exakte Übereinstimmung mit lokalen Daten)
- **Teilweise:** Februar 2026 (lokal nur 25 Tage erfasst; Monatsdifferenz dokumentiert)
- **Vollständig:** März–Juni 2026 (nachgeholt 01.07.2026; PV-Abweichung < 1,8%, Q2 < 0,3%)

Detailliertes Audit: siehe [SOLARWEB_ABGLEICH.md § 6](../audit/SOLARWEB_ABGLEICH.md#6-vergleichsprotokoll-bis-30062026).

---

## 📊 Abgleich-Status

| Monat | Lokal vorhanden | Solarweb vorhanden | Abgleich Status |
|---|:---:|:---:|---|
| Jan 2026 | ✅ | ✅ | ✅ Vollständig (exakt) |
| Feb 2026 | 🟡 (25d) | ✅ | 🟡 Teilweise (Erfassungslücke) |
| Mär 2026 | ✅ | ✅ | ✅ Vollständig (Δ -1,7%) |
| Apr 2026 | ✅ | ✅ | ✅ Vollständig (Δ -0,3%) |
| Mai 2026 | ✅ | ✅ | ✅ Vollständig (Δ -0,2%) |
| Jun 2026 | ✅ | ✅ | ✅ Vollständig (Δ -0,2%) |
| Jul 2026 | ✅ | ✅ | Abgleich-Matrix fehlt noch |
| Aug 2026 | ✅ | ✅ | Abgleich-Matrix fehlt noch |
| Sep 2026 | ✅ | ✅ | Abgleich-Matrix fehlt noch |
| Okt 2026 | ✅ | ✅ | ✅ `abgleich_2026-10_daily_vs_pvsystem.csv` (Δ PV -0,38%) |
| Nov 2026 | lfd. | ⏳ nach 01.12. | — Solarweb-Zugang endet 26.11.2026 |

**Legende:** ✅ verfügbar/gut | 🟡 unvollständig | Δ = PV-Abweichung lokal vs. Solarweb

---


## 📊 Statistik

| Kategorie | Anzahl | Größe |
|---|---:|---|
| Jahres-Backups | 4 | 3,7 KB |
| Solarweb-Tagesdaten | 14 (2021-11 – 2026-10) | ~120 KB |
| Validierungsdaten | 3 | 2,9 KB |
| Vergleichsmatrizen | 3 (Jan, Feb, Okt 2026) | ~8 KB |
| **Gesamt** | | |

---

## 🔐 Sicherheit & Wartung

- ✅ Archive unter Versionskontrolle (Git)
- ⚠️ Keine Solarweb-Credentials in den CSVs (separates Handling in `.secrets`)
- 🔄 Monatliche Erweiterung (neue Abgleiche)

---

## Verwandte Dokumentation

- [doc/audit/SOLARWEB_ABGLEICH.md](../audit/SOLARWEB_ABGLEICH.md) — Detaillierte Abgleich-Anleitung
- [doc/meta/KI_BEITRAGSANALYSE.md](../meta/KI_BEITRAGSANALYSE.md) — Repository-Statistik (Stand 01.07.26)
- [scripts/fetch_solarweb_daily.py](../../scripts/fetch_solarweb_daily.py) — Datenbeschaffung
- [scripts/import_solarweb_daily.py](../../scripts/import_solarweb_daily.py) — Datenbeschaffung
