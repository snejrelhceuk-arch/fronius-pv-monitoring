# WP0 — Datenhygiene & Doku-Konsolidierung (NQ2-Implementierung)

**Priorität:** URGENT (muss vor allen anderen WPs ausgeführt werden)  
**Dauer:** ~2 h  
**Abhängig:** keiner

---

## Kontext

Du arbeitest am PV-System (Rolle N, PAC4200, NQ-Modul). Lies zuerst **AGENTS.md** vollständig, dann:
- `doc/netzqualitaet/NQ2_ROADMAP.md` (diese Planung)
- `doc/dev_prompt/NQ2-Prompt.md` (Nutzer-Anforderung)
- `doc/netzqualitaet/NQ_TIEFENPRUEFUNG_2026-07-12.md` (Audit-Status)
- `doc/dev_prompt/ANFORDERUNGEN.md` (bestehend, zu korrigieren)
- `doc/dev_prompt/PAC_Clone/prompt.md` (bestehend, zu korrigieren)
- `config/nq_config.json`, `nq/schema/nq_tech_schema.sql`, `nq/schema/nq_primary_schema.sql`

---

## Aufgabe: 5 Aufgabenblöcke

### 1. CT-Richtung-One-Time-Fix (Stromrichter-Korrektur 20:20 heute)

**Hintergrund:** PAC4200-Messwandler-Stromrichtung wurde heute ~20:20 korrigiert. Daten VOR 20:20 haben falsche Vorzeichen (Bezug ↔ Einspeisung vertauscht).

**Aktion:**

a) **Tech tmpfs (volatil, aber konsistenz-halber aufräumen):**
   ```bash
   ssh admin@192.0.2.181 sqlite3 /dev/shm/nq_cache.db \
     "DELETE FROM nq_raw_fast, nq_raw_medium WHERE ts < $(date -d '2026-07-13 20:20:00' +%s);"
   ```
   Oder über Python-Skript (sauberer, mit Logging):
   - Funktion `_cleanup_ct_data_tech()` in neuem `scripts/nq_cleanup_ct.py`.
   - Liest Tech-tmpfs, findet alle Zeilen < heute 20:20, löscht sie, loggt in `nq_capping_log`.
   - Warnung an stdout: „Deleting X rows older than 2026-07-13 20:20 from Tech tmpfs".

b) **Primary SD (persistent, kritisch):**
   - `nq/db/nq_2026-07.db`:
     ```sql
     DELETE FROM nq_energy_daily WHERE day = '2026-07-13';
     DELETE FROM nq_energy_checkpoint WHERE day = '2026-07-13';
     ```
   - Begründung: Tages-Differenzmethode `compute_daily` hat Vorzeichen-Fehler bei nq_energy_raw VOR 20:20 gezogen.
   - After: neue Checkpoints ab 20:20 sammeln (ab morgen 00:00, oder ab heute 20:20 rekonstruieren mit manuellen Zählerstanden).
   - Script: `_cleanup_ct_data_primary()` in `scripts/nq_cleanup_ct.py`.

c) **Logging & Audit-Trail:**
   - Beide Cleanups in `nq_capping_log` (Tech + Primary):
     ```sql
     INSERT INTO nq_capping_log(ts, trigger, table_name, rows_deleted, tmpfs_mb)
       VALUES(now(), 'ct_polarity_fix_2026-07-13_20:20', 'nq_raw_*', X, NULL);
     ```
   - Stdout-Meldung: Zeige gelöschte Zeilen-Anzahlen je Tabelle.
   - Verifizierung: `SELECT COUNT(*) FROM nq_raw_fast WHERE ts < 1689262800;` = 0.

**Verifikation:**
- `SELECT COUNT(*) FROM nq_energy_daily WHERE day = '2026-07-13';` = 0 (Primary).
- `sqlite3 /dev/shm/nq_cache.db "SELECT COUNT(*) FROM nq_raw_fast WHERE ts < 1689262800;"` = 0 (Tech).

---

### 2. Doku-Korrektur: „Harmonische nicht möglich" → Falsch

**Befund:** `ANFORDERUNGEN.md` §9 + `PAC_Clone/prompt.md` §3 + andere Stellen behaupten, PAC4200 liefert Harmonische **nicht** per Modbus. **Falsch.** Der Poller liest sie, Tiefenprüfung bestätigt.

