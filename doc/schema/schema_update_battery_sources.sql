-- Schema-Update: Batterie-Quellen-Trennung (PV vs Netz)
-- Datum: 07.02.2026
-- Zweck: Unterscheidung zwischen PV-Ladung und Netz-Nachladung für korrekte Visualisierung

-- === TABELLE: data_1min ===
ALTER TABLE data_1min ADD COLUMN P_inBatt_PV REAL;      -- Batterie-Ladung aus PV (W)
ALTER TABLE data_1min ADD COLUMN P_inBatt_Grid REAL;    -- Batterie-Ladung aus Netz (W)
ALTER TABLE data_1min ADD COLUMN W_inBatt_PV REAL;      -- Energie Batterie←PV (Wh)
ALTER TABLE data_1min ADD COLUMN W_inBatt_Grid REAL;    -- Energie Batterie←Netz (Wh)

-- === TABELLE: data_15min ===
ALTER TABLE data_15min ADD COLUMN P_inBatt_PV REAL;
ALTER TABLE data_15min ADD COLUMN P_inBatt_Grid REAL;
ALTER TABLE data_15min ADD COLUMN W_inBatt_PV REAL;
ALTER TABLE data_15min ADD COLUMN W_inBatt_Grid REAL;

-- === TABELLE: hourly_data ===
ALTER TABLE hourly_data ADD COLUMN P_inBatt_PV REAL;
ALTER TABLE hourly_data ADD COLUMN P_inBatt_Grid REAL;
ALTER TABLE hourly_data ADD COLUMN W_inBatt_PV REAL;
ALTER TABLE hourly_data ADD COLUMN W_inBatt_Grid REAL;

-- Hinweis: Alte Daten haben NULL in diesen Spalten - OK während Entwicklung!
-- Neue Aggregationen füllen Werte automatisch
