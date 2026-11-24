import numpy as np

from detection import Config, evaluate

rng = np.random.default_rng(42)


def normal_series(n=120):
    latency = 0.08 + rng.normal(0, 0.004, n)  # ~80 ms p95, small noise
    errors = np.clip(rng.normal(0.002, 0.002, n), 0, None)
    return latency, errors


def test_normal_traffic_is_not_flagged():
    latency, errors = normal_series()
    result = evaluate(latency, errors)
    assert result.status == "ok"
    assert result.severity == "none"


def test_latency_spike_is_flagged():
    latency, errors = normal_series()
    latency[-5:] = 0.6  # p95 jumps to 600 ms
    result = evaluate(latency, errors)
    assert result.status == "anomaly"
    assert result.zscores["latency_p95"] > 4
    assert any("latency_p95" in r for r in result.reasons)


def test_error_spike_with_zero_baseline_is_flagged():
    latency, _ = normal_series()
    errors = np.zeros(len(latency))  # perfectly healthy before the fault
    errors[-5:] = 0.4
    result = evaluate(latency, errors)
    assert result.status == "anomaly"
    assert result.zscores["error_rate"] > 4


def test_combined_spike_is_critical():
    latency, errors = normal_series()
    latency[-5:] = 0.7
    errors[-5:] = 0.5
    result = evaluate(latency, errors)
    assert result.status == "anomaly"
    assert result.severity == "critical"
    assert result.iforest_flag


def test_not_enough_history():
    result = evaluate([0.08] * 10, [0.0] * 10)
    assert result.status == "insufficient_data"


def test_single_noisy_point_is_ignored():
    latency, errors = normal_series()
    latency[-3] = 0.5  # one blip; "now" is the median of the last 3 points
    result = evaluate(latency, errors, Config(z_threshold=6))
    assert result.status == "ok"


def test_zscore_only_mode_never_uses_forest_for_alerting():
    latency, errors = normal_series()
    result = evaluate(latency, errors, Config(method="zscore"))
    assert result.status == "ok"


def test_huge_spike_stays_critical_even_if_forest_disagrees():
    latency, errors = normal_series()
    latency[-5:] = 0.5
    # Simulate a long-running fault already inside the baseline
    latency[-25:-5] = 0.5
    result = evaluate(latency, errors)
    assert result.status == "anomaly"
    assert result.severity == "critical"
