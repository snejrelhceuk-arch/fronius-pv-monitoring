-- ====================================================================
-- SCHEMA-ERWEITERUNG: Absolute Energiezähler-Werte
-- ====================================================================
-- Datum: 07.02.2026
-- Zweck: Lückenlose Energiebilanzierung über beliebige Zeiträume
--
-- KONZEPT:
-- 1. Jede Aggregationstabelle speichert Start/End Absolutwerte
-- 2. Separate Checkpoint-Tabelle für feste Raster-Zeitpunkte
-- 3. Validierung: SUM(deltas) == (end - start)
-- ====================================================================

-- ====================================================================
-- 1. CHECKPOINT-TABELLE (feste Referenzpunkte)
-- ====================================================================
CREATE TABLE IF NOT EXISTS energy_checkpoints (
    ts INTEGER PRIMARY KEY,           -- Exakter Raster-Zeitpunkt (Unix Epoch)
    checkpoint_type TEXT NOT NULL,    -- 'year_start', 'month_start', 'week_start', 'day_start', 'hour_start'
    
    -- Absolute Zählerstände zum Zeitpunkt ts
    W_AC_Inv REAL,        -- Inverter AC Gesamtertrag
    W_DC1 REAL,           -- MPPT1 DC Ertrag
    W_DC2 REAL,           -- MPPT2 DC Ertrag
    W_Exp_Netz REAL,      -- Netzeinspeisung (TotWhExp, negativ)
    W_Imp_Netz REAL,      -- Netzbezug (TotWhImp, positiv)
    W_Exp_F2 REAL,        -- F2 Erzeugung (TotWhImp, negativ)
    W_Imp_F2 REAL,        -- F2 Bezug (TotWhImp, positiv)
    W_Exp_F3 REAL,        -- F3 Erzeugung (TotWhImp, negativ)
    W_Imp_F3 REAL,        -- F3 Bezug (TotWhImp, positiv)
    W_Imp_WP REAL,        -- Wärmepumpe Verbrauch
    
    -- Zusätzliche Info
    source TEXT,          -- 'measured' (direkter Wert) oder 'interpolated' (berechnet)
    created_at INTEGER    -- Timestamp der Checkpoint-Erstellung
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_type ON energy_checkpoints(checkpoint_type, ts);
CREATE INDEX IF NOT EXISTS idx_checkpoints_ts ON energy_checkpoints(ts DESC);

-- ====================================================================
-- 2. ERWEITERUNG: data_1min (14 Tage Retention)
-- ====================================================================
ALTER TABLE data_1min ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE data_1min ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE data_1min ADD COLUMN W_DC1_start REAL;
ALTER TABLE data_1min ADD COLUMN W_DC1_end REAL;
ALTER TABLE data_1min ADD COLUMN W_DC2_start REAL;
ALTER TABLE data_1min ADD COLUMN W_DC2_end REAL;
ALTER TABLE data_1min ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE data_1min ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE data_1min ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE data_1min ADD COLUMN W_Imp_Netz_end REAL;

-- ====================================================================
-- 3. ERWEITERUNG: data_15min (90 Tage Retention)
-- ====================================================================
ALTER TABLE data_15min ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE data_15min ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE data_15min ADD COLUMN W_DC1_start REAL;
ALTER TABLE data_15min ADD COLUMN W_DC1_end REAL;
ALTER TABLE data_15min ADD COLUMN W_DC2_start REAL;
ALTER TABLE data_15min ADD COLUMN W_DC2_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_Netz_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_F2_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_F2_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_F2_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_F2_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_F3_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Exp_F3_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_F3_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_F3_end REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_WP_start REAL;
ALTER TABLE data_15min ADD COLUMN W_Imp_WP_end REAL;

-- ====================================================================
-- 4. ERWEITERUNG: hourly_data (1 Jahr Retention)
-- ====================================================================
ALTER TABLE hourly_data ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE hourly_data ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE hourly_data ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE hourly_data ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE hourly_data ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE hourly_data ADD COLUMN W_Imp_Netz_end REAL;

-- ====================================================================
-- 5. ERWEITERUNG: daily_data (5 Jahre Retention)
-- ====================================================================
ALTER TABLE daily_data ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE daily_data ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE daily_data ADD COLUMN W_DC1_start REAL;
ALTER TABLE daily_data ADD COLUMN W_DC1_end REAL;
ALTER TABLE daily_data ADD COLUMN W_DC2_start REAL;
ALTER TABLE daily_data ADD COLUMN W_DC2_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_Netz_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_F2_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_F2_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_F2_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_F2_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_F3_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Exp_F3_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_F3_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_F3_end REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_WP_start REAL;
ALTER TABLE daily_data ADD COLUMN W_Imp_WP_end REAL;

-- ====================================================================
-- 6. ERWEITERUNG: data_weekly (10 Jahre Retention)
-- ====================================================================
ALTER TABLE data_weekly ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_DC1_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_DC1_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_DC2_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_DC2_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_Netz_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_F2_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_F2_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_F2_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_F2_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_F3_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Exp_F3_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_F3_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_F3_end REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_WP_start REAL;
ALTER TABLE data_weekly ADD COLUMN W_Imp_WP_end REAL;

-- ====================================================================
-- 7. ERWEITERUNG: data_monthly (unbegrenzt)
-- ====================================================================
ALTER TABLE data_monthly ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_DC1_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_DC1_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_DC2_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_DC2_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_Netz_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_F2_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_F2_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_F2_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_F2_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_F3_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Exp_F3_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_F3_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_F3_end REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_WP_start REAL;
ALTER TABLE data_monthly ADD COLUMN W_Imp_WP_end REAL;

-- ====================================================================
-- 8. ERWEITERUNG: data_yearly (unbegrenzt)
-- ====================================================================
ALTER TABLE data_yearly ADD COLUMN W_AC_Inv_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_AC_Inv_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_DC1_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_DC1_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_DC2_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_DC2_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_Netz_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_Netz_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_Netz_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_Netz_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_F2_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_F2_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_F2_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_F2_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_F3_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Exp_F3_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_F3_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_F3_end REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_WP_start REAL;
ALTER TABLE data_yearly ADD COLUMN W_Imp_WP_end REAL;

-- ====================================================================
-- ANWENDUNG:
-- sqlite3 data.db < db_schema_absolute_values.sql
-- ====================================================================
