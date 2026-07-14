# NQ2-Roadmap — Audit, Reconciliation & Implementierung (Rolle N, PAC4200)

**Datum:** 2026-07-13 (Umsetzung WP0–WP5: 2026-07-14)  
**Status:** **WP0–WP5 implementiert** (2026-07-14). WP6 (Analyse/Mustererkennung) offen.  
**Priorität:** NQ2 hat Vorrang vor bestehendem NQ-Stand  
**Deliverable:** Diese Roadmap + 8 Work-Package-Prompts unter `doc/dev_prompt/NQ2-*/`

> **Umsetzungsstand 2026-07-14 (WP0–WP5):**
> - **WP0** ✅ Tote Stubs entfernt (`pac_client`/`nq_export_tech`/`nq_ingest_primary`); Tier-Benennung (fast/medium/slow) vereinheitlicht; Harmonik-Doku korrigiert (Extension @9001/@11001/@22001 = H3..H31); Retention 12 h angeglichen; `config/nq_config.json` um NQ2-Parameter erweitert; CT-Fix-Skript `scripts/nq_cleanup_ct.py` (Dry-Run-Default, `--commit`). **Ausführung des CT-Fix bleibt dem Betreiber** (destruktiv auf Produktions-NQ-DBs).
> - **WP1** ✅ PAC-Clone Single-Reader (`/api/pac4200/live` → `tech_read.fetch_tech_snapshot`, kein PAC-Direktzugriff); Frequenz im Medium-Tier (`nq_raw_medium.f`); `LimitMonitor` (Software-Grenzwerte → `nq_limit_alerts` + best-effort Mail). *PAC-interne Grenzwert-Status-Register bewusst nicht implementiert (No-Go: Adressen nicht erfinden) — Auswertung aus verifizierten Skalaren.*
> - **WP2** ✅ `nq_energy_monthly`/`nq_energy_yearly` + `rollup_month`/`rollup_year` + Timer; Transienten (`nq/aggregate/nq_transients.py` → `nq_transient_5min`), Transfer trägt sie mit.
> - **WP3** ✅ `/api/nq/energy/<day|month|year>/<key>`; PAC-Spiegelung additiv im Maschinenraum-Footer.
> - **WP4** ✅ `nq/transfer/nq_event_transfer.py` (Sofort-Transfer, `has_snippet`/`peak`, Cooldown+Ähnlichkeits-Dedup, Log-Cap 10000); `/api/nq/event/<id>`.
> - **WP5** ✅ `/netzqualitaet/chart` (feste 5-min-Tag-Ansicht, Event-Marker → 200-ms-Drill-down); `/api/nq/aggregates`; Navigations-Konsolidierung (oben nur Zeit-Navi, Seiten in der Schublade, `PVNavContext` 1 h).

---

## 1. Executive Summary

NQ2 ist zu großen Teilen bereits **real** (Tech-Collector 200 ms + Harmonik-1 s, 4h-Transfer/Aggregationskaskade, Energie-Differenzmethode, HF/NF/VLF-Skelette). Der Plan gleicht Widersprüche zugunsten NQ2 ab und schnürt die offenen Themen in 8 abhängigkeitssortierte **Work-Packages** (WP0–WP6), bestätigt durch User-Decisions.

**Architektur-Leitlinie (Rolle N):**
- Tech: RAM-first, Collector nur, kein SD-Nutzdaten-Write
- Primary: Aggregation/Analyse, SD-Speicherung, read-only auf `data.db`
- Single-Reader: Tech liest PAC4200 (Clients pollen Tech)

---

## 2. Audit — Was ist Real (verifiziert 2026-07-12/13)

