"""Anomaly detection logic (pure functions, no network or web code).

Two methods are combined:
  1. Robust z-score: how far the latest value is from the recent baseline,
     measured with median / MAD so earlier spikes don't distort the baseline.
  2. Isolation Forest (scikit-learn): looks at latency and error rate together
     and flags points that are unusual as a pair.

Result: z-score breach => "warning". z-score breach that is also confirmed by
Isolation Forest, or is very large, => "critical". Isolation Forest alone never
raises an alert, which keeps false alarms low.
"""
from dataclasses import dataclass, field

import numpy as np
from sklearn.ensemble import IsolationForest

# Smallest "normal" variation per metric. Without this floor, a metric that is
# always 0 (like error rate) would make any tiny change look infinitely unusual.
MIN_SCALE = {"latency_p95": 0.005, "error_rate": 0.01}


@dataclass
class Config:
    z_threshold: float = 4.0       # robust z-score needed to raise a warning
    recent_points: int = 3         # "now" = median of this many latest points
    min_baseline_points: int = 40  # need this much history before detecting
    method: str = "both"           # "zscore", "iforest" or "both"


@dataclass
class Result:
    status: str                    # "ok", "anomaly" or "insufficient_data"
    severity: str = "none"         # "none", "warning" or "critical"
    zscores: dict = field(default_factory=dict)
    current: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    iforest_flag: bool = False
    reasons: list = field(default_factory=list)


def robust_zscore(baseline, value, min_scale):
    """Distance of `value` from the baseline median, in robust std units."""
    median = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - median)))
    scale = max(1.4826 * mad, min_scale)  # 1.4826 makes MAD comparable to std dev
    return (value - median) / scale, median


def evaluate(latency, error_rate, config=None):
    """Judge whether the newest points in two aligned series are anomalous.

    latency, error_rate: equal-length sequences, oldest first.
    """
    config = config or Config()
    latency = np.asarray(latency, dtype=float)
    error_rate = np.asarray(error_rate, dtype=float)
    n_recent = config.recent_points

    if len(latency) < config.min_baseline_points + n_recent:
        return Result(status="insufficient_data")

    series = {"latency_p95": latency, "error_rate": error_rate}
    result = Result(status="ok")

    # Method 1: robust z-score per metric (only upward spikes matter here)
    z_breach = []
    for name, values in series.items():
        baseline, recent = values[:-n_recent], values[-n_recent:]
        current = float(np.median(recent))  # median: one-off blips are ignored
        z, median = robust_zscore(baseline, current, MIN_SCALE[name])
        result.zscores[name] = round(z, 2)
        result.current[name] = round(current, 4)
        result.baseline[name] = round(median, 4)
        if z > config.z_threshold:
            z_breach.append(name)
            result.reasons.append(
                f"{name} is {current:.3f} vs normal {median:.3f} (z={z:.1f})"
            )

    # Method 2: Isolation Forest on (latency, error rate) pairs
    features = np.column_stack([latency, error_rate])
    forest = IsolationForest(n_estimators=100, contamination=0.02, random_state=0)
    forest.fit(features[:-n_recent])
    recent_point = np.median(features[-n_recent:], axis=0, keepdims=True)
    result.iforest_flag = bool(forest.predict(recent_point)[0] == -1)

    zscore_hit = bool(z_breach)
    if config.method == "zscore":
        anomalous = zscore_hit
    elif config.method == "iforest":
        anomalous = result.iforest_flag
    else:  # "both"
        anomalous = zscore_hit
    if config.method == "iforest" and result.iforest_flag:
        result.reasons.append("Isolation Forest flagged this (latency, error) pattern")

    if anomalous:
        result.status = "anomaly"
        # Critical = a clear z-score breach that is either confirmed by the forest
        # or very large (3x the threshold). The size rule keeps severity stable
        # during a long fault, when the forest's baseline starts absorbing it.
        very_large = max(result.zscores.values()) > 3 * config.z_threshold
        result.severity = (
            "critical" if (zscore_hit and (result.iforest_flag or very_large)) else "warning"
        )
    return result
