# WP4 — Event-Schnipsel-Pipeline (NQ2-Anpassung zur EVENT-Card)

**Priorität:** High  
**Dauer:** ~7 h  
**Abhängig:** WP0 (Datenhygiene)

---

## Kontext

Basis: `doc/dev_prompt/EVENT/prompt.md` (existiert). Hier: **NQ2-spezifische Anpassungen & Erweiterungen** (max_duration_s=300, 24h-Dedup-Regel, Event-Log-Cap 10000).

---

## Aufgaben (4 Blöcke)

### 1. nq_event_transfer.py — Sofort-Transfer event=1-RAW

a) **Neue Datei: `nq/transfer/nq_event_transfer.py`**
   - Liest Tech-tmpfs: `SELECT * FROM nq_raw_fast/medium WHERE event=1 AND ts > last_transfer_ts ORDER BY ts`.
   - Transferiert zu Primary `nq_event_fast/medium` sofort (nicht Tages-Transfer warten).
   - Markiert Zeilen als transferred (oder löscht sie sofort; At-Least-Once via Insert).
   - Timing: nach jedem Tech-Poller-Flush (alle 15 s); oder separater Daemon (1 min Interval).

b) **Funktion: `transfer_events()`**
   ```python
   def transfer_events(host: str, tmpfs_db: str, primary_db: str):
       """Fetch event-marked rows from Tech, insert to Primary nq_event_* (no wait for daily)."""
       # SSH-Fetch nq_raw_fast WHERE event=1 + ts > last_acked
       # INSERT OR REPLACE into nq_event_fast on Primary
       # Mark transferred in nq_transfer_log
   ```

c) **Systemd-Service:** `pv-nq-event-transfer.service` (Typ: simple/forking, Restart: always).
   - Oder: Integration in `nq_agg_transfer.py` als Sub-Routine (vor main()).

d) **Capping-Integration:**
   - Event-markierte Zeilen NICHT gelöscht durch Zeitring oder Größen-Kappung.
   - Nur wenn erfolgreich zu Primary transferiert: löschen.
   - Und: Stale-Event-Kappung nach `event_stale_cap_s` (config, z.B. 1 h), falls Transfer hängt.

**Verifikation:**
- Event-Zeilen sofort auf Primary nach Trigger (nicht erst nach 24 h).
- `nq_transfer_log` dokumentiert Event-Transfers.

---

### 2. has_snippet + peak_quantity/peak_value setzen

a) **`nq_events`-Katalog-Befüllung (in `nq/analysis/nq_events.py` oder eigenem Modul):**
   - Beim Event-Trigger: Katalog-Zeile anlegen.
   - Felder:
     - `has_snippet`: 1 wenn RAW-Transfer erfolgt (abhängig von Transfer-Status).
     - `peak_quantity`: z.B. `'u_l1'` (welche Größe das Extremum hatte).
     - `peak_value`: Zahl (z.B. 245.3 V oder 15.2 A).
     - `severity`: normalisiert [0, 1] = (Wert - Sollwert) / (Limit - Sollwert), capped.

b) **Dedup-Filter: Cooldown-Regel (120 s)**
   ```python
   def check_cooldown(trigger_type: str, phase: str, ts: int, last_event_ts: dict) -> bool:
       key = f"{trigger_type}_{phase}"
       if key not in last_event_ts:
           last_event_ts[key] = ts
           return True  # Allow
       if ts - last_event_ts[key] >= 120:
           last_event_ts[key] = ts
           return True
       return False  # Cooldown active, skip
   ```

c) **Ähnlichkeits-Dedup: Trigger-Ähnlichkeit (24 h Abstand)**
   - Wenn neuer Trigger gleich wie letzter UND Messgrößen ±30 % Amplitude UND ±10 % Zeitbereich:
     - Nicht als neuer Schnipsel speichern.
     - Katalog-Zeile: `kind='duplicate'`, `metrics={'similar_to_event_id': X, 'delta_hours': Y}`.
   - Min-Abstand: 24 h (konfigurierbar).

d) **Event-Log-Cap: 10000 Zeilen**
   ```python
   def cap_event_log():
       count = db.execute("SELECT COUNT(*) FROM nq_events").fetchone()[0]
       if count > 10000:
           oldest_id = db.execute(
               "SELECT event_id FROM nq_events ORDER BY created_ts ASC LIMIT 1"
           ).fetchone()[0]
           # Delete older events + associated snippets
           db.execute("DELETE FROM nq_events WHERE event_id <= ?", (oldest_id,))
           db.execute("DELETE FROM nq_event_fast WHERE event_id <= ?", (oldest_id,))
           # etc.
   ```

**Verifikation:**
- `SELECT has_snippet, peak_quantity, peak_value, severity FROM nq_events LIMIT 5;` → Werte sichtbar.
- Zweites Event gleichen Triggers in <120 s: nicht gespeichert (Cooldown).
- Ähnliches Event >24 h später: nur Beschreibung, kein Snippet.
- Event-Count: `SELECT COUNT(*) FROM nq_events;` ≤ 10000 (gekappt).