| Komponente | Status | Details |
|---|---|---|
| **Tech-Collector** | ✅ Läuft | `nq/collector/nq_poller.py` — Fast 200ms (A+B), Slow 1s (Harmonik @9001/@11001/@22001), Energie 60s. tmpfs `/dev/shm/nq_cache.db` |
| **Transfer (4h)** | ✅ Läuft | `nq/transfer/nq_agg_transfer.py` — nq_agg_10s Tech→Primary, at-least-once, idempotent. Timer 00:10. |
| **Aggregation** | ✅ Läuft | `nq/aggregate/nq_aggregate.py` — 10s→5min→hourly→daily. Timer 00:15. Kaskade korrekt. |
| **Energie-Rollup** | ⚠️ Täglich nur | `nq/transfer/nq_energy_rollup.py` — nq_energy_daily (00:05). Monats-/Jahres-Fixpunkte **fehlen**. |
| **Analyse-Skelette** | ⚠️ Skelett | `nq/analysis/nq_{events,hf,nf,vlf}.py` importierbar. Timer pv-nq-analysis (00:30), pv-nq-primary-cap (00:40) existieren. |
| **Datenbank-Schemata** | ✅ OK | `nq_tech_schema.sql`, `nq_primary_schema.sql` schlüssig; `nq_raw_slow` jetzt vorhanden (Fix 2026-07-12). |
| **UI — PAC-Clone** | ✅ Läuft | `/pac4200` existiert, aber liest noch **direkt vom PAC**. Umstellen auf Tech-Puffer ist WP1. |
| **UI — NQ-Tableau** | ✅ Läuft | `/netzqualitaet/live` vorhanden; DB-Switch Kern↔NQ über `/api/nq/realtime_smart` (SSH read tmpfs, ~12h). |
| **Backups** | ✅ OK | GFS (son/vater/großvater), Offsite (Pi5-FB), Longterm (Pi4-Küche) angelegt. |

---

## 3. Audit — Drift gegen NQ2 (zu beheben WP0)

| # | Befund | NQ2-Anspruch | Aktion |
|---|---|---|---|
| 1 | `ANFORDERUNGEN.md` + `PAC_Clone/prompt.md` behaupten „Harmonische 2..64 **nicht möglich**" | Harmonische sollen gemessen & gespeichert werden | Doku-Korrektur: PAC liefert sie; Poller liest sie |
| 2 | fast/medium/slow-Benennung verwirrend | fast=200ms RMS; medium=1s Harmonik+Freq; slow=Zähler 300s | Klasse umbenennen oder kommentieren |
| 3 | PAC-Clone-Live liest **direkt vom PAC** | Tech ist einziger PAC-Leser; Clients pollen Tech-Puffer | → WP1: Umstellen auf Tech-RAM-Duplikat |
| 4 | Energie-Rollup nur täglich; kein Monats-/Jahres-Fixpunkt | Zähler an Tag/Monat/Jahr-Grenzen fixieren für Tooltip-Spiegelung | → WP2: Neue Tabellen, Rollup-Erweiterung |
| 5 | Transienten nicht gemessen (nur min/avg/max) | Spalten für pos/neg Transienten, slew-Raten | → WP2: Transienten in nq_5min berechnen |
| 6 | Frequenz in Fast-Block (refresht aber nur ~10s real) | Freq gehört ins 1s-Tier (medium) | → WP0/WP1: Umverteilung |
| 7 | Grenzwert-Speicher nicht pollt | Status-Register read-only pollen; Sofort-Mail bei Überschreitung | → WP1: Medium-Tier-Erweiterung + Mail-Pfad |
| 8 | Event-Snippet-Pipeline unvollständig | Schnipsel sofort Tech→Primary, has_snippet/peak_*, `/api/nq/event/<id>`, Chart-Marker | → WP4: Fertigstellung EVENT-Prompt-Anpassungen | #user Anmerkung: Schnipsel werden auf Primary erst beim Filtern vor dem Aggregieren erstellt und gespeichert!
| 9 | Primary-Langzeit-Aggregate nicht per API abrufbar | `/api/nq/realtime_smart` nur Tech-tmpfs (~12h); 5min/hourly/daily-Aggregate sollen abrufbar sein | → WP5: Langzeit-API + Chart-Quelle |
| 10 | Doku-Drift: retention 12/72 h Mixed; `CHANGE_ME_PRIMARY` ungenutzт; tote Stubs | Konsistenz herstellen | → WP0: Bereinigung |

---

## 4. Entscheidungen (User-bestätigt)

| Thema | Entscheidung | Begründung |
|---|---|---|
| **CT-Richtung (20:20 alte Daten)** | Betroffene Zeilen löschen + heutigen Energie-Tag ab sauberem Checkpoint neu rechnen | Tech-tmpfs altert ohnehin; Persistent betroffen nur heute. Keine Invertierung (komplex, fehleranfällig). |
| **Grenzwert-Speicher (Schreib-PAC-Zugriff)** | Separates guarded Einmal-Commissioning-Skript (`scripts/nq_pac4200_limits.sh`), explizit freigegeben | Ausnahme zu Rolle-N-read-only, aber bewusst, mit Audit-Log. Collector bleibt read-only. |
| **Schnipsel-Max-Dauer** | 300 s, konfigurierbar (`max_duration_s`), harte Obergrenze | NQ2 schwankt 60–300 s; 300 s bietet mehr Kontext für Transienten. |
| **Deliverable-Format** | Roadmap-Doc + 8 Work-Package-Prompts unter `doc/dev_prompt/NQ2-*/` | Bessere Handoff-Struktur als ein Monolithen-Prompt. |

