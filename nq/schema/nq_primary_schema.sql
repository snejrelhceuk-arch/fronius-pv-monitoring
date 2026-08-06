-- nq_primary_schema.sql — NQ-Aggregat-/Analyse-DB auf Primary (SD, sparsam)
-- Rolle N. Ziel: Übernahme der 5-min-Skalaraggregate + Event-RAW von Tech,
-- Aggregationskaskade analog Produktion (5 min → hourly → daily),
-- Event-RAW dauerhaft in Originalauflösung.
--
-- Monatsdatei: nq/db/nq_YYYY-MM.db (wie Legacy nq/legacy/db-Muster).

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ---------------------------------------------------------------------------
-- Harmonik-RAW (1-s-Auflösung) — von Tech übernommen, Basis für _run_harm_5min.
-- Schema identisch zu nq_raw_slow auf Tech. Nur kurz gehalten (SD-Schonung,
-- primary_rawslow_hours); nach der 5-min-Aggregation nicht mehr benötigt.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_raw_slow (
    ts     INTEGER NOT NULL,
    meas   TEXT    NOT NULL,   -- 'U_LN' | 'U_LL' | 'I'
    phase  INTEGER NOT NULL,   -- 1..3
    ord    INTEGER NOT NULL,   -- 1 (Grundschw.) oder 3,5,...,31
    value  REAL,
    event  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ts, meas, phase, ord)
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

-- Monats-Fixpunkte (NQ2 WP2): Delta 1.→1. (00:00–00:00 localtime). Quelle für
-- die Tooltip-Spiegelung in der Jahres-Ansicht. Aus den day_start-Checkpoints
-- des Monatsanfangs/-endes gebildet (Differenzmethode, wie nq_energy_daily).
CREATE TABLE IF NOT EXISTS nq_energy_monthly (
    month           TEXT PRIMARY KEY,   -- YYYY-MM (localtime)
    wh_imp_start    REAL, wh_imp_end    REAL, wh_imp_delta    REAL,
    wh_exp_start    REAL, wh_exp_end    REAL, wh_exp_delta    REAL,
    varh_imp_start  REAL, varh_imp_end  REAL, varh_imp_delta  REAL,
    varh_exp_start  REAL, varh_exp_end  REAL, varh_exp_delta  REAL,
    vah_start       REAL, vah_end       REAL, vah_delta       REAL,
    src             TEXT,               -- 'counter' | 'reset_fallback' | 'partial'
    n_samples       INTEGER,
    created_ts      INTEGER NOT NULL
);

-- Jahres-Fixpunkte (NQ2 WP2): Delta 1.1.→1.1. Quelle für Tooltip in Gesamt-Ansicht.
CREATE TABLE IF NOT EXISTS nq_energy_yearly (
    year            TEXT PRIMARY KEY,   -- YYYY (localtime)
    wh_imp_start    REAL, wh_imp_end    REAL, wh_imp_delta    REAL,
    wh_exp_start    REAL, wh_exp_end    REAL, wh_exp_delta    REAL,
    varh_imp_start  REAL, varh_imp_end  REAL, varh_imp_delta  REAL,
    varh_exp_start  REAL, varh_exp_end  REAL, varh_exp_delta  REAL,
    vah_start       REAL, vah_end       REAL, vah_delta       REAL,
    src             TEXT,
    n_samples       INTEGER,
    created_ts      INTEGER NOT NULL
);

-- Transienten je 5-min-Fenster + Phase (NQ2 WP2). Auf Tech aus nq_raw_fast
-- berechnet, hierher transferiert. count_pos/neg = Anzahl schneller Sprünge;
-- slew_avg/max = mittlere/maximale Anstiegsgeschwindigkeit (V/s bzw. A/s).
CREATE TABLE IF NOT EXISTS nq_transient_5min (
    ts          INTEGER NOT NULL,   -- Fenster-Start (5-min-Raster)
    phase       INTEGER NOT NULL,   -- 1..3
    trans_u_pos INTEGER, trans_u_neg INTEGER,
    slew_u_avg  REAL,    slew_u_max  REAL,
    trans_i_pos INTEGER, trans_i_neg INTEGER,
    slew_i_avg  REAL,    slew_i_max  REAL,
    n           INTEGER NOT NULL,
    PRIMARY KEY (ts, phase)
) WITHOUT ROWID;

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
-- Musteranalyse-Datensatz (NQ2/WP6): permanenter "sauberer" Netz-Signaldatensatz.
-- Grid-seitige Spannung = gemessene PCC-Spannung + interner IR-Abfall zurueck-
-- addiert (dU_int = I*(R*cos_phi + X*sin_phi), Z aus config/nq_impedance.json).
-- Damit sind hinter dem Netzanschlusspunkt liegende (interne) Lasteffekte
-- entfernt; uebrig bleibt das netzseitige (externe) Signal fuer Aufschwing-/
-- Reflexions-/LF-Paket-Analyse. f ist systemweit (keine Korrektur). Quelle: nq_5min.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nq_pattern_5min (
    ts          INTEGER PRIMARY KEY,   -- 5-min-Bucket (wie nq_5min)
    u_clean_l1  REAL, u_clean_l2 REAL, u_clean_l3 REAL,   -- netzseitige U_LN [V] (intern bereinigt)
    u_meas_l1   REAL, u_meas_l2  REAL, u_meas_l3  REAL,   -- Referenz: gemessene PCC-U_LN [V]
    freq        REAL,                                     -- Netzfrequenz [Hz] (systemweit)
    pf_l1       REAL, pf_l2 REAL, pf_l3 REAL,             -- Leistungsfaktor (signiert, cos_phi)
    phi_l1      REAL, phi_l2 REAL, phi_l3 REAL,           -- Phasenwinkel phi [grad]
    i_l1        REAL, i_l2 REAL, i_l3 REAL,               -- Referenz: signierter Strom [A]
    du_int_max  REAL,                                     -- max |dU_int| ueber die Phasen [V]
    origin      TEXT,                                     -- 'extern' | 'intern' (Bucket-Dominanz)
    n_samples   INTEGER,
    src         TEXT,                                     -- 'pac_residual'
    created_ts  INTEGER NOT NULL
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
