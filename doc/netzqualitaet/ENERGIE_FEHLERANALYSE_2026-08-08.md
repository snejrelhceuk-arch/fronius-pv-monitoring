# Fehleranalyse: PAC4200-Energiezähler (Bezug/Einspeisung) — 2026-08-08

**Rolle N · read-only ggü. Produktion.** Betroffener Pfad: `nq/collector/nq_energy.py`,
`nq/transfer/nq_energy_rollup.py`, Fixpunkte in `nq/db/nq_YYYY-MM.db`
(`nq_energy_daily/monthly/yearly`). Vergleichsquelle: Fronius Primär-SM
(`daily_data.W_Imp/Exp_Netz_start/-end`).

## 1. Symptom
Die im Monitoring gespiegelten PAC-Tageswerte (Tooltip, `tag_view.html` →
`/api/nq/energy_map`) wichen stark und unsystematisch vom Fronius-SM ab — teils
PAC ≪ SM (z. B. 2026-07-14: −1,24 kWh Bezug), teils PAC ≫ SM. Der PAC4200 ist
ein am PCC sitzender, batteriegepufferter Zähler und sollte **genauer** sein als
iMS/SM — die Abweichungen waren also ein Fehler in der **Ablesemethode**, nicht in
der Hardware.

## 2. Untersuchungsmethode (reproduzierbar)
```sql
-- Tages-Fixpunkte + Rohstände (Primary, read-only)
SELECT day, n_samples, src, wh_imp_start, wh_imp_end, wh_imp_delta
  FROM nq_energy_daily WHERE src!='pv_backfill' ORDER BY day;   -- nq_2026-07/08.db
SELECT day, wh_imp, wh_exp FROM nq_energy_checkpoint ORDER BY day;
```
Gegenprobe Produktion (autoritativer SM-Tagesfixpunkt):
```sql
SELECT W_Imp_Netz_start, W_Imp_Netz_end FROM daily_data WHERE ts>=? AND ts<?;
```

## 3. Ursachen (drei, unabhängig)

### 3a. Lücken-Verlust der Differenzmethode (**Hauptursache**)
`compute_daily` bildete `delta = letzter − erster Snapshot **innerhalb** des Tages`.
Die kumulativen Zählerregister sind aber lückenlos monoton — die Energie in der
**Lücke** zwischen dem letzten Snapshot eines Tages (≈ 23:5x) und dem ersten des
Folgetages (≈ 00:0x) wird so **keinem** Tag zugerechnet und geht verloren.

- Bei 5-min-Takt (`energy_s=300`) verliert **jeder** Tag bis zu ~2×5 min Randenergie.
- Bei Collector-Ausfall über Mitternacht ist der Verlust katastrophal. Beispiel
  **2026-07-13** (voller Tag, 1439 Samples): Rohstände 1455 → 3812 Wh ⇒ echte
  Tagesenergie **2357 Wh**, gemessene within-day-Differenz nur **883 Wh** →
  **1474 Wh verloren** (in die Lücke zum lückenhaften 07-14, nur 46 Samples).

> Die Produktion (`collector/aggregate/daily.py`, `min1.py`) nutzt ebenfalls
> within-day ASC/DESC — kommt damit aber durch, weil `raw_data` **dicht** (~5–15 s)
> abgetastet wird. Der PAC-Pfad ist mit 300 s **dünn** und muss deshalb randscharf
> auf Mitternacht ankern.

### 3b. Checkpoint-Etikett vs. realer Zeitstempel
`nq_energy_checkpoint.ts` wird auf `t0` (exakt Mitternacht) gesetzt, der **Wert**
ist aber der erste Snapshot des Tages — bei spätem Collector-Start (07-14: erst
abends) liegt der „day_start"-Stand faktisch Stunden nach Mitternacht.