---

### 3. `/api/nq/event/<event_id>` Drill-down-Endpoint

a) **Route in `routes/pac4200.py`:**
   ```python
   @bp.route('/api/nq/event/<int:event_id>')
   def api_nq_event(event_id):
       """Holt RAW-Schnipsel je event_id. Wide-Format."""
       event = db.execute("SELECT * FROM nq_events WHERE event_id=?", (event_id,)).fetchone()
       if not event:
           return jsonify({'error': 'not found'}), 404
       
       # Hole Fast + Medium RAW
       fast_rows = db.execute(
           "SELECT ts_ms, u_l1, u_l2, ... FROM nq_event_fast WHERE event_id=? ORDER BY ts_ms",
           (event_id,)
       ).fetchall()
       medium_rows = db.execute(
           "SELECT ts, ... FROM nq_event_medium WHERE event_id=? ORDER BY ts",
           (event_id,)
       ).fetchall()
       
       # Pivot zu Wide-Format (wie /api/realtime_smart)
       data = pivot_to_wide([...fast, ...medium...])
       return jsonify({
           'event': event,
           'data': data,
           'count': len(data),
       })
   ```

b) **Response-Format:**
   ```json
   {
       "event": {
           "event_id": 42,
           "ts_start": 1689262800,
           "ts_end": 1689263100,
           "duration_s": 300,
           "kind": "thd_spike",
           "severity": 0.85,
           "peak_quantity": "thd_u_l1",
           "peak_value": 8.7
       },
       "data": [
           {"ts_ms": 1689262800000, "u_l1": 230.2, "i_l1": 15.3, "p_tot": 3450, ...},
           ...
       ],
       "count": 1500
   }
   ```

**Verifikation:**
- `curl http://127.0.0.1:5000/api/nq/event/42` → JSON-Response mit Schnipsel-Details + RAW-Daten.
- 200 ms-Auflösung sichtbar (ts_ms, nicht ts).

---

### 4. Config-Erweiterung + max_duration_s=300

a) **`config/nq_config.json`:**
   ```json
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
   }
   ```

b) **Nq_config-Validierung:** `max_duration_s` muss `>= pre_window_s + post_window_s` sein.

---

## Abhängigkeiten & Blockaden

- WP0: Doku-Klarheit nötig (Event-Konzept).
- WP5: Chart-Marker braucht diesen Endpoint.

## Definition of Done

- [ ] `nq/transfer/nq_event_transfer.py` implementiert (sofort-Transfer event=1-Zeilen).
- [ ] `nq_events` Katalog: has_snippet, peak_quantity, peak_value, severity befüllt.
- [ ] Cooldown-Filter (120 s): zweites Event gleichen Triggers nicht im Fenster.
- [ ] Ähnlichkeits-Dedup: 24 h Abstand, ±30% Amplitude, ±10% Zeit.
- [ ] Event-Log-Cap 10000: `SELECT COUNT(*) <= 10000`.
- [ ] `/api/nq/event/<event_id>` Endpoint: Wide-Format RAW-Snippet.
- [ ] Config: max_duration_s=300 + andere Parameter.
- [ ] Systemd-Service `pv-nq-event-transfer.service` (oder Integration in agg_transfer).
- [ ] Test: Trigger-Event → sofort auf Primary → API abrufbar.
- [ ] `python3 -m py_compile nq/transfer/nq_event_transfer.py`.
- [ ] Doc-Check exit 0.

---

## Commit-Message

```
feat(nq/wp4): Event-Snippet-Pipeline — Sofort-Transfer + Dedup + Drill-down-API

- Implement nq_event_transfer.py: real-time event=1-RAW transfer (Tech → Primary, before stale-cap)
- Populate nq_events catalog: has_snippet, peak_quantity, peak_value, severity (0..1)
- Cooldown-filter: no new snippet same trigger within 120s (prevent spam)
- Similarity-dedup: if trigger similar (±30% amplitude, ±10% time) + >24h apart → description only, no snippet
- Event-log-cap: retain max 10000 events (FIFO delete oldest)
- Add /api/nq/event/<event_id> endpoint: return Wide-Format RAW-series (nq_event_fast/medium)
- Extend config/nq_config.json: max_duration_s=300 (default, configurable), dedup_amplitude_pct, dedup_time_pct, etc.
- Add systemd service pv-nq-event-transfer (or integrate into pv-nq-agg-transfer)

NQ2-Roadmap §6.4. Transient snippets (<300s) captured & queryable.
Dedup prevents event-log bloat. Blocks: WP5 (Chart Markers).
Depends: WP0. Related: doc/dev_prompt/EVENT/prompt.md + NQ2_ROADMAP.md#WP4
```

