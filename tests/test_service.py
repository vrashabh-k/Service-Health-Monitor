import app as service_app


def client():
    service_app.app.config["TESTING"] = True
    return service_app.app.test_client()


def sample(name, **labels):
    from prometheus_client import REGISTRY
    return REGISTRY.get_sample_value(name, labels)


def test_health_and_metrics_endpoints():
    c = client()
    assert c.get("/health").json["status"] == "ok"
    assert b"http_requests_total" in c.get("/metrics").data or c.get("/metrics").status_code == 200


def test_successful_request_is_counted():
    c = client()
    service_app.BASE_LATENCY_MS = 1
    before = sample("http_requests_total", service="orders", endpoint="charge", status="200") or 0
    assert c.post("/charge").status_code == 200
    after = sample("http_requests_total", service="orders", endpoint="charge", status="200")
    assert after == before + 1


def test_chaos_error_injection_returns_500_and_is_counted():
    c = client()
    service_app.BASE_LATENCY_MS = 1
    c.post("/chaos", json={"error_rate": 1.0, "duration_s": 30})
    assert c.post("/charge").status_code == 500
    assert sample("http_requests_total", service="orders", endpoint="charge", status="500") >= 1
    c.delete("/chaos")
    assert c.post("/charge").status_code == 200


def test_chaos_latency_is_applied_then_cleared():
    import time
    c = client()
    service_app.BASE_LATENCY_MS = 1
    c.post("/chaos", json={"latency_ms": 200, "duration_s": 30})
    t = time.perf_counter()
    c.post("/charge")
    assert time.perf_counter() - t >= 0.2
    c.delete("/chaos")
    t = time.perf_counter()
    c.post("/charge")
    assert time.perf_counter() - t < 0.1
