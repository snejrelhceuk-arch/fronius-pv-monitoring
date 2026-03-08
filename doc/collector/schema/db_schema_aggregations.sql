-- Wöchentliche Aggregation
CREATE TABLE IF NOT EXISTS data_weekly (
    ts INTEGER PRIMARY KEY,  -- Timestamp Montag 00:00 der Woche
    
    -- Energie-Deltas (Summen über Woche in Wh)
    W_PV_total_delta REAL,  -- Gesamt-PV = DC1+DC2+F2+F3
    W_DC1_delta REAL,
    W_DC2_delta REAL,
    W_Exp_Netz_delta REAL,
    W_Imp_Netz_delta REAL,
    W_Exp_F2_delta REAL,
    W_Imp_F2_delta REAL,
    W_Exp_F3_delta REAL,
    W_Imp_F3_delta REAL,
    W_Exp_WP_delta REAL,
    W_Imp_WP_delta REAL,
    W_Bat_Charge_delta REAL,
    W_Bat_Discharge_delta REAL,
    
    -- Frequenz (wichtig für alle Zeiträume!)
    f_Netz_min REAL,
    f_Netz_max REAL,
    f_Netz_avg REAL,
    
    -- Leistungswerte Inverter
    P_AC_Inv_min REAL,
    P_AC_Inv_max REAL,
    P_AC_Inv_avg REAL,
    P_DC_Inv_min REAL,
    P_DC_Inv_max REAL,
    P_DC_Inv_avg REAL,
    
    -- MPPT
    P_DC1_min REAL,
    P_DC1_max REAL,
    P_DC1_avg REAL,
    P_DC2_min REAL,
    P_DC2_max REAL,
    P_DC2_avg REAL,
    
    -- Batterie
    SOC_Batt_min REAL,
    SOC_Batt_max REAL,
    SOC_Batt_avg REAL,
    
    -- Netz-Leistung
    P_Netz_min REAL,
    P_Netz_max REAL,
    P_Netz_avg REAL,
    
    -- Netz-Spannung
    U_L1_N_Netz_min REAL,
    U_L1_N_Netz_max REAL,
    U_L1_N_Netz_avg REAL,
    U_L2_N_Netz_min REAL,
    U_L2_N_Netz_max REAL,
    U_L2_N_Netz_avg REAL,
    U_L3_N_Netz_min REAL,
    U_L3_N_Netz_max REAL,
    U_L3_N_Netz_avg REAL,
    
    -- Zusätzliche Messpunkte
    P_F2_min REAL,
    P_F2_max REAL,
    P_F2_avg REAL,
    P_F3_min REAL,
    P_F3_max REAL,
    P_F3_avg REAL,
    P_WP_min REAL,
    P_WP_max REAL,
    P_WP_avg REAL
);