---

## 5. Work-Packages — Abhängigkeitsmodell

```
WP0 (Datenhygiene + Doku)
├─→ WP1 (PAC-Clone Single-Reader + Medium-Tier + Grenzwerte)
├─→ WP2 (Fixpunkt-Zähler + Transienten)
│   ├─→ WP3 (Zähler-Spiegelung Tooltip)
│   └─→ WP5 (NQ-Chart + Marker)
├─→ WP4 (Event-Schnipsel-Pipeline)
│   └─→ WP5 (Event-Marker/Drill-down im Chart)
└─→ WP6 (Analyse/Mustererkennung, experimentell, parallel ab WP2+)
```

---

## 6. Work-Package Details

### WP0 — Datenhygiene & Doku-Konsolidierung (URGENT, klein)
**Abhängig:** keiner  
**Dauer:** ~2 h  
**Scope:**
1. **CT-Richtung-Fix (One-Time):**
   - Tech: `DELETE FROM nq_raw_fast/medium/slow, nq_agg_10s WHERE ts < HEUTE_20:20` (vor Datenverlust warnen).
   - Primary: `DELETE FROM nq_energy_daily WHERE day = TODAY` + `DELETE FROM nq_energy_checkpoint WHERE day = TODAY`; ab sauberem Checkpoint (nach 20:20 heute) neu berechnen.
   - Logging: `nq_capping_log` dokumentiert gelöschte Zeilen + Ursache.
2. **Doku-Korrektur:**
   - Grep „Harmonische nicht möglich" → 0 (ersetzen durch „verfügbar, gepollt via @9001/@11001/@22001").
   - `fast/medium/slow`-Benennung vereinheitlichen: fast=200ms, medium=1s Harmonik+Freq, slow=Zähler 300s.
   - PAC-Live-Kommentar: „liest **alle** verfügbaren Messgrößen inkl. Harmonische bis H31".
3. **Drift-Cleanup:**
   - `retention.raw_hours`: 12 h auf Tech (vorhanden), 12 h auf Primary (neu). Kommentare angleichen.
   - `transfer.primary_host="CHANGE_ME_PRIMARY"` (Pull-Modell): entfernen oder dokumentieren (wird nicht genutzt).
   - Tote Stubs: `nq/collector/pac_client.py`, `nq/transfer/nq_export_tech.py`, `nq/transfer/nq_ingest_primary.py` entfernen oder in Collector-Card als `pac_live.py` referenzieren.
4. **Roadmap-Doc:**
   - Diese Datei (`doc/netzqualitaet/NQ2_ROADMAP.md`) anlegen.
5. **Cards aktualisieren:**
   - `last_review=2026-07-13` auf berührten Cards.

**Prompt:** `doc/dev_prompt/NQ2-WP0-Datenhygiene/prompt.md`

---

### WP1 — PAC-Clone Single-Reader + Medium-Tier + Grenzwert-Status
**Abhängig:** WP0  
**Dauer:** ~4–6 h  
**Scope:**
1. **PAC-Live-Quellen-Umstieg:**
   - Untersuchen: Sind Lesezugriffe auf tmpfs schädlich für Fast-Loop-Schreibrate? (Messung: 200 ms-Raster-Jitter bei gleichzeitigem SSH-Read.)
   - Optionen prüfen: (a) RAM-Ring (Duplikat letzter Fast-Snapshot, 1–2 s), (b) direktes tmpfs-SELECT, (c) nur Accept, dass 1–5 Clients direkt lesen.
   - **Empfehlung:** (b) einfachste & schnellste → `/api/pac4200/live` nutzt SSH-one-liner `SELECT * FROM nq_raw_fast ORDER BY ts_ms DESC LIMIT 1` (letzte Zeile = aktuellster Snapshot).
   - `/api/pac4200/live` refaktor: `pac_live.read_snapshot(host=config.PAC_IP)` ersetzen durch lokalen tmpfs-Read über SSH-Fetch (analog `nq/tech_read.py`).
