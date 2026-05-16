"""
collector.buffer — RAM-Buffer + Batch-Flush in raw_data.

Sammelt Poll-Records in einer deque und schreibt sie alle FLUSH_INTERVAL
Sekunden mit executemany() in die tmpfs-DB. Bei DB-Lock bleibt der Buffer
erhalten (Datenverlust-frei bis maxlen).
"""

import logging
import sqlite3
import threading
import time
from collections import deque

import config

DB_FILE = config.DB_PATH

ram_buffer = deque(maxlen=config.BUFFER_MAXLEN)
ram_buffer_lock = threading.Lock()


def save_raw_data(timestamp, inv_data, sm_netz_data, sm_f2_data, sm_f3_data, sm_wp_data, p_batt, poll_dur_ms, batt_api):
    """Speichere Rohdaten in RAM-Buffer (Batch-Write alle 60s).

    p_batt wird NICHT in raw_data gespeichert (rekonstruierbar aus
    P_DC_Inv - mppt_sum), sondern nur fuer energy_state-Akkumulation.
    batt_api liefert U_Batt_API / I_Batt_API zur Ueberwachung.
    """
    try:
        def val(data, key, default=None):
            v = data.get(key, {}).get('value')
            return v if v is not None else default

        def safe_pf(pf_val):
            """Power Factor: -100..100 -> 0.0..1.0, immer positiv."""
            if pf_val is None:
                return None
            return round(abs(pf_val) / 100.0, 3)

        inv = inv_data.get('inverter_data', {})
        mppt = inv_data.get('mppt', {})
        storage = inv_data.get('storage', {})
        sm_netz = sm_netz_data.get('meter_data', {})
        sm_f2 = sm_f2_data.get('meter_data', {})
        sm_f3 = sm_f3_data.get('meter_data', {})
        sm_wp = sm_wp_data.get('meter_data', {})

        record = (
            timestamp,
            # Inverter
            val(inv, 'AphA'), val(inv, 'AphB'), val(inv, 'AphC'),
            val(inv, 'PPVphAB'), val(inv, 'PPVphBC'), val(inv, 'PPVphCA'),
            val(inv, 'PhVphA'), val(inv, 'PhVphB'), val(inv, 'PhVphC'),
            val(inv, 'W'), val(inv, 'VA'), val(inv, 'VAr'), safe_pf(val(inv, 'PF')), val(inv, 'WH'),
            val(inv, 'DCW'),
            # MPPT
            val(mppt, '1_DCA'), val(mppt, '1_DCV'), val(mppt, '1_DCW'), val(mppt, '1_DCWH'),
            val(mppt, '2_DCA'), val(mppt, '2_DCV'), val(mppt, '2_DCW'), val(mppt, '2_DCWH'),
            # Battery
            val(storage, 'ChaState'), val(storage, 'ChaSt'),
            batt_api.get('voltage'), batt_api.get('current'),
            # SM Netz
            val(sm_netz, 'A'), val(sm_netz, 'AphA'), val(sm_netz, 'AphB'), val(sm_netz, 'AphC'),
            val(sm_netz, 'PhV'), val(sm_netz, 'PhVphA'), val(sm_netz, 'PhVphB'), val(sm_netz, 'PhVphC'),
            val(sm_netz, 'PPVphAB'), val(sm_netz, 'PPVphBC'), val(sm_netz, 'PPVphCA'),
            val(sm_netz, 'Hz'), val(sm_netz, 'W'), val(sm_netz, 'WphA'), val(sm_netz, 'WphB'), val(sm_netz, 'WphC'),
            val(sm_netz, 'VA'), val(sm_netz, 'VAR'), safe_pf(val(sm_netz, 'PF')),
            val(sm_netz, 'TotWhExp'), val(sm_netz, 'TotWhImp'),
            # SM F2
            val(sm_f2, 'W'), val(sm_f2, 'WphA'), val(sm_f2, 'WphB'), val(sm_f2, 'WphC'),
            val(sm_f2, 'VA'), val(sm_f2, 'VAR'), safe_pf(val(sm_f2, 'PF')),
            val(sm_f2, 'TotWhExp'), val(sm_f2, 'TotWhImp'),
            # SM WP
            val(sm_wp, 'W'), val(sm_wp, 'WphA'), val(sm_wp, 'WphB'), val(sm_wp, 'WphC'),
            val(sm_wp, 'VA'), val(sm_wp, 'VAR'), safe_pf(val(sm_wp, 'PF')),
            val(sm_wp, 'TotWhImp'),
            # SM F3
            val(sm_f3, 'W'), val(sm_f3, 'WphA'), val(sm_f3, 'WphB'), val(sm_f3, 'WphC'),
            val(sm_f3, 'VA'), val(sm_f3, 'VAR'), safe_pf(val(sm_f3, 'PF')),
            val(sm_f3, 'TotWhExp'), val(sm_f3, 'TotWhImp'),
            # Meta
            poll_dur_ms,
        )

        with ram_buffer_lock:
            if len(ram_buffer) >= ram_buffer.maxlen:
                logging.warning(f"RAM-Buffer voll ({len(ram_buffer)}/{ram_buffer.maxlen}) — aelteste Daten gehen verloren! DB-Flush haengt?")
            ram_buffer.append(record)

    except Exception as e:
        logging.error(f"Save Raw Data Error: {e}")