-- Monatliche Aggregation
CREATE TABLE IF NOT EXISTS data_monthly (
    ts INTEGER PRIMARY KEY,  -- Timestamp 1. des Monats 00:00
    
    -- Energie-Deltas (Summen über Monat in Wh)
    W_PV_total_delta REAL,  -- Gesamt-PV = DC1+DC2+F2+F3
    W_DC1_delta REAL,
    W_DC2_delta REAL,
    W_Exp_Netz_delta REAL,
    W_Imp_Netz_delta REAL,
    W_Exp_F2_delta REAL,
    W_Imp_F2_delta REAL,
    W_Exp_F3_delta REAL,
    W_Imp_F3_delta REAL,
    W_Exp_WP_delta REAL,
    W_Imp_WP_delta REAL,
    W_Bat_Charge_delta REAL,
    W_Bat_Discharge_delta REAL,
    
    -- Frequenz
    f_Netz_min REAL,
    f_Netz_max REAL,
    f_Netz_avg REAL,
    
    -- Leistungswerte
    P_AC_Inv_min REAL,
    P_AC_Inv_max REAL,
    P_AC_Inv_avg REAL,
    P_DC_Inv_min REAL,
    P_DC_Inv_max REAL,
    P_DC_Inv_avg REAL,
    
    P_DC1_min REAL,
    P_DC1_max REAL,
    P_DC1_avg REAL,
    P_DC2_min REAL,
    P_DC2_max REAL,
    P_DC2_avg REAL,
    
    SOC_Batt_min REAL,
    SOC_Batt_max REAL,
    SOC_Batt_avg REAL,
    
    P_Netz_min REAL,
    P_Netz_max REAL,
    P_Netz_avg REAL,
    
    U_L1_N_Netz_min REAL,
    U_L1_N_Netz_max REAL,
    U_L1_N_Netz_avg REAL,
    U_L2_N_Netz_min REAL,
    U_L2_N_Netz_max REAL,
    U_L2_N_Netz_avg REAL,
    U_L3_N_Netz_min REAL,
    U_L3_N_Netz_max REAL,
    U_L3_N_Netz_avg REAL,
    
    P_F2_min REAL,
    P_F2_max REAL,
    P_F2_avg REAL,
    P_F3_min REAL,
    P_F3_max REAL,
    P_F3_avg REAL,
    P_WP_min REAL,
    P_WP_max REAL,
    P_WP_avg REAL
);

-- Jährliche Aggregation
CREATE TABLE IF NOT EXISTS data_yearly (
    ts INTEGER PRIMARY KEY,  -- Timestamp 1. Januar 00:00
    
    -- Energie-Deltas (Summen über Jahr in Wh)
    W_PV_total_delta REAL,  -- Gesamt-PV = DC1+DC2+F2+F3
    W_DC1_delta REAL,
    W_DC2_delta REAL,
    W_Exp_Netz_delta REAL,
    W_Imp_Netz_delta REAL,
    W_Exp_F2_delta REAL,
    W_Imp_F2_delta REAL,
    W_Exp_F3_delta REAL,
    W_Imp_F3_delta REAL,
    W_Exp_WP_delta REAL,
    W_Imp_WP_delta REAL,
    W_Bat_Charge_delta REAL,
    W_Bat_Discharge_delta REAL,
    
    -- Frequenz
    f_Netz_min REAL,
    f_Netz_max REAL,
    f_Netz_avg REAL,
    
    -- Leistungswerte
    P_AC_Inv_min REAL,
    P_AC_Inv_max REAL,
    P_AC_Inv_avg REAL,
    P_DC_Inv_min REAL,
    P_DC_Inv_max REAL,
    P_DC_Inv_avg REAL,
    
    P_DC1_min REAL,
    P_DC1_max REAL,
    P_DC1_avg REAL,
    P_DC2_min REAL,
    P_DC2_max REAL,
    P_DC2_avg REAL,
    
    SOC_Batt_min REAL,
    SOC_Batt_max REAL,
    SOC_Batt_avg REAL,
    
    P_Netz_min REAL,
    P_Netz_max REAL,
    P_Netz_avg REAL,
    
    U_L1_N_Netz_min REAL,
    U_L1_N_Netz_max REAL,
    U_L1_N_Netz_avg REAL,
    U_L2_N_Netz_min REAL,
    U_L2_N_Netz_max REAL,
    U_L2_N_Netz_avg REAL,
    U_L3_N_Netz_min REAL,
    U_L3_N_Netz_max REAL,
    U_L3_N_Netz_avg REAL,
    
    P_F2_min REAL,
    P_F2_max REAL,
    P_F2_avg REAL,
    P_F3_min REAL,
    P_F3_max REAL,
    P_F3_avg REAL,
    P_WP_min REAL,
    P_WP_max REAL,
    P_WP_avg REAL
);

-- Indices für schnelle Abfragen
CREATE INDEX IF NOT EXISTS idx_weekly_ts ON data_weekly(ts);
CREATE INDEX IF NOT EXISTS idx_monthly_ts ON data_monthly(ts);
CREATE INDEX IF NOT EXISTS idx_yearly_ts ON data_yearly(ts);
