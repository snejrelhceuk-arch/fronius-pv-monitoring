#!/usr/bin/env python3
"""
Wattpilot-Rekonstruktion 22.–27.5.2026 aus Lastsprüngen in data_1min.

Identifiziert Intervalle mit hoher Netzlast (potenzielle Ladevorgänge),
zeigt sie in einer interaktiven HTML-Tabelle mit Bestätigungshäkchen,
berechnet die Integrale der bestätigten Intervalle und schreibt das
Ergebnis in wattpilot_daily.

Effekt: Die bestätigten kWh werden aus w_haushalt (Sonstige) heraus-
genommen und als w_wattpilot (Wattpilot) in der Verbraucher-Ansicht
ausgewiesen.

Usage:
    cd /home/admin/Dokumente/PVAnlage/pv-system
    python3 scripts/wattpilot_reconstruct_may22_27.py
    # → öffnet http://127.0.0.1:8765 im Browser
    # → nach Bestätigung werden wattpilot_daily-Einträge geschrieben
"""

import os
import sys
import json
import sqlite3
import datetime
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# ── Pfade ──────────────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH   = os.path.join(REPO_ROOT, 'data.db')

# ── Parameter ─────────────────────────────────────────────────────────────
START_DATE        = datetime.date(2026, 5, 22)
END_DATE          = datetime.date(2026, 5, 28)   # exklusiv
LOAD_THRESHOLD_W  = 5500   # W – Mindestlast für Wattpilot-Verdacht
MIN_DURATION_MIN  = 8      # Minuten – Mindestdauer eines Intervalls
GAP_TOLERANCE_MIN = 4      # Minuten – kurze Lücken unter Schwelle werden überbrückt
BASELINE_W        = 2000   # W – geschätzte Haushaltslast während Ladung
SERVER_PORT       = 8765


# ══════════════════════════════════════════════════════════════════════════════
#  Daten-Analyse
# ══════════════════════════════════════════════════════════════════════════════

def load_1min_data(date: datetime.date) -> list:
    """Lädt (ts, P_Direct, P_outBatt, P_Imp, P_WP_avg) für einen Tag."""
    ts0 = int(datetime.datetime.combine(date, datetime.time.min).timestamp())
    ts1 = ts0 + 86400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT ts, P_Direct, P_outBatt, P_Imp, P_WP_avg '
        'FROM data_1min WHERE ts >= ? AND ts < ? ORDER BY ts',
        (ts0, ts1)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def detect_intervals(rows: list) -> list:
    """
    Erkennt Ladeintervalle: Perioden mit Gesamt-Last > LOAD_THRESHOLD_W
    für mind. MIN_DURATION_MIN Minuten.

    Formel: load = P_Direct + P_outBatt + P_Imp
    (P_Direct = PV → Last direkt; P_outBatt = Batterie-Entladung; P_Imp = Netzbezug)

    Rückgabe: Liste von (iv_rows, row_idx_start) – row_idx_start ist der
    Index des ersten Intervall-Punktes in `rows` (für Baseline-Berechnung).
    """
    intervals  = []
    current    = []   # akkumulierte (ts, load)-Tupel des aktuellen Intervalls
    current_i0 = 0    # Index des ersten current-Punktes in rows
    gap_count  = 0

    for i, (ts, pd, pob, pi, pwp) in enumerate(rows):
        pd  = pd  or 0.0
        pob = pob or 0.0
        pi  = pi  or 0.0
        load = pd + pob + pi

        if load >= LOAD_THRESHOLD_W:
            if not current:
                current_i0 = i
            current.append((ts, load))
            gap_count = 0
        else:
            if current:
                gap_count += 1
                current.append((ts, load))   # Gap-Zeilen vorläufig mitführen
                if gap_count > GAP_TOLERANCE_MIN:
                    # Intervall beenden – Gap-Zeilen am Ende abschneiden
                    while current and current[-1][1] < LOAD_THRESHOLD_W:
                        current.pop()
                    if len(current) >= MIN_DURATION_MIN:
                        intervals.append((list(current), current_i0))
                    current   = []
                    gap_count = 0

    # Letztes Intervall schließen
    if current:
        while current and current[-1][1] < LOAD_THRESHOLD_W:
            current.pop()
        if len(current) >= MIN_DURATION_MIN:
            intervals.append((list(current), current_i0))

    return intervals


