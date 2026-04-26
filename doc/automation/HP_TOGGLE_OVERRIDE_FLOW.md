# HP Toggle Override Flow — Complete Analysis

> **Stand 2026-04-26 (Audit-Update):**
> Verschoben von Repo-Wurzel nach `doc/automation/`.
> Klärungen zur Two-Layer-Logik und zu `extern_respekt_s` siehe `## 3.0`
> direkt unten — die ursprünglichen Detail-Beschreibungen weiter unten
> wurden inhaltlich nicht geändert, ihre Default-Werte stimmen aber
> jetzt mit dem Code überein (`extern_respekt_s = 1800` durchgängig).

## Overview
The system detects **external HP switching** (manual user OFF/ON via Fritz!DECT, pv-config, or physical switch) and creates a **respekt_hold** that prevents the Engine from immediately overriding the user action. This uses three key components:

1. **operator_overrides table** — Stores user intents (hp_toggle on/off)
2. **RegelHeizpatrone.bewerte()** — Detects external state transitions
3. **OperatorOverrideProcessor** — Maintains active respekt holds

---

## 1. WHERE HP TOGGLE OVERRIDES ARE CREATED/STORED

### Database Schema (steuerbox/intent_handler.py)
```sql
CREATE TABLE IF NOT EXISTS operator_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,                    -- 'hp_toggle'
    params_json TEXT NOT NULL,               -- {"state": "on"|"off"|"neutral"}
    created_at TEXT NOT NULL,                -- ISO-8601 timestamp
    respekt_s INTEGER NOT NULL,              -- Hold duration (default 1800s = 30 min)
    source TEXT NOT NULL DEFAULT 'steuerbox',
    status TEXT NOT NULL DEFAULT 'open'      -- 'open' | 'active' | 'done' | 'released'
);

CREATE TABLE IF NOT EXISTS steuerbox_audit (
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    override_id INTEGER,
    note TEXT                                -- 'override hold active', 'respekt window expired', etc.
);
```

### Override Creation Flow (steuerbox/intent_handler.py → handle_intent)

**When user clicks "HP OFF" in Steuerbox UI:**

```python
def handle_intent(action: str, params: dict[str, Any], client_ip: str, respekt_s: int | None = None):
    """
    action = 'hp_toggle'
    params = {'state': 'off'}
    respekt_s = 1800  (30 min default, configurable)
    """
    effektive_respekt_s = int(respekt_s or config.STEUERBOX_DEFAULT_RESPEKT_S)
    normalized = validate_action(action, params, effektive_respekt_s)
    
    # ✓ Write to operator_overrides with status='open'
    cur = conn.execute(
        'INSERT INTO operator_overrides (action, params_json, created_at, respekt_s, source, status) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (
            'hp_toggle',
            json.dumps({'state': 'off'}, ensure_ascii=False),  
            _utc_now_iso(),
            1800,
            'steuerbox',
            'open',                    # ← Initial state
        ),
    )
    override_id = int(cur.lastrowid)
    
    # Close any previous live overrides for hp_toggle
    _close_live_overrides_for_action(conn, 'hp_toggle', override_id)
    
    # Return result with respekt_s, override_id, status
```

---

## 2. HOW EXTERNAL HP SWITCHING IS DETECTED & STORED

### Detection Mechanism (automation/engine/regeln/geraete.py)

**State Transition Detection in `RegelHeizpatrone.bewerte()`:**

