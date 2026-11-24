"""Detector service: polls Prometheus, runs anomaly detection, exposes a REST API.

Endpoints (used by the React dashboard):
  GET  /api/status          current health of every service
  GET  /api/anomalies       history of detected anomaly events
  POST /api/chaos/<service> inject a fault (demo helper)
  GET  /metrics             detector's own Prometheus metrics (shown in Grafana)
"""
import os
import threading
import time
from collections import deque

import requests
from flask import Flask, Response, jsonify, request
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge,
                               generate_latest)

from detection import Config, evaluate

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
SERVICES = [s for s in os.getenv("SERVICES", "orders,payments").split(",") if s]
# Where each service lives, used only by the demo fault-injection button
SERVICE_URLS = {s: os.getenv(f"{s.upper()}_URL", f"http://{s}:5000") for s in SERVICES}
# "orders>payments" means orders depends on (calls) payments
DEPENDENCIES = [d.split(">") for d in os.getenv("DEPENDENCIES", "").split(",") if ">" in d]
INTERVAL_S = float(os.getenv("DETECT_INTERVAL_S", "5"))
STEP_S = int(os.getenv("QUERY_STEP_S", "5"))
RATE_WINDOW = os.getenv("RATE_WINDOW", "30s")
HISTORY_MIN = int(os.getenv("BASELINE_MINUTES", "15"))
CONFIG = Config(
    z_threshold=float(os.getenv("Z_THRESHOLD", "4.0")),
    min_baseline_points=int(os.getenv("MIN_BASELINE_POINTS", "40")),
    method=os.getenv("DETECTOR_METHOD", "both"),
)

ANOMALY_GAUGE = Gauge("anomaly_detected", "1 if the service is anomalous", ["service"])
ZSCORE_GAUGE = Gauge("anomaly_zscore", "Latest robust z-score", ["service", "metric"])
EVENTS_TOTAL = Counter("anomaly_events_total", "Anomaly events detected", ["service", "severity"])

app = Flask(__name__)
_lock = threading.Lock()
_status = {s: {"service": s, "status": "starting"} for s in SERVICES}
_events = deque(maxlen=200)
_open_event = {}  # service -> event currently in progress
_next_id = 1


def _query_range(query, start, end):
    """Run a Prometheus range query; return {timestamp: value}, skipping NaN."""
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": STEP_S},
        timeout=5,
    )
    resp.raise_for_status()
    result = resp.json()["data"]["result"]
    if not result:
        return {}
    points = {}
    for ts, value in result[0]["values"]:
        value = float(value)
        if value == value:  # NaN != NaN
            points[ts] = value
    return points


def _fetch_series(service):
    """Get p95 latency and error rate for a service, aligned by timestamp."""
    end = time.time()
    start = end - HISTORY_MIN * 60
    latency_q = (
        f'histogram_quantile(0.95, sum by (le) (rate('
        f'http_request_duration_seconds_bucket{{service="{service}"}}[{RATE_WINDOW}])))'
    )
    # "or vector(0)": Prometheus returns no series at all when there are no 5xx
    # responses, so fall back to 0 to mean "zero errors" instead of "no data".
    error_q = (
        f'(sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[{RATE_WINDOW}]))'
        f' or vector(0))'
        f' / sum(rate(http_requests_total{{service="{service}"}}[{RATE_WINDOW}]))'
    )
    latency = _query_range(latency_q, start, end)
    errors = _query_range(error_q, start, end)
    common = sorted(set(latency) & set(errors))
    return common, [latency[t] for t in common], [errors[t] for t in common]


def _record_event(service, result):
    """Open, update or close the anomaly event for this service."""
    global _next_id
    now = time.time()
    event = _open_event.get(service)
    if result.status == "anomaly":
        if event is None:
            event = {"id": _next_id, "service": service, "started_at": now,
                     "ended_at": None, "severity": result.severity,
                     "reasons": result.reasons}
            _next_id += 1
            _open_event[service] = event
            _events.appendleft(event)
            EVENTS_TOTAL.labels(service, result.severity).inc()
        else:
            event["reasons"] = result.reasons
            if result.severity == "critical":
                event["severity"] = "critical"
    elif event is not None:
        event["ended_at"] = now
        del _open_event[service]


def detection_loop():
    while True:
        for service in SERVICES:
            try:
                _, latency, errors = _fetch_series(service)
                result = evaluate(latency, errors, CONFIG)
                with _lock:
                    _status[service] = {
                        "service": service,
                        "status": result.status,
                        "severity": result.severity,
                        "current": result.current,
                        "baseline": result.baseline,
                        "zscores": result.zscores,
                        "iforest_flag": result.iforest_flag,
                        "reasons": result.reasons,
                        "points": len(latency),
                        "required": CONFIG.min_baseline_points + CONFIG.recent_points,
                        "updated_at": time.time(),
                    }
                    _record_event(service, result)
                ANOMALY_GAUGE.labels(service).set(1 if result.status == "anomaly" else 0)
                for metric, z in result.zscores.items():
                    ZSCORE_GAUGE.labels(service, metric).set(z)
            except Exception as exc:  # keep the loop alive if Prometheus is down
                with _lock:
                    _status[service] = {"service": service, "status": "no_data",
                                        "error": str(exc)[:200]}
        time.sleep(INTERVAL_S)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/status")
def api_status():
    with _lock:
        return jsonify(list(_status.values()))


@app.get("/api/anomalies")
def api_anomalies():
    with _lock:
        return jsonify(list(_events))


@app.get("/api/topology")
def api_topology():
    return jsonify(services=SERVICES, dependencies=DEPENDENCIES)


@app.get("/api/faults")
def api_faults():
    out = {}
    for name, url in SERVICE_URLS.items():
        try:
            out[name] = requests.get(f"{url}/chaos", timeout=2).json()
        except Exception:
            out[name] = None
    return jsonify(out)


@app.get("/api/history/<service>")
def api_history(service):
    """Recent latency / error-rate readings, used for the charts."""
    if service not in SERVICES:
        return jsonify(error="unknown service"), 404
    ts, latency, errors = _fetch_series(service)
    return jsonify([{"t": t, "latency": l, "error": e} for t, l, e in zip(ts, latency, errors)])


@app.post("/api/chaos/<service>")
def api_chaos(service):
    """Demo helper: forward a fault-injection request to a service."""
    if service not in SERVICE_URLS:
        return jsonify(error="unknown service"), 404
    body = request.get_json(silent=True) or {}
    resp = requests.post(f"{SERVICE_URLS[service]}/chaos", json=body, timeout=3)
    return jsonify(resp.json()), resp.status_code


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def start_background_loop():
    threading.Thread(target=detection_loop, daemon=True).start()


if __name__ == "__main__":
    start_background_loop()
    app.run(host="0.0.0.0", port=8000, threaded=True)
