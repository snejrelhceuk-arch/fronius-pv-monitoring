-- Wattpilot (Wallbox) Zählerstand-Erfassung
-- Speichert regelmäßig den Gesamt-Zählerstand (eto) vom Wattpilot per WebSocket.
-- Tägliche Delta-Berechnung für daily_data und monthly_statistics.

-- Zählerstand-Tabelle (alle 5 Minuten ein Eintrag)
CREATE TABLE IF NOT EXISTS wattpilot_readings (
    ts REAL PRIMARY KEY,              -- Unix-Timestamp der Messung
    energy_total_wh REAL NOT NULL,    -- Gesamt-Zählerstand (eto) in Wh
    power_w REAL DEFAULT 0,           -- Aktuelle Ladeleistung in W
    car_state INTEGER DEFAULT 0,      -- Auto-Status (1=Idle, 2=Charging, ...)
    session_wh REAL DEFAULT 0,        -- Session-Energie in Wh
    temperature_c REAL DEFAULT 0,     -- Gerätetemperatur in °C
    phase_mode INTEGER DEFAULT 0,     -- 1=1-phasig, 2=3-phasig
    amp INTEGER DEFAULT 0,            -- aktuell eingestellter Maximalstrom [A]
    trx TEXT,                         -- aktuell erkannter RFID-Chip
    lmo INTEGER DEFAULT 0,            -- Lademodus (3=Default,4=Eco,5=NextTrip)
    frc INTEGER DEFAULT 0             -- Force-State (0=neutral,1=off,2=on)
);

CREATE INDEX IF NOT EXISTS idx_wattpilot_ts ON wattpilot_readings(ts);

-- Tägliche Wattpilot-Aggregate (berechnet aus Zählerstand-Deltas)
CREATE TABLE IF NOT EXISTS wattpilot_daily (
    ts REAL PRIMARY KEY,              -- Unix-Timestamp (00:00 UTC des Tages)
    energy_wh REAL DEFAULT 0,         -- Tages-Verbrauch in Wh (Delta eto)
    energy_start_wh REAL,             -- Zählerstand Tagesanfang
    energy_end_wh REAL,               -- Zählerstand Tagesende
    max_power_w REAL DEFAULT 0,       -- Maximale Ladeleistung
    charging_hours REAL DEFAULT 0,    -- Stunden mit Ladung (car_state=2)
    sessions INTEGER DEFAULT 0        -- Anzahl Lade-Sessions (Übergänge zu car_state=2)
);

CREATE INDEX IF NOT EXISTS idx_wattpilot_daily_ts ON wattpilot_daily(ts);
