#!/usr/bin/env python3
"""
battery_scheduler.py — Automatische Batterie-Steuerung
=======================================================
Wird alle 15 Minuten per Cron aufgerufen.
Trifft zwei Entscheidungen pro Tag basierend auf PV-Prognose:

  ① Morgens:      SOC_MIN 20% → 5%  (Batterie tiefer entladen)
  ② Nachmittags:  SOC_MAX 70% → 100% (mehr Kapazität freigeben)

Plus: Prognosegesteuerter Zellausgleich 1×/Monat.

Konfiguration:  config/battery_control.json
Logging:        battery_control_log (SQLite) + stdout
Doku:           doc/BATTERY_ALGORITHM.md

Nutzung:
  python3 battery_scheduler.py              # Normaler Lauf (Cron)
  python3 battery_scheduler.py --status     # Nur Status anzeigen
  python3 battery_scheduler.py --dry-run    # Testlauf ohne Schreiben
  python3 battery_scheduler.py --force-morning   # Morgen-Öffnung erzwingen
  python3 battery_scheduler.py --force-afternoon # Nachmittag-Erhöhung erzwingen
  python3 battery_scheduler.py --reset      # Auf Komfort-Defaults zurücksetzen
"""

import sys
import os
import json
import time
import sqlite3
from host_role import is_failover

if is_failover():
    sys.exit(0)
import logging
import argparse
from datetime import datetime, date, timedelta

# Encoding fix für RPi
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════
# PFADE & KONFIGURATION
# ═══════════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import config

CONFIG_FILE = os.path.join(BASE_DIR, 'config', 'battery_control.json')
DB_PATH = config.DB_PATH
STATE_FILE = os.path.join(BASE_DIR, 'config', 'battery_scheduler_state.json')

LOG = logging.getLogger('battery_scheduler')


# ═══════════════════════════════════════════════════════════════
# KONFIGURATION LADEN
# ═══════════════════════════════════════════════════════════════

def load_config():
    """Lade battery_control.json."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        LOG.error(f"Config nicht lesbar: {e}")
        return None


def load_state():
    """Lade persistenten State (Tages-Flags, letzter Zellausgleich)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'morning_done': False,
        'afternoon_done': False,
        'manual_override': False,
        'evening_rate_active': False,
        'evening_rate_percent': None,
        'last_date': None,
        'last_balancing': None,
        'balancing_active': False,
    }


def save_state(state):
    """Persistiere State."""
    if _DRY_RUN:
        LOG.debug("[DRY RUN] State nicht gespeichert")
        return
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# DATENBANK
# ═══════════════════════════════════════════════════════════════

_DRY_RUN = False  # Global flag, wird von main() gesetzt

