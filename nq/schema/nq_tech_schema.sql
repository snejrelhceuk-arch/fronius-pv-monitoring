-- nq_tech_schema.sql — NQ-Collector-DB auf Tech (tmpfs, RAM-first)
-- Rolle N. Ziel: RAW-Blöcke (fast/medium/slow) + 3–10 s-Aggregat im
-- /dev/shm-tmpfs, 12 h Ring-Buffer (retention.raw_hours), Kappung gegen
-- tmpfs-Überlauf. NQ2-Tier: fast=200ms Skalare, medium=1s Harmonik+Freq,
-- slow=Energiezähler (energy_s). RAW wird 4-stündlich nach Primary exportiert.
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
    p_l1    REAL, p_l2  REAL, p_l3  REAL,   -- Phase-Wirkleistung
    p_tot   REAL, q_tot REAL, s_tot REAL,   -- Wirk/Blind/Scheinleistung (gesamt)
    pf_l1   REAL, pf_l2 REAL, pf_l3 REAL,   -- Phase-Leistungsfaktor
    pf      REAL,                            -- Leistungsfaktor (gesamt)
    f       REAL,                            -- Netzfrequenz
    event   INTEGER NOT NULL DEFAULT 0       -- 1 = Ereignis-markiert (Transfer als RAW)
);
CREATE INDEX IF NOT EXISTS idx_nq_fast_event ON nq_raw_fast(event);

-- ---------------------------------------------------------------------------
-- Medium-Block: Block B komplett (FLOAT2_MAP Adr. 243..295), 200 ms
-- ts_ms PK (Millisekunden) analog nq_raw_fast — war ts (Sekunden, veraltet).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_medium (
    ts_ms       INTEGER PRIMARY KEY,   -- Unix epoch milliseconds
    cosphi_l1 REAL, cosphi_l2 REAL, cosphi_l3 REAL,
    ang_l1    REAL, ang_l2    REAL, ang_l3    REAL,
    thd_u_l1  REAL, thd_u_l2  REAL, thd_u_l3  REAL,
    thd_u_l12 REAL, thd_u_l23 REAL, thd_u_l31 REAL,  -- L-L THD (neu)
    thd_i_l1  REAL, thd_i_l2  REAL, thd_i_l3  REAL,
    idist_l1  REAL, idist_l2  REAL, idist_l3  REAL,
    i_n       REAL,
    unbal_u   REAL, unbal_i   REAL,               -- Unsymmetrie U/I (neu)
    f         REAL,                    -- Netzfrequenz (NQ2 Medium-Tier: real ~10s Refresh)
    event     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nq_medium_event ON nq_raw_medium(event);

-- ---------------------------------------------------------------------------
-- Slow-Block: Einzelharmonische 2..64 (U + I je Phase), Long-Format (~5 s)
-- 378 Werte/Snapshot = 63 Ordnungen × 2 Größen (U/I) × 3 Phasen.
-- Normalisiert statt 378 Spalten: kompakt, indizierbar, erweiterbar.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_slow (
    ts     INTEGER NOT NULL,
    meas   TEXT    NOT NULL,   -- 'U_LN' | 'U_LL' | 'I'
    phase  INTEGER NOT NULL,   -- 1..3 (U_LN: L1/L2/L3; U_LL: L12/L23/L31; I: L1/L2/L3)
    ord    INTEGER NOT NULL,   -- Ordnung 1 (Grundschw.) oder 3,5,...,31 (Oberschw.)
    value  REAL,               -- H1: Betrag V/A; H3..H31: % der Grundschwingung
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
-- Transienten je 5-min-Fenster + Phase (NQ2 WP2) — auf Tech aus nq_raw_fast
-- berechnet (nq/aggregate/nq_transients.py), dann nach Primary transferiert.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_transient_5min (
    ts          INTEGER NOT NULL,
    phase       INTEGER NOT NULL,
    trans_u_pos INTEGER, trans_u_neg INTEGER,
    slew_u_avg  REAL,    slew_u_max  REAL,
    trans_i_pos INTEGER, trans_i_neg INTEGER,
    slew_i_avg  REAL,    slew_i_max  REAL,
    n           INTEGER NOT NULL,
    PRIMARY KEY (ts, phase)
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
-- Grenzwert-Alarme (NQ2 WP1): Software-Auswertung der Skalare gegen 'grenzwerte'.
-- Der Poller (LimitMonitor) schreibt hier bei dauerhafter Überschreitung eine
-- Zeile; acked=1 wenn Mail versendet. Primary kann unquittierte Alarme lesen
-- und nachverschicken. Read-only ggü. Produktion bleibt gewahrt.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_limit_alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,      -- Alarm-Zeitpunkt (Unix seconds)
    limit_name TEXT    NOT NULL,      -- z. B. 'u_ln_max_l1','i_max_l2','freq_min','thd_u_l3'
    quantity   TEXT,                  -- gemessene Größe
    value      REAL,                  -- Messwert bei Auslösung
    threshold  REAL,                  -- verletzte Grenze
    pct        REAL,                  -- Ausschöpfung in % der Spanne
    mailed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nq_limit_alerts_ts ON nq_limit_alerts(ts);

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
