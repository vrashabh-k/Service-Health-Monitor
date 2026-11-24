"""A small instrumented microservice used as the monitoring target.

The same code runs as two containers ("orders" and "payments").
`orders` calls `payments` over HTTP, so a fault in payments also
shows up as errors/latency in orders (like a real dependency chain).

Every request is recorded in Prometheus metrics, and a /chaos endpoint
lets you inject latency or errors on demand to test the detector.
"""
import os
import random
import threading
import time

import requests
from flask import Flask, Response, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

SERVICE = os.getenv("SERVICE_NAME", "orders")
DOWNSTREAMS = [u for u in os.getenv("DOWNSTREAM_URLS", "").split(",") if u]  # full URLs called by /checkout
BASE_LATENCY_MS = float(os.getenv("BASE_LATENCY_MS", "40"))
IGNORED_ENDPOINTS = {"metrics", "health", "chaos", "static"}

REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests", ["service", "endpoint", "status"]
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

app = Flask(__name__)

_chaos_lock = threading.Lock()
_chaos = {"latency_ms": 0.0, "error_rate": 0.0, "until": 0.0}


def _active_chaos():
    """Return the current fault settings, or zeros if the fault has expired."""
    with _chaos_lock:
        if time.time() > _chaos["until"]:
            return 0.0, 0.0
        return _chaos["latency_ms"], _chaos["error_rate"]


def _simulate_work():
    """Sleep for a realistic duration and maybe fail, based on chaos settings."""
    extra_latency_ms, error_rate = _active_chaos()
    jitter = random.uniform(-0.25, 0.25) * BASE_LATENCY_MS
    time.sleep(max(0.0, BASE_LATENCY_MS + jitter + extra_latency_ms) / 1000.0)
    return random.random() < error_rate


@app.before_request
def _start_timer():
    g.start = time.perf_counter()


@app.after_request
def _record_metrics(response):
    endpoint = request.endpoint
    if endpoint and endpoint not in IGNORED_ENDPOINTS:
        elapsed = time.perf_counter() - g.start
        LATENCY.labels(SERVICE, endpoint).observe(elapsed)
        REQUESTS.labels(SERVICE, endpoint, str(response.status_code)).inc()
    return response


@app.get("/health")
def health():
    return jsonify(status="ok", service=SERVICE)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/charge", methods=["GET", "POST"])
def charge():
    if _simulate_work():
        return jsonify(error="payment failed", service=SERVICE), 500
    return jsonify(status="charged", service=SERVICE)


@app.route("/reserve", methods=["GET", "POST"])
def reserve():
    if _simulate_work():
        return jsonify(error="reservation failed", service=SERVICE), 500
    return jsonify(status="reserved", service=SERVICE)


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if _simulate_work():
        return jsonify(error="checkout failed", service=SERVICE), 500
    for url in DOWNSTREAMS:
        try:
            if requests.post(url, timeout=2).status_code >= 500:
                return jsonify(error=f"dependency error: {url}", service=SERVICE), 502
        except requests.RequestException:
            return jsonify(error=f"dependency unreachable: {url}", service=SERVICE), 502
    return jsonify(status="order placed", service=SERVICE)


@app.route("/chaos", methods=["GET", "POST", "DELETE"])
def chaos():
    """GET: show fault state. POST: inject a fault. DELETE: clear it."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        with _chaos_lock:
            _chaos["latency_ms"] = float(body.get("latency_ms", 0))
            _chaos["error_rate"] = min(1.0, max(0.0, float(body.get("error_rate", 0))))
            _chaos["until"] = time.time() + float(body.get("duration_s", 60))
    elif request.method == "DELETE":
        with _chaos_lock:
            _chaos.update(latency_ms=0.0, error_rate=0.0, until=0.0)
    latency_ms, error_rate = _active_chaos()
    remaining = max(0, round(_chaos["until"] - time.time())) if (latency_ms or error_rate) else 0
    return jsonify(service=SERVICE, latency_ms=latency_ms, error_rate=error_rate, remaining_s=remaining)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), threaded=True)