def log_action(action, param=None, old_value=None, new_value=None,
               reason='', forecast_kwh=None, cloud_avg=None,
               soc=None, surplus_kwh=None, manual=False):
    """Schreibe Eintrag in battery_control_log."""
    if _DRY_RUN:
        LOG.debug(f"[DRY RUN] Log: {action} — {reason}")
        return
    try:
        with sqlite3.connect(DB_PATH) as db:
            db.execute("""
                INSERT INTO battery_control_log
                    (ts, action, param, old_value, new_value, reason,
                     forecast_kwh, cloud_avg, soc_at_decision, surplus_kwh, manual)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (time.time(), action, param, old_value, new_value, reason,
                  forecast_kwh, cloud_avg, soc, surplus_kwh, 1 if manual else 0))
    except Exception as e:
        LOG.error(f"DB-Logging fehlgeschlagen: {e}")


def get_current_soc():
    """Aktuellen SOC aus data_1min (letzte 5 Minuten)."""
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = db.execute("""
                SELECT SOC_Batt_avg FROM data_1min
                WHERE ts > ? - 300
                ORDER BY ts DESC LIMIT 1
            """, (time.time(),)).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def get_avg_consumption_kw(minutes=30):
    """Durchschnittlicher Verbrauch der letzten N Minuten [kW]."""
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = db.execute("""
                SELECT AVG(P_Imp + P_outBatt + P_Direct) / 1000.0
                FROM data_1min
                WHERE ts > ? - ?
            """, (time.time(), minutes * 60)).fetchone()
            return row[0] if row and row[0] else None
    except Exception:
        return None


def _get_live_pv_power():
    """Aktuelle PV-Leistung aus data_1min (letzte 5 Minuten) [W].

    Liest P_DC1 + P_DC2 (= echte PV-String-Erzeugung, ohne Batterie).
    Returns: float (Watt) oder None wenn nicht verfügbar.
    """
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = db.execute("""
                SELECT COALESCE(P_DC1_avg, 0) + COALESCE(P_DC2_avg, 0)
                FROM data_1min
                WHERE ts > ? - 300
                ORDER BY ts DESC LIMIT 1
            """, (time.time(),)).fetchone()
            return row[0] if row and row[0] is not None else None
    except Exception:
        return None


def get_remaining_pv_surplus_kwh(hourly_forecast, current_hour, consumption_kw,
                                 power_hourly=None):
    """
    Berechne verbleibenden PV-Überschuss bis Sonnenuntergang [kWh].

    Nutzt die Geometrie-Engine (power_hourly) für echte AC-Leistung,
    Fallback auf GHI×Faktor wenn nicht verfügbar.
    """
    # ★ Bevorzugt: Echte Power-Prognose
    if power_hourly:
        remaining_pv = 0.0
        remaining_consumption = 0.0
        for h in power_hourly:
            # Hour aus ISO-Zeitstempel extrahieren
            hr = h.get('hour')
            if hr is None:
                t = h.get('time', '')
                try:
                    hr = int(t[11:13]) + int(t[14:16]) / 60.0
                except (ValueError, IndexError):
                    continue
            else:
                hr = float(hr)
            if hr <= current_hour:
                continue
            ac_w = h.get('total_ac', 0) or 0
            remaining_pv += ac_w / 1000.0       # kWh (1 Stunde)
            remaining_consumption += consumption_kw
        surplus = remaining_pv - remaining_consumption
        return remaining_pv, surplus

    # Fallback: GHI-basiert (ungenau, nur Notlösung)
    if not hourly_forecast:
        return None, None

    remaining_pv = 0.0
    remaining_consumption = 0.0

    for h in hourly_forecast:
        if h['hour'] <= current_hour:
            continue
        ghi_w = h.get('ghi', 0) or 0
        remaining_pv += ghi_w / 1000.0
        remaining_consumption += consumption_kw

    surplus = remaining_pv - remaining_consumption
    return remaining_pv, surplus


# ═══════════════════════════════════════════════════════════════
# INVERTER-STEUERUNG (Wrapper)
# ═══════════════════════════════════════════════════════════════

class InverterControl:
    """Abstrahiert Fronius HTTP API + Modbus in ein Interface."""

    MAX_RETRIES = 2   # Automatische Wiederholungen bei Fehlern
    RETRY_DELAY = 1.5 # Sekunden zwischen Retry-Versuchen

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._api = None
        self._modbus = None

    def _get_api(self):
        """Lazy-Init Fronius HTTP API."""
        if self._api is None:
            try:
                from fronius_api import BatteryConfig
                self._api = BatteryConfig()
            except Exception as e:
                LOG.error(f"Fronius API nicht verfügbar: {e}")
        return self._api

    def _get_modbus(self):
        """Lazy-Init Modbus Client."""
        if self._modbus is None:
            try:
                from battery_control import ModbusClient, IP_ADDRESS, PORT
                client = ModbusClient(IP_ADDRESS, PORT)
                if client.connect():
                    self._modbus = client
                    time.sleep(0.1)
                else:
                    LOG.error("Modbus-Verbindung fehlgeschlagen")
            except Exception as e:
                LOG.error(f"Modbus nicht verfügbar: {e}")
        return self._modbus

    def _retry(self, op_name, get_fn, reset_attr, exec_fn):
        """Generische Retry-Logik für API- und Modbus-Operationen.
        
        Args:
            op_name: Name für Logging
            get_fn: callable → Ressource (API/Modbus-Client)
            reset_attr: Attributname zum Zurücksetzen bei Fehler ('_api' oder '_modbus')
            exec_fn: callable(resource) → Ergebnis
        """
        for attempt in range(self.MAX_RETRIES + 1):
            resource = get_fn()
            if not resource:
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"  {op_name}: nicht verbunden — Retry {attempt+1}/{self.MAX_RETRIES}")
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
                    continue
                return False
            try:
                result = exec_fn(resource)
                # API-Calls (kein Rückgabewert) → True; Modbus (bool) → prüfen
                if result is None or result is True:
                    return True
                if result:
                    return True
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"  {op_name}: fehlgeschlagen — Retry {attempt+1}/{self.MAX_RETRIES}")
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
            except Exception as e:
                LOG.error(f"  {op_name}: {e}")
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"  {op_name}: Retry {attempt+1}/{self.MAX_RETRIES}")
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
        return False

    def _retry_api(self, op_name, func):
        """HTTP-API-Operation mit Retry-Logik."""
        return self._retry(op_name, self._get_api, '_api', func)

    def _retry_modbus(self, op_name, func):
        """Modbus-Operation mit Retry-Logik."""
        return self._retry(op_name, self._get_modbus, '_modbus', func)

    def close(self):
        if self._modbus:
            self._modbus.close()
            self._modbus = None

    def get_current_settings(self):
        """Lese aktuelle SOC-Einstellungen vom Inverter."""
        api = self._get_api()
        if not api:
            return None
        try:
            values = api.get_values()
            return {
                'soc_min': values.get('BAT_M0_SOC_MIN'),
                'soc_max': values.get('BAT_M0_SOC_MAX'),
                'soc_mode': values.get('BAT_M0_SOC_MODE'),
                'grid_charge': values.get('HYB_EVU_CHARGEFROMGRID'),
            }
        except Exception as e:
            LOG.error(f"Einstellungen nicht lesbar: {e}")
            return None

    def _command(self, log_msg, dry_msg, retry_fn, op_name, func):
        """Generischer Dispatcher: Log + Dry-Run-Guard + Retry."""
        LOG.info(log_msg)
        if self.dry_run:
            LOG.info(f"  [DRY RUN] {dry_msg}")
            return True
        return retry_fn(op_name, func)

    def set_soc_min(self, value):
        """SOC_MIN setzen via HTTP API (mit Retry)."""
        return self._command(
            f"→ SOC_MIN = {value}%", f"Würde SOC_MIN auf {value}% setzen",
            self._retry_api, 'SOC_MIN', lambda api: api.set_soc_min(value))

    def set_soc_max(self, value):
        """SOC_MAX setzen via HTTP API (mit Retry)."""
        return self._command(
            f"→ SOC_MAX = {value}%", f"Würde SOC_MAX auf {value}% setzen",
            self._retry_api, 'SOC_MAX', lambda api: api.set_soc_max(value))

    def set_soc_mode(self, mode):
        """SOC_MODE setzen ('auto' oder 'manual') (mit Retry)."""
        return self._command(
            f"→ SOC_MODE = {mode}", f"Würde SOC_MODE auf '{mode}' setzen",
            self._retry_api, 'SOC_MODE', lambda api: api.set_soc_mode(mode))

    def set_auto_modbus(self):
        """Modbus: Alle Lade-/Entladelimits aufheben (mit Retry)."""
        from battery_control import auto_battery
        return self._command(
            "→ Modbus AUTOMATIK (StorCtl_Mod=0)", "Würde Modbus StorCtl_Mod=0 setzen",
            self._retry_modbus, 'Modbus-Auto', lambda c: auto_battery(c))

    def set_discharge_rate(self, percent):
        """Modbus: Entladerate begrenzen (0-100% von WChaMax) (mit Retry)."""
        from battery_control import set_discharge_rate as _sdr
        return self._command(
            f"→ Entladerate = {percent}%", f"Würde Entladerate auf {percent}% setzen",
            self._retry_modbus, 'Entladerate', lambda c: _sdr(c, percent))

    def hold_battery(self):
        """Modbus: Batterie halten (kein Laden/Entladen) (mit Retry)."""
        from battery_control import hold_battery as _hb
        return self._command(
            "→ Batterie HOLD (Entladerate=0%)", "Würde Batterie halten",
            self._retry_modbus, 'Batterie-Hold', lambda c: _hb(c))

    def get_modbus_status(self):
        """Modbus: Aktuellen StorCtl_Mod und Raten lesen."""
        client = self._get_modbus()
        if not client:
            return None
        try:
            from battery_control import read_raw, read_int16_scaled, REG
            storctl = read_raw(client, REG['StorCtl_Mod'])
            outwrte, _, _ = read_int16_scaled(client, REG['OutWRte'], REG['InOutWRte_SF'])
            inwrte, _, _ = read_int16_scaled(client, REG['InWRte'], REG['InOutWRte_SF'])
            soc, _, _ = read_int16_scaled(client, REG['ChaState'], REG['ChaState_SF'])
            return {
                'storctl_mod': storctl,
                'discharge_rate': outwrte,
                'charge_rate': inwrte,
                'soc_modbus': soc,
            }
        except Exception as e:
            LOG.error(f"Modbus-Status nicht lesbar: {e}")
            return None


# ═══════════════════════════════════════════════════════════════
# ALGORITHMUS-KERN
# ═══════════════════════════════════════════════════════════════

def run_scheduler(args):
    """Hauptlogik — wird alle 15 Minuten aufgerufen."""

    # --- Config laden ---
    cfg = load_config()
    if not cfg:
        LOG.error("Konfiguration fehlt — Abbruch")
        return False

    state = load_state()
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    current_hour = now.hour + now.minute / 60.0

    # --- Prognose laden ---
    try:
        from solar_forecast import SolarForecast
        sf = SolarForecast()
        strategy = sf.get_strategy_inputs()
        hourly = sf.get_hourly_forecast()
        # ★ Echte PV-Leistungsprognose via Geometrie-Engine (pro Stunde AC-Watt)
        power_hourly = sf.get_hourly_power_forecast()
        if power_hourly:
            LOG.info(f"Power-Prognose geladen: {len(power_hourly)} Stunden, "
                     f"Peak={max(h.get('total_ac',0) or 0 for h in power_hourly):.0f}W")
        else:
            LOG.warning("Geometrie-Engine nicht verfügbar — Fallback auf GHI")
    except Exception as e:
        LOG.warning(f"Prognose nicht verfügbar: {e}")
        strategy = {'valid': False, 'expected_kwh': 0, 'cloud_cover_avg': 50}
        hourly = None
        power_hourly = None

    forecast_kwh = strategy.get('expected_kwh', 0)
    cloud_avg = strategy.get('cloud_cover_avg', 50)
    soc = get_current_soc()

    # --- Nur Status anzeigen ---
    if args.status:
        _print_status(cfg, state, strategy, soc)
        return True

    # --- Manual Override? ---
    if state.get('manual_override') and not args.force_morning and not args.force_afternoon:
        LOG.info(f"Manual Override aktiv — überspringe automatische Steuerung")
        save_state(state)
        return True

    inverter = InverterControl(args.dry_run)

    try:
        # ═══════════════════════════════════════════════════════
        # TAGES-RESET: SOC-Werte + Flags bei neuem Tag zurücksetzen
        # ═══════════════════════════════════════════════════════
        if state.get('last_date') != today_str:
            LOG.info(f"═══ Neuer Tag: {today_str} ═══")
            state['morning_done'] = False
            state['afternoon_done'] = False
            # manual_override bleibt bis manuell aufgehoben!
            state['last_date'] = today_str

            # Zellausgleich beenden (falls gestern aktiv)
            if state.get('balancing_active'):
                LOG.info("Zellausgleich beendet")
                state['balancing_active'] = False

            # ★ KRITISCH: SOC + Modbus auf Komfort-Defaults zurücksetzen
            # Verhindert, dass Stress-Werte vom Vortag aktiv bleiben!
            LOG.info("Tages-Reset: SOC + Modbus → Komfort-Defaults")
            _apply_comfort_defaults(cfg, state, inverter)
            save_state(state)  # Sofort persistieren

        # ═══════════════════════════════════════════════════════
        # KONSISTENZ-PRÜFUNG: Inverter vs. erwarteter Zustand
        # ═══════════════════════════════════════════════════════
        _verify_consistency(cfg, state, inverter, current_hour, strategy)

        # --- Zellausgleich prüfen ---
        if cfg.get('zellausgleich', {}).get('aktiv', False):
            did_balancing = _check_balancing(cfg, state, strategy, inverter, soc)
            if did_balancing:
                save_state(state)
                return True

        # Wenn Zellausgleich heute aktiv, prüfe ob er beendet werden kann
        if state.get('balancing_active'):
            sunset_h = strategy.get('sunset_hour', 17.0)
            if current_hour > sunset_h + 0.5:
                # Sunset + 30 Min vorbei → Balancing beenden, Komfort-Defaults
                LOG.info(f"Zellausgleich beendet (Sunset+30 Min vorbei) "
                         f"— zurück auf Komfort-Defaults")
                state['balancing_active'] = False
                _apply_comfort_defaults(cfg, state, inverter)
                log_action('balancing_end', None, None, None,
                           f"Zellausgleich beendet: Sunset {sunset_h:.1f}h, "
                           f"jetzt {current_hour:.1f}h")
            else:
                LOG.info("Zellausgleich-Tag — keine SOC-Steuerung")
                save_state(state)
                return True

        morgen_cfg = cfg.get('morgen_algorithmus', {})
        nachmittag_cfg = cfg.get('nachmittag_algorithmus', {})

        # --- Morgen-Algorithmus ---
        # Öffnung ab Sonnenaufgang (verschiebt sich jahreszeitlich automatisch).
        # Vorher (fenster_start_stunde=5) war viel zu früh → Entladung im Dunkeln.
        sunrise_h = strategy.get('sunrise_hour', 7.5)
        morning_end = sunrise_h + morgen_cfg.get('fenster_stunden_nach_sunrise', 3)

        if (morgen_cfg.get('aktiv', True)
                and sunrise_h <= current_hour <= morning_end
                and (not state['morning_done'] or args.force_morning)):
            _morning_algorithm(cfg, state, strategy, hourly, power_hourly,
                               inverter, soc, forecast_kwh, cloud_avg,
                               args.force_morning)

        # --- Nachmittag-Algorithmus ---
        afternoon_start = nachmittag_cfg.get('start_stunde', 12)
        sunset_h = strategy.get('sunset_hour', 17.0)

        if (nachmittag_cfg.get('aktiv', True)
                and afternoon_start <= current_hour
                and (not state['afternoon_done'] or args.force_afternoon)):
            _afternoon_algorithm(cfg, state, strategy, hourly, power_hourly,
                                 inverter, soc, forecast_kwh, cloud_avg,
                                 args.force_afternoon)

        # --- Abend-/Nacht-Algorithmus (Entladerate begrenzen) ---
        _evening_algorithm(cfg, state, strategy, inverter, soc, current_hour)

    finally:
        inverter.close()

    save_state(state)
    return True


# ═══════════════════════════════════════════════════════════════
# MORGEN-ALGORITHMUS
# ═══════════════════════════════════════════════════════════════

def _morning_algorithm(cfg, state, strategy, hourly, power_hourly,
                       inverter, soc, forecast_kwh, cloud_avg, force=False):
    """SOC_MIN Öffnung: Batterie entleeren bevor PV übernimmt.

    Wird ab Sonnenaufgang aufgerufen (caller prüft sunrise_hour).
    Nur zwei Regeln:
      A) Prognose < min_pv → NICHT öffnen (schlechter Tag)
      B) SOC bereits < soc_min_open + 2 → nicht nötig
    Sonst: sofort öffnen. Batterie entlädt nur durch realen Verbrauch,
    PV-Anstieg kommt innerhalb ~30 Min nach Sunrise sicher.
    """

    morgen = cfg['morgen_algorithmus']
    grenzen = cfg['soc_grenzen']
    soc_min_default = grenzen['komfort_min']       # Komfort-Untergrenze (default 25%)
    soc_min_open = grenzen['stress_min']            # Stress-Untergrenze (default 5%)
    min_pv = morgen.get('min_pv_prognose_kwh', 5.0)

    LOG.info(f"── Morgen-Check: SOC={soc}%, Prognose={forecast_kwh:.0f} kWh, "
             f"Komfort-Min={soc_min_default}% ──")

    # Bereits erledigt?
    if state['morning_done'] and not force:
        LOG.debug("morning_done — übersprungen")
        return

    # REGEL A: Schlechter Tag → nicht öffnen
    if forecast_kwh < min_pv and not force:
        state['morning_done'] = True
        reason = f"Nicht geöffnet: Prognose {forecast_kwh:.0f} kWh < {min_pv} kWh"
        LOG.info(f"  ✗ {reason}")
        log_action('morning_skip', 'soc_min', soc_min_default, soc_min_default,
                   reason, forecast_kwh, cloud_avg, soc)
        return

    # REGEL B: Batterie schon nahe am Ziel → nicht nötig
    if soc is not None and soc < soc_min_open + 2 and not force:
        reason = f"SOC={soc:.1f}% bereits nah an Ziel-Minimum {soc_min_open}% — nicht nötig"
        LOG.info(f"  ✗ {reason}")
        return

    # → ÖFFNEN (sofort, kein Timing-Gate)
    settings = inverter.get_current_settings()
    old_min = settings['soc_min'] if settings else soc_min_default

    if old_min <= soc_min_open:
        state['morning_done'] = True
        LOG.info(f"  ≡ SOC_MIN bereits auf {old_min}% — keine Änderung")
        return

    ok = inverter.set_soc_min(soc_min_open)

    if ok:
        state['morning_done'] = True
        reason = (f"Geöffnet: {old_min}%→{soc_min_open}%, "
                  f"Prognose {forecast_kwh:.0f} kWh, SOC={soc:.0f}%")
        LOG.info(f"  ✓ {reason}")
        log_action('morning_open', 'soc_min', old_min, soc_min_open,
                   reason, forecast_kwh, cloud_avg, soc)
    else:
        LOG.error("  ✗ SOC_MIN setzen fehlgeschlagen!")


def _find_takeover_hour(hourly, morgen_cfg, power_hourly=None):
    """Finde erste Stunde, in der PV den Verbrauch deckt.

    Nutzt die Geometrie-Engine (power_hourly) für echte AC-Leistung,
    Fallback auf GHI wenn nicht verfügbar.
    """
    # Threshold: 80% des aktuellen Verbrauchs
    threshold_factor = morgen_cfg.get('uebernahme_schwelle', 0.8)
    base_load = get_avg_consumption_kw(30)
    if not base_load:
        base_load = morgen_cfg.get('drain_rate_fallback_kw', 1.5)

    threshold_w = base_load * 1000.0 * threshold_factor

    # ★ Bevorzugt: Echte Power-Prognose via Geometrie-Engine
    if power_hourly:
        for h in power_hourly:
            ac_w = h.get('total_ac', 0) or 0
            # Hour aus ISO-Zeitstempel extrahieren
            hr = h.get('hour')
            if hr is None:
                t = h.get('time', '')
                try:
                    hr = float(t[11:13])
                except (ValueError, IndexError):
                    continue
            LOG.debug(f"  Takeover-Check: {hr:.0f}h AC={ac_w:.0f}W "
                      f"(Schwelle={threshold_w:.0f}W)")
            if ac_w > threshold_w:
                LOG.info(f"  Takeover: {hr:.0f}h mit {ac_w:.0f}W > "
                         f"{threshold_w:.0f}W")
                return hr
        return None

    # Fallback: GHI-basiert (UNGENAU — nur wenn Geometrie nicht verfügbar)
    if not hourly:
        return None
    LOG.warning("  Takeover: Fallback auf GHI-Formel (ungenau!)")

    for h in hourly:
        ghi = h.get('ghi', 0) or 0
        cloud = h.get('cloud_cover', 50) or 50
        cloud_factor = 1.0 - 0.7 * (cloud / 100.0)
        effective_pv_w = ghi * cloud_factor * 5.0
        if effective_pv_w > threshold_w:
            return h['hour']

    return None


def _get_drain_rate(cfg, morgen_cfg):
    """Drain-Rate in kW (gewichteter Mix aus Live + Historisch)."""
    mix = morgen_cfg.get('drain_rate_mix', {})
    live_weight = mix.get('live_gewicht', 0.3)
    hist_weight = mix.get('historisch_gewicht', 0.7)
    fallback = morgen_cfg.get('drain_rate_fallback_kw', 1.5)

    live = get_avg_consumption_kw(30)
    hist = get_avg_consumption_kw(120)  # Längerer Zeitraum als Proxy

    if live and hist:
        return live * live_weight + hist * hist_weight
    elif live:
        return live
    elif hist:
        return hist
    return fallback


# ═══════════════════════════════════════════════════════════════
# NACHMITTAG-ALGORITHMUS
# ═══════════════════════════════════════════════════════════════

def _afternoon_algorithm(cfg, state, strategy, hourly, power_hourly,
                         inverter, soc, forecast_kwh, cloud_avg, force=False):
    """SOC_MAX Erhöhung: Mehr Kapazität freigeben wenn PV-Fenster sich schliesst."""

    nachmittag = cfg['nachmittag_algorithmus']
    grenzen = cfg['soc_grenzen']
    soc_max_low = grenzen['komfort_max']            # Komfort-Obergrenze (default 80%)
    soc_max_full = grenzen['stress_max']             # Stress-Obergrenze (default 100%)
    surplus_factor = nachmittag.get('surplus_sicherheitsfaktor', 1.3)
    cloud_heavy = nachmittag.get('wolken_schwer_prozent', 85)
    max_hours = nachmittag.get('max_stunden_vor_sunset', 1.5)

    now = datetime.now()
    current_hour = now.hour + now.minute / 60.0
    sunset_h = strategy.get('sunset_hour', 17.0)
    hours_to_sunset = sunset_h - current_hour

    LOG.info(f"── Nachmittag-Check: SOC={soc}%, Sunset in {hours_to_sunset:.1f}h, "
             f"Wolken={cloud_avg}% ──")

    # Bereits erledigt?
    if state['afternoon_done'] and not force:
        LOG.debug("afternoon_done — übersprungen")
        return

    # Wenn SOC_MAX bereits auf max steht, nichts zu tun
    settings = inverter.get_current_settings()
    old_max = settings['soc_max'] if settings else soc_max_low

    if old_max >= soc_max_full:
        state['afternoon_done'] = True
        LOG.info(f"  ≡ SOC_MAX bereits auf {old_max}% — keine Änderung")
        return

    # Verbrauch + PV-Rest berechnen (echte AC-Prognose bevorzugt)
    consumption_kw = get_avg_consumption_kw(60) or 1.5
    remaining_pv, surplus = get_remaining_pv_surplus_kwh(
        hourly, int(current_hour), consumption_kw, power_hourly)

    fill_needed = (soc_max_full - soc_max_low) / 100.0 * cfg['batterie']['kapazitaet_kwh']

    should_raise = False
    reason = ''

    # REGEL C: Deadline
    if hours_to_sunset <= max_hours or force:
        should_raise = True
        reason = f"Deadline: {hours_to_sunset:.1f}h bis Sunset"

    # REGEL D: Wenig PV übrig
    elif remaining_pv is not None and remaining_pv < 1.0:
        should_raise = True
        reason = f"Wenig PV übrig: {remaining_pv:.1f} kWh"

    # REGEL E: Stark bewölkt
    elif cloud_avg > cloud_heavy:
        should_raise = True
        reason = f"Stark bewölkt: {cloud_avg:.0f}% > {cloud_heavy}%"

    # REGEL F: PV-Fenster schliesst sich
    elif surplus is not None and surplus <= fill_needed * surplus_factor:
        should_raise = True
        reason = f"Surplus {surplus:.1f} kWh ≤ Fill {fill_needed:.1f}×{surplus_factor}"

    if should_raise:
        ok = inverter.set_soc_max(soc_max_full)
        if ok:
            state['afternoon_done'] = True
            LOG.info(f"  ✓ SOC_MAX: {old_max}%→{soc_max_full}% — {reason}")
            log_action('afternoon_raise', 'soc_max', old_max, soc_max_full,
                       reason, forecast_kwh, cloud_avg, soc,
                       surplus_kwh=surplus)
        else:
            LOG.error("  ✗ SOC_MAX setzen fehlgeschlagen!")
    else:
        surplus_str = f"{surplus:.1f}" if surplus else "?"
        LOG.info(f"  ⏳ Warte: Surplus={surplus_str} kWh > "
                 f"Fill={fill_needed:.1f}×{surplus_factor} kWh")


# ═══════════════════════════════════════════════════════════════
# ABEND-/NACHT-ALGORITHMUS (Entladerate begrenzen)
# ═══════════════════════════════════════════════════════════════

def _evening_algorithm(cfg, state, strategy, inverter, soc, current_hour):
    """
    Entladerate-Begrenzung für Abend und Nacht.

    Schützt die Batterie vor schneller Entladung durch hohe Abendlasten
    (Backofen, Waschmaschine, Trockner). Grid übernimmt Spitzenlasten.

    Phasen (konfigurierbar in battery_control.json):
      Abend (default 15:00–00:00): 29% ≈ 3,0 kW — Grundlast OK, Spitzen → Grid
      Nacht (default 00:00–06:00): 10% ≈ 1,0 kW — Standby-Verbrauch
      Tag   (default 06:00–15:00): AUTOMATIK     — PV-Betrieb, keine Limits

    Sonder-Logik:
      - SOC < kritisch_soc (10%): Entladesperre (0%) → Batterie schützen
      - Zellausgleich aktiv: Keine Einschränkung (braucht vollen Zyklus)
    """
    zeit_cfg = cfg.get('zeitsteuerung', {})
    leist_cfg = cfg.get('leistungsbegrenzung', {})
    grenzen = cfg.get('soc_grenzen', {})

    abend_ab = zeit_cfg.get('abend_entladelimit_ab', 15)
    abend_bis = zeit_cfg.get('abend_entladelimit_bis', 0)   # 0 = Mitternacht
    nacht_ab = zeit_cfg.get('nacht_entladelimit_ab', 0)
    nacht_bis = zeit_cfg.get('nacht_entladelimit_bis', 6)

    abend_rate = leist_cfg.get('entladerate_abend_prozent', 29)
    nacht_rate = leist_cfg.get('entladerate_nacht_prozent', 10)
    kritisch_soc = grenzen.get('kritisch_soc', 10)

    # Zellausgleich aktiv → keine Einschränkung
    if state.get('balancing_active'):
        LOG.debug("  Abend-Algo: Zellausgleich aktiv — übersprungen")
        return

    # Phase bestimmen
    target_rate = None
    phase = None

    # SOC-Notbremse: unterhalb kritischem SOC → Entladesperre
    if soc is not None and soc < kritisch_soc:
        target_rate = 0
        phase = f"SOC-SCHUTZ ({soc:.0f}% < {kritisch_soc}%)"

    # Abend-Phase: ab abend_ab bis Mitternacht
    elif abend_ab <= current_hour or (abend_bis > 0 and current_hour < abend_bis):
        target_rate = abend_rate
        phase = f"ABEND ({abend_ab}:00–{abend_bis or 24}:00)"

    # Nacht-Phase: 0:00 bis nacht_bis
    elif nacht_ab <= current_hour < nacht_bis:
        target_rate = nacht_rate
        phase = f"NACHT ({nacht_ab}:00–{nacht_bis}:00)"

    # Tag-Phase: keine Begrenzung
    else:
        # Prüfe ob derzeit ein Limit aktiv ist, das aufgehoben werden muss
        if state.get('evening_rate_active'):
            LOG.info(f"── Abend-Limit aufheben: Tag-Phase ({nacht_bis}:00–{abend_ab}:00) ──")
            ok = inverter.set_auto_modbus()
            if ok:
                old_rate = state.get('evening_rate_percent', '?')
                state['evening_rate_active'] = False
                state['evening_rate_percent'] = None
                LOG.info(f"  ✓ Entladerate: {old_rate}%→AUTOMATIK")
                log_action('evening_auto', 'discharge_rate', old_rate, 'auto',
                           f"Tag-Phase: Limits aufgehoben")
            else:
                LOG.error("  ✗ Modbus Auto fehlgeschlagen!")
        return

    # Bereits auf korrekter Rate?
    current_rate = state.get('evening_rate_percent')
    if state.get('evening_rate_active') and current_rate == target_rate:
        # Modbus-Realität prüfen (Defense-in-Depth):
        # Falls jemand/etwas den Modbus zwischenzeitlich zurückgesetzt hat,
        # muss die Rate erneut geschrieben werden.
        modbus = inverter.get_modbus_status()
        if modbus and modbus.get('storctl_mod', 0) == 0:
            LOG.warning(f"⚠ State={target_rate}% aber Modbus=AUTO — setze erneut")
            # Nicht return → fällt durch zum Rate-Setzen
        else:
            LOG.info(f"  ≡ Abend-Algo: {phase} — bereits auf {target_rate}%")
            return

    # → RATE SETZEN
    LOG.info(f"── Abend-Algo: {phase} — Entladerate auf {target_rate}% ──")

    # NUR Entladerate begrenzen — Laden bleibt IMMER erlaubt!
    # Bug-Fix 2026-02-27: hold_battery() blockierte auch Laden → SOC-Deadlock
    # bei SOC < kritisch_soc (Batterie konnte nie über 10% laden).
    # BYD BMS schafft nur ~500W Not-Ladung im Hold-Modus.
    ok = inverter.set_discharge_rate(target_rate)

    if ok:
        old_rate = current_rate if state.get('evening_rate_active') else 'auto'
        state['evening_rate_active'] = True
        state['evening_rate_percent'] = target_rate

        LOG.info(f"  ✓ Entladerate: {old_rate}→{target_rate}% ({phase})")
        log_action('evening_limit', 'discharge_rate', old_rate, target_rate,
                   f"{phase}, SOC={soc:.0f}%" if soc else phase)
    else:
        LOG.error(f"  ✗ Entladerate setzen fehlgeschlagen!")


# ═══════════════════════════════════════════════════════════════
# ZELLAUSGLEICH (prognosegesteuert)
# ═══════════════════════════════════════════════════════════════

def _check_balancing(cfg, state, strategy, inverter, soc):
    """Prüfe ob heute Zellausgleich durchgeführt werden soll."""
    bal = cfg.get('zellausgleich', {})
    if not bal.get('aktiv', False):
        return False

    # Bereits heute Balancing gestartet?
    if state.get('balancing_active'):
        return False  # Wird am Folgetag beim Tages-Reset beendet

    # Letzter Ausgleich
    last_str = state.get('last_balancing') or bal.get('letzter_ausgleich')
    days_since = 999
    if last_str:
        try:
            last_date = datetime.strptime(last_str, '%Y-%m-%d').date()
            days_since = (date.today() - last_date).days
        except Exception:
            pass

    # Schon diesen Monat gemacht?
    if last_str:
        try:
            last_date = datetime.strptime(last_str, '%Y-%m-%d').date()
            if last_date.year == date.today().year and last_date.month == date.today().month:
                return False  # Diesen Monat schon erledigt
        except Exception:
            pass

    # Schwelle bestimmen
    min_kwh = bal.get('min_prognose_kwh', 25.0)
    max_tage = bal.get('max_tage_ohne_ausgleich', 45)
    spaetester_tag = bal.get('spaetester_tag', 28)
    notfall_kwh = bal.get('notfall_min_prognose_kwh', 15.0)

    current_day = date.today().day
    threshold = min_kwh

    # Schwelle absenken wenn spät im Monat oder lange her
    if current_day > spaetester_tag or days_since > 35:
        threshold = notfall_kwh
        LOG.info(f"  Zellausgleich: Abgesenkte Schwelle {notfall_kwh} kWh "
                 f"(Tag {current_day}, {days_since} Tage seit letztem)")

    forecast_kwh = strategy.get('expected_kwh', 0)

    if forecast_kwh < threshold:
        LOG.info(f"  Zellausgleich: Prognose {forecast_kwh:.0f} kWh < "
                 f"Schwelle {threshold:.0f} kWh — warte auf besseren Tag")
        return False

    # → ZELLAUSGLEICH AUSLÖSEN
    LOG.info(f"  ★ ZELLAUSGLEICH: Prognose {forecast_kwh:.0f} kWh ≥ {threshold:.0f} kWh, "
             f"{days_since} Tage seit letztem")

    bal_min = bal.get('soc_min_waehrend', 5)
    bal_max = bal.get('soc_max_waehrend', 100)
    bal_mode = bal.get('modus', 'auto')

    ok1 = inverter.set_soc_min(bal_min)
    ok2 = inverter.set_soc_max(bal_max)
    ok3 = inverter.set_soc_mode(bal_mode) if bal_mode == 'auto' else True
    ok4 = inverter.set_auto_modbus()  # Keine Lade-/Entladelimits

    if ok1 and ok2 and ok3 and ok4:
        state['balancing_active'] = True
        state['morning_done'] = True
        state['afternoon_done'] = True
        state['last_balancing'] = date.today().isoformat()

        reason = (f"Zellausgleich: Prognose {forecast_kwh:.0f} kWh, "
                  f"Modus={bal_mode}, SOC {bal_min}%–{bal_max}%")
        LOG.info(f"  ✓ {reason}")
        log_action('balancing_start', 'soc_mode', None, None,
                   reason, forecast_kwh, strategy.get('cloud_cover_avg'), soc)

        # letzter_ausgleich auch in Config persistieren
        _update_config_balancing_date()
        save_state(state)
        return True
    else:
        LOG.error("  ✗ Zellausgleich konnte nicht aktiviert werden!")
        return False


def _update_config_balancing_date():
    """Aktualisiere letzter_ausgleich in battery_control.json."""
    if _DRY_RUN:
        LOG.debug("[DRY RUN] Würde letzter_ausgleich in Config aktualisieren")
        return
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        cfg['zellausgleich']['letzter_ausgleich'] = date.today().isoformat()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        LOG.warning(f"Config-Update fehlgeschlagen: {e}")


# ═══════════════════════════════════════════════════════════════
# KONSISTENZ-PRÜFUNG
# ═══════════════════════════════════════════════════════════════

def _verify_consistency(cfg, state, inverter, current_hour, strategy=None):
    """Prüfe ob der Inverter-Zustand mit dem State übereinstimmt.

    Erkennt und korrigiert Inkonsistenzen, z.B.:
      - Modbus-Limits die während Tag-Phase noch aktiv sind
      - SOC-Werte die nicht dem erwarteten Zustand entsprechen
      - State-File das nicht zur Inverter-Realität passt

    ★ Respektiert das Morgen-Entladefenster: Wenn SOC_MIN=5% während
      des Morgen-Fensters gesetzt ist, wird NICHT auf Komfort korrigiert.

    Wird bei JEDEM Scheduler-Lauf ausgeführt (Kosten: 1× Modbus-Read).
    """
    if strategy is None:
        strategy = {}
    zeit_cfg = cfg.get('zeitsteuerung', {})
    grenzen = cfg.get('soc_grenzen', {})
    nacht_bis = zeit_cfg.get('nacht_entladelimit_bis', 6)
    abend_ab = zeit_cfg.get('abend_entladelimit_ab', 15)
    fixes = 0
    settings = None  # Wird ggf. vom SOC_MIN-Block gesetzt und vom SOC_MAX-Block wiederverwendet

    # --- Modbus-Konsistenz: Tag-Phase ohne Limits? ---
    if nacht_bis <= current_hour < abend_ab:
        # Tag-Phase: Es sollten KEINE Modbus-Limits aktiv sein
        # (außer Zellausgleich oder wenn morning rate aktiv)
        if not state.get('balancing_active') and not state.get('evening_rate_active'):
            modbus = inverter.get_modbus_status()
            if modbus and modbus.get('storctl_mod', 0) != 0:
                storctl = modbus['storctl_mod']
                LOG.warning(f"⚠ Konsistenz: Tag-Phase aber StorCtl_Mod="
                            f"{storctl} — korrigiere auf AUTO")
                ok = inverter.set_auto_modbus()
                if ok:
                    fixes += 1
                    log_action('consistency_fix', 'storctl_mod', storctl, 0,
                               'Tag-Phase: Modbus-Limit war fälschlich aktiv')

    # --- SOC-Konsistenz: Morning nicht gelaufen → SOC_MIN = Komfort? ---
    # ★ WICHTIG: Nur korrigieren wenn wir NICHT im Morgen-Entladefenster
    #   sind!  Während des Fensters kann die Automation-Engine oder der
    #   Benutzer SOC_MIN absichtlich auf 5% gesetzt haben.  Eine
    #   "Korrektur" auf 25% würde die Morgen-Entladung verhindern!
    morgen_cfg_kons = cfg.get('morgen_algorithmus', {})
    sunrise_h_kons = strategy.get('sunrise_hour', 7.5)
    # ★ Morgen-Fenster = Sonnenaufgang bis Sonnenaufgang + X Stunden
    # Kein fester Startpunkt mehr (war 5:00) — Sunrise ist frühester Start.
    morning_start_h = sunrise_h_kons
    morning_end_h = sunrise_h_kons + morgen_cfg_kons.get('fenster_stunden_nach_sunrise', 3)
    im_morgen_fenster = morning_start_h <= current_hour <= morning_end_h

    if not state.get('morning_done') and not state.get('balancing_active'):
        settings = inverter.get_current_settings()
        if settings:
            expected_min = grenzen.get('komfort_min', 25)
            actual_min = settings.get('soc_min')
            if actual_min is not None and actual_min != expected_min:
                if im_morgen_fenster:
                    # Im Morgen-Fenster: SOC_MIN=5% ist GEWOLLT (Entladung!)
                    # Nicht korrigieren, sondern loggen und respektieren.
                    LOG.info(f"ℹ Konsistenz: SOC_MIN={actual_min}% ≠ {expected_min}% "
                             f"— aber im Morgen-Fenster ({morning_start_h:.0f}–"
                             f"{morning_end_h:.1f}h), NICHT korrigiert (Entladung gewollt)")
                else:
                    LOG.warning(f"⚠ Konsistenz: SOC_MIN={actual_min}% "
                                f"erwartet {expected_min}% — korrigiere")
                    ok = inverter.set_soc_min(expected_min)
                    if ok:
                        fixes += 1
                        log_action('consistency_fix', 'soc_min',
                                   actual_min, expected_min,
                                   'SOC_MIN ≠ Komfort-Wert (morning noch nicht gelaufen)')

    # --- SOC-Konsistenz: Afternoon nicht gelaufen → SOC_MAX prüfen ---
    # ★ RICHTUNGSLOGIK: SOC_MAX höher als Komfort = MEHR Ladekapazität
    #   = immer sicher → NICHT abwärts korrigieren!
    #   SOC_MAX tiefer als Komfort = Batterie eingeschränkt → korrigieren.
    #   Komfort-Reset am Tagesanfang handhabt den Reset auf 75%.
    if not state.get('afternoon_done') and not state.get('balancing_active'):
        settings = inverter.get_current_settings() if fixes == 0 else settings
        if not settings:
            settings = inverter.get_current_settings()
        if settings:
            expected_max = grenzen.get('komfort_max', 75)
            actual_max = settings.get('soc_max')
            if actual_max is not None and actual_max != expected_max:
                if actual_max > expected_max:
                    # Mehr Kapazität als Komfort → sicher, NICHT korrigieren
                    LOG.info(f"ℹ Konsistenz: SOC_MAX={actual_max}% > Komfort "
                             f"{expected_max}% — nicht korrigiert "
                             f"(mehr Ladekapazität ist sicher)")
                else:
                    # Weniger Kapazität als Komfort → eingeschränkt, korrigieren
                    LOG.warning(f"⚠ Konsistenz: SOC_MAX={actual_max}% "
                                f"< Komfort {expected_max}% — korrigiere hoch")
                    ok = inverter.set_soc_max(expected_max)
                    if ok:
                        fixes += 1
                        log_action('consistency_fix', 'soc_max',
                                   actual_max, expected_max,
                                   'SOC_MAX unter Komfort-Wert — korrigiert hoch')

    if fixes > 0:
        LOG.info(f"Konsistenz-Prüfung: {fixes} Korrektur(en) durchgeführt")

    return fixes


# ═══════════════════════════════════════════════════════════════
# KOMFORT-DEFAULTS
# ═══════════════════════════════════════════════════════════════

def _apply_comfort_defaults(cfg, state, inverter):
    """Setze SOC-Grenzen + Modbus auf den konfigurierten Komfort-Bereich.

    Wird aufgerufen bei:
      - Tages-Reset (neuer Tag)
      - Ende Zellausgleich
      - Manueller --reset

    Setzt ALLES zurück: HTTP-API (SOC_MIN/MAX/MODE) + Modbus (StorCtl_Mod=0).
    """
    grenzen = cfg['soc_grenzen']
    soc_min = grenzen['komfort_min']    # default 25%
    soc_max = grenzen['komfort_max']    # default 75%

    LOG.info(f"Komfort-Defaults: SOC_MIN={soc_min}%, SOC_MAX={soc_max}%, "
             f"Modbus=AUTO")

    ok1 = inverter.set_soc_min(soc_min)
    ok2 = inverter.set_soc_max(soc_max)
    ok3 = inverter.set_soc_mode('manual')
    ok4 = inverter.set_auto_modbus()  # ★ Auch Modbus-Limits aufheben!

    # State bereinigen
    state['evening_rate_active'] = False
    state['evening_rate_percent'] = None

    if not (ok1 and ok2 and ok3 and ok4):
        LOG.error("⚠ Komfort-Defaults teilweise fehlgeschlagen! "
                  f"API: min={ok1} max={ok2} mode={ok3}, Modbus={ok4}")

    log_action('comfort_reset', None, None, None,
               f"Komfort-Bereich: SOC {soc_min}%–{soc_max}%, Modbus=AUTO")


# ═══════════════════════════════════════════════════════════════
# STATUS-ANZEIGE
# ═══════════════════════════════════════════════════════════════

def _print_status(cfg, state, strategy, soc):
    """Zeige aktuellen Status übersichtlich an."""
    now = datetime.now()
    grenzen = cfg['soc_grenzen']

    print("=" * 65)
    print("  BATTERIE-SCHEDULER — Status")
    print("=" * 65)
    print(f"\n  Zeitpunkt:       {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Komfort-Bereich: SOC {grenzen['komfort_min']}%–{grenzen['komfort_max']}%")
    print(f"  Stress-Bereich:  SOC {grenzen['stress_min']}%–{grenzen['stress_max']}%")
    print(f"  SOC aktuell:     {soc:.1f}%" if soc else "  SOC aktuell:     N/A")

    print(f"\n  Prognose:")
    print(f"    PV-Ertrag:     {strategy.get('expected_kwh', 0):.0f} kWh")
    print(f"    Qualität:      {strategy.get('quality', '?')}")
    print(f"    Bewölkung Ø:   {strategy.get('cloud_cover_avg', '?')}%")
    print(f"    Sunrise:       {strategy.get('sunrise', '?')}")
    print(f"    Sunset:        {strategy.get('sunset', '?')}")

    print(f"\n  Tages-Flags:")
    print(f"    morning_done:     {state.get('morning_done', False)}")
    print(f"    afternoon_done:   {state.get('afternoon_done', False)}")
    print(f"    manual_override:  {state.get('manual_override', False)}")
    print(f"    balancing_active: {state.get('balancing_active', False)}")

    last_bal = state.get('last_balancing') or cfg.get('zellausgleich', {}).get('letzter_ausgleich')
    print(f"    letzter Ausgl.:   {last_bal or 'nie'}")

    # Letzter Log-Eintrag
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = db.execute("""
                SELECT ts, action, reason FROM battery_control_log
                ORDER BY ts DESC LIMIT 1
            """).fetchone()
            if row:
                ts = datetime.fromtimestamp(row[0])
                print(f"\n  Letzter Log-Eintrag:")
                print(f"    {ts.strftime('%Y-%m-%d %H:%M')} — {row[1]}: {row[2]}")
    except Exception:
        pass

    print("\n" + "=" * 65)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Batterie-Scheduler — Automatische SOC-Steuerung',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--status', action='store_true',
                        help='Nur Status anzeigen, keine Aktionen')
    parser.add_argument('--dry-run', action='store_true',
                        help='Testlauf ohne Schreibzugriffe')
    parser.add_argument('--force-morning', action='store_true',
                        help='Morgen-Öffnung erzwingen')
    parser.add_argument('--force-afternoon', action='store_true',
                        help='Nachmittag-Erhöhung erzwingen')
    parser.add_argument('--reset', action='store_true',
                        help='Auf Komfort-Defaults zurücksetzen')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Debug-Ausgabe')

    args = parser.parse_args()

    # Logging konfigurieren
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        level=level
    )

    global _DRY_RUN
    if args.dry_run:
        _DRY_RUN = True
        LOG.info("═══ DRY RUN — keine Änderungen am Inverter ═══")

    if args.reset:
        cfg = load_config()
        if cfg:
            inverter = InverterControl(args.dry_run)
            state = load_state()
            _apply_comfort_defaults(cfg, state, inverter)
            state['manual_override'] = False
            state['morning_done'] = False
            state['afternoon_done'] = False
            save_state(state)
            inverter.close()
            LOG.info("Reset auf Komfort-Defaults durchgeführt")
        return

    try:
        run_scheduler(args)
    except Exception as e:
        LOG.error(f"Unbehandelter Fehler: {e}", exc_info=True)
        # Fail-Safe: Nicht auf radikale Werte stellen
        log_action('error', None, None, None, str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