def _baseline_from_pre(all_rows: list, iv_start_idx: int,
                       look_back: int = 10) -> float:
    """
    Schätzt die normale Haushaltslast aus den `look_back` Minuten vor dem
    Intervall. Ausreißer > LOAD_THRESHOLD_W werden ignoriert (könnten ein
    vorangegangenes Ladeintervall sein).

    Fallback auf BASELINE_W wenn keine ausreichenden Vorminuten vorhanden.
    """
    pre_start = max(0, iv_start_idx - look_back)
    pre_rows  = all_rows[pre_start:iv_start_idx]
    loads = []
    for ts, pd, pob, pi, pwp in pre_rows:
        pd = pd or 0.0; pob = pob or 0.0; pi = pi or 0.0
        load = pd + pob + pi
        if load < LOAD_THRESHOLD_W:   # nur normale Lastpunkte
            loads.append(load)
    if len(loads) >= 3:
        return round(sum(loads) / len(loads))
    return BASELINE_W


def interval_stats(iv_rows: list, all_rows: list, iv_start_idx: int) -> dict:
    """
    Berechnet Kennzahlen eines Intervalls.

    Baseline wird aus den 10 Vorminuten des Tages bestimmt – nicht als
    fixer Schätzwert, sondern als gemessener Leerlauf-Durchschnitt.
    """
    baseline = _baseline_from_pre(all_rows, iv_start_idx)
    loads    = [r[1] for r in iv_rows]
    ts0      = iv_rows[0][0]
    ts1      = iv_rows[-1][0]
    dur      = len(iv_rows)                          # ~Minuten
    gross    = sum(loads) / 60.0                     # Wh
    net      = max(0.0, sum(max(0.0, l - baseline) for l in loads) / 60.0)
    return {
        'ts_start'    : int(ts0),
        'ts_end'      : int(ts1),
        'dt_start'    : datetime.datetime.fromtimestamp(ts0).strftime('%H:%M'),
        'dt_end'      : datetime.datetime.fromtimestamp(ts1).strftime('%H:%M'),
        'duration_min': dur,
        'max_w'       : round(max(loads)),
        'avg_w'       : round(sum(loads) / dur),
        'gross_wh'    : round(gross),
        'baseline_w'  : round(baseline),
        'net_wh'      : round(net),
    }


def load_existing_daily() -> dict:
    """Gibt vorhandene wattpilot_daily-Einträge für den Zeitraum zurück.
    { 'YYYY-MM-DD': energy_wh }"""
    ts0 = int(datetime.datetime(START_DATE.year, START_DATE.month, START_DATE.day).timestamp())
    ts1 = int(datetime.datetime(END_DATE.year,   END_DATE.month,   END_DATE.day).timestamp())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT ts, energy_wh FROM wattpilot_daily WHERE ts >= ? AND ts < ? ORDER BY ts',
        (ts0, ts1)
    )
    result = {}
    for ts, ewh in c.fetchall():
        result[datetime.date.fromtimestamp(ts).isoformat()] = round(ewh or 0)
    conn.close()
    return result


def load_daily_consumption() -> dict:
    """Gibt W_Consumption_total aus daily_data für den Zeitraum zurück.
    { 'YYYY-MM-DD': consumption_wh }"""
    ts0 = int(datetime.datetime(START_DATE.year, START_DATE.month, START_DATE.day).timestamp())
    ts1 = int(datetime.datetime(END_DATE.year,   END_DATE.month,   END_DATE.day).timestamp())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT ts, W_Consumption_total FROM daily_data WHERE ts >= ? AND ts < ? ORDER BY ts',
        (ts0, ts1)
    )
    result = {}
    for ts, wcons in c.fetchall():
        result[datetime.date.fromtimestamp(ts).isoformat()] = round(wcons or 0)
    conn.close()
    return result


def collect_candidates() -> list:
    """Führt die Analyse für alle Tage durch und gibt eine Liste von Kandidaten-Dicts zurück."""
    existing    = load_existing_daily()
    consumption = load_daily_consumption()
    candidates  = []
    idx = 0

    d = START_DATE
    while d < END_DATE:
        day_str = d.isoformat()
        rows    = load_1min_data(d)
        ivs     = detect_intervals(rows)

        for iv_rows, iv_start_idx in ivs:
            stats = interval_stats(iv_rows, rows, iv_start_idx)
            candidates.append({
                'id'          : idx,
                'day'         : day_str,
                'ts_start'    : stats['ts_start'],
                'ts_end'      : stats['ts_end'],
                'dt_start'    : stats['dt_start'],
                'dt_end'      : stats['dt_end'],
                'duration_min': stats['duration_min'],
                'max_w'       : stats['max_w'],
                'avg_w'       : stats['avg_w'],
                'gross_wh'    : stats['gross_wh'],
                'baseline_w'  : stats['baseline_w'],
                'net_wh'      : stats['net_wh'],
                'existing_wh' : existing.get(day_str, 0),
                'total_wh'    : consumption.get(day_str, 0),
            })
            idx += 1

        d += datetime.timedelta(days=1)

    return candidates