```python
class RegelHeizpatrone(Regel):
    def __init__(self):
        self._letzter_hp_zustand = None      # Track last observed state
        self._extern_ein_ts = 0              # Timestamp of external ON
        self._extern_aus_ts = 0              # Timestamp of external OFF
        self._warte_auf_engine_aus = False   # Flag: Engine expects HP to turn off
        
    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
        
        # ─── DETECT EXTERNAL ON: OFF→ON without Engine involvement ───
        if (obs.heizpatrone_aktiv and self._letzter_hp_zustand is not None
                and not self._letzter_hp_zustand):  # State transition OFF→ON
            
            if self._burst_ende == 0 and not self._drain_modus:
                # ✓ External ON detected: NOT from Engine burst/drain
                self._extern_ein_ts = time.time()
                LOG.info(f'HP extern eingeschaltet erkannt → Hysterese aktiv')
                logge_extern('fritzdect', 'HP extern EIN',
                             'Manuell eingeschaltet (nicht durch Engine)')
        
        # ─── DETECT EXTERNAL OFF: ON→OFF without Engine-hp_aus ───
        if (not obs.heizpatrone_aktiv and self._letzter_hp_zustand is not None
                and self._letzter_hp_zustand):  # State transition ON→OFF
            
            engine_hat_ausgeschaltet = self._warte_auf_engine_aus
            if engine_hat_ausgeschaltet:
                # ✓ Engine turned it OFF: clear flag
                self._warte_auf_engine_aus = False
                self._warte_auf_engine_aus_ts = 0
            else:
                # ✓ External OFF detected: NOT from Engine
                self._extern_aus_ts = time.time()
                self._burst_ende = 0
                self._burst_start = 0
                self._drain_modus = False
                LOG.info(f'HP extern ausgeschaltet erkannt → EIN-Sperre aktiv')
                logge_extern('fritzdect', 'HP extern AUS',
                             'Manuell ausgeschaltet (nicht durch Engine) → EIN-Sperre aktiv')
        
        # Clear external ON state when HP goes OFF
        if not obs.heizpatrone_aktiv:
            self._extern_ein_ts = 0
        
        self._letzter_hp_zustand = obs.heizpatrone_aktiv
        
        # Check if external hold is currently active
        ist_extern = (self._extern_ein_ts > 0
                      and (time.time() - self._extern_ein_ts) < extern_respekt)
```

### How Detection is Logged
```
~/~  YYYY-MM-DD, HH:MM:SS  EXTERN     fritzdect      HP extern AUS            --     Manuell ausgeschaltet (nicht durch Engine) → EIN-Sperre aktiv
     ↑                      ↑          ↑              ↑                        ↑
     ~=ungefähr             EXTERN     aktor          kommando                 ergebnis=--
```

---

## 3. RESPEKT_HOLD MECHANISM — HOW EXTERNAL AUS CREATES A HOLD

### 3.0 Wie die beiden Layer KOORDINIERT zusammenarbeiten (Stand 2026-04-26)

Layer 1 (Regel-Veto in `geraete.py`) und Layer 2 (Override-Reapply in
`operator_overrides.py`) sind **nicht redundant**, sondern bedienen
unterschiedliche Quellen — und sind seit 2026-04-26 explizit verkoppelt:

| Quelle einer Schalt-Absicht | Layer 1 wirkt? | Layer 2 wirkt? |
|---|---|---|
| Manuelles Schalten am Fritz!DECT-Taster | **Ja** (Zustands-Übergangs-Erkennung in `bewerte()`) | indirekt — siehe Verkopplung unten |
| Klick „HP OFF/ON" in Steuerbox-UI | nur passiv | **Ja** (DB-Override + Reapply bei Drift) |
| Engine-Eigenaktion (Burst, Drain) | nicht relevant | nicht relevant |

**Verkopplung (symmetrisch, beide Richtungen, 2026-04-26):**
Wenn Layer 1 eine externe Schaltung erkennt (`_extern_ein_ts` oder
`_extern_aus_ts` wird gesetzt), ruft die Regel synchron
`_cancel_conflicting_overrides()` auf. Diese Methode setzt offene/aktive
DB-Overrides der **Gegenrichtung** auf `status='released'` und schreibt
einen `steuerbox_audit`-Eintrag pro betroffenem Override.

```
Layer 1 erkennt extern AUS  →  cancelt alle hp_toggle(state=on)-Overrides
Layer 1 erkennt extern EIN  →  cancelt alle hp_toggle(state=off)-Overrides
(analog: klima_toggle)
```

Deshalb kann `_active_hold_needs_reapply()` ohne Spekulation arbeiten:
Wenn ein Override im Status `active` auftaucht, hat keine externe Aktion
ihn verworfen, und Drift bedeutet schlichten Reapply-Bedarf. Die frühere
„nicht reapplien, könnte ja extern sein"-Heuristik ist 2026-04-26
entfallen.

**Konsistenz `extern_respekt_s` (2026-04-26):**
Matrix = Code-Default = Doku = **1800 s (30 min)** für `heizpatrone`,
`klimaanlage`, `soc_extern`, `ww_absenkung`, `heiz_absenkung`. Die
früheren `3600`-Defaults im Code wurden auf `1800` korrigiert.

---

### Two-Layer Hold System

#### Layer 1: Rule-Level Hold (geraete.py)

When external OFF detected at time T, with `extern_respekt_s = 1800` (30 min):

```python
# ─── In bewerte() ───
# When HP is OFF and external OFF was detected:
extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
if (self._extern_aus_ts > 0
        and (time.time() - self._extern_aus_ts) < extern_respekt):
    
    verbleibend = int(extern_respekt - (time.time() - self._extern_aus_ts))
    LOG.debug(f'HP extern AUS → EIN-Sperre noch {verbleibend}s')
    return 0  # ← VETO: Score=0, Engine cannot turn HP on
```

