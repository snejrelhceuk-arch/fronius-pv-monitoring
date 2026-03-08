-- Fronius PV-Anlage Datenbank Schema V4
-- Technisch korrekte Namenskonvention
-- Datum: 30.12.2025
--
-- Namenskonvention:
--   P_*     = Leistungen (W)
--   W_*     = Elektrische Arbeit (Wh)
--   I_*     = Ströme (A)
--   U_*     = Spannungen (V)
--   f_*     = Frequenz (Hz)
--   S_*     = Scheinleistung (VA)
--   Q_*     = Blindleistung (var)
--   PF_*    = Leistungsfaktor
--   SOC_*   = State of Charge (%)
--   T_*     = Temperaturen (°C)

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ====================================================================
-- RAW DATA TABLE (5-Sekunden-Intervall, 72 Stunden Aufbewahrung)
-- ====================================================================
CREATE TABLE IF NOT EXISTS raw_data (
    ts REAL PRIMARY KEY,  -- Unix-Timestamp
    
    -- === INVERTER (Unit 1) ===
    -- AC-Ströme
    I_L1_Inv REAL,        -- AphA
    I_L2_Inv REAL,        -- AphB
    I_L3_Inv REAL,        -- AphC
    
    -- AC-Spannungen (verkettete Spannungen)
    U_L1_L2_Inv REAL,     -- PPVphAB
    U_L2_L3_Inv REAL,     -- PPVphBC
    U_L3_L1_Inv REAL,     -- PPVphCA
    
    -- AC-Spannungen (Phase-Nullleiter)
    U_L1_N_Inv REAL,      -- PhVphA
    U_L2_N_Inv REAL,      -- PhVphB
    U_L3_N_Inv REAL,      -- PhVphC
    
    -- AC-Leistungen
    P_AC_Inv REAL,        -- W (Wirkleistung)
    S_Inv REAL,           -- VA (Scheinleistung)
    Q_Inv REAL,           -- VAr (Blindleistung)
    PF_Inv REAL,          -- Power Factor (0.00 bis 1.00)
    W_AC_Inv REAL,        -- WH (Energie-Zähler)
    
    -- DC-Werte Inverter
    P_DC_Inv REAL,        -- DCW
    
    -- === MPPT 1+2 (DC-Generatoren F1) ===
    I_DC1 REAL,           -- MPPT1 DCA
    U_DC1 REAL,           -- MPPT1 DCV
    P_DC1 REAL,           -- MPPT1 DCW
    W_DC1 REAL,           -- MPPT1 DCWH (Energie-Zähler)
    
    I_DC2 REAL,           -- MPPT2 DCA
    U_DC2 REAL,           -- MPPT2 DCV
    P_DC2 REAL,           -- MPPT2 DCW
    W_DC2 REAL,           -- MPPT2 DCWH
    
    -- === BATTERIE ===
    SOC_Batt REAL,        -- ChaState (State of Charge in %)
    ChaSt_Batt INTEGER,   -- ChaSt (Ladestatus: 1=OFF, 2=EMPTY, 3=DISCHARGING, 4=CHARGING, 5=FULL, 6=HOLDING, 7=TESTING)
    U_Batt_API REAL,      -- Spannung aus Fronius Storage API (V)
    I_Batt_API REAL,      -- Strom aus Fronius Storage API (A, negativ=Entladung)
    
    -- === SMARTMETER NETZ (Unit 2 - Primärer Smartmeter) ===
    I_Netz REAL,          -- A (Gesamtstrom)
    I_L1_Netz REAL,       -- AphA
    I_L2_Netz REAL,       -- AphB
    I_L3_Netz REAL,       -- AphC
    
    U_Netz REAL,          -- PhV (Durchschnitt)
    U_L1_N_Netz REAL,     -- PhVphA
    U_L2_N_Netz REAL,     -- PhVphB
    U_L3_N_Netz REAL,     -- PhVphC
    
    U_L1_L2_Netz REAL,    -- PPVphAB
    U_L2_L3_Netz REAL,    -- PPVphBC
    U_L3_L1_Netz REAL,    -- PPVphCA
    
    f_Netz REAL,          -- Hz (Frequenz) **WICHTIG**
    
    P_Netz REAL,          -- W (Wirkleistung, positiv=Bezug, negativ=Einspeisung)
    P_L1_Netz REAL,       -- WphA
    P_L2_Netz REAL,       -- WphB
    P_L3_Netz REAL,       -- WphC
    
    S_Netz REAL,          -- VA
    Q_Netz REAL,          -- VAR
    PF_Netz REAL,         -- Power Factor
    
    W_Exp_Netz REAL,      -- TotWhExp (Einspeisung-Zähler, konstant steigend!)
    W_Imp_Netz REAL,      -- TotWhImp (Bezug-Zähler)
    
    -- === SMARTMETER F2 (Unit 3 - Generator F2) ===
    P_F2 REAL,            -- W
    P_L1_F2 REAL,         -- WphA
    P_L2_F2 REAL,         -- WphB
    P_L3_F2 REAL,         -- WphC
    
    S_F2 REAL,            -- VA
    Q_F2 REAL,            -- VAR
    PF_F2 REAL,           -- Power Factor
    
    W_Exp_F2 REAL,        -- TotWhExp
    W_Imp_F2 REAL,        -- TotWhImp
    
    -- === SMARTMETER WP (Unit 4 - Wärmepumpe) ===
    P_WP REAL,            -- W
    P_L1_WP REAL,         -- WphA
    P_L2_WP REAL,         -- WphB
    P_L3_WP REAL,         -- WphC
    
    S_WP REAL,            -- VA
    Q_WP REAL,            -- VAR
    PF_WP REAL,           -- Power Factor
    
    W_Imp_WP REAL,        -- TotWhImp
    
    -- === SMARTMETER F3 (Unit 6 - Generator F3) ===
    P_F3 REAL,            -- W
    P_L1_F3 REAL,         -- WphA
    P_L2_F3 REAL,         -- WphB
    P_L3_F3 REAL,         -- WphC
    
    S_F3 REAL,            -- VA
    Q_F3 REAL,            -- VAR
    PF_F3 REAL,           -- Power Factor
    
    W_Exp_F3 REAL,        -- TotWhExp
    W_Imp_F3 REAL,        -- TotWhImp
    
    -- === META ===
    t_poll_ms INTEGER     -- Polling-Dauer in Millisekunden
);

CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_data(ts);

-- ====================================================================
-- 15-MINUTEN AGGREGATION (4 Wochen Aufbewahrung)
-- ====================================================================
CREATE TABLE IF NOT EXISTS data_15min (
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
    
    -- Energiezähler (Differenzen über 15min)
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
    W_Imp_WP_delta REAL
);

CREATE INDEX IF NOT EXISTS idx_15min_ts ON data_15min(ts);

-- ====================================================================
-- STÜNDLICHE AGGREGATION (12 Wochen)
-- ====================================================================
CREATE TABLE IF NOT EXISTS hourly_data (
    ts REAL PRIMARY KEY,
    -- Aggregation aus 4x 15min (MIN der mins, MAX der maxs)
    P_AC_Inv_avg REAL, P_AC_Inv_min REAL, P_AC_Inv_max REAL,
    P_DC_Inv_avg REAL, P_DC_Inv_min REAL, P_DC_Inv_max REAL,
    P_DC1_avg REAL, P_DC1_min REAL, P_DC1_max REAL,
    P_DC2_avg REAL, P_DC2_min REAL, P_DC2_max REAL,
    SOC_Batt_avg REAL, SOC_Batt_min REAL, SOC_Batt_max REAL,
    U_Batt_API_avg REAL, U_Batt_API_min REAL, U_Batt_API_max REAL,
    I_Batt_API_avg REAL, I_Batt_API_min REAL, I_Batt_API_max REAL,
    P_Netz_avg REAL, P_Netz_min REAL, P_Netz_max REAL,
    f_Netz_avg REAL, f_Netz_min REAL, f_Netz_max REAL,
    P_F2_avg REAL, P_F2_min REAL, P_F2_max REAL,
    P_F3_avg REAL, P_F3_min REAL, P_F3_max REAL,
    P_WP_avg REAL, P_WP_min REAL, P_WP_max REAL,
    
    W_PV_total_delta REAL,  -- Gesamt-PV = DC1+DC2+F2+F3
    W_Exp_Netz_delta REAL,
    W_Imp_Netz_delta REAL
);

CREATE INDEX IF NOT EXISTS idx_hourly_ts ON hourly_data(ts);

