# WP1 — PAC-Clone Single-Reader + Medium-Tier + Grenzwert-Status (NQ2)

**Priorität:** High  
**Dauer:** ~5 h  
**Abhängig:** WP0 (Datenhygiene)

---

## Kontext

Du arbeitest am pv-system (Rolle N, PAC4200). Lies zuerst **AGENTS.md**, dann:
- `doc/netzqualitaet/NQ2_ROADMAP.md` §6 (WP1-Scope)
- `doc/dev_prompt/NQ2-Prompt.md` (Live-Ansicht + Frequenz + Grenzwert-Speicher)
- `nq/pac_live.py` (aktuelle Registerkarte + Snapshot-Funktion)
- `routes/pac4200.py` (Web-API `/api/pac4200/live`)
- `nq/collector/nq_poller.py` (Fast/Medium-Loops; Harmonik; Event-Trigger)
- `config/nq_config.json` (analysis.limit_mail_enabled neu)
- `doc/netzqualitaet/MESSTECHNIK.md` (Refresh-Raten Feldtest)
- `doc/netzqualitaet/PAC4200-Modbus.md` (Register-Referenz) + `doc/netzqualitaet/PAC4200_Betriebsanleitung.pdf` (PDF, Status-Register)

---

## Aufgaben (4 Blöcke)

### 1. PAC-Live-Quellen-Umstieg: Direct Read → Tech-Puffer

**Problem:** `/api/pac4200/live` ruft `pac_live.read_snapshot(host=config.PAC_IP)` direkt vom PAC auf. Das erzeugt mehrfache Modbus-Lese-Zugriffe parallel (Clients vs. Collector). NQ2: Tech soll **einziger PAC-Leser** sein; Clients pollen Tech-Puffer.

**Sinnhaftigkeit RAM-Ring prüfen:**
- **Frage:** Sind Lesezugriffe auf tmpfs während Fast-Loop-Schreibrate schädlich?
- **Messung (im Code als Kommentar/Debug-Output):**
  - Schreibe 200 ms-Loop und gleichzeitig SSH-Read-Loop (~2 s Abstand).
  - Messe: Jitter der nq_raw_fast-Einträge (sollten stabil alle 200 ms come in).
  - Alternativ: Prüfe WAL-Lock-Frequenz, Seiten-Flushes bei concurrent read.
- **Erwartung:** Minimal → direkter tmpfs-Read genügt (Option b).
- **Fallback:** RAM-Ring nur wenn massiver Jitter (Option a).

**Aktion (Option b — simplest, preferred):**

a) **`/api/pac4200/live` umschreiben:**
   ```python
   @bp.route('/api/pac4200/live')
   def api_pac4200_live():
       try:
           # Hole letzten Fast-Snapshot von Tech tmpfs (neuester Eintrag)
           snap = fetch_tech_latest_fast()  # neue Funktion
           return jsonify(snap)
       except Exception as e:
           logging.exception("PAC live fetch failed")
           return jsonify({'error': str(e)}), 500
   ```

b) **Neue Funktion `fetch_tech_latest_fast()` in `nq/tech_read.py`:**
   ```python
   def fetch_tech_latest_fast() -> dict:
       """Holt letzten nq_raw_fast-Row von Tech tmpfs via SSH."""
       host = _tech_host(cfg)
       tmpfs_db = cfg.get("tmpfs", {}).get("db_path")
       remote_code = (
           "import sqlite3,json\n"
           f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True)\n"
           f"r=c.execute(\"SELECT * FROM nq_raw_fast ORDER BY ts_ms DESC LIMIT 1\").fetchone()\n"
           "if r: print(json.dumps({...}))\n"  # Schema-Mapping
       )
       # SSH-Execute, parse JSON zurück
       # Response: { ts_ms, u_l1, u_l2, u_l3, i_l1, ..., f, event }
   ```

c) **`pac_live.read_snapshot()` beibehalten als Fallback** (für Feldtest-Offline-Checks), aber nicht in Web-Produktionsroute.

d) **Cache-TTL optional:** Wenn Latenz >500 ms → Caching mit 1 s TTL (gut genug für LCD-Clone).

**Verifikation:**
- `/api/pac4200/live` liefert ohne direkten PAC-Zugriff (strace zeigt keine PAC-Modbus-Connects).
- Latenz <500 ms (über SSH-Hüpfer + Abfrage akzeptabel).
- Gleichzeitiger Collector-Poller blockiert nicht.

---

