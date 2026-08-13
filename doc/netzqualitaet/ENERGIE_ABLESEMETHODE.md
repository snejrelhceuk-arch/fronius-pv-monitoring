# PAC4200-Energiezähler: Ablesemethode & Tages-Fixpunkte

**Rolle N**

Dieses Dokument beschreibt die **produktive Routine-Methode** zur Erfassung der PAC4200-Energiezähler (Bezug/Einspeisung) und deren Validierung gegen den Fronius Master-SM.

## 1. Übersicht

Die PAC4200-Energiezähler werden **nicht** kontinuierlich gelesen, sondern:
1. Als **Snapshots** alle 5 Minuten auf Tech (tmpfs)
2. **Täglich** zu einem Tages-Fixpunkt aggregiert auf Primary (SD)
3. Mit **SM-Werten validiert** (Vergleichsseite)

**Ziel:** Energieerhaltende Messung mit <0,5% Abweichung zum SM.

## 2. Snapshot-Erfassung (Tech, tmpfs)

### 2.1 Hardware & Register
- **Gerät:** PAC4200 am PCC (Point of Common Coupling)
- **Register:** Kumulative FLOAT64-Zähler @ 801 (Modbus, read-only)
  - `Wh_imp` (Bezug)
  - `Wh_exp` (Einspeisung)
  - `varh_imp`, `varh_exp` (Blindenergie)
  - `VAh` (Scheinenergie)
- **Batterie-gepuffert:** Zähler überleben Stromausfall

### 2.2 Snapshot-Takt
- **Intervall:** 300 Sekunden (5 Minuten)
- **Config:** `config/nq_config.json → collector.energy_s = 300`
- **Service:** `pv-nq-poller.service` auf Pi4-Tech
- **Ziel-DB:** `/dev/shm/nq_cache.db` (tmpfs, RAM)
- **Tabelle:** `nq_energy_raw (ts, wh_imp, wh_exp, varh_imp, varh_exp, vah)`

### 2.3 Fehlertoleranz
- Modbus-Timeout → Sample überspringen (kein Absturz)
- `INSERT OR REPLACE` → idempotent (doppelte Snapshots überschreiben sich)
- tmpfs volatil → egal bei Reboot (Zähler kumulativ)

## 3. Tages-Fixpunkt-Berechnung (Primary, SD)

### 3.1 Timer & Ablauf
- **Wann:** Täglich 00:05 Uhr (Timer: `pv-nq-energy-rollup.timer`)
- **Service:** `pv-nq-energy-rollup.service` auf Pi5-Primary
- **Skript:** `python3 -m nq.transfer.nq_energy_rollup [--day YYYY-MM-DD]`
- **Ziel-DB:** `nq/db/nq_YYYY-MM.db` (Monats-DB, SD)

### 3.2 Datenfluss
1. **Fetch Snapshots via SSH:** Holt `nq_energy_raw` von Tech, Fenster `[t0−2h, t1+2h]`
   - `t0` = Mitternacht des Vortages (00:00:00)
   - `t1` = Mitternacht des aktuellen Tages (24:00:00)
   - 2h Rand = Bracketing für Interpolation

2. **Boundary-Interpolation** (`compute_daily_boundary`):
   - Findet Snapshots **vor** und **nach** Mitternacht
   - Interpoliert **linear** → Zählerstand exakt um 00:00:00
   - Beispiel:
     ```
     23:55:00 → 1000 Wh
     00:05:00 → 1005 Wh
     → 00:00:00 interpoliert = 1002.5 Wh
     ```
   - **Energieerhaltend:** `Ende(Tag D) = Anfang(Tag D+1)` → Teleskopierung

3. **Delta berechnen:**
   ```
   wh_imp_delta = wh_imp_end - wh_imp_start
   ```

4. **Qualität markieren** (`src`):
   - `counter` = ✅ Sauber bracketiert & interpoliert, kein Reset
   - `partial` = ⚠️ Kein sauberer Rand, within-day Fallback
   - `reset_fallback` = ⚠️ Zähler-Reset erkannt, Teildelta-Summe
   - `sm_substitute` = 🔧 PAC ungültig (Zählerunterbrechung/Anlaufphase) → SM-Wert eingesetzt
   - `pv_backfill` = 📚 Historisch aus Produktions-DB

5. **Schreiben:** `nq_energy_daily` + `nq_energy_checkpoint`

### 3.3 Beispiel-Datensatz

```sql
SELECT day, wh_imp_start, wh_imp_end, wh_imp_delta, src, n_samples
FROM nq_energy_daily WHERE day='2026-08-05';
```