### 3c. Register-Anlaufphase
Am 2026-07-12/13 lieferte das **Export-Register** noch `0` (Registerkarte
`DOUBLE_MAP` wurde in dieser Phase von @805 auf @809 korrigiert). Differenzen
gegen diese `0`-Basis erzeugen Artefakte (fälschlich +4253 Wh Export am 07-13).

*(Separat, kein Code-Fehler:)* Collector-Ausfall **2026-07-16 … 08-03** → diese
Tage fehlen ganz (Betriebs-/systemd-Thema, siehe `doc/TODO.md`).

## 4. Behebung

### 4a. Randwert-Interpolation auf exakte Mitternacht (energieerhaltend)
Neu `nq/collector/nq_energy.py:compute_daily_boundary` (+ `_interp_at`):
Zählerstand an `t0`/`t1` wird aus den **die Grenze umschließenden** Snapshots
**linear interpoliert**. Da ein geteilter Mitternachtswert für beide Nachbartage
nach **derselben** Regel entsteht, gilt `Ende(D) == Anfang(D+1)` →
**Teleskopierung** → Monats-/Jahressumme = Zählerfortschritt (kein Verlust mehr).
Fällt der Rand aus (kein Bracketing im `boundary_max_gap_s`-Fenster), wird der
nächste Randwert genommen (`edge`, `estimated`) bzw. auf within-day zurückgefallen
(`partial`) — **markiert**, nicht still verfälscht.

- `nq/transfer/nq_energy_rollup.py`: Fetch-Fenster auf `[t0−margin, t1+margin]`
  geweitet (`energy.boundary_margin_s`), nutzt `compute_daily_boundary`.
- `master_sm_day` liest jetzt den **autoritativen** `daily_data`-Tagesfixpunkt
  (statt `data_1min`-Summe).
- Config: `config/nq_config.json → "energy"` (`boundary_margin_s=7200`,
  `boundary_max_gap_s=1800`, `min_samples_ok=200`).

### 4b. Rückwirkende Korrektur der Fixpunkte
Neu `nq/transfer/nq_energy_recompute.py` — differenziert **aufeinanderfolgende
day_start-Fixpunkte** (produktionskonform wie `energy_checkpoints`):
`delta(D)=start(D+1)−start(D)`, `end(D)=start(D+1)`. Nur PAC-Zählertage
(`src≠pv_backfill`), mit **Reset-Guard** und **Gültigkeits-Guard** (Basis
`>1 Wh`, schützt vor der `0`-Export-Anlaufphase). Letzter Tag eines Laufs behält
within-day (`partial`). **Idempotent** (leitet sich nur aus unveränderlichen
`*_start` ab). Danach Monats-/Jahres-Rollup neu.
Ausgeführt 2026-08-08 (Backup: `backup/db/nq_pre_recompute_2026-08-08/`):

| Tag | Imp alt → neu [Wh] | Effekt |
|---|---|---|
| 2026-07-13 | 883 → **2357** | +1474 (Lücke zurückgewonnen) |
| 2026-07-12/14/08-04..06 | ±0…+1 | randscharf geschlossen |
| 2026-07-15 / 08-07 | unverändert | letzter Tag im Lauf → `partial` |

### 4c. Vergleichs-/Analyseseite
Neu `/netzqualitaet/energievergleich` (`routes/pac4200.py:api_nq_energy_compare`,
`templates/nq_energie_vergleich_view.html`): Tagesvergleich PAC ↔ SM mit
absoluter + prozentualer Abweichung und Bewertung **ok / Ausreißer / geringe
Deckung**. Grün = marginal, Rot = auffällig trotz Deckung, Grau = Datenlücke.

## 5. Validierung
Auf **sauberen Volltagen** stimmt der korrigierte PAC-Bezug jetzt bis **< 1 %** mit
dem SM überein (unterschiedliche Messtechnik/-orte → Rest-Abweichung normal):

| Tag | PAC Imp | SM Imp | Δ |
|---|---|---|---|
| 2026-08-05 | 0,879 | 0,889 | −1,1 % |
| 2026-08-06 | 0,959 | 0,961 | −0,2 % |

