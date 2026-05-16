"""
collector.poller — Orchestrator: poll_once + poller_loop.

Bewusst behalten als zeitlich-deterministische Klammer um die anderen Module.
Die Reihenfolge der Operationen in poll_once() (Modbus-Read -> Energie-Integration
-> Save -> WP-Protokoll -> Cache -> Versions-Check) ist relevant und darf
nicht weiter zerlegt werden.
"""

import logging
import sqlite3
import threading
import time

import requests

import config
import db_init
import modbus_quellen

from db_utils import get_db_connection

from . import attachment_state as att
from . import buffer as buf
from . import energy_state as estate
from . import pid_lock
from . import wp_power_protocol as wp
from .modbus_client import RawModbusClient
from .sunspec import extract_device_data, read_device_data

# Logging-Konfiguration (frueher in modbus_v3.py)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.WARNING)

IP_ADDRESS = modbus_quellen.IP_ADDRESS
PORT = modbus_quellen.PORT
POLL_INTERVAL = config.POLL_INTERVAL
FRONIUS_API_BASE = config.FRONIUS_API_BASE

# Modbus-Verbindungs-Lock (eine Verbindung pro Poll-Zyklus)
modbus_lock = threading.Lock()

# SunSpec-Cache (fuer Web-API-Konsumenten)
sunspec_cache = {'devices': {}, 'last_update': 0}
sunspec_cache_lock = threading.Lock()

# Statische Common-Block-Daten je Device (Modell 1: nur 1x lesen)
static_device_data = {}
static_device_data_lock = threading.Lock()


