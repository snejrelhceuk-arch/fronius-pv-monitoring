"""Regressionstests für die Akku-Belastungs-Analyse.

Stress (Haltbarkeit): SOC > stress_high (90 %) / < stress_low (10 %).
Außerhalb Komfort: SOC > komfort_max (80 %) / < komfort_min (20 %) — schließt
die Stresszeit ein. Bänder kommen aus battery_control.json (soc_bands); die
Tests übergeben sie explizit, um unabhängig von der Live-Config zu sein.
"""

from routes.verbraucher import (
    SOC_STRESS_HIGH_PCT,
    SOC_STRESS_LOW_PCT,
    _aggregate_soc_buckets,
    _summarize_soc_points,
)

BANDS = {'komfort_min': 20, 'komfort_max': 80, 'stress_low': 10, 'stress_high': 90}


def test_default_thresholds_are_high90_low10():
    assert SOC_STRESS_HIGH_PCT == 90
    assert SOC_STRESS_LOW_PCT == 10


def test_summarize_infers_interval_and_counts_stress_and_komfort():
    points = [(0, 96.0), (600, 97.0), (1200, 8.0)]  # Intervall-Median = 600 s = 10 min

    result = _summarize_soc_points(points, bands=BANDS)

    assert result['high_stress_minutes'] == 20.0  # 96 + 97 > 90 -> 2 x 10 min
    assert result['low_stress_minutes'] == 10.0   # 8 < 10 -> 10 min
    # Ausserhalb Komfort schliesst Stress ein: 96,97 > 80 und 8 < 20.
    assert result['komfort_high_minutes'] == 20.0
    assert result['komfort_low_minutes'] == 10.0
    assert result['komfort_outside_minutes'] == 30.0
    assert result['day_max'] == 97.0
    assert result['day_min'] == 8.0
    assert result['current'] == 8.0


def test_summarize_respects_explicit_interval():
    points = [(0, 99.0), (60, 50.0), (120, 5.0)]

    result = _summarize_soc_points(points, interval_s=60, bands=BANDS)

    assert result['high_stress_minutes'] == 1.0
    assert result['low_stress_minutes'] == 1.0
    # 50 liegt im Komfortband -> nur die Extremwerte zaehlen ausserhalb Komfort.
    assert result['komfort_outside_minutes'] == 2.0


def test_summarize_excludes_stress_boundaries_but_komfort_counts():
    points = [(0, 90.0), (60, 10.0)]

    result = _summarize_soc_points(points, interval_s=60, bands=BANDS)

    # Genau auf der Stressgrenze -> kein Stress.
    assert result['high_stress_minutes'] == 0.0
    assert result['low_stress_minutes'] == 0.0
    # 90 > 80 und 10 < 20 -> ausserhalb Komfort.
    assert result['komfort_high_minutes'] == 1.0
    assert result['komfort_low_minutes'] == 1.0


def test_summarize_empty_returns_none():
    result = _summarize_soc_points([], bands=BANDS)

    assert result['current'] is None
    assert result['day_max'] is None
    assert result['high_stress_minutes'] == 0.0
    assert result['low_stress_minutes'] == 0.0
    assert result['komfort_high_minutes'] == 0.0
    assert result['komfort_low_minutes'] == 0.0


def test_aggregate_buckets_groups_max_min_stress_and_komfort():
    points = [
        (0, 99.0), (60, 40.0),
        (120, 5.0), (180, 8.0),
    ]

    def key_fn(ts):
        return 'A' if ts < 120 else 'B'

    buckets = _aggregate_soc_buckets(points, key_fn, interval_s=60, bands=BANDS)

    assert buckets['A']['high_min'] == 1.0
    assert buckets['A']['low_min'] == 0.0
    assert buckets['A']['komfort_high_min'] == 1.0   # 99 > 80
    assert buckets['A']['komfort_low_min'] == 0.0    # 40 im Komfortband
    assert buckets['A']['max'] == 99.0
    assert buckets['A']['min'] == 40.0
    assert buckets['B']['low_min'] == 2.0
    assert buckets['B']['high_min'] == 0.0
    assert buckets['B']['komfort_low_min'] == 2.0    # 5 und 8 < 20
