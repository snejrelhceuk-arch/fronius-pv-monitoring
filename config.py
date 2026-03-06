"""
Zentrale Konfiguration für Fronius PV-Monitoring
Alle gemeinsam genutzten Parameter an einer Stelle.
"""
import os

# --- Pfade ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(BASE_DIR, '.secrets')
DB_PATH = '/dev/shm/fronius_data.db'          # Primäre DB im RAM (tmpfs)
DB_PERSIST_PATH = os.path.join(BASE_DIR, 'data.db')  # Persist-Kopie auf SD-Card (Pi4)
PID_FILE = os.path.join(BASE_DIR, 'collector.pid')


def load_secret(env_key, secrets_file=None):
    """Lade ein Secret aus Umgebungsvariable oder .secrets-Datei.

    Args:
        env_key: Name der Umgebungsvariable (z.B. 'FRONIUS_PASS')
        secrets_file: Pfad zur .secrets-Datei (Default: SECRETS_FILE)

    Returns:
        str or None: Das Secret, oder None wenn nicht gefunden.
    """
    pw = os.environ.get(env_key)
    if pw:
        return pw
    sf = secrets_file or SECRETS_FILE
    if os.path.exists(sf):
        with open(sf, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                if key.strip() == env_key:
                    return val.strip()
    return None

# --- Standort: Erlau, Landkreis Mittelsachsen, Sachsen ---
LATITUDE = 51.01
LONGITUDE = 12.95
ELEVATION = 315              # Meter über NN
TIMEZONE = 'Europe/Berlin'

# --- PV-Anlage (seit Okt/2025: 37.59 kWp) ---
PV_KWP_TOTAL = 37.59        # Gesamt installierte Leistung
PV_INVERTER_KW = 26.5       # F1=12kW + F2=10kW + F3=4.5kW
PV_BATTERY_KWH = 20.48      # BYD HVS parallel (2x usable)
PV_NULLEINSPEISUNG = True    # Nulleinspeiser

# --- Netzwerk ---
INVERTER_IP = '192.0.2.122'
MODBUS_PORT = 502
FRONIUS_API_BASE = f'http://{INVERTER_IP}/solar_api/v1'
WEB_API_HOST = '0.0.0.0'
WEB_API_PORT = 8000

# --- Failover-Host (failover-host) ---
FAILOVER_IP = '192.0.2.105'
FAILOVER_USER = 'jk'
FAILOVER_PV_BASE = '/srv/pv-system'

# --- Wattpilot (Wallbox) ---
WATTPILOT_IP = '192.0.2.197'
WATTPILOT_TIMEOUT = 10             # WebSocket Timeout (Sek.)
WATTPILOT_POLL_INTERVAL = 10       # Zählerstand-Abfrage alle 10 Sekunden (synchron mit Flow-Chart)
WATTPILOT_RETRY_INTERVAL = 5       # Sekunden bis Retry bei WebSocket-Konflikt (App, Netzwerk)
WATTPILOT_MAX_RETRIES = 2          # Max. Wiederholungen pro Zyklus (0=kein Retry)
WATTPILOT_READINGS_RETENTION_DAYS = 90   # Einzelmessungen (90 Tage)
WATTPILOT_DAILY_RETENTION_DAYS = 3650    # Tagesaggregate (~10 Jahre)

# --- Datenerfassung ---
POLL_INTERVAL = 3          # Sekunden zwischen Modbus-Abfragen
BUFFER_MAXLEN = 400        # RAM-Buffer Größe (~20min bei 3s Polling)
FLUSH_INTERVAL = 60        # Sekunden zwischen DB-Writes

# --- tmpfs-DB Persistierung ---
# Alternierende Sicherung: ungerade Tage → SD lokal, gerade Tage → Pi5
# Jede Einzelsicherung max. 2 Tage alt, zusammen max. 1 Tag Lücke.
# Fixpunkte (daily_data._start/_end) decken Tages-/Monats-/Jahreswerte ab.
DB_PERSIST_UNIT = 'hour'
PI5_BACKUP_HOST = 'admin@192.0.2.195'
PI5_BACKUP_DB_PATH = '/srv/pv-system/data.db'

# --- Retention Policies ---
RAW_DATA_RETENTION_DAYS = 7        # raw_data (Pi4/SD-Karten-kompatibel)
DATA_1MIN_RETENTION_DAYS = 90     # 1min-Aggregate (Tag-Chart)
DATA_15MIN_RETENTION_DAYS = 90    # 15min-Aggregate (techn. Basis)
HOURLY_RETENTION_DAYS = 365       # Stunden-Aggregate
DAILY_RETENTION_DAYS = 3650       # Tages-Aggregate (~10 Jahre)
DATA_MONTHLY_RETENTION_DAYS = 3650  # Monatl. techn. Aggregate (~10 Jahre)
# monthly_statistics + yearly_statistics: PERMANENT (Anlagen-Historie)

# --- Stromtarife (PRIMAT — alle Analysen nutzen diese Tabelle) ---
# Format: (Gültig_ab_Tag, Preis_EUR/kWh)
# Sortiert chronologisch. Der letzte Eintrag gilt bis auf Weiteres.
STROMTARIFE = [
    # (YYYY, MM, DD),  EUR/kWh   — Vertrag / Anlass
    ((2021, 11,  5),   0.300),   # Anlagenbeginn
    ((2023,  1,  1),   0.400),   # Preiserhöhung
    ((2024,  2, 23),   0.330),   # Tarifwechsel
    ((2026,  2, 23),   0.3030),  # Vattenfall — 30,30 ct/kWh + 14,90 EUR/Monat Grundpreis, 2J Preisgarantie
]
EINSPEISEVERGUETUNG = 0.000       # Nulleinspeiser — keine Vergütung

# Strom-Grundpreis (monatliche Fixkosten inkl. Zählermiete, unabhängig vom Verbrauch)
# Format: (Gültig_ab_Tag, EUR/Monat)
STROM_GRUNDPREISE = [
    ((2021, 11,  5),  10.00),    # Pauschal 10 EUR/Monat (inkl. Zählermiete)
    ((2026,  2, 23),  14.90),    # Vattenfall — 14,90 EUR/Monat, 2J Preisgarantie
]

# --- Finanzdaten (Investitionen & Betriebskosten) ---
INVEST_PV_2022 = 24000           # EUR (PV-Anlage + Batterie)
INVEST_PV_2024 = 8000            # EUR (Erweiterung 13kWp + Optimierer)
INVEST_BATT_2026 = 3000          # EUR (2. BYD HVS Tower, parallel)
INVEST_WP_2022 = 12000           # EUR (Wärmepumpe)
GESAMT_INVEST_PV = INVEST_PV_2022 + INVEST_PV_2024 + INVEST_BATT_2026  # 35.000 EUR
GESAMT_INVEST_HAUSHALT = GESAMT_INVEST_PV + INVEST_WP_2022  # 47.000 EUR

HAUSHALT_BASIS_KWH = 3000        # kWh/Jahr Grundlast (Licht, Komfort, Lüftung)

# WP-elektrisch Basis (ohne Heizpatrone-Anteil)
WP_BASIS = {
    2021: 0,       # Nur 2 Monate, WP-Daten nicht relevant
    2022: 2318,
    2023: 2774,
    2024: 3255,
    2025: 3018,
    2026: 300,     # Nur 2 Monate, Schätzung anteilig
}

# Heizkosten-Ersparnis (eingesparte Brennstoffkosten vs. vorher Öl/Gas)
# Jahresbudget — wird NUR auf Heizperiode-Monate (Okt–Mär) verteilt.
# Pro Heizmonat: Jahresbudget / 6. Sommermonaten (Apr–Sep): 0 EUR.
# Basis: ca. 1.500 EUR/Jahr Heizkosten vor 2022
HEIZKOSTEN_ERSPARNIS = {
    2021: 1500,    # 100% Basis (nur Nov+Dec vorhanden → 2 × 250 = 500 EUR)
    2022: 1500,    # 100% Basis
    2023: 3000,    # 200% (Energiekrise)
    2024: 2700,    # 180%
    2025: 2700,    # 180%
    2026: 2700,    # 180% (nur Jan+Feb bisher → 2 × 450 = 900 EUR)
}

# Heizperiode: Monate in denen Heizkosten anfallen
HEIZPERIODE_MONATE = {10, 11, 12, 1, 2, 3}  # Okt–Mär (6 Monate)

# --- E-Mail-Benachrichtigungen ---
# Einmalige Meldung bei kritischen Events (Deduplizierung: 1× pro Event-Typ pro Tag)
NOTIFICATION_EMAIL = 'failover-user@example.invalid'
NOTIFICATION_SMTP_HOST = 'smtp.example.invalid'  # SMTP-Relay
NOTIFICATION_SMTP_PORT = 465               # SSL (nicht 587/STARTTLS)
NOTIFICATION_SMTP_USER = 'alerts@example.invalid'
# SMTP-Passwort: NICHT hier — verschlüsselt in /etc/pv-system/smtp_pass.key
# Setzen via: pv-config → Benachrichtigungen → SMTP-Passwort
NOTIFICATION_FROM = 'alerts@example.invalid'
# Meldbare Events — Keys müssen in EVENT_THRESHOLDS definiert sein
NOTIFICATION_EVENTS = ['batt_temp_40', 'batt_soc_kritisch']
# Schwellwerte für Events (obs_feld, operator, schwelle)
EVENT_THRESHOLDS = {
    'batt_temp_40':      {'obs_feld': 'batt_temp_max_c', 'op': '>=', 'schwelle': 40,  'text': 'Batterie-Temperatur ≥ 40°C'},
    'batt_soc_kritisch': {'obs_feld': 'batt_soc_pct',    'op': '<',  'schwelle': 5,   'text': 'Batterie SOC < 5%'},
    'batt_temp_45':      {'obs_feld': 'batt_temp_max_c', 'op': '>=', 'schwelle': 45,  'text': 'Batterie-Temperatur ≥ 45°C (ALARM)'},
    'netz_ueberlast':    {'obs_feld': 'grid_power_w',    'op': '>=', 'schwelle': 24000,'text': 'Netz-Überlast ≥ 24 kW'},
}

def get_strompreis(year, month):
    """
    Gibt den Strompreis (EUR/kWh) für einen Monat zurück.
    Bei Tarifwechsel innerhalb eines Monats: tagesgenau gewichteter Durchschnitt.
    """
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    
    total = 0.0
    for day in range(1, days_in_month + 1):
        date_tuple = (year, month, day)
        price = STROMTARIFE[0][1]  # Fallback: erster Tarif
        for valid_from, p in STROMTARIFE:
            if date_tuple >= valid_from:
                price = p
            else:
                break
        total += price
    
    return round(total / days_in_month, 6)


def get_grundpreis(year, month):
    """
    Gibt den Strom-Grundpreis (EUR/Monat) für einen Monat zurück.
    Bei Tarifwechsel innerhalb eines Monats: tagesgenau gewichteter Durchschnitt.
    """
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    
    total = 0.0
    for day in range(1, days_in_month + 1):
        date_tuple = (year, month, day)
        price = STROM_GRUNDPREISE[0][1]  # Fallback: erster Eintrag
        for valid_from, p in STROM_GRUNDPREISE:
            if date_tuple >= valid_from:
                price = p
            else:
                break
        total += price
    
    return round(total / days_in_month, 2)