**Result**: When `_extern_aus_ts` is active and within `extern_respekt_s` window:
- `bewerte()` returns **score=0** (hard veto)
- `erzeuge_aktionen()` is NOT called
- HP stays OFF, no matter what the normal scoring says

---

#### Layer 2: Override-Level Hold (operator_overrides.py)

When user creates an override via Steuerbox API:

```python
def process_pending(self, actuator, matrix: dict, limit: int = 20):
    # ─── READ 'active' OVERRIDES (already executed) ───
    active_rows = conn.execute(
        "SELECT id, action, params_json, created_at, respekt_s FROM operator_overrides "
        "WHERE status='active' ORDER BY id ASC",
    ).fetchall()
    
    for row in active_rows:
        override_id = int(row[0])
        action = row[1]  # e.g., 'hp_toggle'
        params = json.loads(row[2])  # e.g., {'state': 'off'}
        created_at = row[3]
        respekt_s = int(row[4])
        
        # ─── CHECK IF RESPEKT WINDOW EXPIRED ───
        remaining_s = self._remaining_respekt_s(created_at, respekt_s)
        if remaining_s <= 0:
            # Respekt window has expired → mark as 'done'
            self._set_status(conn, override_id, 'done')
            self._audit(conn, action, params, 
                       {'ok': True, 'info': 'respekt window expired'},
                       override_id, 'override hold expired')
            done += 1
            continue
        
        # ─── REAPPLY IF STATE DRIFTED ───
        # (Check if actual device state differs from desired state)
        if not self._active_hold_needs_reapply(action, params, obs_flags, elapsed_s=elapsed_s):
            skipped += 1
            continue
        
        # ✓ Device state drifted or reapply needed: execute override action again
        action_plan = self._map_override_to_actions(action, params, matrix, elapsed_s=elapsed_s)
        results = actuator.ausfuehren_plan(action_plan)
        # e.g., hp_aus executed → Fritz!DECT sends switch-off command
```

---

## 4. COMPLETE FLOW: USER MANUAL OFF → RESPEKT_HOLD

### Timeline: User turns HP OFF externally

```
T=0:00
├─ User clicks "HP OFF" in Steuerbox UI OR manually switches Fritz!DECT
│
├─→ steuerbox_api.py: POST /api/ops/hp_toggle
│   └─→ intent_handler.handle_intent(action='hp_toggle', params={'state': 'off'}, respekt_s=1800)
│       ├─ Validate params
│       ├─ INSERT INTO operator_overrides (status='open', created_at=T=0:00, respekt_s=1800)
│       └─ override_id=42 created
│
├─→ automation_daemon.py: OperatorOverrideProcessor.process_pending()
│   ├─ SELECT FROM operator_overrides WHERE status='open'
│   ├─ _map_override_to_actions('hp_toggle', {'state': 'off'})
│   │  └─ returns [{'aktor': 'fritzdect', 'kommando': 'hp_aus', ...}]
│   ├─ actuator.ausfuehren_plan([hp_aus])  ← Sends command to Fritz!DECT
│   ├─ UPDATE operator_overrides SET status='active' WHERE id=42  ← RESPEKT_HOLD ACTIVE!
│   └─ _audit(..., 'override executed, respekt hold active', respekt_s=1800)

T=0:05 (5 min later, Engine cycle runs)
├─→ Engine.bewerte() on RegelHeizpatrone
│   ├─ obs.heizpatrone_aktiv = False (HP is off, we see it)
│   ├─ obs.heizpatrone_aktiv != self._letzter_hp_zustand (False != True)
│   ├─ But _warte_auf_engine_aus=True? 
│   │  ├─ YES: Engine DID turn it off → clear flag
│   │  └─ NO: External turn-off detected → _extern_aus_ts=T, log "extern AUS"
│   │
│   ├─ Check respekt window:
│   │  └─ (T_now - _extern_aus_ts) = 5 min < extern_respekt_s (30 min)
│   │  └─ → return score=0 (VETO)
│   └─ Result: No EIN action possible, Engine respects user OFF

T=0:10 (and every 10s after during respekt window)
├─→ OperatorOverrideProcessor.process_pending() (runs every cycle)
│   ├─ SELECT FROM operator_overrides WHERE status='active'
│   ├─ remaining_s = 1800 - 10 = 1790s
│   ├─ Check _active_hold_needs_reapply():
│   │  ├─ action='hp_toggle', state='off', ist_an=False
│   │  └─ → Device is already OFF and desired is OFF → return False (no reapply needed)
│   └─ skipped += 1 (efficient: don't spam switch commands)

T=30:00 (30 min later, respekt window expires)
├─→ OperatorOverrideProcessor.process_pending()
│   ├─ remaining_s = 1800 - 1800 = 0
│   ├─ → UPDATE operator_overrides SET status='done' WHERE id=42
│   └─ _audit(..., 'override hold expired')
│
├─→ Next Engine cycle: RegelHeizpatrone.bewerte()
│   ├─ (T_now - _extern_aus_ts) = 30 min ≥ extern_respekt_s (30 min)
│   ├─ → ist_extern=False
│   └─ → Normal scoring rules apply, Engine regains control
```

