#!/usr/bin/env python3
"""
WP Hysterese-Register lesen und optional schreiben.

Liest Register 47 (HZ-Hysterese, Auflösung 0.1 K) und
Register 5045 (WW-Hysterese, Auflösung 1 K).

Lauf auf Pi4-Tech (direkter RS485-Zugang):
  python3 tools/wp_test_hysterese.py           # nur lesen
  python3 tools/wp_test_hysterese.py --apply   # +0.5K schreiben
"""
import sys
import time
import logging
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
LOG = logging.getLogger(__name__)

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 19200
SLAVE_ID = 1

REG_HZ_HYSTERESE = 47    # uint16, 0.1 K/LSB, Bereich 5..50 (= 0.5..5.0 K)
REG_WW_HYSTERESE = 5045  # uint16, 1 K/LSB, Bereich 2..15 K


def _read_hysterese(client) -> dict:
    hz_raw = ww_raw = None

    rr = client.read_holding_registers(address=REG_HZ_HYSTERESE, count=1, slave=SLAVE_ID)
    if not rr.isError():
        hz_raw = rr.registers[0]

    rr = client.read_holding_registers(address=REG_WW_HYSTERESE, count=1, slave=SLAVE_ID)
    if not rr.isError():
        ww_raw = rr.registers[0]

    return {
        'hz_raw': hz_raw,
        'hz_k': round(hz_raw / 10.0, 1) if hz_raw is not None else None,
        'ww_raw': ww_raw,
        'ww_k': float(ww_raw) if ww_raw is not None else None,
    }


def run(apply: bool = False):
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        LOG.error("pymodbus nicht installiert")
        return False

    client = ModbusSerialClient(
        port=SERIAL_PORT, baudrate=BAUD_RATE,
        bytesize=8, parity='N', stopbits=1, timeout=2.0,
    )
    if not client.connect():
        LOG.error("Verbindung zu %s fehlgeschlagen", SERIAL_PORT)
        return False

    try:
        LOG.info("═" * 60)
        LOG.info("WP Hysterese-Test — Reg 47 (HZ) + Reg 5045 (WW)")
        LOG.info("═" * 60)

        before = _read_hysterese(client)
        LOG.info("[VORHER]  HZ-Hysterese (Reg %d): raw=%s → %.1f K",
                 REG_HZ_HYSTERESE, before['hz_raw'], before['hz_k'] or 0)
        LOG.info("[VORHER]  WW-Hysterese (Reg %d): raw=%s → %s K",
                 REG_WW_HYSTERESE, before['ww_raw'], before['ww_k'])

        if not apply:
            LOG.info("\n(Nur Lesen — kein Schreiben. --apply für +0.5 K)")
            LOG.info("═" * 60)
            return True

        # ── Neue Zielwerte berechnen (je +0.5 K) ─────────────────
        if before['hz_raw'] is None or before['ww_raw'] is None:
            LOG.error("Lesen fehlgeschlagen — kein Schreiben")
            return False

        new_hz_raw = before['hz_raw'] + 5          # +0.5 K × 10
        new_ww_raw = before['ww_raw'] + 1          # +1 K (nächste ganze Zahl)

        # Grenzen einhalten
        new_hz_raw = max(5, min(50, new_hz_raw))   # 0.5..5.0 K
        new_ww_raw = max(2, min(15, new_ww_raw))   # 2..15 K

        LOG.info("\n[SCHREIBEN] HZ: %d → %d (%.1f → %.1f K)",
                 before['hz_raw'], new_hz_raw,
                 before['hz_k'], new_hz_raw / 10.0)
        LOG.info("[SCHREIBEN] WW: %d → %d (%s → %d K)",
                 before['ww_raw'], new_ww_raw, before['ww_k'], new_ww_raw)

        rr = client.write_register(address=REG_HZ_HYSTERESE, value=new_hz_raw, slave=SLAVE_ID)
        if rr.isError():
            LOG.error("Schreib-Fehler Reg %d: %s", REG_HZ_HYSTERESE, rr)
            return False
        LOG.info("  ✓ HZ-Hysterese geschrieben")
        time.sleep(0.5)

        rr = client.write_register(address=REG_WW_HYSTERESE, value=new_ww_raw, slave=SLAVE_ID)
        if rr.isError():
            LOG.error("Schreib-Fehler Reg %d: %s", REG_WW_HYSTERESE, rr)
            return False
        LOG.info("  ✓ WW-Hysterese geschrieben")
        time.sleep(1.0)

        # ── Rücklesen ─────────────────────────────────────────────
        after = _read_hysterese(client)
        LOG.info("\n[NACHHER] HZ-Hysterese (Reg %d): raw=%s → %.1f K",
                 REG_HZ_HYSTERESE, after['hz_raw'], after['hz_k'] or 0)
        LOG.info("[NACHHER] WW-Hysterese (Reg %d): raw=%s → %s K",
                 REG_WW_HYSTERESE, after['ww_raw'], after['ww_k'])

        hz_ok = after['hz_raw'] == new_hz_raw
        ww_ok = after['ww_raw'] == new_ww_raw
        LOG.info("\n[VERGLEICH] HZ: %s  WW: %s",
                 "✓ OK" if hz_ok else "✗ ABWEICHUNG", "✓ OK" if ww_ok else "✗ ABWEICHUNG")

        LOG.info("\nFür soc_param_matrix.json:")
        LOG.info("  hz_hysterese_k: %.1f", after['hz_k'] or new_hz_raw / 10.0)
        LOG.info("  ww_hysterese_k: %d", after['ww_k'] or new_ww_raw)
        LOG.info("═" * 60)
        return hz_ok and ww_ok

    except Exception as e:
        LOG.error("Fehler: %s", e, exc_info=True)
        return False
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='WP Hysterese lesen (+optionl schreiben)')
    parser.add_argument('--apply', action='store_true',
                        help='Hysterese-Werte um +0.5 K erhöhen und zurückschreiben')
    args = parser.parse_args()
    sys.exit(0 if run(apply=args.apply) else 1)
