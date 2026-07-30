"""Regressionstests für die Akku-Stress-Analyse (SOC-Stressdauern >95 % / <10 %)."""

from routes.verbraucher import (
    SOC_STRESS_HIGH_PCT,
    SOC_STRESS_LOW_PCT,
    _aggregate_soc_buckets,
    _summarize_soc_points,
)


def test_thresholds_are_high95_low10():
    assert SOC_STRESS_HIGH_PCT == 95
    assert SOC_STRESS_LOW_PCT == 10


def test_summarize_infers_interval_and_counts_stress():
    points = [(0, 96.0), (600, 97.0), (1200, 8.0)]  # Intervall-Median = 600 s = 10 min

    result = _summarize_soc_points(points)

    assert result['high_stress_minutes'] == 20.0  # 96 + 97 > 95 → 2 × 10 min
    assert result['low_stress_minutes'] == 10.0   # 8 < 10 → 10 min
    assert result['day_max'] == 97.0
    assert result['day_min'] == 8.0
    assert result['current'] == 8.0


def test_summarize_respects_explicit_interval():
    points = [(0, 99.0), (60, 50.0), (120, 5.0)]

    result = _summarize_soc_points(points, interval_s=60)

    assert result['high_stress_minutes'] == 1.0
    assert result['low_stress_minutes'] == 1.0


def test_summarize_excludes_threshold_boundaries():
    points = [(0, 95.0), (60, 10.0)]

    result = _summarize_soc_points(points, interval_s=60)

    assert result['high_stress_minutes'] == 0.0
    assert result['low_stress_minutes'] == 0.0


def test_summarize_empty_returns_none():
    result = _summarize_soc_points([])

    assert result['current'] is None
    assert result['day_max'] is None
    assert result['high_stress_minutes'] == 0.0
    assert result['low_stress_minutes'] == 0.0


def test_aggregate_buckets_groups_max_min_and_stress():
    points = [
        (0, 99.0), (60, 40.0),
        (120, 5.0), (180, 8.0),
    ]

    def key_fn(ts):
        return 'A' if ts < 120 else 'B'

    buckets = _aggregate_soc_buckets(points, key_fn, interval_s=60)

    assert buckets['A']['high_min'] == 1.0
    assert buckets['A']['low_min'] == 0.0
    assert buckets['A']['max'] == 99.0
    assert buckets['A']['min'] == 40.0
    assert buckets['B']['low_min'] == 2.0
    assert buckets['B']['high_min'] == 0.0