### 2. Frequenz ins 1s-Tier (Medium) verschieben

**Problem:** Frequenz (Reg. 55) refresht real ~10 s (Feldtest 2026-07-12). Mit 200 ms-Poll sind alle 50 Reads identisch → Datenredundanz + Speicherverschwendung.

**Aktion:**

a) **`nq/pac_live.py` — Registerkarte umbauen:**
   - Aktuell: Frequenz in Block A (`FLOAT_MAP`).
   - Neu: Verschiebe zu Block B (`FLOAT2_MAP`) oder neuer `MEDIUM_MAP`.
   - Register 55 ist ohnehin in Block B vorhanden (Bestandteil der Betriebswerte). Nur Read-Optimierung, nicht neue Hardware.

b) **`nq/collector/nq_poller.py` — Medium-Loop-Anpassung:**
   ```python
   def _medium_loop(self):
       """1s-Poll: Harmonische (@9001/@11001/@22001) + Frequenz (Reg.55) + THD-I (neu)."""
       while self.running:
           try:
               snap = read_medium_snapshot()  # + Freq aus Block B neu
               self._write_raw_medium(snap, ts)
               time.sleep(1.0)
           except Exception as e:
               logging.error(f"Medium-loop failed: {e}")
   ```

c) **`nq_raw_medium` Spalten-Update:**
   - Neue Spalte: `f REAL` (Frequenz in Hz).
   - (Harmonische bereits vorhanden via Long-Format `nq_raw_slow`; keine Spalten-Änderung nötig. Falls Harmonik noch in Medium: auch dort bleiben.)

d) **Fast-Loop: Frequenz entfernen** oder als letzte bekannte Freq speichern (nicht neu pollen).

**Verifikation:**
- `SELECT COUNT(DISTINCT f) FROM nq_raw_medium` → viel weniger Wiederholungen als vorher.
- Frequenz-Spalte befüllt; Änderungen sichtbar ~10 s Abstand (realistisch).

---

### 3. Grenzwert-STATUS-Register read-only pollen (Tier 1)

**Hintergrund:** NQ2: „Grenzwert-Speicher abfragen, um daraus Sofort-Alarm initialisieren". Das bedeutet: PAC4200 hat interne Limits setzen, und wir lesen nur die STATUS-Flags (ob überschritten), kein Schreib-Zugriff.

**Aufgaben:**

a) **PAC4200_Betriebsanleitung.pdf durchsuchen:**
   - Abschnitte „Status Memory" / „Alarm Memory" / „Limit Registers".
   - Sammle Register-Adressen für: U_over/under_L1/L2/L3, I_over_L1/L2/L3, I_N, Freq_over/under, THD_over.
   - Typisch: Bereich ~500–800 (Status-Bytes, Bit-Flags).
   - Dokument: Liste in Kommentar `nq/pac_live.py` oder `MESSTECHNIK.md` abschnitt „Grenzwert-STATUS".

b) **`nq/pac_live.py` — neuer Read-Block „LIMITS_MAP":**
   ```python
   LIMITS_MAP = {
       'over_u_l1': (reg_addr_u_over_l1, 'FLOAT'),  # Aus PDF
       'under_u_l1': (reg_addr_u_under_l1, 'FLOAT'),
       ...
       'over_i_l1': (...),
       ...
       'over_freq': (...),
       'under_freq': (...),
   }
   def read_limits_snapshot():
       """Read STATUS-Register (Flags) — read-only, kein Schreib-Zugriff."""
       # Gibt dict zurück: { over_u_l1: 0/1, ... }
   ```

c) **`nq/collector/nq_poller.py` — Medium-Loop-Erweiterung:**
   ```python
   snap_medium = read_medium_snapshot()
   snap_limits = read_limits_snapshot()  # neu, 1 s-Raster
   combined = {**snap_medium, **snap_limits}
   self._write_raw_medium(combined, ts)
   ```

d) **`nq_raw_medium`-Schema erweitern:**
   - Neue Spalten: `over_u_l1, under_u_l1, ..., over_i_l1, ..., over_freq, under_freq` (bool oder 0/1).
   - Optional: separate Tabelle `nq_limits_status` (Long-Format) falls viele Flags.

**Verifikation:**
- `SELECT DISTINCT over_u_l1 FROM nq_raw_medium LIMIT 10;` zeigt 0/1-Werte.
- Limit-Flags korrelieren mit Messgrößen (wenn U_L1 knapp unter Grenzwert: over_u_l1=0; knapp drüber: 1).

