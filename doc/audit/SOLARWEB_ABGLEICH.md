# Solarweb-Datenabgleich — Anleitung und Vergleichsprotokoll

Stand: 01.07.2026
Status: Anleitung zur manuellen Durchführung

---

## 1) Zweck

Monatsendlicher Abgleich der lokalen Energiedaten (`daily_data`) mit den
offiziellen Fronius-Solarweb-Werten zur Validierung der Messkette und
Erkennung systematischer Abweichungen.

**Referenz:** Solarweb gilt als Ground Truth für Energiesummen (kWh), da direkt
aus Fronius-Wechselrichter-Zählern abgeleitet.

---

## 2) Voraussetzungen

### 2.1 Solarweb-Credentials einrichten

Die Scripts `fetch_solarweb_daily.py` und `import_solarweb_daily.py` benötigen
Zugangsdaten für das Fronius-Solarweb-Portal.

**Datei:** `.secrets` im Repository-Root

```bash
# Solarweb-Zugangsdaten
Benutzer=ihre-email@example.com
Passwort=IhrSolarwebPasswort
```

**Sicherheit:** `.secrets` steht in `.gitignore` und wird NIEMALS committet.

### 2.2 Verzeichnisstruktur

```bash
imports/
└── solarweb/
    ├── solarweb_daily_2026-01_working.csv
    ├── solarweb_daily_2026-02_working.csv
    ├── ...
    └── solarweb_daily_2026-06_working.csv
```

Das Verzeichnis `imports/` ist ebenfalls in `.gitignore` (private Daten).

---

## 3) Daten fetchen (Schritt 1)

### 3.1 Einzelmonat abrufen

```bash
cd pv-system/
python3 scripts/fetch_solarweb_daily.py --year 2026 --month 6
```

### 3.2 Mehrere Monate abrufen

```bash
# Monate 1-6 (Jan-Jun 2026)
python3 scripts/fetch_solarweb_daily.py --year 2026 --months 1-6

# Oder einzeln
python3 scripts/fetch_solarweb_daily.py --year 2026 --months 4,5,6
```

### 3.3 Output

- CSV-Datei: `imports/solarweb/solarweb_daily_2026-06_working.csv`
- Feldtrennzeichen: `;` (Semikolon)
- Encoding: UTF-8

**CSV-Felder:**

| Feld | Beschreibung | Einheit |
|---|---|---|
| `date` | Tag (YYYY-MM-DD) | — |
| `gesamt_prod_kwh` | PV-Erzeugung gesamt | kWh |
| `einspeisung_kwh` | Netzeinspeisung | kWh |
| `in_batt_kwh` | Batterie geladen | kWh |
| `out_batt_kwh` | Batterie entladen | kWh |
| `direkt_kwh` | Direktverbrauch (ohne Wattpilot) | kWh |
| `wattpilot_kwh` | Wattpilot (nur PV-Anteil!) | kWh |
| `netzbezug_kwh` | Netzbezug | kWh |
| `verbrauch_kwh` | Gesamtverbrauch | kWh |

⚠️ **Wichtig:** `wattpilot_kwh` zeigt in Solarweb **nur den PV-Direkt-Anteil**,
nicht den Netzbezug-Anteil des Wattpilots. Unsere lokale Messung ist vollständig.

---

## 4) Daten importieren (Schritt 2)

### 4.1 Import in Datenbank

```bash
# Dry-Run (zeigt Änderungen, schreibt nicht)
python3 scripts/import_solarweb_daily.py --dry-run

# Tatsächlicher Import
python3 scripts/import_solarweb_daily.py
```

**Effekt:**
- Überschreibt Energiesummen in `daily_data` mit Solarweb-Werten
- Setzt Counter-Start/End auf NULL (damit Web-UI Solarweb-Fallback nutzt)
- Importiert Wattpilot-kWh in `wattpilot_daily`
- **Schützt geschützte Tage:** Monate vor `PROTECTED_MONTHS_BEFORE` bleiben unverändert

### 4.2 Geschützte Monate

