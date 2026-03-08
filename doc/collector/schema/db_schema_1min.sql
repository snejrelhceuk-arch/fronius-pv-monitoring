-- ====================================================================
-- 1-MINUTEN AGGREGATION (14 Tage Retention)
-- ====================================================================
-- Zwischenstufe zwischen raw_data (3s) und data_15min (15min)
-- Für hochauflösende Tag-Visualisierung
-- ~1440 Einträge pro Tag, ~20.000 Einträge gesamt
-- ====================================================================

CREATE TABLE IF NOT EXISTS data_1min (
    ts REAL PRIMARY KEY,
    
    -- Alle technischen Werte mit Min/Max
    -- Inverter AC
    P_AC_Inv_avg REAL, P_AC_Inv_min REAL, P_AC_Inv_max REAL,
    I_L1_Inv_avg REAL, I_L1_Inv_min REAL, I_L1_Inv_max REAL,
    I_L2_Inv_avg REAL, I_L2_Inv_min REAL, I_L2_Inv_max REAL,
    I_L3_Inv_avg REAL, I_L3_Inv_min REAL, I_L3_Inv_max REAL,
    U_L1_N_Inv_avg REAL, U_L1_N_Inv_min REAL, U_L1_N_Inv_max REAL,
    U_L2_N_Inv_avg REAL, U_L2_N_Inv_min REAL, U_L2_N_Inv_max REAL,
    U_L3_N_Inv_avg REAL, U_L3_N_Inv_min REAL, U_L3_N_Inv_max REAL,
    
    -- Inverter DC
    P_DC_Inv_avg REAL, P_DC_Inv_min REAL, P_DC_Inv_max REAL,
    
    -- MPPT
    P_DC1_avg REAL, P_DC1_min REAL, P_DC1_max REAL,
    P_DC2_avg REAL, P_DC2_min REAL, P_DC2_max REAL,
    
    -- Batterie
    SOC_Batt_avg REAL, SOC_Batt_min REAL, SOC_Batt_max REAL,
    U_Batt_API_avg REAL, U_Batt_API_min REAL, U_Batt_API_max REAL,
    I_Batt_API_avg REAL, I_Batt_API_min REAL, I_Batt_API_max REAL,
    
    -- Netz
    P_Netz_avg REAL, P_Netz_min REAL, P_Netz_max REAL,
    f_Netz_avg REAL, f_Netz_min REAL, f_Netz_max REAL,
    U_L1_N_Netz_avg REAL, U_L1_N_Netz_min REAL, U_L1_N_Netz_max REAL,
    U_L2_N_Netz_avg REAL, U_L2_N_Netz_min REAL, U_L2_N_Netz_max REAL,
    U_L3_N_Netz_avg REAL, U_L3_N_Netz_min REAL, U_L3_N_Netz_max REAL,
    
    -- F2/F3/WP
    P_F2_avg REAL, P_F2_min REAL, P_F2_max REAL,
    P_F3_avg REAL, P_F3_min REAL, P_F3_max REAL,
    P_WP_avg REAL, P_WP_min REAL, P_WP_max REAL,
    
    -- Energiezähler (Differenzen über 1min)
    W_AC_Inv_delta REAL,
    W_DC1_delta REAL,
    W_DC2_delta REAL,
    W_Exp_Netz_delta REAL,
    W_Imp_Netz_delta REAL,
    W_Exp_F2_delta REAL,
    W_Imp_F2_delta REAL,
    W_Exp_F3_delta REAL,
    W_Imp_F3_delta REAL,
    W_Exp_WP_delta REAL,
    W_Imp_WP_delta REAL
);

CREATE INDEX IF NOT EXISTS idx_1min_ts ON data_1min(ts);