2. **Frequenz ins 1s-Tier (Medium):**
   - Real-Refresh ~10 s (verifiziert Feldtest). Fast-Poll 200 ms macht keine neuen Werte.
   - Umverteilung: Frequenz von Block A zu Block B (oder Medium-Block-Erweiterung).
   - Poller + pac_live anpassen.
3. **Grenzwert-STATUS-Register pollt (read-only):**
   - PDF-Register ermitteln (`PAC4200_Betriebsanleitung.pdf` §Status-Memory).
   - Medium-Tier (1 s) um Grenzwert-Status-Spalten erweitern (z. B. `over_u_l1`, `over_i_l2`, etc. als Flags 0/1).
   - `nq_raw_medium` um 6–12 Spalten erweitern oder separate Tabelle `nq_limits_status`.
   - Config: `analysis.limit_regs` (Register-Adressen) + `analysis.limit_window` (Cooldown für Mail).
4. **Sofort-Alarm-Mail bei Grenzwert-Überschreitung:**
   - Wenn Grenzwert-Flag für >10 s dauerhaft gesetzt → Mail über `diagnos/event_notifier.py` (bestehend).
   - Asynchron, damit Poller nicht blockiert.
   - `nq_config.json`: `"analysis": { "limit_mail_enabled": true, "limit_mail_cooldown_s": 300, ... }`.

**Prompt:** `doc/dev_prompt/NQ2-WP1-PAC-Reader/prompt.md`

---

### WP2 — Aggregation: Fixpunkt-Zähler + Transienten
**Abhängig:** WP0  
**Dauer:** ~5–7 h  
**Scope:**
1. **Fixpunkt-Zählertabellen anlegen:**
   - `nq_energy_daily`: existiert (00:00–00:00).
   - `nq_energy_monthly`: neu (1.→1., 00:00–00:00 localtime). 12 Zeilen/Jahr.
   - `nq_energy_yearly`: neu (1.1.→1.1., 00:00–00:00 localtime). 1 Zeile/Jahr (geplant 10 a).
   - Schema: `[period_key, wh_imp_start/end/delta, wh_exp_start/end/delta, varh_imp_start/end/delta, varh_exp_start/end/delta, vah_start/end/delta, src, created_ts]` (wie `nq_energy_daily`).
2. **Monats-/Jahres-Rollup:**
   - Neue Funktionen in `nq/transfer/nq_energy_rollup.py`: `rollup_month(month)`, `rollup_year(year)`.
   - Abholen: day_start-Checkpoint des Monats-Starts, day_end-Checkpoint des Monats-Ends → Differenz.
   - Systemd-Timer neu: `pv-nq-energy-rollup-month.timer` (1.→1. 00:10), `pv-nq-energy-rollup-year.timer` (1.1. 00:10).
   - Beide idempotent: `INSERT OR REPLACE`.
3. **Transienten in 5min messen & speichern:**
   - Vor 4h-Aggregations-Transfer: Auf Tech `nq_raw_fast` RAW über 5min-Fenster analysieren.
   - Transienten = Nulldurchgangs-Sprünge in U/I (z. B. dU >3 V in <1 s).
   - Spalten in `nq_5min`: `trans_pos_u1, trans_neg_u1, trans_pos_i1, ..., slew_u_avg_v_per_s, slew_u_max_v_per_s, slew_i_avg_a_per_s, slew_i_max_a_per_s` (je Phase).
   - Berechnung auf Tech, in `nq_agg_10s` speichern (neue Spalte `quantity='trans_...'`), dann mit 5min aggregieren.
   - Konfigurierbar: `event_filter.trans_threshold_v`, `trans_threshold_a`.
4. **5min-RAW-Retention 90 Tage (unverändert).**

**Prompt:** `doc/dev_prompt/NQ2-WP2-Aggregation/prompt.md`

---

### WP3 — Zähler-Spiegelung Monitoring-Tooltip
**Abhängig:** WP2  
**Dauer:** ~2 h  
**Scope:**
1. **Read-only-API für Zähler-Fixpunkte:**
   - `/api/nq/energy/<period_key>` → tägliche/monatliche/jährliche Werte aus `nq_energy_daily/monthly/yearly`.
   - Abfrage nach Period-Type (day=YYYY-MM-DD, month=YYYY-MM, year=YYYY).
   - Response: `{ period: "2026-07-01", wh_imp_delta: ..., wh_exp_delta: ..., from: "PAC4200" }`.