---

### 4. Sofort-Alarm-Mail bei Grenzwert-Überschreitung

**Workflow:**
1. Medium-Loop liest `over_*`-Flags.
2. Wenn Flag >0 für 10 s dauerhaft: Mail auslösen (nicht bei jedem Sample).
3. Cooldown 300 s (nicht alle 10 s mailen).

**Aktion:**

a) **`config/nq_config.json` erweitern:**
   ```json
   "analysis": {
     ...
     "limit_mail_enabled": true,
     "limit_mail_cooldown_s": 300,
     "limit_window_s": 10,
     "_comment": "Wenn Limit-Flag >10s dauerhaft: Mail, dann Cooldown 300s."
   }
   ```

b) **`nq/collector/nq_poller.py` — Limit-Detektor (einfache Zustandsmaschine):**
   ```python
   class LimitMonitor:
       def __init__(self, limit_name, window_s, cooldown_s):
           self.limit_name = limit_name
           self.triggered_since = None
           self.last_mail_ts = None
           self.window_s = window_s
           self.cooldown_s = cooldown_s
       
       def check(self, flag_value, ts):
           if flag_value > 0:
               if not self.triggered_since:
                   self.triggered_since = ts
               elif ts - self.triggered_since >= self.window_s:
                   if not self.last_mail_ts or ts - self.last_mail_ts >= self.cooldown_s:
                       send_limit_mail(self.limit_name)
                       self.last_mail_ts = ts
           else:
               self.triggered_since = None
   ```

c) **Mail-Integration (über `diagnos/event_notifier.py` analog):**
   - Nutzer-Konfiguration: E-Mail-Adresse + Mail-Subject-Template.
   - Asynchroner Versand (kein Poller-Blocking).
   - Logging in `nq_capping_log` oder neue Tabelle `nq_limit_alerts`.

d) **Fallback:** Wenn Mail-Send fehlschlägt, loggen aber nicht wiederholen (verhindert Spam).

**Verifikation:**
- Manuell: Limite im PAC setzen (if möglich via Commissioning-Skript), Grenzwert überschreiten.
- Test-Mail-Versand: Log-Output „Limit mail sent for over_u_l1 at ...".
- Cooldown greift: zweite Mail erst nach 300 s (nicht nach 10 s).

---

## Abhängigkeiten & Blockaden

- WP0 muss abgeschlossen sein (Doku-Klarheit Frequenz-Tier).
- WP2 parallel möglich (keine Daten-Abhängigkeiten, nur Architektur-Clarity).

## Definition of Done

- [ ] `/api/pac4200/live` umgestellt auf Tech-SSH-Fetch (kein PAC-Direktread).
- [ ] Messung: Latenz <500 ms + Collector-Jitter minimal.
- [ ] Frequenz pollt 1 s-Raster (Dupletten reduziert).
- [ ] `nq_raw_medium` Spalte `f REAL` für Frequenz.
- [ ] PAC4200-Grenzwert-STATUS-Register identifiziert (aus PDF).
- [ ] `read_limits_snapshot()` implementiert, read-only.
- [ ] `nq_raw_medium` um Limit-Flags erweitert.
- [ ] `LimitMonitor` Zustandsmaschine läuft, Mail-Versand funktioniert.
- [ ] `config/nq_config.json` um `limit_*`-Parameter erweitert.
- [ ] `python3 -m py_compile nq/pac_live.py nq/collector/nq_poller.py nq/tech_read.py`.
- [ ] Doc-Check exit 0; Card-Update last_review=2026-07-13.

---

## Commit-Message

```
feat(nq/wp1): PAC-Clone Single-Reader + Medium-Tier Freq + Limit-Status

- Refactor /api/pac4200/live: direct PAC-read → Tech-tmpfs-SSH-fetch
- Move Frequency (Reg.55) from fast (200ms, redundant) to medium (1s, realistic)
- Read-only poll Limit-STATUS registers (over_u_l1, over_i_l1, etc.) in medium-loop
- Add LimitMonitor: trigger mail if limit-flag >10s + cooldown 300s
- Extend nq_raw_medium schema: column `f` (freq) + limit flags
- Update config/nq_config.json: limit_mail_enabled, limit_window_s, limit_cooldown_s

NQ2-Roadmap §6.1. Tech as single PAC-reader; Clients poll Tech.
Depends: WP0 (Doku). Blocks: WP5 (API).

Related: doc/netzqualitaet/NQ2_ROADMAP.md#WP1
```