| Spalte | Wert | Bedeutung |
|--------|------|-----------|
| day | 2026-08-05 | Datum |
| wh_imp_start | 12345.678 | Zählerstand 00:00:00 (Wh) |
| wh_imp_end | 13234.760 | Zählerstand 24:00:00 (Wh) |
| wh_imp_delta | 889.082 | Tages-Bezug (Wh) |
| src | counter | Qualität: sauber interpoliert |
| n_samples | 288 | Anzahl Snapshots (5 min × 288 = 24 h) |

### 3.4 Gültigkeits-Guards

**Null-Register (Anlaufphase):**
- Wenn `*_start ≤ 1.0 Wh` → nicht gültig
- Beispiel: Export-Register war 2026-07-12/13 noch `0.000`
- → Wird als `partial` markiert oder ignoriert

**Reset-Erkennung:**
- `end < start - 1 Wh` → Reset
- Oder `delta > 3 × Σ(Teildelta)` → Sprung
- → Fällt auf Summe der positiven Teildelta zurück, `src='reset_fallback'`

## 4. Monats- & Jahres-Fixpunkte

### 4.1 Timer
- **Monat:** 1. des Monats, 00:10 Uhr (`pv-nq-energy-rollup-month.timer`)
- **Jahr:** 1. Januar, 00:10 Uhr (`pv-nq-energy-rollup-year.timer`)

### 4.2 Methode
- Aggregiert `nq_energy_daily` über den Zeitraum
- `delta = Σ Tages-Deltas` (reset-aware bereits je Tag)
- `start` = erster Tag `*_start`
- `end` = letzter Tag `*_end`
- Schreibt `nq_energy_monthly` bzw. `nq_energy_yearly`

## 5. Validierung gegen SM

### 5.1 Vergleichsquelle
- **Fronius Primär-SM** (Master-SM)
- **Tabelle:** `data.db → daily_data`
- **Felder:** `W_Imp_Netz_start`, `W_Imp_Netz_end` (autoritativer Tages-Fixpunkt)

### 5.2 Vergleichsseite
- **URL:** `/netzqualitaet/energievergleich`
- **API:** `/api/nq/energy_compare?days=90`
- **Anzeige:** Reine Tabelle (Tag, PAC/SM Bezug/Einspeisung kWh, Δ absolut/%)

### 5.3 Bewertungskriterien

Verglichen werden **zwei unabhängige Messgeräte am selben PCC** (PAC4200 mit
150/5A-0,2S-Wandlern vs. Fronius Primär-SM). Beide zählen **saldierend** (Netto
über alle drei Phasen) und integrieren jeweils ihre **eigene** Wirkleistung.

| Abweichung | Status | Bedeutung |
|------------|--------|-----------|
| < 2% | ✅ Normal | Im kombinierten Toleranzband beider Geräte |
| 2% – 5% | ⚠️ Auffällig | Prüfen: Datenlücke? Collector-Ausfall? Anlaufphase? |
| > 5% | ❌ Kritisch | Systematik prüfen (s. u.) |

**IST-Befund (nur voll abgedeckte Tage, `n_samples≈288`):**
- **Bezug (Import)** stimmt gut überein: ±0…7% (meist ±3%), streut um 0.
- **Einspeisung (Export)** wird vom PAC **systematisch höher** gezählt:
  typ. **+5…+26%** (absolut ≈ +0,03…+0,19 kWh/Tag).
- Ursache ist **kein** Verdrahtungs-/Konfig-Fehler (Strombeträge, Blindleistung
  Q, Netto-Bezug und Registerabbild stimmen zwischen beiden Geräten überein; das
  PAC integriert seine eigene P_tot exakt — verifiziert). Es ist eine echte
  **Zwei-Geräte-Divergenz an einem Punkt mit sehr niedrigem Leistungsfaktor**
  (PF am PCC häufig 0,3–0,5, hohe kapazitive Blindleistung). Ein kleiner
  Phasenwinkel-Unterschied (~0,3°, am Rand der 0,2S-Klasse), angewandt auf die
  große Blindleistung, ergibt einen Netto-Wirkleistungs-Offset von ~4 W ≈
  0,1 kWh/Tag. Auf den großen Bezug ist das prozentual winzig, auf die kleine
  Einspeisung prozentual groß.
- **Wichtig:** **Gültige** PAC-Messtage werden **nie** mit SM-Werten überschrieben
  (das würde reale Abweichungen verschleiern). Nur **wirklich ungültige** Tage
  (Zählerunterbrechung/Anlaufphase, z. B. vor 2026-08-05) werden per
  `nq_energy_invalidate` **explizit** an SM angeglichen (`src='sm_substitute'`),
  damit die kumulativen Statistiken nicht durch Startup-Artefakte verfälscht
  werden. Rückwirkende Neuberechnung gültiger Tage nur via `nq_energy_recompute`
  (aus echten PAC-`*_start`-Fixpunkten).