**Aktion:**

a) **`doc/dev_prompt/ANFORDERUNGEN.md`:**
   - Suche: `"Harmonische 2..64 blockiert"`
   - Ersetze: `"Harmonische werden gemessen (Read-only, Adressen @9001/@11001/@22001) und in nq_raw_slow gespeichert. Slow-Tier: 1 s Raster (via pac_live.read_harm_snapshot)."`

b) **`doc/dev_prompt/PAC_Clone/prompt.md` §3:**
   - Befund korrekt: „PAC4200 liefert per Modbus keine **Einzelharmonik-Spektren** in der öffentlichen Register-Map" (nur THD-Gesamtwert + Verzerrungsstrom, nicht die 378 Einzelwerte H2..H64).
   - **Aber:** Wir lesen sie lokal aus Block-B-Erweiterung. Korrigiere: „Modbus-Standard-Map hat nur THD-Gesamtwert. Einzelharmonische @9001/@11001/@22001 sind in der Siemens-Erweiterung verfügbar. Der Poller liest sie seit 2026-07-12 erfolgreich."

c) **`doc/netzqualitaet/MESSTECHNIK.md`:**
   - Abschnitt „Gemessene Refresh-Raten" oder ähnlich: Änderung dokumentieren.
   - Alt: „Harmonische: noch offen" → Neu: „Harmonische 2..31 (ungerade, 16 Ordnungen × 3 Phasen × 2 Größen U/I) per Block @9001/@11001/@22001, ~1 s Refresh. Verifiziert Feldtest 2026-07-12."

d) **`nq/README.md`:**
   - Harmonik-Verfügbarkeit erwähnen (momentan nur Erwähnung als „Placeholder für zukünftige Daten").

**Verifikation:**
```bash
grep -r "nicht möglich" doc/dev_prompt doc/netzqualitaet --include="*.md"
# Output = 0 (keine Treffer mehr)
```

---

### 3. fast/medium/slow-Tier Benennung vereinheitlichen

**Befund:** Nomenclature ist verwirrend. NQ2 definiert klar:
- **fast:** 200 ms RMS-Werte (U, I, P, Q, S, cos φ) → nq_raw_fast
- **medium:** 1 s Harmonische + Frequenz → nq_raw_medium (mislabeled: „Medium" aber enthält Harmonik)
- **slow:** Zähler-Snapshots 300 s → nq_energy_raw

**Aktion:**

a) **`nq/collector/nq_poller.py`:**
   - Kommentar-Klarheit: Zeige die Tier-Zuordnung am Top des Moduls:
     ```python
     # Tier 0 (fast, 200 ms): Block A + B Skalare (U, I, P, Q, S, cos φ, THD-U/I, Freq, Unsymmetrie)
     #   → nq_raw_fast (ts_ms PK, 200 ms-Raster)
     # Tier 1 (medium, 1 s): Harmonische + Grenzwert-Status
     #   → nq_raw_medium (ts PK, 1 s-Raster)
     # Tier 2 (slow, 300 s): Energiezähler (kumulativ)
     #   → nq_energy_raw (ts PK)
     ```
   - Alle Variablen/Funktionsnamen konsistent durchziehen (`_fast_loop`, `_medium_loop`).

b) **`nq/pac_live.py`:**
   - Kommentar: „Block A (Tier 0 fast)" + „Block B (Tier 1 medium)"

c) **`config/nq_config.json`:**
   - Kommentar zu `polling`:
     ```json
     "polling": {
       "fast_ms": 200,
       "medium_ms": 1000,
       "slow_ms": -1, #Anmerkung user: soll 300ms sein!
       "_comment": "Tier0=fast(200ms Skalare), Tier1=medium(1s Harmonik+Freq), Tier2=slow(-1=disabled, Zähler im energy_s)"
     }
     ```

**Verifikation:**
- `grep -r "Tier.*fast\|medium\|slow" nq/collector nq/pac_live.py` zeigt Verwendung.

---

### 4. Doku-Drift bereinigen

**Aufgaben:**