# ══════════════════════════════════════════════════════════════════════════════
#  DB-Schreibpfad
# ══════════════════════════════════════════════════════════════════════════════

def apply_confirmed(confirmed_energies: dict) -> list:
    """
    Schreibt/aktualisiert wattpilot_daily für bestätigte Tage.

    confirmed_energies: { 'YYYY-MM-DD': net_wh_total (kumuliert über Intervalle) }

    Wenn für einen Tag bereits ein Eintrag existiert (z. B. 22.5. mit 7193 Wh
    aus echtem eto), wird ADDIERT (nicht ersetzt), damit reale Messwerte
    erhalten bleiben. Ausnahme: Explizit im Dict auf 0 gesetzt → überspringen.

    Rückgabe: Liste von Log-Zeilen für die Bestätigungsseite.
    """
    existing = load_existing_daily()
    log      = []
    conn     = sqlite3.connect(DB_PATH)
    c        = conn.cursor()

    for day_str, new_wh in confirmed_energies.items():
        if new_wh <= 0:
            log.append(f'SKIP  {day_str}: 0 Wh – nichts zu speichern')
            continue

        day = datetime.date.fromisoformat(day_str)
        ts  = int(datetime.datetime.combine(day, datetime.time.min).timestamp())
        old_wh = existing.get(day_str, 0)

        if old_wh > 0:
            # Bereits vorhanden → ADDIEREN
            total_wh = old_wh + new_wh
            c.execute(
                'UPDATE wattpilot_daily SET energy_wh = ? WHERE ts = ?',
                (round(total_wh), ts)
            )
            log.append(
                f'ADD   {day_str}: {old_wh} Wh (vorh.) + {round(new_wh)} Wh '
                f'= {round(total_wh)} Wh → UPDATE'
            )
        else:
            # Neu anlegen
            c.execute(
                '''INSERT OR REPLACE INTO wattpilot_daily
                   (ts, energy_wh, max_power_w, charging_hours, sessions)
                   VALUES (?, ?, 0, ?, 1)''',
                (ts, round(new_wh), round(new_wh / 11000.0, 2))
            )
            log.append(f'NEW   {day_str}: {round(new_wh)} Wh → INSERT')

    conn.commit()
    conn.close()
    return log


# ══════════════════════════════════════════════════════════════════════════════
#  HTML-Generierung
# ══════════════════════════════════════════════════════════════════════════════

