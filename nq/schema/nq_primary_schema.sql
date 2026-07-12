-- nq_primary_schema.sql — NQ-Aggregat-/Analyse-DB auf Primary (SD, sparsam)
-- Rolle N. Ziel: Übernahme der 3–10 s-Aggregate + Event-RAW von Tech,
-- Aggregationskaskade analog Produktion (3–10 s → 5 min → hourly → daily),
-- Event-RAW dauerhaft in Originalauflösung.
--
-- Monatsdatei: nq/db/nq_YYYY-MM.db (wie Legacy netzqualitaet/db-Muster).

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ---------------------------------------------------------------------------
-- Übernommenes 3–10 s-Aggregat (Retention 72 h auf Primary; Basis der Kaskade)
-- Schema identisch zu nq_agg_10s auf Tech.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_agg_10s (
    ts        INTEGER NOT NULL,
    quantity  TEXT    NOT NULL,
    meas      TEXT,
    phase     INTEGER,
    ord       INTEGER,
    vmin REAL, vavg REAL, vmax REAL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (ts, quantity, meas, phase, ord)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- 5-min-Aggregat (Retention ~90 d)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_5min (
    ts        INTEGER NOT NULL,   -- Bucket-Start (5-min-Raster)
    quantity  TEXT    NOT NULL,
    meas      TEXT,
    phase     INTEGER,
    ord       INTEGER,
    vmin REAL, vavg REAL, vmax REAL, vstd REAL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (ts, quantity, meas, phase, ord)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Stunden-Aggregat (Retention ~365 d)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_hourly (
    ts        INTEGER NOT NULL,
    quantity  TEXT    NOT NULL,
    meas      TEXT,
    phase     INTEGER,
    ord       INTEGER,
    vmin REAL, vavg REAL, vmax REAL, vstd REAL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (ts, quantity, meas, phase, ord)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Tages-Aggregat (Retention ~10 a)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_daily (
    day       TEXT    NOT NULL,   -- YYYY-MM-DD (localtime)
    quantity  TEXT    NOT NULL,
    meas      TEXT,
    phase     INTEGER,
    ord       INTEGER,
    vmin REAL, vavg REAL, vmax REAL, vstd REAL,
    n         INTEGER NOT NULL,
    PRIMARY KEY (day, quantity, meas, phase, ord)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Event-RAW (Originalauflösung, dauerhaft) — für Transienten-Rekonstruktion.
-- Spiegelt die Tech-RAW-Blöcke; nur Event-markierte Segmente werden übernommen.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_event_fast (
    ts_ms   INTEGER PRIMARY KEY,
    event_id INTEGER,
    u_l1 REAL, u_l2 REAL, u_l3 REAL,
    u_l12 REAL, u_l23 REAL, u_l31 REAL,
    i_l1 REAL, i_l2 REAL, i_l3 REAL,
    p_tot REAL, q_tot REAL, s_tot REAL,
    pf REAL, f REAL
);
CREATE INDEX IF NOT EXISTS idx_nq_ev_fast_eid ON nq_event_fast(event_id);

CREATE TABLE IF NOT EXISTS nq_event_medium (
    ts       INTEGER PRIMARY KEY,
    event_id INTEGER,
    thd_u_l1 REAL, thd_u_l2 REAL, thd_u_l3 REAL,
    thd_i_l1 REAL, thd_i_l2 REAL, thd_i_l3 REAL,
    unbalance_u REAL, unbalance_i REAL
);
CREATE INDEX IF NOT EXISTS idx_nq_ev_med_eid ON nq_event_medium(event_id);

CREATE TABLE IF NOT EXISTS nq_event_slow (
    ts     INTEGER NOT NULL,
    event_id INTEGER,
    meas   TEXT    NOT NULL,
    phase  INTEGER NOT NULL,
    ord    INTEGER NOT NULL,
    value  REAL,
    PRIMARY KEY (ts, meas, phase, ord)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_nq_ev_slow_eid ON nq_event_slow(event_id);

-- ---------------------------------------------------------------------------
-- Ereignis-Katalog (klassifizierte Netzereignisse)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start   INTEGER NOT NULL,
    ts_end     INTEGER NOT NULL,
    duration_s REAL,                -- <= 60 s (Snippet-Kappung)
    band       TEXT    NOT NULL,   -- 'HF_local' | 'NF_global' | 'VLF'
    kind       TEXT,               -- z. B. 'thd_spike','freq_nadir','dfd','changepoint'
    trigger    TEXT,               -- auslösende Größe/Schwelle ('du_step','df_step','thd_u',...)
    severity   REAL,
    peak_quantity TEXT,            -- Größe des Extremwerts (Auffindbarkeit im Aggregat)
    peak_value REAL,               -- Extremwert (Min/Max) des Snippets
    origin     TEXT,               -- 'lokal' | 'unklar' | 'netzseitig'
    dedup_key  TEXT,               -- Wiederholungsfilter (gleicher Trigger im Cooldown)
    n_samples  INTEGER,
    has_snippet INTEGER NOT NULL DEFAULT 0,  -- 1 = RAW-Serie in nq_event_* gespeichert
    metrics    TEXT,               -- JSON mit Kennzahlen
    created_ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nq_events_time ON nq_events(ts_start);
CREATE INDEX IF NOT EXISTS idx_nq_events_band ON nq_events(band);
CREATE INDEX IF NOT EXISTS idx_nq_events_dedup ON nq_events(dedup_key, ts_start);

-- ===========================================================================
-- ENERGIE / DIFFERENZMETHODE (Zählervergleich PAC4200 ↔ Master-SM ↔ iMS)
-- ===========================================================================

-- Tages-Energie per Differenzmethode: Zählerstand Tagesanfang/-ende + Delta je
-- Zähler, plus Reset-Erkennung (Muster wie Produktion: _counter_or_fallback).
-- delta = end - start; bei Zähler-Reset (negativ / Sprung) -> Fallback-Flag.
CREATE TABLE IF NOT EXISTS nq_energy_daily (
    day             TEXT PRIMARY KEY,   -- YYYY-MM-DD (localtime)
    wh_imp_start    REAL, wh_imp_end    REAL, wh_imp_delta    REAL,
    wh_exp_start    REAL, wh_exp_end    REAL, wh_exp_delta    REAL,
    varh_imp_start  REAL, varh_imp_end  REAL, varh_imp_delta  REAL,
    varh_exp_start  REAL, varh_exp_end  REAL, varh_exp_delta  REAL,
    vah_start       REAL, vah_end       REAL, vah_delta       REAL,
    src             TEXT,               -- 'counter' | 'reset_fallback' | 'partial'
    n_samples       INTEGER,
    created_ts      INTEGER NOT NULL
);

-- Day-Start-Fixpunkte (kumulative Zählerstände) für Langfrist-Abgleich.
-- Analog energy_checkpoints der Produktions-DB.
CREATE TABLE IF NOT EXISTS nq_energy_checkpoint (
    ts        INTEGER PRIMARY KEY,   -- exakter day_start-Zeitstempel (localtime)
    day       TEXT    NOT NULL,
    wh_imp REAL, wh_exp REAL, varh_imp REAL, varh_exp REAL, vah REAL
);

-- iMS-Ablesungen des Netzbetreibers (kumulative Zählerstände, manuell/Portal).
-- Basis für den Vergleich gegen PAC4200 + Master-SM.
CREATE TABLE IF NOT EXISTS nq_ims_reading (
    ts        INTEGER PRIMARY KEY,   -- Ablese-Zeitpunkt
    day       TEXT    NOT NULL,
    imp_kwh   REAL,                  -- Bezug (Zählerstand kumulativ)
    exp_kwh   REAL,                  -- Lieferung (Zählerstand kumulativ)
    source    TEXT,                  -- 'manual' | 'portal' | 'foto'
    note      TEXT
);

-- Tages-Vergleich PAC4200 vs Master-SM (Fronius Primär-SM, read-only aus
-- Produktions-DB) vs iMS (Netzbetreiber). Abweichungen sichtbar machen.
CREATE TABLE IF NOT EXISTS nq_energy_compare (
    day           TEXT PRIMARY KEY,
    pac_imp_kwh   REAL, pac_exp_kwh   REAL,   -- aus nq_energy_daily
    msm_imp_kwh   REAL, msm_exp_kwh   REAL,   -- Fronius Primär-SM (W_Imp/Exp_Netz)
    ims_imp_kwh   REAL, ims_exp_kwh   REAL,   -- Netzbetreiber-iMS
    d_pac_msm_imp REAL, d_pac_msm_exp REAL,   -- PAC - MasterSM
    d_pac_ims_imp REAL, d_pac_ims_exp REAL,   -- PAC - iMS
    note          TEXT,
    created_ts    INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Ingest-Log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_ingest_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    date_covered TEXT    NOT NULL,
    agg_rows     INTEGER NOT NULL,
    event_rows   INTEGER NOT NULL,
    duration_s   REAL
);