2. **Tooltip-Integration:**
   - Maschinenraum-Ansichten (Monat/Jahr/Gesamt) zeigen Bezug/Einspeisung vom Master-SM.
   - Tooltip-Zusatztext (Klammern): `"Bezug: 45.2 kWh (PAC: 45.1 kWh)"` (Vergleich PAC vs. SM).
   - Template-Anpassung in `templates/echtzeit_view.html` (Tooltip-Renderer).

**Prompt:** `doc/dev_prompt/NQ2-WP3-Zaehler-Spiegelung/prompt.md`

---

### WP4 — Event-Schnipsel-Pipeline (Fertigstellung EVENT-Prompt + NQ2-Anpassung)
**Abhängig:** WP0  
**Dauer:** ~6–8 h  
**Scope:**
1. **nq_event_transfer.py — Sofort-Transfer event=1-RAW:**
   - Tech: beim Trigger-Flag-Setzen (`event=1`) Schnipsel sofort nach Primary schreiben (nicht erst beim Tages-Transfer).
   - Oder: priorisierter Transfer-Thread (alle 60 s, event=1-Zeilen mit Eile).
   - Before Stale-Kappung nach 1 h (tmpfs flüchtig).
   - nq_capping_log: Nur Non-Event-RAW gelöscht; Event-Zeilen bis Transfer.
2. **has_snippet + peak_quantity/peak_value setzen:**
   - nq_events-Katalog: `has_snippet=1`, `peak_quantity='u_l1'`, `peak_value=245.3` (Extremum im Schnipsel).
   - Severity = normalisierte Überschreitung: (gemessen - Sollwert) / (Schwellwert - Sollwert), capped [0,1].
   - Dedup-Filter: gleicher `trigger` + Phase → kein neuer Schnipsel für 120 s (Cooldown).
   - Ähnlichkeits-Dedup: Trigger gleich + Größen ±30 % Amplitude + ±10 % Zeitfenster + min 24 h Abstand → nur Beschreibung, kein Snippet.
   - Event-Log-Cap: 10000 Zeilen Retention (älteste löschen).
3. **API `/api/nq/event/<event_id>`:**
   - Wide-Format: `[{ts_ms, u_l1, i_l1, p_tot, ...}, ...]` aus `nq_event_fast/medium/slow`.
   - Zeitraum: ts_start - pre_window bis ts_end + post_window.
4. **max_duration_s=300, konfigurierbar.**

**Prompt:** `doc/dev_prompt/NQ2-WP4-Events/prompt.md`

---

### WP5 — NQ-Chart + Event-Marker/Drill-down + Langzeit-Aggregate
**Abhängig:** WP2 (Aggregate), WP4 (Event-API)  
**Dauer:** ~8–10 h  
**Scope:**
1. **Feste Tag-Ansicht im 5min-Raster:**
   - `/netzqualitaet/chart?day=YYYY-MM-DD` → 288 Buckets (5min), keine dynamischen Zoom/Pan in den Tag.
   - Chart-Breite: feste Pixelanzahl; jeder Bucket = konstante Pixelbreite.
   - Min/Avg/Max als Bänder (min/max als Fläche, Avg als Linie), optional std als Fehlerbalken.
   - Zoom-out über Tage fließend möglich (Navi ← Tag / Tag → mit Pfeilen).
   - Zoom-in (bei Click auf Bucket) → Snippet-Drill-down (siehe 2).
2. **Event-Marker + Snippet-Drill-down:**
   - Marker im 5min-Chart: wenn `[nq_events.ts_start, ts_end]` ∩ 5min-Bucket → Marker (⚡ Icon) am Bucket-Anfang.
   - Click auf Marker → Overlay-Chart (300 s, 200 ms-Auflösung, alle nq_event_* Größen).
   - Wenn Event >5 min: Navi-Pfeile (← Prev 5min / Next 5min →) um Snippet zu scrollen (mehrere zusammenhängende 300s-Charts).
   - Extremwert-Marker: max/min je Größe im 5min-Bucket als kleine Kreuze oder Punkte am Chart.
3. **Langzeit-Aggregate per API:**
   - `/api/nq/aggregates?range=5min&start=ts1&end=ts2` → aus Primary `nq_5min/hourly/daily`.
   - Response: `{ data: [{ts, quantity, vmin, vavg, vmax, vstd}, ...], resolution: "5min", ... }`.
   - `/netzqualitaet/chart?range=month&month=YYYY-MM` → Tag-Ansicht + Monat-Aggregate.
   - Ähnlich für `range=year&year=YYYY`.
