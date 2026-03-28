#!/usr/bin/env python3
"""
Batch Re-Aggregation mit modifiziertem aggregate_1min.py
"""
import sys
import time as time_module

# Zeitstempel von Command Line
if len(sys.argv) > 1:
    target_ts = int(sys.argv[1])
else:
    print("Usage: batch_reaggregate.py <timestamp>")
    sys.exit(1)

# Monkey-patch time.time() um aggregate_1min zu täuschen
original_time = time_module.time
time_module.time = lambda: target_ts + 60  # +60 weil aggregate_1min -60 macht

# Import aggregate_1min NACH dem Patch
from aggregate_1min import aggregate_1min

# Führe Aggregation aus
aggregate_1min()

# Restore
time_module.time = original_time
