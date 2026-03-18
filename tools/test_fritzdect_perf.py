#!/usr/bin/env python3
"""
Fritz!DECT Performance-Test: 10s Polling-Sicherheit testen.

Führt 30 Abfragen mit 10s Intervall durch (~5 Minuten) und prüft:
  ✓ Request-Latenz (sollte <3s sein)
  ✓ Fehlerrate (sollte <5% sein)
  ✓ Power-Stabilität (keine >500W Sprünge ohne Grund)
  ✓ Fritz!Box Health (SSH-Latenz nicht >2x Baseline)

Nutzung:
  cd pv-system
  python3 tools/test_fritzdect_perf.py [--duration 300] [--interval 10]
"""

import sys
import json
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Projekt-Root hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent))

# Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
LOG = logging.getLogger('fritzdect_perf_test')

# ════════════════════════════════════════════════════════════════

def measure_ssh_latency() -> float:
    """SSH-Verbindung zur Fritz!Box testen (Roundtrip in ms)."""
    try:
        cfg_path = Path(__file__).parent.parent / 'config' / 'fritz_config.json'
        if not cfg_path.exists():
            return None
        
        with open(cfg_path) as f:
            cfg = json.load(f)
        
        fritz_ip = cfg.get('fritz_ip', '192.168.178.1')
        
        start = time.time()
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '2', fritz_ip],
            capture_output=True,
            timeout=5
        )
        latency_ms = (time.time() - start) * 1000
        
        if result.returncode == 0:
            return latency_ms
    except Exception as e:
        LOG.debug(f"SSH latency check: {e}")
    
    return None

