-- Statistik-Erweiterung für historische Daten (seit 05.11.2021)
-- Monatliche und jährliche Aggregate mit Kostenberechnung

-- Monatliche Statistiken
CREATE TABLE IF NOT EXISTS monthly_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    
    -- Verbrauch
    heizpatrone_kwh REAL DEFAULT 0,           -- Heizpatrone-Verbrauch
    netz_bezug_kwh REAL DEFAULT 0,            -- Netzbezug
    batt_entladung_kwh REAL DEFAULT 0,        -- Batterieentladung
    direktverbrauch_kwh REAL DEFAULT 0,       -- Direktverbrauch PV
    wattpilot_kwh REAL DEFAULT 0,             -- Wattpilot (Wallbox) ab 2024
    gesamt_verbrauch_kwh REAL DEFAULT 0,      -- Gesamtverbrauch
    
    -- Produktion
    solar_erzeugung_kwh REAL DEFAULT 0,       -- PV-Erzeugung total
    batt_ladung_kwh REAL DEFAULT 0,           -- Batterieladung
    netz_einspeisung_kwh REAL DEFAULT 0,      -- Netzeinspeisung (berechnet)
    
    -- Kennzahlen
    autarkie_prozent REAL DEFAULT 0,          -- Autarkiegrad in %
    eigenverbrauch_prozent REAL DEFAULT 0,    -- Eigenverbrauchsquote in %
    
    -- Kosten (kumulativ seit Jahresanfang)
    kosten_gesamt_eur REAL DEFAULT 0,         -- Gesamtkosten kumulativ
    kosten_batterie_eur REAL DEFAULT 0,       -- Anteil Batteriekosten
    batterie_amort_prozent REAL DEFAULT 0,    -- Amortisation Batterie in %
    
    -- Strompreise (für Monat)
    strompreis_bezug_eur_kwh REAL DEFAULT 0.30,      -- €/kWh Bezug
    einspeiseverguetung_eur_kwh REAL DEFAULT 0.082,  -- €/kWh Einspeisung
    
    UNIQUE(year, month)
);

-- Jährliche Statistiken (automatisch aggregiert)
CREATE TABLE IF NOT EXISTS yearly_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL UNIQUE,
    
    -- Verbrauch (Jahressummen)
    heizpatrone_kwh REAL DEFAULT 0,
    netz_bezug_kwh REAL DEFAULT 0,
    batt_entladung_kwh REAL DEFAULT 0,
    direktverbrauch_kwh REAL DEFAULT 0,
    wattpilot_kwh REAL DEFAULT 0,
    gesamt_verbrauch_kwh REAL DEFAULT 0,
    
    -- Produktion (Jahressummen)
    solar_erzeugung_kwh REAL DEFAULT 0,
    batt_ladung_kwh REAL DEFAULT 0,
    netz_einspeisung_kwh REAL DEFAULT 0,
    
    -- Durchschnittliche Kennzahlen
    autarkie_prozent_avg REAL DEFAULT 0,
    eigenverbrauch_prozent_avg REAL DEFAULT 0,
    
    -- Kosten (Jahresende)
    kosten_gesamt_eur REAL DEFAULT 0,
    kosten_batterie_eur REAL DEFAULT 0,
    batterie_amort_prozent REAL DEFAULT 0,
    
    -- Ersparnisse
    ersparnis_autarkie_eur REAL DEFAULT 0,        -- Ersparnis durch Autarkie
    ersparnis_eigenverbrauch_eur REAL DEFAULT 0,  -- Ersparnis durch Eigenverbrauch
    einnahmen_einspeisung_eur REAL DEFAULT 0      -- Einnahmen Einspeisung
);

-- View für Gesamtstatistik
CREATE VIEW IF NOT EXISTS v_statistics_overview AS
SELECT 
    'Monatlich' as typ,
    year || '-' || printf('%02d', month) as periode,
    solar_erzeugung_kwh,
    direktverbrauch_kwh,
    batt_ladung_kwh,
    batt_entladung_kwh,
    netz_bezug_kwh,
    netz_einspeisung_kwh,
    gesamt_verbrauch_kwh,
    autarkie_prozent,
    kosten_gesamt_eur
FROM monthly_statistics
UNION ALL
SELECT 
    'Jährlich' as typ,
    CAST(year AS TEXT) as periode,
    solar_erzeugung_kwh,
    direktverbrauch_kwh,
    batt_ladung_kwh,
    batt_entladung_kwh,
    netz_bezug_kwh,
    netz_einspeisung_kwh,
    gesamt_verbrauch_kwh,
    autarkie_prozent_avg,
    kosten_gesamt_eur
FROM yearly_statistics
ORDER BY periode DESC;

-- Index für schnelle Abfragen
CREATE INDEX IF NOT EXISTS idx_monthly_year_month ON monthly_statistics(year, month);
CREATE INDEX IF NOT EXISTS idx_yearly_year ON yearly_statistics(year);
