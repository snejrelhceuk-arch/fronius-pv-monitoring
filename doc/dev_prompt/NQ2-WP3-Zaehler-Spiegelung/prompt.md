# WP3 — Zähler-Spiegelung Monitoring-Tooltip (NQ2)

**Priorität:** Medium  
**Dauer:** ~2 h  
**Abhängig:** WP2 (Fixpunkt-Zähler)

---

## Kontext

Nutzer-Anforderung: „in den Ansichten Monat/Jahr/Gesamt zeigen die Tooltipps Bezug und Einspeisung - hier kann in Klammern der durch das PAC gemessene, für das Intervall gültige Wert stehen."

---

## Aufgaben (2 Blöcke)

### 1. Read-Only-API für Zähler-Fixpunkte

**Endpoint:** `/api/nq/energy/<period>`

a) **Neue Route in `routes/pac4200.py`:**
   ```python
   @bp.route('/api/nq/energy/<period_type>/<period_key>')
   def api_nq_energy(period_type, period_key):
       """
       period_type: 'day'|'month'|'year'
       period_key: 'YYYY-MM-DD'|'YYYY-MM'|'YYYY'
       Returns: { period, wh_imp_delta, wh_exp_delta, varh_imp_delta, ..., from: 'PAC4200' }
       """
       if period_type == 'day':
           row = db.execute("SELECT * FROM nq_energy_daily WHERE day=?", (period_key,)).fetchone()
       elif period_type == 'month':
           row = db.execute("SELECT * FROM nq_energy_monthly WHERE month=?", (period_key,)).fetchone()
       elif period_type == 'year':
           row = db.execute("SELECT * FROM nq_energy_yearly WHERE year=?", (period_key,)).fetchone()
       else:
           return jsonify({'error': 'invalid period_type'}), 400
       
       if not row:
           return jsonify({'error': 'no data'}), 404
       
       return jsonify({
           'period': period_key,
           'wh_imp_delta': row['wh_imp_delta'],
           'wh_exp_delta': row['wh_exp_delta'],
           'varh_imp_delta': row['varh_imp_delta'],
           'varh_exp_delta': row['varh_exp_delta'],
           'vah_delta': row['vah_delta'],
           'from': 'PAC4200',
           'src': row['src'],  # 'counter' | 'reset_fallback' | 'partial'
       })
   ```

b) **Authentifizierung:** read-only, kein Auth nötig (wie andere `/api/nq/` Endpoints).

**Verifikation:**
- `curl http://127.0.0.1:5000/api/nq/energy/day/2026-07-13` → JSON mit wh_imp_delta etc.
- HTTP 404 für nicht vorhandene Tage.

---

### 2. Tooltip-Integration in Maschinenraum (Monat/Jahr/Gesamt)

a) **Frontend-Logik in `templates/echtzeit_view.html`:**
   - Wenn DB=nq (PAC4200):
     - Tooltip auf Bezug/Einspeisung-Zelle: bestehender Wert (aus Master-SM) + Klammer mit PAC-Wert.
     - Abfrage: `/api/nq/energy/month/2026-07` (beim Laden der Monat-Ansicht).
     - Template: `"Bezug: 45.2 kWh (PAC: 45.1 kWh)"` (oder ähnlich).

b) **JavaScript-Code (Chart-Renderer + Tooltip):**
   ```javascript
   // When rendering Monat-View:
   const pac_energy = await fetch(`/api/nq/energy/month/${month}`).then(r => r.json());
   
   // In Tooltip-Function:
   const master_sm_value = row.wh_imp_delta;
   const pac_value = pac_energy.wh_imp_delta;
   const tooltip_text = `Bezug: ${master_sm_value} kWh (PAC: ${pac_value} kWh)`;
   ```

c) **UI/UX:**
   - Quelle-Icon neben dem Klammerwert: ⓘ (Information) oder ⚡ (PAC).
   - Abweichung in % berechnen + Warnung, wenn >5 % (z.B. rote Schrift).
   - Beispiel: `"Bezug: 45.2 kWh (PAC: 45.1 kWh, Δ-0.2%)"`.

d) **Fehlerbehandlung:**
   - Wenn PAC-Abruf fehlschlägt: nur Master-SM-Wert zeigen (kein Crash).
   - Log: warn "PAC energy fetch failed for ...".

**Verifikation:**
- Monat-Ansicht laden → Tooltip zeigt PAC-Klammerwert.
- Jahres-Ansicht laden → analoges Tooltip.
- Abweichung <5 %: grün, >5 %: orange/rot.

---

## Definition of Done

- [ ] `/api/nq/energy/<period_type>/<period_key>` Endpoint implementiert (read-only).
- [ ] Abfrage auf `nq_energy_daily`, `nq_energy_monthly`, `nq_energy_yearly` funktioniert.
- [ ] HTTP 404 für fehlende Perioden.
- [ ] Template `echtzeit_view.html` Tooltip erweitert um PAC-Klammerwert.
- [ ] JavaScript: `/api/nq/energy/` parallel abrufen, Wert in Tooltip einfügen.
- [ ] Abweichung berechnet + optionale Farbcodierung.
- [ ] Test: Monat/Jahr/Gesamt-Ansicht mit DB=nq, Tooltip sichtbar.
- [ ] Doc-Check exit 0.

---

## Commit-Message

```
feat(nq/wp3): Energy Tooltip Mirroring — PAC4200 vs Master-SM

- Add /api/nq/energy/<period_type>/<period_key> endpoint (read-only)
- Query nq_energy_{daily,monthly,yearly} for PAC-measured deltas
- Extend echtzeit_view.html tooltip: show PAC-value in parens "(PAC: X.X kWh)"
- Calculate deviation % + optional color coding (green <5%, orange/red ≥5%)
- Graceful fallback if PAC-fetch fails (show Master-SM only)

NQ2-Roadmap §6.3. Zählerstände-Vergleich für Betreiber-Transparenz.
Depends: WP2 (Fixpoint tables). Related: doc/netzqualitaet/NQ2_ROADMAP.md#WP3
```