- **Absolute Wahrheit** liefert nur der **iMS/Netzbetreiber-Zähler**
  (`nq_ims_reading`, Fixpunkte in `doc/MESSSYSTEM_FIXPUNKTE.md`) — regelmäßig
  ablesen, um zu entscheiden, welches Gerät näher an der Eichgröße liegt.

## 6. src-Status Übersicht

| src | Qualität | Ursache | Aktion |
|-----|----------|---------|--------|
| `counter` | ✅ Exzellent | Sauber bracketiert, interpoliert, kein Reset | Keine |
| `partial` | ⚠️ Akzeptabel | Kein Bracketing oder 0-Register, within-day Fallback | Bei >2% Abweichung prüfen |
| `reset_fallback` | ⚠️ Unsicher | Zähler-Reset erkannt, Teildelta-Summe | Bei Wiederholung: Hardware prüfen |
| `sm_substitute` | 🔧 Ersetzt | PAC ungültig (Zählerunterbrechung/Anlaufphase), SM eingesetzt | Nur historisch (< 2026-08-05) |
| `pv_backfill` | 📚 Historisch | Aus Produktions-DB vor PAC-Start | Nur vor 2026-07-12 |

## 7. Timer-Kette (Übersicht)

**Täglich auf Primary:**
```
00:05  pv-nq-energy-rollup          Energie-Tages-Fixpunkt (Vortag)
00:10  pv-nq-agg-transfer           5-min-Transfer Tech→Primary
00:15  pv-nq-aggregate              hourly/daily Aggregate
00:30  pv-nq-analysis               Netzereignis-Analyse
00:40  pv-nq-primary-cap            Event-Kappung
```

**Monatlich:**
```
01. 00:10  pv-nq-energy-rollup-month   Monats-Fixpunkt
```

**Jährlich:**
```
01.01. 00:10  pv-nq-energy-rollup-year    Jahres-Fixpunkt
```

## 8. Troubleshooting

### 8.1 Abweichung >0,5% bei `src='counter'`

**Mögliche Ursachen:**
1. **Collector-Ausfall** während des Tages → `n_samples` deutlich <288
2. **Modbus-Fehler** → Snapshots lückenhaft → schlechtes Bracketing
3. **Uhr-Drift** zwischen Tech und Primary → Zeitstempel-Mismatch
4. **SM-Fehler** → sehr selten, aber SM kann auch falsch liegen

**Diagnose:**
```bash
# Prüfe n_samples
sqlite3 nq/db/nq_2026-08.db "SELECT day, n_samples, src FROM nq_energy_daily WHERE day='2026-08-08';"

# Prüfe Snapshots
ssh admin@192.0.2.181 "sqlite3 /dev/shm/nq_cache.db 'SELECT COUNT(*) FROM nq_energy_raw WHERE ts>=... AND ts<...;'"

# Systemd-Log
journalctl -u pv-nq-poller.service -u pv-nq-energy-rollup.service --since "2026-08-08"
```

### 8.2 `src='partial'` trotz vollem Tag

**Ursache:** Kein Bracketing um Mitternacht (Rand außerhalb `boundary_max_gap_s=1800 s`)

**Fix:**
- `boundary_margin_s` in `nq_config.json` erhöhen (aktuell 7200 s = 2 h)
- Oder `boundary_max_gap_s` erhöhen (aktuell 1800 s = 30 min)

### 8.3 Monats-/Jahres-Fixpunkt fehlt

**Symptom:** Tooltip zeigt keine PAC-Werte für Monat/Jahr

**Diagnose:**
```bash
# Prüfe Monats-Fixpunkt
sqlite3 nq/db/nq_2026-08.db "SELECT * FROM nq_energy_monthly WHERE month='2026-08';"

# Manually trigger
sudo -u admin python3 -m nq.transfer.nq_energy_rollup --month 2026-08
```

## 9. Backup & Wiederherstellung

**GFS-Backup:**
- **Skript:** `scripts/backup_nq_gfs.sh`
- **Ziel:** Lokal + Offsite (Pi5-FB)
- **Rhythmus:** daily/weekly/monthly

**Restore (falls nötig):**
```bash
# Beispiel: Wiederherstelle Tag 2026-08-08
cp backup/db/nq_2026-08_2026-08-08.db nq/db/nq_2026-08.db
sudo -u admin python3 -m nq.transfer.nq_energy_rollup --day 2026-08-08
```

## Siehe auch
- `NQ_TESTS_UND_DB.md` — Schema & Tests
- `nq/collector/nq_energy.py` — Implementierung
- `nq/transfer/nq_energy_rollup.py` — Tages-Rollup