def fetch_battery_api():
    """Hole Batterie U/I/T aus Fronius Storage API (zur Ueberwachung)."""
    try:
        url = f'{FRONIUS_API_BASE}/GetStorageRealtimeData.cgi?Scope=System'
        resp = requests.get(url, timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            controller = data.get('Body', {}).get('Data', {}).get('0', {}).get('Controller', {})
            return {
                'voltage': controller.get('Voltage_DC'),
                'current': controller.get('Current_DC'),
                'temperature': controller.get('Temperature_Cell'),
                'soc': controller.get('StateOfCharge_Relative'),
            }
    except Exception as e:
        logging.debug(f"Battery API fetch failed: {e}")
    return {'voltage': None, 'current': None, 'temperature': None, 'soc': None}


def poll_once():
    """Einmaliges Polling aller Geraete."""
    poll_start = time.time()
    client = None

    try:
        # WICHTIG: Verbindung NUR fuer diesen Lesezyklus oeffnen!
        # Damit Modbus-Bus fuer WR-Kommunikation (F1<->F2<->F3) frei bleibt
        with modbus_lock:
            client = RawModbusClient(IP_ADDRESS, port=PORT, timeout=5.0)
            if not client.connect():
                logging.error("Modbus Connect Failed")
                return False

        time.sleep(0.1)  # Kurze Stabilisierung

        POLL_DEVICES = [
            ('inverter',  modbus_quellen.INVERTER),
            ('prim_sm',   modbus_quellen.PRIM_SM_F1),
            ('sec_sm_F2', modbus_quellen.SEC_SM_F2),
            ('sec_sm_WP', modbus_quellen.SEC_SM_WP),
            ('sec_sm_F3', modbus_quellen.SEC_SM_F3),
        ]

        def _read_poll_devices(active_client):
            devices = {}
            missing_critical = []

            for dev_key, unit_id in POLL_DEVICES:
                skip_ids = [1] if dev_key in static_device_data else []
                models = read_device_data(active_client, unit_id, skip_ids)
                if dev_key == 'inverter' and not models:
                    logging.error("Inverter read failed")
                    return None, ['inverter']

                data = extract_device_data(models or [])
                if data.get('common'):
                    with static_device_data_lock:
                        static_device_data[dev_key] = data['common']

                # F1/F2 sind kritisch fuer Gesamtfluss + Aggregation.
                # Bei Firmware-Updates kann kurzzeitig Header-Read scheitern;
                # dann erzwingen wir einen Reconnect-Retry statt NULL-Zeilen.
                if dev_key in ('prim_sm', 'sec_sm_F2') and not data.get('meter_data'):
                    missing_critical.append(dev_key)

                devices[dev_key] = data

            return devices, missing_critical

        devices, missing_critical = _read_poll_devices(client)
        if devices is None:
            return False

        if missing_critical:
            trigger = ','.join(missing_critical)
            logging.warning(
                "Kritische SunSpec-Daten fehlen (%s) - Reconnect-Retry",
                trigger,
            )
            with modbus_lock:
                client.close()
                client = RawModbusClient(IP_ADDRESS, port=PORT, timeout=5.0)
                if not client.connect():
                    logging.error("Modbus Reconnect Failed nach fehlendem Header")
                    att.update_reconnect_event(trigger, success=False)
                    return False

            time.sleep(0.1)
            devices, missing_critical_retry = _read_poll_devices(client)
            if devices is None:
                att.update_reconnect_event(trigger, success=False)
                return False
            if missing_critical_retry:
                logging.error(
                    "Kritische SunSpec-Daten weiterhin fehlend (%s) - Poll verworfen",
                    ','.join(missing_critical_retry),
                )
                att.update_reconnect_event(trigger, success=False)
                return False
            att.update_reconnect_event(trigger, success=True)

        # Batterieleistung berechnen
        def get_val(dev_key, model_key, field_key, default=0):
            try:
                return devices.get(dev_key, {}).get(model_key, {}).get(field_key, {}).get('value', default)
            except Exception:
                return default

        dcw = get_val('inverter', 'inverter_data', 'DCW')
        dcw_1 = get_val('inverter', 'mppt', '1_DCW')
        dcw_2 = get_val('inverter', 'mppt', '2_DCW')
        p_batt = dcw - (dcw_1 + dcw_2)

        # Batterie U/I aus Fronius Storage API (zur Ueberwachung, nicht zur Berechnung)
        batt_api = fetch_battery_api()

        # Energie-Integration mit ECHTEM Zeitintervall
        # WICHTIG: Nicht POLL_INTERVAL (3s) annehmen! Realer Durchlauf variiert:
        # - CPU-Throttling bei Hitze: 3s -> 5-10s
        # - Modbus-Timeouts: bis 57s gemessen
        # - Fronius Firmware-Updates: Antwortzeiten aendern sich
        # - Parallele battery_control.py Modbus-Writes: +0.2-0.5s
        last_poll = estate.energy_state.get('last_poll_time')
        now = time.time()
        if last_poll and (now - last_poll) < 30:  # Max 30s, sonst war Pause/Restart
            dt_hours = (now - last_poll) / 3600.0
        else:
            dt_hours = POLL_INTERVAL / 3600.0  # Fallback beim ersten Poll / nach Restart

        with estate.energy_lock:
            # PV F1 (MPPT1 + MPPT2) - DC-Leistung mit Wirkungsgrad-Korrektur + WR-Eigenverbrauch
            # Typischer WR-Wirkungsgrad: 97% (DC->AC Verluste)
            # WR-Eigenverbrauch: 40W im Betrieb, 10W Standby (nachts)
            pv_f1_dc_w = dcw_1 + dcw_2
            wr_f1_consumption = 40 if pv_f1_dc_w > 50 else 10
            pv_f1_w = max(0, pv_f1_dc_w * 0.97 - wr_f1_consumption)
            estate.energy_state['W_PV_F1'] += pv_f1_w * dt_hours

            pv_f2_w = get_val('sec_sm_F2', 'meter_data', 'W')
            if pv_f2_w > 0:
                estate.energy_state['W_PV_F2'] += pv_f2_w * dt_hours
            else:
                estate.energy_state['W_WR_F2_consumption'] += abs(pv_f2_w) * dt_hours

            pv_f3_w = get_val('sec_sm_F3', 'meter_data', 'W')
            if pv_f3_w > 0:
                estate.energy_state['W_PV_F3'] += pv_f3_w * dt_hours
            else:
                estate.energy_state['W_WR_F3_consumption'] += abs(pv_f3_w) * dt_hours

            grid_w = get_val('prim_sm', 'meter_data', 'W')
            if grid_w > 0:
                estate.energy_state['W_Imp_Grid'] += grid_w * dt_hours
            else:
                estate.energy_state['W_Exp_Grid'] += abs(grid_w) * dt_hours

            # Batterie - gesteuert ueber ChaSt (Charge State)
            # ChaSt=3: Entladung, ChaSt=4: Ladung
            batt_charge_state = get_val('inverter', 'storage', 'ChaSt')
            w_batt = abs(p_batt) * dt_hours

            if batt_charge_state == 3:
                estate.energy_state['W_Batt_discharge'] += w_batt
            elif batt_charge_state == 4:
                estate.energy_state['W_Batt_charge'] += w_batt

            estate.energy_state['last_poll_time'] = time.time()

        # WICHTIG: Verbindung schliessen BEVOR Zeitmessung!
        # Damit Connect+Read+Close in t_poll_ms erfasst wird
        if client:
            with modbus_lock:
                client.close()

        poll_end = time.time()
        poll_dur_ms = int((poll_end - poll_start) * 1000)

        buf.save_raw_data(
            poll_end,
            devices['inverter'],
            devices['prim_sm'],
            devices['sec_sm_F2'],
            devices['sec_sm_F3'],
            devices['sec_sm_WP'],
            p_batt,
            poll_dur_ms,
            batt_api,
        )

        # Dauerhafter Nachweis fuer Netzbetreiber: minutliche WP-Leistungsmaxima.
        wp_power = get_val('sec_sm_WP', 'meter_data', 'W')
        wp.track_wp_power_protocol(poll_end, wp_power)

        with sunspec_cache_lock:
            sunspec_cache['devices'] = devices
            sunspec_cache['last_update'] = poll_end

        # Versionswechsel-Trigger: feste Vollpruefung + Discovery + Persistenz
        att.version_change_check_and_revalidate(client, devices)

        # Energy State alle 60s speichern
        if int(poll_end) % 60 < POLL_INTERVAL:
            estate.save_energy_state()

        # Erfolgreichen Poll im Attachment-State tracken (gedrosselt)
        att.update_poll_success()

        return True

    except Exception as e:
        logging.error(f"Poll Error: {e}")
        att.update_poll_error()
        return False

    finally:
        # Sicherheitsnetz: Falls Exception vor normalem close()
        if client:
            try:
                with modbus_lock:
                    if hasattr(client, 'sock') and client.sock:
                        client.close()
            except Exception:
                pass


def cleanup_db():
    """Loesche alte Daten gemaess Retention-Policies aus config.py."""
    conn = None
    try:
        now = time.time()

        conn = get_db_connection()
        if not conn:
            return
        c = conn.cursor()

        # Retention-Policies (monthly/yearly: PERMANENT)
        RETENTION = [
            ('raw_data',    config.RAW_DATA_RETENTION_DAYS),
            ('data_1min',   config.DATA_1MIN_RETENTION_DAYS),
            ('data_15min',  config.DATA_15MIN_RETENTION_DAYS),
            ('hourly_data', config.HOURLY_RETENTION_DAYS),
            ('daily_data',  config.DAILY_RETENTION_DAYS),
        ]

        deleted = {}
        for table, days in RETENTION:
            limit = now - (days * 86400)
            c.execute(f"DELETE FROM {table} WHERE ts < ?", (limit,))
            deleted[table] = c.rowcount

        conn.commit()

        # WAL-Checkpoint statt VACUUM (VACUUM blockiert auf tmpfs alles, ist sinnlos im RAM)
        total_deleted = sum(deleted.values())
        if total_deleted > 1000:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        if total_deleted > 0:
            parts = ', '.join(f"{t}={n}" for t, n in deleted.items() if n > 0)
            print(f"[INFO] Cleanup: {parts}")
    except Exception as e:
        logging.error(f"Cleanup Error: {e}")
    finally:
        if conn:
            conn.close()


def poller_loop():
    """Haupt-Polling-Schleife."""
    print("[INFO] Poller gestartet")

    # tmpfs-DB sicherstellen (NVMe -> RAM beim Boot)
    if not db_init.ensure_tmpfs_db():
        logging.error("tmpfs-DB konnte nicht initialisiert werden!")
        return

    # Persist-Thread: tmpfs -> SD-Card alle 5min (Crash-Sicherheit)
    db_init.start_persist_thread()

    # PID-File-Schutz: Nur eine Instanz erlaubt
    pid_lock.create_pid_file()

    # Persistierten Versions-/Anknuepfungszustand laden
    att.load_attachment_state()

    # Dauerprotokoll fuer Netzbetreiber aus vorhandenen 1min-Daten auffuellen.
    wp.backfill_wp_protocol_from_db()

    estate.restore_energy_state()

    poll_errors = 0
    last_flush = time.time()
    last_cleanup = time.time()

    while True:
        try:
            loop_start = time.time()

            if not poll_once():
                poll_errors += 1
                if poll_errors > 5:
                    logging.error("Zu viele Fehler hintereinander")
                    poll_errors = 0
                    time.sleep(10)  # Laengere Pause bei wiederholten Fehlern
            else:
                poll_errors = 0

            now = time.time()

            # Flush Buffer (SD Card Protection)
            if now - last_flush >= config.FLUSH_INTERVAL:
                t0 = time.time()
                buf.flush_buffer_to_db()
                flush_dur = time.time() - t0
                if flush_dur > 5.0:
                    logging.warning(f"[TIMING] flush_buffer_to_db dauerte {flush_dur:.1f}s!")
                last_flush = now

            # ENTFERNT: Aggregation aus Collector entfernt (verursacht 88s-Luecken in raw_data).
            # 15min + hourly Aggregation laufen via Cron:
            #   aggregate.py      -> 0,15,30,45 * * * *
            #   aggregate_1min.py -> * * * * * (inkl. Backfill)

            # Cleanup alle 1h
            if now - last_cleanup >= 3600:
                cleanup_db()
                last_cleanup = now

            # Loop-Timing ueberwachen (Luecken-Diagnose)
            loop_dur = time.time() - loop_start
            if loop_dur > 10.0:
                logging.warning(f"[TIMING] Polling-Loop dauerte {loop_dur:.1f}s (>10s)!")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("[INFO] Schreibe verbleibende Daten...")
            buf.flush_buffer_to_db()
            wp.flush_wp_power_protocol()
            break
        except Exception as e:
            logging.error(f"Poller Error: {e}")
            time.sleep(5)