---

## 5. KEY CODE SECTIONS

### A. External AUS Detection → Logging
**File: [automation/engine/regeln/geraete.py](automation/engine/regeln/geraete.py#L562-L576)**

```python
# Extern-AUS: HP ging EIN→AUS ohne Engine-hp_aus
if (not obs.heizpatrone_aktiv and self._letzter_hp_zustand is not None
        and self._letzter_hp_zustand):
    engine_hat_ausgeschaltet = self._warte_auf_engine_aus
    if engine_hat_ausgeschaltet:
        self._warte_auf_engine_aus = False
        self._warte_auf_engine_aus_ts = 0
    else:
        self._extern_aus_ts = time.time()
        self._burst_ende = 0
        self._burst_start = 0
        self._drain_modus = False
        LOG.info(f'HP extern ausgeschaltet erkannt → EIN-Sperre aktiv')
        logge_extern('fritzdect', f'HP extern AUS',
                     'Manuell ausgeschaltet (nicht durch Engine) → EIN-Sperre aktiv')
```

### B. Respekt Window Veto
**File: [automation/engine/regeln/geraete.py](automation/engine/regeln/geraete.py#L719-728)**

```python
# Extern-AUS respektieren: HP wurde manuell ausgeschaltet → Sperre
extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
if (self._extern_aus_ts > 0
        and (time.time() - self._extern_aus_ts) < extern_respekt):
    verbleibend = int(extern_respekt - (time.time() - self._extern_aus_ts))
    LOG.debug(f'HP extern AUS → EIN-Sperre noch {verbleibend}s')
    return 0  # ← Hard veto: score=0
```

### C. Override Hold Status Transitions
**File: [automation/engine/operator_overrides.py](automation/engine/operator_overrides.py#L49-68)**

```python
if self._uses_respekt_hold(action, params) and respekt_s > 0:
    self._set_status(conn, override_id, 'active')  # ← RESPEKT_HOLD ACTIVE
    self._audit(
        conn,
        action,
        params,
        {'ok': True, 'results': results, 'hold_active': True, 'respekt_s': respekt_s},
        override_id,
        'override executed, respekt hold active',
    )
    held += 1
else:
    self._set_status(conn, override_id, 'done')
    # ...
```

### D. Hold Reapply Logic (Smart, Non-Redundant)
**File: [automation/engine/operator_overrides.py](automation/engine/operator_overrides.py#L195-210)**

```python
@staticmethod
def _active_hold_needs_reapply(action: str, params: dict[str, Any],
                               obs_flags: dict[str, bool | None],
                               elapsed_s: int = 0) -> bool:
    """True wenn ein aktiver Hold erneut ausgeführt werden muss."""
    if action == 'hp_toggle':
        state = params.get('state')  # 'on' or 'off'
        ist_an = obs_flags.get('heizpatrone_aktiv')
        
        if ist_an is None:
            return False
        
        # Device state matches desired state → no reapply needed
        if state == 'on' and ist_an is True:
            return False  # ← HP is ON, user wanted ON → don't spam
        if state == 'off' and ist_an is False:
            return False  # ← HP is OFF, user wanted OFF → don't spam
    
    # Device state drifted or unknown → reapply to enforce hold
    return True
```

### E. Override → Action Mapping
**File: [automation/engine/operator_overrides.py](automation/engine/operator_overrides.py#L356-379)**

```python
def _map_override_to_actions(self, action: str, params: dict[str, Any], matrix: dict) -> list[dict[str, Any]]:
    if action == 'hp_toggle':
        state = params.get('state')
        if state == 'on':
            return [self._mk('fritzdect', 'hp_ein', None, 'Steuerbox Override: HP EIN')]
        if state == 'off':
            return [self._mk('fritzdect', 'hp_aus', None, 'Steuerbox Override: HP AUS')]
        if state == 'neutral':
            return []
        return None
```

---

## 6. SECURITY FEATURES & SAFEGUARDS

### Hard Guards NEVER overridden by respekt_hold

```python
# ── HARTE Kriterien: IMMER sofort, auch bei Extern ──
if obs.ww_temp_c >= temp_max:  # > 78°C
    return int(score * 1.5)  # ← Overheat emergency, ALWAYS active

if (obs.batt_soc_pct or 0) <= soc_schutz_abs:  # ≤ 5%
    return int(score * 1.5)  # ← Deep-discharge protection, ALWAYS active

# Extern-Autoritäts-Override: manuelle Einschaltung bei niedrigem SOC überstimmen
if ist_extern:
    extern_notaus_soc = get_param(matrix, self.regelkreis, 'extern_notaus_soc_pct', 15)
    if (obs.batt_soc_pct or 0) <= extern_notaus_soc:
        return int(score * 1.5)  # ← If user turns ON but SOC < 15%, override
```

### Steuerbox Validation (steuerbox/validators.py)

```python
def validate_action(action: str, params: dict[str, Any], respekt_s: int) -> dict[str, Any]:
    # Hard Guard: Heizpatrone darf nicht EIN bei kritischem SOC/Uebertemperatur.
    if action == 'hp_toggle' and state == 'on':
        soc_pct = params.get('soc_pct')
        if isinstance(soc_pct, (int, float)) and soc_pct <= config.STEUERBOX_HP_NOTAUS_SOC_PCT:
            abort(422, description='hp blocked: soc too low')  # ← Reject at API level
        
        uebertemp_c = params.get('uebertemp_c')
        if isinstance(uebertemp_c, (int, float)) and uebertemp_c >= config.STEUERBOX_HP_UEBERTEMP_C:
            abort(422, description='hp blocked: overtemperature')  # ← Reject at API level
```

---

## 7. PARAMETER CONFIGURATION

From `config/battery_control.json`:

```json
{
  "heizpatrone": {
    "extern_respekt_s": {
      "wert": 1800,
      "min": 900,
      "max": 7200,
      "einheit": "s",
      "beschreibung": "Respektiere manuelle EIN/AUS für diese Zeit (30 min default, 15–120 min)"
    },
    "extern_notaus_soc_pct": {
      "wert": 15,
      "min": 5,
      "max": 30,
      "einheit": "%",
      "beschreibung": "SOC-Schwelle bei der manueller EIN überstimmt wird"
    }
  }
}
```

---

## Summary: Detection & Hold Flow

| Step | Component | Logic | Status |
|------|-----------|-------|--------|
| 1 | User action | Click "HP OFF" in UI | `operator_overrides.status='open'` |
| 2 | Intent handler | Validate, insert record | `operator_overrides.status='open'` |
| 3 | OperatorOverrideProcessor | Execute `hp_aus` command → Fritz!DECT | `operator_overrides.status='active'` |
| 4 | RegelHeizpatrone | Detect OFF state transition | `_extern_aus_ts=T` set |
| 5 | Engine.bewerte() | Check respekt window, return `score=0` | **Hard veto active** |
| 6 | OperatorOverrideProcessor (every cycle) | Check if reapply needed → Skip if device state matches | Hold maintained |
| 7 | After `extern_respekt_s` expires | Mark override as `done` | **Engine regains control** |

---

## Question: What's currently MISSING?

Based on the analysis, the system **detects external OFF and creates a respekt hold**, BUT there's **no mechanism to CREATE an override from that detection**:

- **Current**: External OFF detected → Logs to schaltlog → `_extern_aus_ts` set → Rule-level veto active
- **Missing**: External OFF → Should auto-insert into `operator_overrides` with `status='active'` to track in audit trail

This means:
✓ Engine respects external OFF (via rule-level hold)
✗ Audit trail only shows "external action detected", not "respekt hold status active"

**Recommendation**: Add trigger in `logge_extern('fritzdect', '...')` to also insert a synthetic override record:

```python
def logge_extern(aktor: str, kommando: str, grund: str):
    # Log to schaltlog as before...
    
    # NEW: Also insert synthetic override for audit trail
    if aktor == 'fritzdect' and kommando == 'HP extern AUS':
        # Insert into operator_overrides with status='active'
        # to track respekt hold in structured DB
        insert_external_override(
            action='hp_toggle',
            params={'state': 'off', 'source': 'external'},
            respekt_s=extern_respekt_s
        )
```