4. **Maschinenraum DB-Switch:** erweitern auf Tab-Buttons (Kern / NQ / Richtung-Navigation).

**Prompt:** `doc/dev_prompt/NQ2-WP5-Chart/prompt.md`

---

### WP6 — Analyse & Mustererkennung (experimentell, modular-offen)
**Abhängig:** WP2 (Aggregate), WP5 (Chart für Darstellung)  
**Dauer:** ~10–15 h (experimentell, iterativ)  
**Scope:**
1. **Intern/Extern-Trennung bidirektional:**
   - Schleifenimpedanz Z_loop aus `config/nq_impedance.json` je Phase.
   - ΔU_internal = ΔI × Z_loop (erwarteter Spannungsabfall bei eigener Last).
   - ΔU_net = ΔU_gemessen - ΔU_internal (Residual für Netz-Analyse).
   - Bei externem Ereignis (ΔU_net Sprung): umgekehrt zur Bereinigung interner Sicht nutzen.
   - Erweitert `nq/analysis/nq_hf.py` + `nq_nf.py`.
2. **Muster auf 4h-Block sofort laufen (vor Verfall):**
   - Nach `nq_agg_transfer` (Tech-Export), vor Datenverwurf (Stale-Cap nach 1 h).
   - Markerierung in `nq_events`: Muster-Kategorie (z. B. `kind='thd_spike'`, `'freq_nadir'`, `'tap_switch'`, `'erzeuger_schaltung'`, `'handels_event'`).
   - Speicherung in `nq_events.metrics` (JSON): Muster-Beschreibung, Metadaten.
3. **Weitere Mustererkennungen über wachsenden Gesamtbereich (VLF) mit niedriger Priorität:**
   - Täglich, nach Aggregation abgeschlossen (Timer 02:00).
   - Ziel A: Aufschwingen im europäischen Netz (grid oscillations), Reflexionen an Netzgrenzen.
   - Ziel B: LF-Schwingungspakete erkennen & wiedererkennen (die durchs Netz wandern).
   - Ziel C: Saisonale Muster (Jahreszeit, Handelstag-Kalender).
   - Modular-offen: weitere Muster ohne Code-Änderung konfigurierbar.
4. **Berichte:**
   - Text-Bericht: `/netzqualitaet/berichte?day=YYYY-MM-DD` oder monatlich.
   - Zusammenfassung auffälliger Muster, Event-Häufung, Trends.
5. **Pvsystem-Cross-Check (read-only aus data.db):**
   - Heizpatrone `FritzDECT_control` aktiv? → origin='lokal'.
   - WP (W_Imp_WP) springt? → origin='lokal'.
   - Wattpilot-Ladestrom ändert? → origin='lokal'.
   - Sonst: `origin='unklar'` oder `'netzseitig'`.

**Prompt:** `doc/dev_prompt/NQ2-WP6-Analyse/prompt.md`

---

## 7. Konfiguration (config/nq_config.json) — NQ2-Anforderungen

```json
{
  "polling": {
    "fast_ms": 200,
    "medium_ms": 1000,
    "energy_s": 60,
    "slow_ms": -1,
    "_comment": "Slow (Harmonik) wurde zeitweise gepollt, wird jetzt in Medium integriert. slow_ms=-1 = disabled."
  },
  "retention": {
    "raw_hours": 12,
    "primary_agg10s_hours": 72,
    "primary_rawslow_hours": 12,
    "primary_5min_days": 90,
    "primary_hourly_days": 365,
    "primary_daily_days": 3650,
    "event_keep_days": 90,
    "event_max_count": 10000
  },
  "event_filter": {
    "enabled": true,
    "du_step_v": 3.0,
    "df_step_hz": 0.02,
    "thd_u_pct": 5.0,
    "di_step_a": 5.0,
    "pre_window_s": 30,
    "post_window_s": 30,
    "max_duration_s": 300,
    "cooldown_s": 120,
    "dedup_amplitude_pct": 30,
    "dedup_time_pct": 10,
    "dedup_min_hours_apart": 24,
    "event_stale_cap_s": 3600
  },
  "analysis": {
    "thd_u_spike_pct": 5.0,
    "thd_i_spike_pct": 80.0,
    "u_band_min_v": 207.0,
    "u_band_max_v": 253.0,
    "df_gradient_hz_per_min": 0.05,
    "dfd_window_s": 180,
    "thres_tap_v": 2.0,
    "z_loop_source": "config/nq_impedance.json",
    "vlf_sigma_threshold": 2.0,
    "limit_mail_enabled": true,
    "limit_mail_cooldown_s": 300,
    "pvsystem_crosscheck": true
  },
  "grenzwerte": {
    "u_ln_min_v": 207.0,
    "u_ln_max_v": 253.0,
    "u_ll_min_v": 360.0,
    "u_ll_max_v": 440.0,
    "i_max_a": 35.0,
    "freq_min_hz": 47.0,
    "freq_max_hz": 52.0,
    "thd_u_max_pct": 8.0,
    "warning_levels": {
      "50pct": "gelb",
      "70pct": "orange",
      "90pct": "rot"
    }
  }
}
```