a) **retention.raw_hours: 12 h vs. „72 h"-Kommentare:**
   - Config aktuell: `retention.raw_hours = 12` (Tech). Gut. 
   - Kommentare in `nq_tech_schema.sql`, `nq_capping.py`: „72 h Ring-Buffer" → Falsch!
   - Korrigiere: „12 h Ring-Buffer (3 Tage historische Daten deckt nicht ganz ab; wird täglich via Transfer nach Primary exportiert)".
   - Primary: `retention.primary_rawslow_hours = 12` auch OK.

b) **`config/nq_config.json` `transfer.primary_host="CHANGE_ME_PRIMARY"`:**
   - Im Pull-Modell (Tech holt von Primary, nicht umgekehrt) nicht genutzt.
   - Entfernen oder kommentieren: `"_transfer_note": "Pull-Modell: Primary lädt via SSH von Tech (nq/transfer/nq_agg_transfer.py). primary_host unused."`

c) **Tote Stubs entfernen:**
   - `nq/collector/pac_client.py` — ist `NotImplementedError`-Stub (durch `pac_live.py` ersetzt). **Entfernen.**
   - `nq/transfer/nq_export_tech.py` — Stub. **Entfernen.**
   - `nq/transfer/nq_ingest_primary.py` — Stub. **Entfernen.**
   - Collector-Card (`doc/llm/cards/netzqualitaet-nq-collector.card.md`): Code-Anchor korrigieren: statt `pac_client.py` → `pac_live.py` + `nq_poller.py`.

**Verifikation:**
- Files existieren nicht mehr: `ls nq/collector/pac_client.py` → not found.
- Grep „CHANGE_ME_PRIMARY" in `config/nq_config.json` → nur in Kommentar.

---

### 5. Cards aktualisieren (last_review)

**Aufgaben:**

Folgende Cards berührt von WP0:
- `doc/llm/cards/netzqualitaet-nq-collector.card.md` — Code-Anchor, Doku-Refs.
- `doc/llm/cards/netzqualitaet-nq-aggregation.card.md` — retention-Kommentar.
- Ggf. neue Card für NQ2-Roadmap anlegen (`netzqualitaet-nq2-roadmap.card.md`), referenziert in `INDEX.md`.

**Standard:**
- YAML frontmatter: `last_review: 2026-07-13`
- Kurzer Eintrag in `Changes` oder `Revision`-Sektion: „WP0 CT-Polarity-Fix + Harmonik-Doku-Korrektur + Tier-Benennung".

---

## Definition of Done

- [ ] `scripts/nq_cleanup_ct.py` fertig (2 Funktionen: Tech + Primary cleanup, Logging).
- [ ] CT-Fix ausgeführt: Tech tmpfs + Primary SD bereinigt; Zeilen-Counts logged.
- [ ] Harmonik-Doku korrekt: „nicht möglich" → 0 Treffer; @9001/@11001/@22001 dokumentiert.
- [ ] fast/medium/slow Tier-Benennung konsistent in Poller + pac_live + config.
- [ ] Retention-Kommentare 12/72 h angleichen; `CHANGE_ME_PRIMARY` entfernt/kommentiert.
- [ ] Tote Stubs (`pac_client.py`, etc.) gelöscht; Code-Anker aktualisiert.
- [ ] Cards: `last_review=2026-07-13` + Änderungs-Notiz.
- [ ] `python3 -m py_compile scripts/nq_cleanup_ct.py` OK.
- [ ] Pre-commit-Hook (`doc-check`): exit 0.
- [ ] Keine hardkodierten IPs in committetem Code (nur 192.0.2.x Platzhalter oder ENV).
- [ ] Nach WP0-Abschluss: WP1 + WP2 Prompts sofort Freigabe-ready.

---

## Commit-Message

```
fix(nq): WP0 — CT-Polarity-Datenhygiene + Doku-Reconciliation

- One-time cleanup: Delete pre-20:20 data (false polarity) from Tech tmpfs + Primary SD
- Correct „harmonics unavailable" docs: 2026-07-12 verified @9001/@11001/@22001 working
- Unify fast/medium/slow tier naming & comments
- Reconcile retention hours 12/72 h comments
- Remove dead stubs (pac_client, nq_export_tech, nq_ingest_primary)
- Update collector Card: code anchor → pac_live.py + nq_poller.py
- Cards: last_review=2026-07-13

NQ2-Roadmap §1 (WP0). All downstream WPs (WP1–WP6) unblocked.

Related: doc/netzqualitaet/NQ2_ROADMAP.md
```

