# CSV-Archiv — Datenverwaltung & Monitoring

Stand: 01.07.2026
Quelle: Pi5-Backup-Archiv

---

## 📋 Verzeichnisinhalt

### Historische Jahres-Backups (2022–2025)

| Datei | Größe | Beschreibung |
|---|---:|---|
| data_2022.csv | 884 B | Jahresarchiv 2022 (komprimiert) |
| data_2023.csv | 919 B | Jahresarchiv 2023 (komprimiert) |
| data_2024.csv | 949 B | Jahresarchiv 2024 (komprimiert) |
| data_2025.csv | 968 B | Jahresarchiv 2025 (komprimiert) |

**Zweck:** Langzeitarchiv für Aggregat-Statistiken

---

### Solarweb-Tagesdaten (Working-CSVs)

| Datei | Größe | Beschreibung |
|---|---:|---|
| solarweb_daily_2026-01_working.csv | 1,8 KB | Jan 2026 — Fronius Solarweb täglich |
| solarweb_daily_2026-02_working.csv | 1,7 KB | Feb 2026 — Fronius Solarweb täglich |

**Status März–Juni 2026:** Nicht im Archiv vorhanden
  - Keine Solarweb-Tages-CSVs für 2026-03 bis 2026-06 gefunden
  - Systematische Backup-Analyse durchgeführt (siehe [SOLARWEB_ABGLEICH.md — Abschnitt 6.6](../audit/SOLARWEB_ABGLEICH.md#66-backup-analyse--märz-bis-juni-2026-stand-01072026))
  - Ursache: Daten nach dem 26.04-Backup nicht beibehalten oder nicht gefetched

**Feldtrennzeichen:** `;` (Semikolon)
**Felder:** date, gesamt_prod_kwh, einspeisung_kwh, in_batt_kwh, wattpilot_kwh, direkt_kwh, netzbezug_kwh, out_batt_kwh, verbrauch_kwh

**Quelle:** `scripts/fetch_solarweb_daily.py`

---

### Solarweb-Validierungsdaten

| Datei | Größe | Beschreibung |
|---|---:|---|
| solarweb_daily_2026-01_reconciled_candidate.csv | 2,4 KB | Jan 2026 — validiert, Candidat für Import |
| solarweb_monthly_2026_reference.csv | 249 B | Monatliche Referenzwerte 2026 |
| solarweb_yearly_2021-26_working.csv | 365 B | Jahresaggregate 2021–2026 |

**Zweck:** QA und Referenzdaten für Konsistenzprüfung

---

### Vergleichsmatrizen (Abgleich Lokal ↔ Solarweb)

| Datei | Größe | Beschreibung |
|---|---:|---|
| abgleich_2026-01_matrix.csv | 556 B | Abweichungsmatrix Jan 2026 |
| abgleich_2026-02_daily_vs_pvsystem.csv | 3,1 KB | Detaillierter Abgleich Feb 2026 (lokal vs. Solarweb) |

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
- Solarweb-Daten (Jan/Feb 2026 verfügbar) → Referenz für Datenqualität

### Für Solarweb-Abgleich (Q2 2026)
- **Vollständig:** Januar 2026 (exakte Übereinstimmung mit lokalen Daten)
- **Teilweise:** Februar 2026 (Abgleichsdatei endet 19.02; Monatsdifferenz dokumentiert)
- **Nicht verfügbar:** März–Juni 2026 (keine Solarweb-Tages-CSVs in Backups)

Detailliertes Audit: siehe [SOLARWEB_ABGLEICH.md § 6](../audit/SOLARWEB_ABGLEICH.md#6-vergleichsprotokoll-q2-2026--januar--juni).

---

## 📊 Abgleich-Status

| Monat | Lokal vorhanden | Solarweb vorhanden | Abgleich Status |
|---|:---:|:---:|---|
| Jan 2026 | ✅ | ✅ | ✅ Vollständig (exakt) |
| Feb 2026 | ✅ | ✅ | 🟡 Teilweise (bis 19.02) |
| Mär 2026 | ✅ | ❌ | ⏹️ Nicht möglich |
| Apr 2026 | ✅ | ❌ | ⏹️ Nicht möglich |
| Mai 2026 | ✅ | ❌ | ⏹️ Nicht möglich |
| Jun 2026 | ✅ | ❌ | ⏹️ Nicht möglich |

**Legende:** ✅ verfügbar | ❌ nicht verfügbar | 🟡 unvollständig | ⏹️ nicht durchführbar

---


## 📊 Statistik

| Kategorie | Anzahl | Größe |
|---|---:|---|
| Jahres-Backups | 4 | 3,7 KB |
| Solarweb-Tagesdaten | 2 | 3,5 KB |
| Validierungsdaten | 3 | 2,9 KB |
| Vergleichsmatrizen | 2 | 3,7 KB |
| **Gesamt** | **11 Dateien** | **~14 KB** |

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