---

## 8. Verifikation je Work-Package

| WP | Verifikation |
|---|---|
| **WP0** | `grep "nicht möglich" doc/netzqualitaet/*.md` = 0; SELECT COUNT betroffener Zeilen bestätigt gelöschte Daten; `python3 -m py_compile nq/collector/nq_poller.py` OK; `nq_config.json` valide. |
| **WP1** | `/api/pac4200/live` liefert ohne PAC-Direktverbindung (SSH-Abfrage `nq_raw_fast`); Grenzwert-Status-Register pollt read-only; Test-Mail-Versand funktioniert. |
| **WP2** | `nq_energy_monthly`/`nq_energy_yearly` Tabellen existieren; Monats-/Jahres-Rollup an exakten Grenzen (1.→1., 1.1.→1.1.); 5min-Transienten-Spalten befüllt (Test: simulierter Stromsprung 32 A). |
| **WP3** | `/api/nq/energy/YYYY-MM-DD` liefert PAC-Klammerwert; Tooltip im Monat/Jahr/Gesamt zeigt „(PAC: X.X kWh)". |
| **WP4** | Schnipsel <300 s sofort auf Primary `nq_event_*` transferiert; Dedup 24h greift (zweiter Schnipsel gleichen Triggers nicht gespeichert); `/api/nq/event/<id>` liefert Wide-Format RAW-Serie. |
| **WP5** | Tag-Chart fix 5min, kein Zoom/Pan in Tag möglich, Zoom-out über Tage fließend; Event-Marker sichtbar; Click → Snippet-Drill-down 300s; Navi-Pfeile bei Multi-Snippet; Langzeit-Aggregat-API `/api/nq/aggregates` antwortet. |
| **WP6** | `analyze_day(day)` läuft idempotent, schreibt Muster in `nq_events`; Residual-Filterung nachweislich aktiv (Test WP-Einschaltvorgang); DFD an 15min-Grenzen mit Normal/Anomalie-Unterscheidung; VLF-Profil-Anomalie erkannt; pvsystem-Abgleich funktioniert. |

**Allgemein:**
- `python3 -m py_compile` aller neuen/geänderten Module.
- Pre-commit-Hook (doc-check): all Cards `last_review=2026-07-13`+, alle Module compilieren.
- Keine hardkodierten IPs (192.168.2.x); nur 192.0.2.x Platzhalter oder ENV-Variablen.
- Keine Write-Zugriffe in `data.db` / Produktion-Tabellen außer WP1 (Mail) und Grenzwert-Commissioning-Skript (guarded).

---

## 9. Zeitplan & Ressourcen

| Phase | Umfang | Dauer | Abhängig | Anmerkung |
|---|---|---|---|---|
| **WP0** | Doku + CT-Fix | ~2 h | keine | URGENT; vor allen anderen Starts. |
| **WP1** | PAC-Quelle + Medium + Grenzwert | ~5 h | WP0 | Parallel zu WP2 möglich. |
| **WP2** | Fixpunkte + Transienten | ~6 h | WP0 | Kritischer Pfad (blockiert WP3/WP5). |
| **WP3** | Tooltip + API | ~2 h | WP2 | Klein, schnell. |
| **WP4** | Event-Transfer + API + Dedup | ~7 h | WP0 | Parallel zu WP2 möglich. |
| **WP5** | Chart + Marker + Langzeit-API | ~9 h | WP2, WP4 | Großer Chart-Refactor; neueste Frontend-Anforderung. |
| **WP6** | Analyse + Muster + VLF | ~12 h | WP2, WP5 | Experimentell; iterativ; niedriger Kritikalität. |
| **Gesamt** | alle WPs | ~40 h | — | Parallel: (WP0, WP1 parallel), (WP2, WP4 parallel), WP5 wartet auf beide. |