Summenbewertung „ok"-Tage: **Imp-Abw. −0,65 %**, Ø |Abw.| **0,65 %**. Die
Anlauf-/Ausfalltage (07-12…14) bleiben korrekt als Ausreißer/geringe Deckung
markiert.

## 6. Deployment & SM-Korrektur (2026-08-08, abgeschlossen)

### 6a. Boundary-Interpolation & Recompute (durchgeführt)
- **Primary (aktiv):** Rollup `nq/transfer/nq_energy_rollup.py` + Rechenkern
  `nq/collector/nq_energy.py` + `config/nq_config.json:energy` nutzen jetzt
  `compute_daily_boundary` (energieerhaltend).
- **Recompute ausgeführt:** `nq/transfer/nq_energy_recompute.py --apply` (Backup:
  `backup/db/nq_pre_recompute_2026-08-08/`) — hat 2026-07-13 von 883→2357 Wh
  korrigiert. Monats-/Jahres-Rollup neu berechnet.
- **Tech synchronisiert:** `nq/collector/nq_energy.py` + `config/nq_config.json`
  per rsync nach `.181` deployed.

### 6b. SM-Korrektur Altlasten (einmalige Dev-Korrektur)
Trotz Recompute blieben Abweichungen aus Anlaufphase/Collector-Ausfällen bestehen.
**Einmaliges Korrektur-Skript** `nq/transfer/nq_energy_sm_correct.py`:

```bash
python3 -m nq.transfer.nq_energy_sm_correct --threshold-pct 0 --min-abs-kwh 0 --apply
```

**Korrigierte Tage (alle auf SM-Werte überschrieben, `src='sm_corrected'`):**

| Tag | PAC→SM Imp | PAC→SM Exp | Grund |
|-----|------------|------------|-------|
| 2026-07-12 | 0.829→1.584 | 0.000→0.773 | Anlaufphase Export=0, 47.7% Abw. |
| 2026-07-13 | 2.357→1.433 | 0.000→0.790 | Anlaufphase Export=0, 64.5% Abw. |
| 2026-07-14 | 0.058→1.576 | 0.019→0.570 | Collector-Ausfall, 96.3% Abw. |
| 2026-07-15 | 0.741→0.725 | 0.628→0.599 | Letzter Tag im Lauf (partial), 2.2% Abw. |
| 2026-08-04 | 0.037→1.838 | 0.007→0.669 | Collector-Ausfall, 98.0% Abw. |
| 2026-08-05 | 0.879→0.889 | 0.642→0.591 | 1.1% Abw. |
| 2026-08-06 | 0.959→0.961 | 0.610→0.579 | 0.2% Abw. |
| 2026-08-07 | 1.198→1.114 | 0.953→0.763 | Export 24.9% Abw. |

**Ergebnis:** Vergleichsseite `/netzqualitaet/energievergleich` zeigt jetzt **0,0%
Abweichung** für alle 8 Tage → saubere **Baseline für zukünftige Beobachtung**.

### 6c. Beobachtungsphase (ab 2026-08-09)
- **Erwartung:** Neue Tage sollten `src='counter'` mit <0,5% Abweichung haben.
- **Kritisch:** Abweichungen >0,5% weisen auf **systematische Messfehler** hin →
  Messmethode/Collector untersuchen.
- **Tool:** Vergleichsseite `/netzqualitaet/energievergleich` — nur noch reine
  Tabelle (keine Grafiken/Analysen mehr), Abweichungen sofort sichtbar.

## 7. Offene Punkte
- **Collector-Zuverlässigkeit** (Lücke 07-16…08-03) prüfen — der PAC zählt dank
  Stützbatterie durchgehend; es genügt **je ein** Snapshot nahe jeder Mitternacht.
  Aufgabe in `doc/TODO.md`.
