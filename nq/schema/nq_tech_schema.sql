-- nq_tech_schema.sql — NQ-Collector-DB auf Tech (tmpfs, RAM-first)
-- Rolle N. Ziel: RAW-Blöcke (fast/medium/slow) + 3–10 s-Aggregat im
-- /dev/shm-tmpfs, 72 h Ring-Buffer, Kappung gegen tmpfs-Überlauf.
--
-- WICHTIG: Die konkreten Skalar-/Harmonik-Spalten folgen der VERIFIZIERTEN
-- Siemens-PAC4200-Registerliste (siehe doc/netzqualitaet/MESSTECHNIK.md).
-- Register/Spalten NICHT erfinden — im Feldtest (Phase 0) bestätigen.
--
-- Konventionen: ts = Unix-Sekunden (localtime-Grenzen wie Produktion),
-- ts_ms = Unix-Millisekunden für den Fast-Block (Sub-Sekunden-Kadenz).

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ---------------------------------------------------------------------------
-- Fast-Block: RMS-Spannung/Strom, Leistung, cos φ, Frequenz (~500 ms)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_fast (
    ts_ms   INTEGER PRIMARY KEY,   -- Unix epoch milliseconds
    u_l1    REAL, u_l2  REAL, u_l3  REAL,   -- Leiter-Neutral-Spannung (RMS)
    u_l12   REAL, u_l23 REAL, u_l31 REAL,   -- Leiter-Leiter-Spannung (RMS)
    i_l1    REAL, i_l2  REAL, i_l3  REAL,   -- Phasenstrom (RMS)
    p_tot   REAL, q_tot REAL, s_tot REAL,   -- Wirk/Blind/Scheinleistung
    pf      REAL,                            -- Leistungsfaktor
    f       REAL,                            -- Netzfrequenz
    event   INTEGER NOT NULL DEFAULT 0       -- 1 = Ereignis-markiert (Transfer als RAW)
);
CREATE INDEX IF NOT EXISTS idx_nq_fast_event ON nq_raw_fast(event);

-- ---------------------------------------------------------------------------
-- Medium-Block: THD + Unsymmetrie (~1 s)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_medium (
    ts          INTEGER PRIMARY KEY,   -- Unix epoch seconds
    thd_u_l1 REAL, thd_u_l2 REAL, thd_u_l3 REAL,
    thd_i_l1 REAL, thd_i_l2 REAL, thd_i_l3 REAL,
    unbalance_u REAL, unbalance_i REAL,
    event       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nq_medium_event ON nq_raw_medium(event);

-- ---------------------------------------------------------------------------
-- Slow-Block: Einzelharmonische 2..64 (U + I je Phase), Long-Format (~5 s)
-- 378 Werte/Snapshot = 63 Ordnungen × 2 Größen (U/I) × 3 Phasen.
-- Normalisiert statt 378 Spalten: kompakt, indizierbar, erweiterbar.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_slow (
    ts     INTEGER NOT NULL,   -- Unix epoch seconds
    meas   TEXT    NOT NULL,   -- 'U' | 'I'
    phase  INTEGER NOT NULL,   -- 1 | 2 | 3
    ord    INTEGER NOT NULL,   -- Harmonische Ordnung 2..64
    value  REAL,               -- Betrag (% der Grundschwingung)
    event  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ts, meas, phase, ord)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_nq_slow_event ON nq_raw_slow(event);

-- ---------------------------------------------------------------------------
-- 3–10 s-Aggregat (min/avg/max) — Transfer-Nutzlast nach Primary.
-- Long-Format: eine Zeile je (bucket, Größe[, phase, ord]).
-- quantity z. B. 'u_l1','i_l2','p_tot','pf','f','thd_u_l1','harm'.
-- Für Harmonische: quantity='harm', meas/phase/ord gefüllt.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_agg_10s (
    ts        INTEGER NOT NULL,   -- Bucket-Start (Unix seconds, 10 s-Raster)
    quantity  TEXT    NOT NULL,
    meas      TEXT,               -- 'U'|'I' nur für Harmonische, sonst NULL
    phase     INTEGER,            -- 1..3 oder NULL
    ord       INTEGER,            -- Harmonische Ordnung oder NULL
    vmin REAL, vavg REAL, vmax REAL,
    n         INTEGER NOT NULL,   -- Anzahl Samples im Bucket
    PRIMARY KEY (ts, quantity, meas, phase, ord)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Energie-Zählerstände (kumulativ) — Roh-Snapshots für die DIFFERENZMETHODE.
-- Langsamer Takt (Zähler ändern sich langsam). Alle vom PAC4200 gelieferten
-- Energiezähler (FLOAT64 @801..817). Diese Snapshots sind die Basis für die
-- Tages-Deltas (start/end/delta) auf Primary und den Vergleich Master-SM / iMS.
-- Von der Kappung NICHT gelöscht, solange der Tag noch nicht transferiert ist.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_energy_raw (
    ts        INTEGER PRIMARY KEY,   -- Unix epoch seconds
    wh_imp    REAL, wh_exp   REAL,   -- Wirkarbeit Bezug / Lieferung
    varh_imp  REAL, varh_exp REAL,   -- Blindarbeit Bezug / Lieferung
    vah       REAL                   -- Scheinarbeit
);

-- ---------------------------------------------------------------------------
-- Kappungs-Audit (echte Lücken sichtbar lassen)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_capping_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    trigger      TEXT    NOT NULL,   -- 'time' | 'size'
    table_name   TEXT    NOT NULL,
    rows_deleted INTEGER NOT NULL,
    tmpfs_mb     REAL
);

-- ---------------------------------------------------------------------------
-- Transfer-Log (At-least-once, Löschung erst nach Quittung)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_transfer_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    date_covered TEXT    NOT NULL,   -- YYYY-MM-DD
    agg_rows     INTEGER NOT NULL,
    event_rows   INTEGER NOT NULL,
    acked        INTEGER NOT NULL DEFAULT 0,
    duration_s   REAL
);
