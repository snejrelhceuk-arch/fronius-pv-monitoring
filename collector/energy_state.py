"""
collector.energy_state — Persistente Energie-Akkumulatoren.

Wird vom Poller bei jedem Zyklus inkrementiert und alle 60s in
energy_state-Tabelle abgelegt. Das Dict-Format ist bewusst NICHT
in eine Dataclass umgewandelt (haette JSON-Persist gebrochen).
"""

import logging
import threading

from db_utils import get_db_connection

energy_state = {
    'W_PV_F1': 0.0,
    'W_PV_F2': 0.0,
    'W_PV_F3': 0.0,
    'W_WR_F2_consumption': 0.0,  # Naechtlicher WR-Verbrauch F2
    'W_WR_F3_consumption': 0.0,  # Naechtlicher WR-Verbrauch F3
    'W_Imp_Grid': 0.0,
    'W_Exp_Grid': 0.0,
    'W_Batt_charge': 0.0,
    'W_Batt_discharge': 0.0,
    'last_poll_time': None,
}
energy_lock = threading.Lock()


def restore_energy_state():
    """Lade Energie-Akkumulatoren aus DB."""
    try:
        conn = get_db_connection()
        if not conn:
            return
        c = conn.cursor()
        c.execute("SELECT key, value FROM energy_state")
        rows = c.fetchall()
        conn.close()

        with energy_lock:
            for key, value in rows:
                if key in energy_state:
                    energy_state[key] = float(value)

        print(f"[INFO] Energie-State wiederhergestellt: Batt Charge={energy_state['W_Batt_charge']:.1f}Wh")
    except Exception as e:
        print(f"[WARN] Konnte Energy-State nicht laden: {e}")


def save_energy_state():
    """Speichere Energie-Akkumulatoren in DB (mit kurzem Timeout)."""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return
        c = conn.cursor()

        with energy_lock:
            for key in ['W_PV_F1', 'W_PV_F2', 'W_PV_F3', 'W_WR_F2_consumption', 'W_WR_F3_consumption',
                        'W_Imp_Grid', 'W_Exp_Grid', 'W_Batt_charge', 'W_Batt_discharge']:
                c.execute("INSERT OR REPLACE INTO energy_state (key, value) VALUES (?, ?)",
                          (key, energy_state[key]))

        conn.commit()
    except Exception as e:
        logging.error(f"Energy State Save Error: {e}")
    finally:
        if conn:
            conn.close()