def flush_buffer_to_db():
    """Schreibt alle Daten aus RAM-Buffer in Datenbank (Batch-Write).

    Non-blocking: Bei DB-Lock schnell abbrechen, Daten bleiben im RAM-Buffer.
    """
    try:
        with ram_buffer_lock:
            if not ram_buffer:
                return
            records_to_write = list(ram_buffer)

        # Kurzer Timeout (1s): bei Lock durch Cron-Jobs schnell abbrechen,
        # statt 88s die Polling-Loop zu blockieren.
        t0 = time.time()
        conn = sqlite3.connect(DB_FILE, timeout=1.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')

        c = conn.cursor()

        c.executemany("""
            INSERT INTO raw_data (
                ts,
                -- Inverter
                I_L1_Inv, I_L2_Inv, I_L3_Inv,
                U_L1_L2_Inv, U_L2_L3_Inv, U_L3_L1_Inv,
                U_L1_N_Inv, U_L2_N_Inv, U_L3_N_Inv,
                P_AC_Inv, S_Inv, Q_Inv, PF_Inv, W_AC_Inv,
                P_DC_Inv,
                -- MPPT
                I_DC1, U_DC1, P_DC1, W_DC1,
                I_DC2, U_DC2, P_DC2, W_DC2,
                -- Battery
                SOC_Batt, ChaSt_Batt,
                U_Batt_API, I_Batt_API,
                -- SM Netz
                I_Netz, I_L1_Netz, I_L2_Netz, I_L3_Netz,
                U_Netz, U_L1_N_Netz, U_L2_N_Netz, U_L3_N_Netz,
                U_L1_L2_Netz, U_L2_L3_Netz, U_L3_L1_Netz,
                f_Netz, P_Netz, P_L1_Netz, P_L2_Netz, P_L3_Netz,
                S_Netz, Q_Netz, PF_Netz,
                W_Exp_Netz, W_Imp_Netz,
                -- SM F2
                P_F2, P_L1_F2, P_L2_F2, P_L3_F2,
                S_F2, Q_F2, PF_F2,
                W_Exp_F2, W_Imp_F2,
                -- SM WP
                P_WP, P_L1_WP, P_L2_WP, P_L3_WP,
                S_WP, Q_WP, PF_WP,
                W_Imp_WP,
                -- SM F3
                P_F3, P_L1_F3, P_L2_F3, P_L3_F3,
                S_F3, Q_F3, PF_F3,
                W_Exp_F3, W_Imp_F3,
                -- Meta
                t_poll_ms
            ) VALUES (
                ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?
            )
        """, records_to_write)

        conn.commit()
        conn.close()

        # Erst NACH erfolgreichem Write den Buffer leeren
        # (Audit 2026-02-27: vorher wurde vor dem Write geleert -> Datenverlust)
        with ram_buffer_lock:
            for _ in range(len(records_to_write)):
                if ram_buffer:
                    ram_buffer.popleft()

        logging.info(f"[FLUSH] {len(records_to_write)} Datensaetze in DB geschrieben")

    except Exception as e:
        logging.error(f"Buffer Flush Error: {e}")