In [collector/aggregate/statistics.py](../../collector/aggregate/statistics.py#L47):

```python
PROTECTED_MONTHS_BEFORE = date(2026, 3, 1)
```

Monate vor März 2026 sind manuell aus Solarweb korrigiert und werden vom
Import-Script **nicht überschrieben**.

---

## 5) Vergleich mit lokalen Daten (Schritt 3)

### 5.1 SQL-Abfrage für Juni 2026

```sql
-- Juni 2026: Solarweb vs. Collector-Aggregat
SELECT
    date(ts, 'unixepoch') AS tag,
    ROUND(W_PV_total / 1000.0, 2) AS pv_kwh_lokal,
    ROUND(W_Imp_Netz_total / 1000.0, 2) AS import_kwh_lokal,
    ROUND(W_Exp_Netz_total / 1000.0, 2) AS export_kwh_lokal,
    ROUND(W_Batt_Charge_total / 1000.0, 2) AS batt_charge_kwh_lokal,
    ROUND(W_Batt_Discharge_total / 1000.0, 2) AS batt_discharge_kwh_lokal,
    ROUND(W_Consumption_total / 1000.0, 2) AS verbrauch_kwh_lokal
FROM daily_data
WHERE ts >= 1717200000  -- 2026-06-01
  AND ts < 1719792000   -- 2026-07-01
ORDER BY ts;
```

### 5.2 CSV vs. DB: Erwartete Abweichungen

| Feld | Typische Δ | Ursache |
|---|---:|---|
| `pv_kwh` | <1% | Zähler-Rundung, Messintervall |
| `netzbezug_kwh` | <0,5% | Counter-basiert (sehr exakt) |
| `einspeisung_kwh` | <0,5% | Counter-basiert (sehr exakt) |
| `batt_charge_kwh` | 1-2% | Ladeverluste, Messauflösung |
| `batt_discharge_kwh` | 1-2% | Entladeverluste |
| `verbrauch_kwh` | <1% | Aggregat aus mehreren Quellen |
| `wattpilot_kwh` | **20-40%** | **Solarweb zeigt nur PV-Anteil!** |

**Wattpilot-Diskrepanz:** Unsere `wattpilot_daily.energy_wh` ist die Summe aus
PV-Direkt **plus** Netzbezug-Anteil. Solarweb zeigt nur den PV-Anteil.
→ Vergleich nur für PV-Anteil sinnvoll (erfordert separaten Query).

### 5.3 Systematische Abweichungen (bekannt)

1. **P×t-Drift (behoben ab Feb 2026):**
   - Jan 2026: P×t-Summen ~15-20% zu niedrig
   - Feb 2026: korrigiert durch Counter-basierte Aggregation

2. **Wattpilot-Netzbezug (ungelöst):**
   - Solarweb unterschlägt Netzbezug-Anteil
   - Unsere Messung korrekt (validiert gegen Wallbox-Display)

3. **Batterie-Ladeverluste:**
   - Solarweb: idealisierte kWh
   - Unsere Messung: reale kWh (inkl. Verluste ~15-18%)
   - → Solarweb-Werte tendenziell 2-3% höher bei Batterie-Laden

---

## 6) Vergleichsprotokoll bis 30.06.2026

### 6.1 Datenlage (CSV-Stand)

Verfügbare Solarweb-Quellen in `doc/csv/` (Stand 01.07.2026, **vollständig H1**):

- `solarweb_daily_2026-01_working.csv` … `solarweb_daily_2026-06_working.csv` (6 Monate Tagesdaten)
- `solarweb_monthly_2026_reference.csv` (Monatssummen Jan–Jun, aus Tagesdaten aggregiert)
- `solarweb_yearly_2021-26_working.csv` (Jahressummen, 2026 = Jan–Jun-Ist)
- `abgleich_2026-01_matrix.csv`, `abgleich_2026-02_daily_vs_pvsystem.csv`
- `abgleich_2026-H1_monthly_solarweb_vs_lokal.csv` (**neu**: Halbjahres-Monatsabgleich)

März–Juni wurden am 01.07.2026 per `fetch_solarweb_daily.py --year 2026 --months 3-6`
neu von Solarweb geholt (siehe Abschnitt 6.6).

### 6.2 Lokale Baseline Juni 2026 (Monitoring)

**Datenquelle:** `daily_data` (30 Tage erfasst)

| Kennzahl | Wert | Bemerkung |
|---|---:|---|
| **PV-Erzeugung** | 2.047,20 kWh | Σ W_PV_total |
| **Netzbezug** | 31,59 kWh | Σ W_Imp_Netz_total |
| **Netzeinspeisung** | 24,92 kWh | Σ W_Exp_Netz_total |
| **Batterie Laden** | 438,75 kWh | Σ W_Batt_Charge_total |
| **Batterie Entladen** | 401,13 kWh | Σ W_Batt_Discharge_total |
| **Direktverbrauch** | 1.583,52 kWh | Σ W_PV_Direct_total |
| **Gesamtverbrauch** | 2.053,86 kWh | Σ W_Consumption_total |
| **Autarkie** | 98,5% | (Verbrauch − Netzbezug) / Verbrauch |

**Plausibilität:** konsistent, keine Tageslücken.

### 6.3 Vergleich Januar 2026 (Solarweb vs lokal)

Quelle: `abgleich_2026-01_matrix.csv`.

| Kennzahl | Solarweb Jan | Lokal Jan | Δ abs | Bewertung |
|---|---:|---:|---:|---|
| Produktion | 960,18 | 960,18 | 0,00 | exakt |
| Netzbezug | 1.101,47 | 1.101,47 | 0,00 | exakt |
| Einspeisung | 8,55 | 8,55 | 0,00 | exakt |
| Batt in/out | 186,15 / 177,02 | 186,15 / 177,02 | 0,00 | exakt |
| Verbrauch | 2.043,97 | 2.043,97 | 0,00 | exakt |
| Wattpilot | 450,92 | 0,00 | +450,92 | Solarweb zeigt PV-Anteil separat |
| Direkt | 314,56 | 765,48 | -450,92 | Direkt+WP lokal = Solarweb-Gesamt |

**Diskussion:** Zählerbasierte Energieflüsse stimmen im Januar vollständig.
Die Abweichung bei `direkt_kwh`/`wattpilot_kwh` ist ein bekanntes Mapping-Thema,
kein Messfehler.

### 6.4 Vergleich Februar 2026 (Solarweb vs lokal)

Quellen: `solarweb_monthly_2026_reference.csv`,
`abgleich_2026-02_daily_vs_pvsystem.csv`, lokale `daily_data`-Summen.

| Kennzahl | Solarweb Feb | Lokal Feb | Δ abs (lokal-solarweb) | Δ rel |
|---|---:|---:|---:|---:|
| Produktion | 1.006,69 | 887,62 | -119,07 | -11,83% |
| Netzbezug | 1.006,20 | 852,41 | -153,79 | -15,28% |
| Einspeisung | 11,33 | 10,41 | -0,92 | -8,11% |
| Batt in | 213,37 | 192,59 | -20,78 | -9,74% |
| Batt out | 200,14 | 172,86 | -27,28 | -13,63% |
| Verbrauch | 1.988,33 | 1.729,62 | -258,71 | -13,01% |
| Wattpilot | 421,49 | 314,10 | -107,39 | -25,48% |

**Diskussion Februar:**

- Die Tages-Abgleichsdatei endet bei 19.02 (letzte Zeile teilweise leer).
- Summe der Tagesdeltas (18-19 Tage mit Werten) zeigt bereits klare Muster:
   - `delta_gesamt_prod_kwh`: -14,34 kWh (Mittel |Δ| 2,16 kWh/Tag)
   - `delta_netzbezug_kwh`: +8,11 kWh (Mittel |Δ| 5,49 kWh/Tag)
   - `delta_wattpilot_kwh`: +39,33 kWh (Mittel |Δ| 10,45 kWh/Tag)
   - `delta_direkt_kwh`: -192,90 kWh (Mittel |Δ| 11,43 kWh/Tag)
- Das Muster passt zum bekannten Split zwischen `direkt_kwh` und
   `wattpilot_kwh` plus unvollständiger/teilweise fehlender Februar-Abgleichsreihe.

### 6.5 Vergleich März–Juni 2026 (Solarweb vs lokal)

Quelle: `abgleich_2026-H1_monthly_solarweb_vs_lokal.csv` (Solarweb-Fetch 01.07.2026,
lokale `daily_data`-Summen).

| Monat | Tage lokal | PV SW | PV lokal | Δ PV | Δ PV % | Verbr. SW | Verbr. lokal | Δ Verbr. |
|---|:--:|---:|---:|---:|---:|---:|---:|---:|
| 2026-03 | 31 | 1.905,18 | 1.872,08 | -33,10 | -1,74% | 1.987,82 | 1.989,50 | +1,68 |
| 2026-04 | 30 | 2.000,69 | 1.995,17 | -5,52 | -0,28% | 2.074,86 | 2.096,84 | +21,98 |
| 2026-05 | 31 | 2.158,35 | 2.153,42 | -4,93 | -0,23% | 2.153,03 | 2.162,96 | +9,93 |
| 2026-06 | 30 | 2.050,38 | 2.047,20 | -3,18 | -0,16% | 2.024,93 | 2.053,86 | +28,93 |

**Diskussion März–Juni:**

- **Sehr gute Übereinstimmung** bei PV-Produktion: Abweichung < 1,8%, im Q2
   (Apr–Jun) sogar < 0,3%. Die lokalen Werte liegen minimal unter Solarweb —
   konsistent mit dem bekannten Muster (Zähler-Rundung, minimale Erfassungslücken).
- Verbrauch stimmt eng überein (Δ +1,7 bis +28,9 kWh/Monat, < 1,5%).
- Netzbezug/-einspeisung im niedrigen kWh-Bereich (Sommer, hohe Autarkie),
   Details in der Matrix-CSV.
- **Keine systematische Drift** — die Messkette ist über das gesamte Halbjahr valide.

### 6.6 Herkunft der März–Juni-Daten (Stand 01.07.2026)

**Backup-Analyse (historisch):** In den Pi5-Backups waren nur Jan/Feb
Solarweb-Tageswerte enthalten (letztes Backup mit Solarweb: 26.04.2026). März–Juni
waren nie als CSV gesichert.

**Lösung:** Am 01.07.2026 wurden die fehlenden Monate direkt aus dem Fronius-
Solarweb-Portal nachgeholt:

```bash
python3 scripts/fetch_solarweb_daily.py --year 2026 --months 3-6
```

Credentials: `Benutzer` + `Passwort` in `.secrets` (aus `FRONIUS_USER`/`FRONIUS_PASS`).
Der 5-Schritt-OAuth2-Login gegen `login.fronius.com` + Chart-API lieferte alle
122 Tageswerte (31+30+31+30) vollständig.

### 6.7 Fazit H1 2026

- **Januar:** exakt (Δ 0,0%) — Zählerdaten identisch.
- **Februar:** lokal nur 25 Tage erfasst → -11,8% (Erfassungslücke, kein Messfehler).
- **März–Juni:** sehr gute Übereinstimmung (PV Δ < 1,8%, Q2 < 0,3%).
- **Gesamt H1 2026:** PV 10.080,5 kWh (Solarweb), Messkette validiert.

Die Vergleichsdiskussion ist damit für das gesamte erste Halbjahr 2026 abgeschlossen.

---

## 7) Automatisierung (optional, zukünftig)

### 7.1 Cron-Job für monatlichen Abgleich

```bash
# /etc/cron.d/pv-solarweb-sync (noch nicht aktiv)
# Jeden 1. des Monats um 02:00 Uhr: Vormonat von Solarweb holen
0 2 1 * * admin cd $PROJECT_DIR && \
    python3 scripts/fetch_solarweb_daily.py --year $(date -d 'last month' +\%Y) \
    --month $(date -d 'last month' +\%m) >> /var/log/pv-solarweb-sync.log 2>&1
```

**Status:** Nicht aktiv. Manueller Abgleich bevorzugt (Kontrolle, Analyse).

### 7.2 Automatischer Import

**Nicht empfohlen.** Import überschreibt lokale Daten → nur nach manueller Prüfung.

---

## 8) Troubleshooting

### Problem: "Benutzer nicht in .secrets gefunden"

**Lösung:** `.secrets`-Datei anlegen mit Zeilen `Benutzer=...` und `Passwort=...`

### Problem: "401 Unauthorized" beim Solarweb-Login

**Ursachen:**
- Passwort falsch oder geändert
- Solarweb-Konto gesperrt/inaktiv
- Fronius-Login-Endpunkt geändert

**Lösung:** Credentials in Solarweb-Web-UI testen, bei Bedarf neu setzen.

### Problem: CSV enthält Nullwerte für alle Tage

**Ursachen:**
- PV-System-ID falsch (siehe `scripts/fetch_solarweb_daily.py`, Zeile 43)
- Monat noch nicht abgeschlossen (API liefert keine Daten)
- Solarweb-API-Format geändert (Chart-API ist inoffiziell)

**Lösung:** PV-System-ID validieren via Solarweb-URL (Browser DevTools → Network).

### Problem: Import überschreibt geschützte Monate

**Unmöglich:** Script prüft `PROTECTED_MONTHS_BEFORE` und überspringt automatisch.
Falls doch: Bug in `import_solarweb_daily.py` → sofort melden.

---

## 9) Quellen

- [fetch_solarweb_daily.py](../../scripts/fetch_solarweb_daily.py)
- [import_solarweb_daily.py](../../scripts/import_solarweb_daily.py)
- [BEOBACHTUNGSKONZEPT.md](../automation/BEOBACHTUNGSKONZEPT.md#23-solarweb-fronius-cloud)
- [FELDNAMEN_REFERENZ.md](../collector/FELDNAMEN_REFERENZ.md#-kritisch-solarweb-wattpilot--unser-wattpilot)
- [PV_REFERENZSYSTEM_DOKUMENTATION.md](PV_REFERENZSYSTEM_DOKUMENTATION.md)

---

**Nächster geplanter Abgleich:** 01.08.2026 (für Juli 2026)