-- ====================================================================
-- TÄGLICHE AGGREGATION (36 Monate)
-- ====================================================================
CREATE TABLE IF NOT EXISTS daily_data (
    ts REAL PRIMARY KEY,
    
    -- Nur selektive Min/Max (6 wichtige Werte)
    P_AC_Inv_avg REAL, P_AC_Inv_min REAL, P_AC_Inv_max REAL,
    f_Netz_avg REAL, f_Netz_min REAL, f_Netz_max REAL,
    P_Netz_avg REAL, P_Netz_min REAL, P_Netz_max REAL,
    P_F2_avg REAL, P_F2_min REAL, P_F2_max REAL,
    P_F3_avg REAL, P_F3_min REAL, P_F3_max REAL,
    SOC_Batt_avg REAL, SOC_Batt_min REAL, SOC_Batt_max REAL,
    
    -- Energiesummen
    W_PV_total REAL,        -- Gesamte PV-Produktion (F1+F2+F3)
    W_Exp_Netz_total REAL,  -- Einspeisung
    W_Imp_Netz_total REAL,  -- Bezug
    W_Consumption_total REAL -- Gesamtverbrauch
);

CREATE INDEX IF NOT EXISTS idx_daily_ts ON daily_data(ts);

-- ====================================================================
-- WÖCHENTLICHE AGGREGATION (für immer)
-- ====================================================================
CREATE TABLE IF NOT EXISTS weekly_data (
    ts REAL PRIMARY KEY,
    
    -- Wie daily_data
    P_AC_Inv_avg REAL, P_AC_Inv_min REAL, P_AC_Inv_max REAL,
    f_Netz_avg REAL, f_Netz_min REAL, f_Netz_max REAL,
    P_Netz_avg REAL, P_Netz_min REAL, P_Netz_max REAL,
    P_F2_avg REAL, P_F2_min REAL, P_F2_max REAL,
    P_F3_avg REAL, P_F3_min REAL, P_F3_max REAL,
    SOC_Batt_avg REAL, SOC_Batt_min REAL, SOC_Batt_max REAL,
    
    W_PV_total REAL,
    W_Exp_Netz_total REAL,
    W_Imp_Netz_total REAL,
    W_Consumption_total REAL
);

CREATE INDEX IF NOT EXISTS idx_weekly_ts ON weekly_data(ts);

-- ====================================================================
-- ENERGIE-AKKUMULATOREN (RAM-State für Energieberechnung)
-- ====================================================================
CREATE TABLE IF NOT EXISTS energy_state (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL DEFAULT 0.0
);

-- Initialisierung
INSERT OR IGNORE INTO energy_state (key, value) VALUES 
    ('W_Batt_charge', 0.0),      -- Batterieladung (kumulativ)
    ('W_Batt_discharge', 0.0),   -- Batterieentladung (kumulativ)
    ('W_Exp_Netz', 0.0),         -- Einspeisung (kumulativ)
    ('W_Imp_Netz', 0.0),         -- Bezug (kumulativ)
    ('W_F2', 0.0),               -- F2 Erzeugung (kumulativ)
    ('W_F3', 0.0),               -- F3 Erzeugung (kumulativ)
    ('W_WP', 0.0);               -- WP Verbrauch (kumulativ)

-- ====================================================================
-- STROMPREIS-TABELLE (für flexible Preisänderungen)
-- ====================================================================
CREATE TABLE IF NOT EXISTS price_history (
    valid_from INTEGER PRIMARY KEY,  -- Unix-Timestamp
    price_per_kwh REAL NOT NULL      -- Euro pro kWh
);

-- Initialisierung mit aktuellen Preisen
INSERT OR IGNORE INTO price_history (valid_from, price_per_kwh) VALUES 
    (0, 0.33),                        -- Bis 21.02.2026: 0.33 €/kWh
    (1740182400, 0.30),               -- Ab 22.02.2026: 0.30 €/kWh
    (1803340800, 0.28);               -- Ab 23.02.2028: 0.28 €/kWh (Beispiel)

-- ====================================================================
-- GERÄTE-INFO (statische Daten)
-- ====================================================================
CREATE TABLE IF NOT EXISTS device_info (
    device TEXT PRIMARY KEY,
    manufacturer TEXT,
    model TEXT,
    serial_number TEXT,
    firmware_version TEXT
);