def build_html(candidates: list) -> str:
    """Erzeugt die HTML-Seite mit Intervall-Tabelle und Bestätigungs-Formular."""

    # Tagesgruppen für Kopfzeilen
    from collections import defaultdict
    day_groups = defaultdict(list)
    for c in candidates:
        day_groups[c['day']].append(c)

    rows_html = []
    for day_str in sorted(day_groups):
        grp       = day_groups[day_str]
        existing  = grp[0]['existing_wh']
        total_wh  = grp[0]['total_wh']
        day_label = datetime.date.fromisoformat(day_str).strftime('%a %d.%m.')

        badge = ''
        if existing > 0:
            badge = (f'<span class="badge bg-info ms-2" '
                     f'title="bereits in wattpilot_daily">'
                     f'{existing} Wh bereits vorhanden</span>')

        rows_html.append(
            f'<tr class="table-secondary"><th colspan="10">'
            f'{day_label}{badge}'
            f'<span class="text-muted ms-3" style="font-weight:normal;font-size:.85em">'
            f'Tagesverbrauch: {total_wh:,} Wh'
            f'</span></th></tr>'
        )

        for iv in grp:
            i        = iv['id']
            dur      = iv['duration_min']
            maxw     = iv['max_w']
            avgw     = iv['avg_w']
            gross    = iv['gross_wh']
            baseline = iv['baseline_w']
            net      = iv['net_wh']
            t0       = iv['dt_start']
            t1       = iv['dt_end']

            # Ampel-Farbe nach Wattpilot-Wahrscheinlichkeit
            if avgw >= 9000:
                row_cls = 'table-success'
            elif avgw >= 6500:
                row_cls = 'table-warning'
            else:
                row_cls = ''

            rows_html.append(f'''
<tr class="{row_cls}" data-id="{i}" data-gross="{gross}">
  <td class="text-center">
    <input class="form-check-input cb-confirm" type="checkbox"
           name="confirmed" value="{i}"
           id="cb{i}">
  </td>
  <td>{t0}–{t1}</td>
  <td>{dur} min</td>
  <td>{maxw:,} W</td>
  <td>{avgw:,} W</td>
  <td class="text-end">{gross:,} Wh</td>
  <td>
    <div class="input-group input-group-sm" style="width:150px">
      <input type="number" class="form-control baseline-input"
             id="bl{i}" value="{baseline}"
             min="0" max="{maxw}" step="50"
             title="Geschätzte normale Haushaltslast vor dem Intervall (aus Vorminuten)"
             data-id="{i}" data-gross="{gross}" data-dur="{dur}">
      <span class="input-group-text" style="font-size:.75rem">W</span>
    </div>
    <div class="text-muted" style="font-size:.75rem">Baseline (Messung)</div>
  </td>
  <td>
    <div class="input-group input-group-sm" style="width:130px">
      <input type="number" class="form-control net-input"
             id="net{i}" name="energy_{i}" value="{net}"
             min="0" max="{gross}" step="1"
             title="Netto-Energie = Brutto minus Haushalt-Baseline (editierbar)">
      <span class="input-group-text" style="font-size:.75rem">Wh</span>
    </div>
    <div class="text-muted" style="font-size:.75rem">→ wird gespeichert</div>
  </td>
  <td>
    <label class="form-check-label text-muted" for="cb{i}">
      &#x2714; Wattpilot
    </label>
  </td>
</tr>''')

    rows_str = '\n'.join(rows_html)
    count    = len(candidates)

    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wattpilot-Rekonstruktion 22.–27.5.2026</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        crossorigin="anonymous">
  <style>
    body {{ padding: 2rem; }}
    h1   {{ font-size: 1.5rem; margin-bottom: .25rem; }}
    .legend {{ font-size: .85rem; }}
  </style>
</head>
<body>
<div class="container-fluid">

<h1>Wattpilot-Rekonstruktion 22.–27.5.2026</h1>
<p class="text-muted mb-3">
  {count} Kandidaten-Intervalle aus <code>data_1min</code> (Last&nbsp;&gt;&nbsp;{LOAD_THRESHOLD_W:,}&nbsp;W
  für&nbsp;&ge;&nbsp;{MIN_DURATION_MIN}&nbsp;min).
  Lücken&nbsp;&le;&nbsp;{GAP_TOLERANCE_MIN}&nbsp;min werden überbrückt.
</p>

<div class="mb-3 legend">
  <span class="badge bg-success me-1">&nbsp;</span> Ø&nbsp;&ge;&nbsp;9&nbsp;kW — sehr wahrscheinlich Wattpilot (3-phasig)&emsp;
  <span class="badge bg-warning me-1">&nbsp;</span> Ø&nbsp;&ge;&nbsp;6,5&nbsp;kW — möglicherweise Wattpilot&emsp;
  <span class="badge bg-light border me-1">&nbsp;</span> unter 6,5&nbsp;kW — unklar
</div>

<form method="POST" action="/confirm" id="mainForm">
<table class="table table-sm table-bordered table-hover align-middle">
  <thead class="table-dark">
    <tr>
      <th style="width:40px">&#x2714;</th>
      <th>Uhrzeit</th>
      <th>Dauer</th>
      <th>Max</th>
      <th>Ø&nbsp;Last</th>
      <th class="text-end">Brutto-Wh</th>
      <th title="Aus Ø-Last der 10 Vorminuten berechnet – editierbar">Baseline&nbsp;W</th>
      <th title="Brutto minus Baseline × Dauer – wird gespeichert; editierbar">Netto-Wh&nbsp;✏</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {rows_str}
  </tbody>
</table>

<div class="d-flex align-items-center gap-3 mt-3">
  <button type="submit" class="btn btn-primary btn-lg">
    &#x2705; Bestätigte Intervalle speichern (wattpilot_daily)
  </button>
  <span class="text-muted">
    Werte werden in <code>wattpilot_daily</code> geschrieben und damit aus
    <em>Verbraucher / Sonstige</em> in <em>Verbraucher / Wattpilot</em> umgebucht.
  </span>
</div>

</form>
</div>