def test_fritzdect_polling(duration_sec: int = 300, interval_sec: int = 10):
    """Starte Fritz!DECT Polling-Test über specified duration."""
    
    from automation.engine.collectors.data_collector import DataCollector
    from automation.engine.obs_state import ObsState
    
    LOG.info(f"═══ Fritz!DECT Performance-Test ═══")
    LOG.info(f"Duration: {duration_sec}s ({duration_sec//interval_sec} cycles)")
    LOG.info(f"Interval: {interval_sec}s")
    LOG.info("")
    
    # Baseline SSH-Latenz
    baseline_ssh_ms = measure_ssh_latency()
    if baseline_ssh_ms:
        LOG.info(f"📡 Baseline SSH-Latenz: {baseline_ssh_ms:.1f}ms")
    else:
        LOG.warning("⚠️  SSH-Latenz konnte nicht gemessen werden (ignorieren)")
    LOG.info("")
    
    dc = DataCollector()
    results = {
        'total_cycles': 0,
        'successful': 0,
        'failed': 0,
        'timeouts': 0,
        'latencies': [],  # [ms]
        'hp_power': [],   # [W]
        'klima_power': [], # [W]
    }
    
    start_time = time.time()
    cycle = 0
    
    try:
        while time.time() - start_time < duration_sec:
            cycle += 1
            results['total_cycles'] += 1
            
            cycle_start = time.time()
            attempt_start = time.time()
            
            try:
                obs = ObsState()
                dc.collect(obs)  # Nur collect() aufrufen, nicht _collect_fritzdect() direkt
                
                # Nur Fritz!DECT Teil zeigen
                dc._collect_fritzdect(obs)
                
                latency_ms = (time.time() - attempt_start) * 1000
                results['latencies'].append(latency_ms)
                results['successful'] += 1
                
                # Leistungen sammeln
                if obs.heizpatrone_power_w is not None:
                    results['hp_power'].append(obs.heizpatrone_power_w)
                if obs.klima_power_w is not None:
                    results['klima_power'].append(obs.klima_power_w)
                
                LOG.info(
                    f"✓ Cycle {cycle:2d}: "
                    f"HP={obs.heizpatrone_power_w:6.1f}W "
                    f"Klima={obs.klima_power_w:6.1f}W "
                    f"(latency: {latency_ms:5.0f}ms)"
                )
                
            except TimeoutError as e:
                results['timeouts'] += 1
                results['failed'] += 1
                LOG.error(f"✗ Cycle {cycle:2d}: TIMEOUT — {e}")
            except Exception as e:
                results['failed'] += 1
                LOG.error(f"✗ Cycle {cycle:2d}: ERROR — {e}")
            
            # Sleep bis zum nächsten Zyklus
            cycle_elapsed = time.time() - cycle_start
            sleep_time = max(0, interval_sec - cycle_elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    except KeyboardInterrupt:
        LOG.info("\n⏹  Test unterbrochen durch Benutzer")
    
    # Statistik-Auswertung
    LOG.info("")
    LOG.info("═══ ERGEBNISSE ═══")
    
    elapsed = time.time() - start_time
    success_rate = (results['successful'] / results['total_cycles'] * 100) if results['total_cycles'] > 0 else 0
    
    LOG.info(f"Gesamtdauer: {elapsed:.1f}s")
    LOG.info(f"Erfolgreiche Abfragen: {results['successful']}/{results['total_cycles']} ({success_rate:.1f}%)")
    LOG.info(f"Fehlerquote: {results['failed']}/{results['total_cycles']} ({100-success_rate:.1f}%)")
    if results['timeouts'] > 0:
        LOG.info(f"  - davon Timeouts: {results['timeouts']}")
    
    if results['latencies']:
        latencies = results['latencies']
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        min_lat = min(latencies)
        
        LOG.info("")
        LOG.info(f"Request-Latenz (ms):")
        LOG.info(f"  Min:    {min_lat:6.1f}")
        LOG.info(f"  Avg:    {avg_lat:6.1f}")
        LOG.info(f"  Max:    {max_lat:6.1f}")
        
        if max_lat > 10000:
            LOG.warning(f"⚠️  Max-Latenz >10s erkannt! Fritz!Box könnte überlastet sein.")
        elif max_lat > 3000:
            LOG.warning(f"⚠️  Einige Requests >3s. Eventuell 10s Intervall zu aggressiv.")
        else:
            LOG.info("✓ Alle Latenz-Checks bestanden")
    
    # Power-Stabilität
    if results['hp_power'] and len(results['hp_power']) > 1:
        LOG.info("")
        LOG.info(f"Heizpatrone Power-Stabilität:")
        hp_min = min(results['hp_power'])
        hp_max = max(results['hp_power'])
        hp_avg = sum(results['hp_power']) / len(results['hp_power'])
        LOG.info(f"  Min:    {hp_min:6.1f}W")
        LOG.info(f"  Avg:    {hp_avg:6.1f}W")
        LOG.info(f"  Max:    {hp_max:6.1f}W")
        LOG.info(f"  Range:  {hp_max - hp_min:6.1f}W")
        
        # Starke Sprünge = Fehler?
        if (hp_max - hp_min) > 500 and hp_max > 200:
            LOG.warning(f"⚠️  Große Power-Schwankungen ({hp_max - hp_min:.0f}W). Geräte instabil?")
    
    if results['klima_power'] and len(results['klima_power']) > 1:
        LOG.info("")
        LOG.info(f"Klimaanlage Power-Stabilität:")
        kl_min = min(results['klima_power'])
        kl_max = max(results['klima_power'])
        kl_avg = sum(results['klima_power']) / len(results['klima_power'])
        LOG.info(f"  Min:    {kl_min:6.1f}W")
        LOG.info(f"  Avg:    {kl_avg:6.1f}W")
        LOG.info(f"  Max:    {kl_max:6.1f}W")
        LOG.info(f"  Range:  {kl_max - kl_min:6.1f}W")
    
    # Health-Check
    LOG.info("")
    LOG.info("═══ SICHERHEITS-CHECKS ═══")
    
    if success_rate >= 95:
        LOG.info("✓ Fehlerrate <5%: BESTANDEN")
    elif success_rate >= 90:
        LOG.warning(f"⚠️  Fehlerrate {100-success_rate:.1f}%: Grenzwert beachten")
    else:
        LOG.error(f"✗ Fehlerrate {100-success_rate:.1f}%: ZU HOCH")
    
    if results['latencies'] and max(results['latencies']) < 5000:
        LOG.info("✓ Max-Latenz <5s: BESTANDEN")
    else:
        LOG.warning("⚠️  Timeouts oder zu lange Latenzen erkannt")
    
    current_ssh = measure_ssh_latency()
    if baseline_ssh_ms and current_ssh:
        ssh_ratio = current_ssh / baseline_ssh_ms
        if ssh_ratio < 2.0:
            LOG.info(f"✓ SSH-Latenz {current_ssh:.1f}ms (Ratio: {ssh_ratio:.2f}x): BESTANDEN")
        else:
            LOG.warning(f"⚠️  SSH-Latenz ist {ssh_ratio:.2f}x Baseline — Fritz!Box könnte überlastet sein")
    
    # EMPFEHLUNG
    LOG.info("")
    if success_rate >= 95 and (not results['latencies'] or max(results['latencies']) < 5000):
        LOG.info("🟢 EMPFEHLUNG: 10-Sekunden-Polling ist SICHER")
    elif success_rate >= 90:
        LOG.info("🟡 EMPFEHLUNG: 10-Sekunden-Polling ist OK, aber 20s wäre sicherer")
    else:
        LOG.info("🔴 EMPFEHLUNG: 10-Sekunden-Polling ist zu aggressiv, verwende 30s")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--duration', type=int, default=300,
                        help='Test-Dauer in Sekunden (default: 300 = 5 Min)')
    parser.add_argument('--interval', type=int, default=10,
                        help='Polling-Intervall in Sekunden (default: 10)')
    
    args = parser.parse_args()
    
    test_fritzdect_polling(duration_sec=args.duration, interval_sec=args.interval)
