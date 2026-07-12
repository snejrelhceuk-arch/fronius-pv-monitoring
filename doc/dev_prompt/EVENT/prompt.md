# Prompt: NQ-Ereignis-Schnipsel (Event-RAW, Speicherung, Darstellung)

**Kontext:** Du arbeitest am pv-system (repo `{REPO_DIR}`,
branch `feat/reformation-wp-bridge`). Lies zuerst AGENTS.md vollständig. Dann:
- `doc/netzqualitaet/NQ_MODUL.md` §8 (Analysetools), §9 (Event-Schnipsel)
- `doc/netzqualitaet/NQ_TESTS_UND_DB.md` §9 (Event-Schnipsel-Konzept)
- `nq/schema/nq_tech_schema.sql` (nq_raw_fast/medium + event=1-Flag)
- `nq/schema/nq_primary_schema.sql` (nq_events, nq_event_fast/medium, peak_quantity)
- `nq/collector/nq_poller.py` (_detect_event + event-Flag-Setzen)
- `config/nq_config.json` (event_filter-Block)
- `templates/echtzeit_view.html` (Maschinenraum-Charting als Vorbild)
- `doc/llm/cards/netzqualitaet-nq-analysis-events.card.md`

---

## Nutzeranforderungen (aus Gespräch)

### Hintergrund und Zielbild
Der Nutzer möchte bemerkenswerte elektrische Ereignisse am Netzanschlusspunkt
dauerhaft und vollauflösend gespeichert haben — als kurze RAW-Serien (max. 60 s)
mit **allen verfügbaren Messgrößen** des PAC4200 (U, I, P, Q, S, PF, THD-U, THD-I,
f, cos φ, Phasenwinkel, Verzerrungsstrom, I_N). Die Anforderungen im Einzelnen:

### A. Auslöser (Trigger)
Konfigurierbare Schwellwerte in `config/nq_config.json` (event_filter):
- **Spannungssprung** `du_step_v` (Default 3 V): |ΔU_LxN| zwischen zwei Polls
- **Frequenzsprung** `df_step_hz` (Default 0.02 Hz): |Δf| zwischen zwei Polls
- **THD-U-Schwelle** `thd_u_pct` (Default 5 %): THDu_Lx ≥ Schwelle
- **Stromsprung** `di_step_a` (Default 5 A): |ΔIs_Lx| zwischen zwei Polls
  (Nutzerbeispiel: „Strom schwankt ja immer, aber nicht um >32A!")
- **THD-I-Schwelle** `thdi_pct` (Default 80 %): extreme Stromverzerrung
- Weitere Trigger nach Bedarf konfigurierbar (P-Sprung, Unsymmetrie-Sprung)
- **Negativ-Trigger** (Rückkehr in Normalbereich) als optionaler Event-Abschluss

### B. Dedup / Wiederholungsfilter
- **Cooldown** `cooldown_s` (Default 120 s): innerhalb dieser Zeit kein neuer
  Schnipsel vom gleichen Trigger-Typ (verhindert Sturm bei anhaltender Störung)
- **dedup_key**: Kombination aus trigger + Phase (z.B. `du_step_L2`)
- Aktiver Cooldown wird in `nq_capping_log` sichtbar gemacht (nicht still)

### C. Schnipsel-Umfang (max. 60 s)
- **Pre-window** `pre_window_s` (Default 30 s): RAW-Zeilen VOR dem Trigger werden
  in `nq_event_fast/medium` kopiert (aus nq_raw_fast where ts ≥ trigger - pre)
- **Post-window** `post_window_s` (Default 30 s): Zeilen NACH dem Trigger
- **Maximale Dauer** `max_duration_s` = 60 s gesamt (Pre+Post)
- **Kein Verlust bei Reboot**: da RAW im tmpfs volatil ist, wird der Schnipsel
  sofort beim Trigger-Erkennen **synchron** in `nq_event_*` auf Primary geschrieben
  (nicht erst beim Tages-Transfer) — oder als priorisierter Transfer markiert

### D. Schnipsel-Ablage auf Primary
In der Monats-DB `nq/db/nq_YYYY-MM.db`:
- `nq_event_fast`: ts_ms, event_id, alle Fast-Spalten (U, I, P, Q, S, PF, f)
- `nq_event_medium`: ts, event_id, alle Medium-Spalten (THD, Unsymmetrie)
- `nq_event_slow`: Platzhalter (noch keine Daten — Harmonik-Register fehlen)
- `nq_events`: Katalog — event_id, ts_start, ts_end, duration_s, band
  (`HF_local`|`NF_global`|`VLF`), kind, trigger, peak_quantity, peak_value,
  severity (0..1, normierte Überschreitung), origin (`lokal`|`unklar`|`netzseitig`),
  dedup_key, n_samples, has_snippet (1 wenn RAW da), metrics (JSON)

### E. Auffindbarkeit in Charts — das Wichtige
Events müssen in den Aggregat-Charts **optisch sichtbar** sein und aufgerufen werden:
1. Im Maschinenraum-Chart (`/maschinenraum?db=nq`) zeigt eine **Ereignis-Markierung**
   als vertikale Linie + kleines Icon (⚡) auf dem Zeitstrahl an, wenn in einem
   Aggregat-Bucket (10 s) ein Event-Snippet vorhanden ist
   (JOIN: `ts_agg_bucket` ∩ `[nq_events.ts_start - pre, nq_events.ts_end + post]`).
2. **Drill-down**: Klick auf ein Event-Marker öffnet einen Overlay-Chart mit der
   hochauflösenden RAW-Serie aus `nq_event_fast` (500-ms-Auflösung, alle Größen).
3. Die Drill-down-API `/api/nq/event/<event_id>` gibt Wide-Format zurück
   (analog `/api/realtime_smart` — ts + alle Größen als Spalten).
4. **Event-Liste** auf der `/netzqualitaet/live`-Seite: Tabelle der letzten Events
   (ts_start, kind, trigger, severity, peak_value, has_snippet) mit Klick auf
   Drill-down.

### F. Implementierungsreihenfolge
1. `nq/transfer/nq_event_transfer.py` — sofortiger (priorisierter) Transfer von
   Event-Schnipseln zu Primary nach Trigger (nicht auf Tages-Transfer warten)
2. `/api/nq/event/<event_id>` Endpoint in `routes/pac4200.py`
3. Event-Marker + Drill-down in `templates/echtzeit_view.html`
4. Event-Liste in `templates/nq_live_view.html`

---

## Architektur-Grenzen (Rolle N, nie verletzen)
- Kein Schreibpfad in `data.db`/Produktionstabellen
- Kein Schreibpfad zum PAC4200 (nur read)
- Tech-SD nicht dauerhaft beschreiben (Event-Transfer sofort zu Primary)
- Kappung: Event-markierte Zeilen (event=1) werden vom Ring-Buffer NICHT gelöscht,
  bis Transfer quittiert

## Definition of Done
- Trigger erkennt Ereignisse live im Poller
- Schnipsel (<60s, Pre+Post) sofort auf Primary übertragen und persistent
- nq_events Katalogeintrag mit peak_quantity/peak_value/severity/dedup_key
- Drill-down-API gibt RAW-Serie zurück
- Chart-Marker + Drill-down sichtbar im NQ-Chart
- doc-check exit 0, alle neuen Module kompilieren