<script>
// Beim Abhaken: Netto-Input en/deaktivieren
document.querySelectorAll('.cb-confirm').forEach(cb => {{
  const id     = cb.value;
  const netIn  = document.getElementById(`net${{id}}`);
  const blIn   = document.getElementById(`bl${{id}}`);
  if (!netIn) return;
  const sync = () => {{
    netIn.disabled = !cb.checked;
    if (blIn) blIn.disabled = !cb.checked;
  }};
  sync();
  cb.addEventListener('change', sync);
}});

// Baseline-Änderung → Netto neu berechnen
document.querySelectorAll('.baseline-input').forEach(blIn => {{
  blIn.addEventListener('input', () => {{
    const id      = blIn.dataset.id;
    const gross   = parseFloat(blIn.dataset.gross);
    const dur     = parseFloat(blIn.dataset.dur);  // Minuten
    const baseline= parseFloat(blIn.value) || 0;
    const netIn   = document.getElementById(`net${{id}}`);
    if (!netIn) return;
    // Netto-Energie = Brutto − Baseline × Dauer / 60
    // Vereinfachung: gleichmäßige Baseline über die gesamte Intervalldauer
    const net = Math.max(0, Math.round(gross - baseline * dur / 60));
    netIn.value = net;
  }});
}});
</script>
</body>
</html>'''


def build_confirm_html(log_lines: list) -> str:
    lines_html = ''.join(f'<li class="list-group-item font-monospace">{l}</li>' for l in log_lines)
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Rekonstruktion abgeschlossen</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        crossorigin="anonymous">
  <style>body {{padding:2rem;}}</style>
</head>
<body>
<div class="container">
  <h1 class="mb-3">&#x2705; wattpilot_daily aktualisiert</h1>
  <ul class="list-group mb-4">{lines_html}</ul>
  <p class="text-muted">
    Die Verbraucher-Ansicht (<code>/api/verbraucher</code>) zeigt nun die
    neuen Werte. Server stoppt in 3&nbsp;Sekunden.
  </p>
</div>
<script>setTimeout(() => window.close(), 3000);</script>
</body>
</html>'''


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP-Server
# ══════════════════════════════════════════════════════════════════════════════

_candidates_cache: list = []
_shutdown_event          = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass   # Kein Noise im Terminal

    def _send(self, html: str, code: int = 200):
        enc = html.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(enc))
        self.end_headers()
        self.wfile.write(enc)

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._send(build_html(_candidates_cache))
        else:
            self._send('<h1>404</h1>', 404)

    def do_POST(self):
        if self.path != '/confirm':
            self._send('<h1>405</h1>', 405)
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length).decode('utf-8')
        params = parse_qs(body)

        # Bestätigte Intervall-IDs
        confirmed_ids = set(params.get('confirmed', []))

        # Energie pro bestätigtem Intervall → pro Tag summieren
        day_totals: dict = {}
        for iv in _candidates_cache:
            id_str = str(iv['id'])
            if id_str not in confirmed_ids:
                continue
            key      = f'energy_{id_str}'
            try:
                wh = float(params.get(key, [str(iv['net_wh'])])[0])
            except (ValueError, IndexError):
                wh = iv['net_wh']
            day_totals[iv['day']] = day_totals.get(iv['day'], 0.0) + wh

        log = apply_confirmed(day_totals)

        for line in log:
            print(f'  {line}')

        self._send(build_confirm_html(log))
        threading.Thread(target=_delayed_shutdown, daemon=True).start()

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def _delayed_shutdown():
    import time
    time.sleep(3)
    _shutdown_event.set()


# ══════════════════════════════════════════════════════════════════════════════
#  Einstiegspunkt
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global _candidates_cache

    print('Analysiere data_1min für 22.–27.5.2026 …')
    _candidates_cache = collect_candidates()
    print(f'  {len(_candidates_cache)} Kandidaten-Intervalle gefunden.')

    if not _candidates_cache:
        print('Keine Intervalle über Schwelle gefunden. Fertig.')
        return

    # Bestehende Tageseinträge anzeigen
    existing = load_existing_daily()
    if existing:
        print('  Vorhandene wattpilot_daily-Einträge:')
        for d, wh in sorted(existing.items()):
            print(f'    {d}: {wh} Wh')

    url = f'http://127.0.0.1:{SERVER_PORT}/'
    print(f'\nStarte Server auf {url}')
    print('Öffne Browser … (Strg+C zum Abbrechen)\n')

    server = HTTPServer(('127.0.0.1', SERVER_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    webbrowser.open(url)

    _shutdown_event.wait()   # Wartet bis POST /confirm verarbeitet wurde
    server.shutdown()
    print('\nFertig. Server gestoppt.')


if __name__ == '__main__':
    main()
