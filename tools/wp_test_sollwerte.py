#!/usr/bin/env python3
"""
Dimplex WP — Test-Script für Sollwert-Schreibzugriffe.

Setzt:
- Register 53 (ruecklauf_soll) auf 30°C
- Register 5047 (ww_soll) auf 50°C

Liest anschließend zurück und vergleicht.
"""
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
LOG = logging.getLogger(__name__)

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 19200
SLAVE_ID = 1


def _signed16(raw):
    return raw - 0x10000 if raw >= 0x8000 else raw


def test_sollwerte(ruecklauf_soll=30, ww_soll=50):
    """Schreibe Sollwerte und lese sie zurück."""
    try:
        from pymodbus.client import ModbusSerialClient
    except ImportError:
        LOG.error("pymodbus nicht installiert")
        return False

    client = ModbusSerialClient(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=2.0,
    )

    if not client.connect():
        LOG.error("Verbindung zu %s fehlgeschlagen", SERIAL_PORT)
        return False

    try:
        LOG.info("═" * 70)
        LOG.info("WP Sollwert-Test")
        LOG.info("═" * 70)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1. Aktuelle Werte lesen (VORHER)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        LOG.info("\n[1] VORHER — Aktuelle Werte auslesen...")
        
        rr = client.read_holding_registers(address=53, count=1, slave=SLAVE_ID)
        vorher_ruecklauf_soll = round(_signed16(rr.registers[0]) / 10.0, 1) if not rr.isError() else None
        
        rr = client.read_holding_registers(address=5047, count=1, slave=SLAVE_ID)
        vorher_ww_soll = _signed16(rr.registers[0]) if not rr.isError() else None
        
        LOG.info(f"  ruecklauf_soll (Reg. 53):  {vorher_ruecklauf_soll} °C")
        LOG.info(f"  ww_soll (Reg. 5047):        {vorher_ww_soll} °C")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. Neue Werte schreiben
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        LOG.info(f"\n[2] Neue Werte schreiben...")
        LOG.info(f"  → ruecklauf_soll = {ruecklauf_soll} °C (Reg. 53)")
        LOG.info(f"  → ww_soll = {ww_soll} °C (Reg. 5047)")
        
        # Register 53 in 0.1°C-Einheiten
        val_53 = int(ruecklauf_soll * 10)
        if val_53 < 0:
            val_53 += 0x10000
        
        rr = client.write_register(address=53, value=val_53, slave=SLAVE_ID)
        if rr.isError():
            LOG.error("  ✗ Schreib-Fehler Register 53")
            return False
        LOG.info("  ✓ Register 53 geschrieben")
        
        time.sleep(0.5)
        
        # Register 5047 in ganzen °C
        val_5047 = int(ww_soll)
        if val_5047 < 0:
            val_5047 += 0x10000
        
        rr = client.write_register(address=5047, value=val_5047, slave=SLAVE_ID)
        if rr.isError():
            LOG.error("  ✗ Schreib-Fehler Register 5047")
            return False
        LOG.info("  ✓ Register 5047 geschrieben")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3. Werte sofort zurücklesen (mit Wartezeit)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        time.sleep(1.0)
        LOG.info("\n[3] NACHHER — Geschriebene Werte überprüfen (1s Wartezeit)...")
        
        rr = client.read_holding_registers(address=53, count=1, slave=SLAVE_ID)
        nachher_ruecklauf_soll = round(_signed16(rr.registers[0]) / 10.0, 1) if not rr.isError() else None
        
        rr = client.read_holding_registers(address=5047, count=1, slave=SLAVE_ID)
        nachher_ww_soll = _signed16(rr.registers[0]) if not rr.isError() else None
        
        LOG.info(f"  ruecklauf_soll (Reg. 53):  {nachher_ruecklauf_soll} °C")
        LOG.info(f"  ww_soll (Reg. 5047):        {nachher_ww_soll} °C")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. Vergleich
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        LOG.info("\n[4] VERGLEICH:")
        
        if nachher_ruecklauf_soll == ruecklauf_soll:
            LOG.info(f"  ✓ ruecklauf_soll: {vorher_ruecklauf_soll} → {nachher_ruecklauf_soll} °C ✓")
        else:
            LOG.warning(f"  ✗ ruecklauf_soll: erwartet {ruecklauf_soll}, gelesen {nachher_ruecklauf_soll} °C")
        
        if nachher_ww_soll == ww_soll:
            LOG.info(f"  ✓ ww_soll: {vorher_ww_soll} → {nachher_ww_soll} °C ✓")
        else:
            LOG.warning(f"  ✗ ww_soll: erwartet {ww_soll}, gelesen {nachher_ww_soll} °C")

        LOG.info("\n" + "═" * 70)
        LOG.info("Test abgeschlossen. Prüfe am WP-Display, ob die Werte angekommen sind.")
        LOG.info("═" * 70)
        return True

    except Exception as e:
        LOG.error(f"Fehler: {e}", exc_info=True)
        return False
    finally:
        client.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='WP Sollwert-Test')
    parser.add_argument('--ruecklauf', type=int, default=30, help='Rücklauf-Soll [°C]')
    parser.add_argument('--ww', type=int, default=50, help='WW-Soll [°C]')
    args = parser.parse_args()
    
    success = test_sollwerte(ruecklauf_soll=args.ruecklauf, ww_soll=args.ww)
    sys.exit(0 if success else 1)
