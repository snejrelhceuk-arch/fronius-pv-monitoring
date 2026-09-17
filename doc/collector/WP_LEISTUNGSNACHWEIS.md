# WP-Leistungsnachweis (Netzbetreiber)

Rechtlich relevanter Langzeit-Nachweis, dass die Wärmepumpe (WP, Dimplex) das
mit dem Netzbetreiber vereinbarte Leistungslimit von **4,2 kW** einhält.
Zusätzlich wird der **Netzbezug** im Moment des WP-Maximums geführt: Er belegt,
dass die seltenen Grenzwert-Überschreitungen in der **Eigenversorgung**
(PV/Batterie) liegen und dem Ziel dienen, den **Eigenverbrauch zu erhöhen** —
nicht durch zusätzlichen Netzbezug entstehen.

## Datenfluss

```
collector/poller.py  →  collector/wp_power_protocol.py  →  logs/wp_netzbetreiber_leistung.csv
   (Rolle A, 3-s-Poll)      (Minuten-Aggregation)              (append-only, endlos)
                                                                     │  read-only (Rolle B)
                                                                     ▼
                                        routes/verbraucher.py:api_verbraucher_wp_leistung
                                                                     ▼
                                        templates/wp_leistung_view.html  (Chart + Tooltip)
```

- **Erfassung:** Der Collector bildet je Minute das WP-Leistungsmaximum
  (`sec_sm_WP`, Betrag). Beim Setzen eines neuen Minuten-Maximums wird die
  gleichzeitige Netzleistung (`prim_sm`) als Netzbezug festgehalten.
- **Persistenz:** `logs/wp_netzbetreiber_leistung.csv` wird bewusst
  **append-only** und **ohne Rotation** geführt (Langzeit-Nachweis, kein Alarm —
  siehe `doc/diagnos/DIAGNOS.md`). Die Datei ist gitignored.
- **Anzeige:** Read-only aus der CSV (Fallback: `data_1min`/`data_15min`),
  erreichbar unter `/verbraucher/wp-leistung` (Alias
  `/analyse/verbraucher/wp-leistung`, Navigation „P-Max WP“).

## CSV-Schema `logs/wp_netzbetreiber_leistung.csv`

| Spalte | Einheit | Bedeutung |
|---|---|---|
| `ts_epoch` | s | Minuten-Bucket (Unix, auf 60 s abgerundet) |
| `ts_local` | — | Lokale Zeit `YYYY-MM-DD HH:MM:SS` |
| `wp_max_w` | W | WP-Leistungsmaximum der Minute (Betrag) |
| `limit_w` | W | Vereinbartes Limit (4200) |
| `within_limit` | 0/1 | 1 = eingehalten, 0 = Überschreitung |
| `samples` | — | Anzahl Messwerte in der Minute |
| `grid_draw_w` | W | **Netzbezug** (`P_Netz` ≥ 0) im Moment des WP-Maximums; leer = unbekannt |

`grid_draw_w` steht am Zeilenende, damit ältere 6-Spalten-Leser kompatibel
bleiben. Ein **leeres Feld** bedeutet „kein Datenbank-Bezug rekonstruierbar“
(nicht „0 W“).

## Netzbezug-Semantik

- `P_Netz`: positiv = Netzbezug, negativ = Einspeisung. Gespeichert wird
  `grid_draw_w = max(0, P_Netz)`. Einspeisung/Ausgeglichenheit ⇒ `0`.
- **Live:** momentaner Wert am WP-Peak (3-s-Auflösung, präzise).
- **Rückwärts rekonstruiert:** Minutenmittel `data_1min.P_Netz_avg` (≥ 0). Es ist
  der faire Repräsentant für die Minute, in der die WP ihr Maximum hatte.

Ein niedriger Netzbezug (Richtwert < 200 W) bei einer Überschreitung belegt die
Eigenversorgung: die WP-Spitze wurde aus PV/Batterie gedeckt.

## Rückwärts-Rekonstruktion

`collector/wp_power_protocol.py:migrate_wp_protocol_add_grid_draw` ergänzt die
Spalte einmalig und idempotent:

- Läuft beim Collector-Start **vor** dem Backfill; überspringt, sobald der
  Header `grid_draw_w` enthält.
- Baut aus `data_1min.P_Netz_avg` eine `ts → Netzbezug`-Map und schreibt die
  Datei **atomar** neu (Temp-Datei + `os.replace`).
- Rekonstruktions-Horizont = Abdeckung von `data_1min`. Ältere Minuten ohne
  DB-Deckung erhalten ein leeres Feld.

Laufende Neuzeilen führen den Netzbezug live mit; `backfill_wp_protocol_from_db`
schließt Lücken nach Neustarts inklusive `grid_draw_w`.

## Web-Ansicht & Tooltip

- Linie „WP-Leistung“, Grenzwert-Markierung bei 4200 W, Streupunkte für
  Überschreitungen.
- **Tooltip:** zeigt zusätzlich den Netzbezug. Bei einer Überschreitung wird der
  Bezug bewertet: `< 200 W` → „Eigenversorgung“, `< 50 %` der WP-Leistung →
  „überw. Eigenversorgung“, sonst „Netzanteil“.
- **Info-Chip** „Netzbezug bei Überschr.“: max/Ø-Netzbezug über alle sichtbaren
  Überschreitungen; markiert Eigenversorgung, wenn der maximale Bezug niedrig ist.

## Invarianten / Rollen

- Rolle A schreibt nur die CSV; Rolle B (Web) liest ausschließlich (kein
  Hardware-Schreibzugriff).
- Datei ist endlos/append-only; keine Trunkierung, keine Historie-Sektion.
- Konvention nicht verwechseln: **WP = Wärmepumpe**, nicht Wattpilot.