---

## 10. Relevante Dateien & Code-Ankerpunkte

| Komponente | Datei | Relevanz |
|---|---|---|
| **Poller** | `nq/collector/nq_poller.py` | Fast-/Medium-/Slow-Loops; Event-Flag; Transienten-Berechnung (WP0/WP1/WP2/WP4). |
| **Live-Registerkarte** | `nq/pac_live.py` | Modbus-Adressen, Vorzeichen-Konvention, Harmonik-Blöcke. WP1: Umstieg auf SSH-tmpfs-Read. |
| **Web-API** | `routes/pac4200.py` | `/api/pac4200/live`, `/api/nq/realtime_smart`, Endpoints (WP1/WP3/WP4/WP5). |
| **Transfer** | `nq/transfer/nq_agg_transfer.py` | Tech→Primary 4h-Transfer (WP0/WP2 Transienten-Berechnung). |
| **Aggregation** | `nq/aggregate/nq_aggregate.py` | 10s→5min→hourly→daily; Transienten-Aggregation (WP2). |
| **Energie-Rollup** | `nq/transfer/nq_energy_rollup.py` | Täglich-Rollup + neu: Monats-/Jahres-Rollup (WP2). |
| **Energie-Collector** | `nq/collector/nq_energy.py` | Zähler-Snapshots, Reset-Erkennung, Differenzmethode. |
| **Tech-Read-Bridge** | `nq/tech_read.py` | SSH-Fetch tmpfs; erweitern für Langzeit-Aggregate (WP5). |
| **Schemata** | `nq/schema/nq_tech_schema.sql`, `nq/schema/nq_primary_schema.sql` | Neue Tabellen: `nq_energy_monthly`, `nq_energy_yearly`; neue Spalten in `nq_5min` (WP2); Limits in `nq_raw_medium` (WP1). |
| **Analyse-Skelette** | `nq/analysis/nq_events.py`, `nq_hf.py`, `nq_nf.py`, `nq_vlf.py` | Bestehend; Erweitern um Residual-Filterung (WP6). |
| **Config** | `config/nq_config.json` | Schwellwerte, Retention, Event-Filter (alle WPs); `config/nq_impedance.json` (WP6). |
| **Templates** | `templates/echtzeit_view.html` | DB-Switch, Chart-Renderer, Tooltip (WP3/WP5). |
| **Systemd** | `config/systemd/pv-nq-*.service/.timer` | Timer für Rollup-Monats-/Jahres (WP2), Event-Kappung (WP4), Analyse-Muster (WP6). |

---

## 11. Handoff & nächste Schritte

1. **Plan absegnen** ← Du bist hier.
2. **WP0 starten:** Datenhygiene + Doku-Korrektur + CT-Fix (URGENT, 2 h).
3. **WP1 + WP2 parallel:** PAC-Quelle (5 h) + Fixpunkt-Zähler/Transienten (6 h).
4. **WP3 nach WP2:** Tooltip-Integration (2 h).
5. **WP4 parallel zu WP1/WP2:** Event-Pipeline (7 h).
6. **WP5 nach WP2 + WP4:** Chart-Refactor (9 h, größtes Frontend-Update).
7. **WP6 nach WP2 + WP5:** Analyse/Muster (12 h, experimentell, optional iterativ).

**Prompts:** 8 separate Dateien unter `doc/dev_prompt/NQ2-*/prompt.md` — je WP ein Prompt mit Kontext, Abhängigkeiten, DoD.

---

## 12. Offene Punkte / Further Considerations

1. **RAM-Ring vs. direktes tmpfs-Read (WP1):** Ist ein separater Duplikat-Ring nötig, oder genügt der letzte `nq_raw_fast`-Row? → In WP1 messen.
2. **Grenzwert-Register korrekte Adressen (WP1):** PDF-Verification erforderlich. Commissioning-Skript später als separate Review.
3. **Scheinleistung nur einmal (nicht richtungsgetrennt):** Klären, ob PAC richtungsgetrennte VAh liefert. Sonst: konfigurierbar dokumentieren.
4. **Fest-Darstellung ohne Zoom/Pan in Tag (WP5):** User-Feedback nach Prototyp. Optional: später dynamisches Zoom-in auf Events-only.
5. **VLF-Analyse rechenintensiv (WP6):** CPU/NVME-Last beobachten; Priorisierung niedriger halten.

---

**Status:** 2026-07-13, Planung abgeschlossen. WP0 Start freigegeben.
