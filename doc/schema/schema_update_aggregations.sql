-- Schema-Erweiterung für detaillierte Energie-Aggregation
-- Datum: 2026-01-04

-- ========================================
-- DAILY_DATA erweitern
-- ========================================
ALTER TABLE daily_data ADD COLUMN W_Batt_Charge_total REAL DEFAULT 0;
ALTER TABLE daily_data ADD COLUMN W_Batt_Discharge_total REAL DEFAULT 0;
ALTER TABLE daily_data ADD COLUMN W_PV_Direct_total REAL DEFAULT 0;

-- ========================================
-- HOURLY_DATA erweitern
-- ========================================
ALTER TABLE hourly_data ADD COLUMN W_Batt_Charge_total REAL DEFAULT 0;
ALTER TABLE hourly_data ADD COLUMN W_Batt_Discharge_total REAL DEFAULT 0;
ALTER TABLE hourly_data ADD COLUMN W_PV_Direct_total REAL DEFAULT 0;

-- ========================================
-- DATA_WEEKLY erweitern
-- ========================================
ALTER TABLE data_weekly ADD COLUMN W_Batt_Charge_total REAL DEFAULT 0;
ALTER TABLE data_weekly ADD COLUMN W_Batt_Discharge_total REAL DEFAULT 0;
ALTER TABLE data_weekly ADD COLUMN W_PV_Direct_total REAL DEFAULT 0;

-- ========================================
-- DATA_MONTHLY erweitern
-- ========================================
ALTER TABLE data_monthly ADD COLUMN W_Batt_Charge_total REAL DEFAULT 0;
ALTER TABLE data_monthly ADD COLUMN W_Batt_Discharge_total REAL DEFAULT 0;
ALTER TABLE data_monthly ADD COLUMN W_PV_Direct_total REAL DEFAULT 0;

-- ========================================
-- DATA_YEARLY erweitern
-- ========================================
ALTER TABLE data_yearly ADD COLUMN W_Batt_Charge_total REAL DEFAULT 0;
ALTER TABLE data_yearly ADD COLUMN W_Batt_Discharge_total REAL DEFAULT 0;
ALTER TABLE data_yearly ADD COLUMN W_PV_Direct_total REAL DEFAULT 0;
