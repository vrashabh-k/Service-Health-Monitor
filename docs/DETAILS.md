# Details: architecture and detection method

A small, containerized monitoring platform. Three Flask microservices (orders, payments, inventory) expose
metrics to **Prometheus**, a **Python anomaly detector** watches those metrics
and flags abnormal behaviour, and the results are shown in **Grafana**
dashboards and a **React** dashboard.

```
 loadgen ──> orders ──> payments
               └────> inventory
               │           │         (Prometheus metrics: latency, errors, rate)
               └─────┬─────┘
                     ▼
               Prometheus ──────> Grafana  (charts)
                     ▲
                     │ queries every 5s
               Detector (Python, scikit-learn) ──> REST API ──> React dashboard
```

## What it does

- **orders** calls **payments** over HTTP, so a problem in payments also shows
  up in orders, like a real dependency chain.
- Every request is measured: request count, latency histogram, status code.
- The detector pulls p95 latency and error rate for each service and compares
  the latest values with the service's own recent baseline.
- A `/chaos` endpoint lets you inject latency or errors to test detection.

## Run it

Requires Docker and Docker Compose.

```bash
docker compose up --build
```

| What                | URL                      |
|---------------------|--------------------------|
| React dashboard (status, charts, tests, glossary, contact) | http://localhost:8080 |
| Grafana (dashboard "Service Health") | http://localhost:3000 (login `admin` / `admin`) |
| Prometheus          | http://localhost:9090    |
| Detector API        | http://localhost:8000/api/status |

**Wait about 3 minutes** after startup: the detector needs history to learn
what "normal" looks like (the dashboard shows "Learning baseline").

## Try a failure

Use the buttons on the React dashboard, or from a terminal:

```bash
# Add 400 ms latency to payments for 60 seconds
curl -X POST localhost:5002/chaos -H 'Content-Type: application/json' \
     -d '{"latency_ms": 400, "duration_s": 60}'

# Make 40% of payments requests fail for 60 seconds
curl -X POST localhost:5002/chaos -H 'Content-Type: application/json' \
     -d '{"error_rate": 0.4, "duration_s": 60}'

# Clear any fault
curl -X DELETE localhost:5002/chaos
```

Within roughly 10 seconds the detector flags payments, and orders as well
because it depends on payments.

## How detection works

For each service, every 5 seconds:

1. Query Prometheus for the last 15 minutes of **p95 latency** and **error rate**.
2. **Robust z-score**: compare "now" (median of the last 3 points) with the
   baseline using median and MAD. This is not thrown off by earlier spikes, and
   a floor on the scale stops a metric that is always 0 from causing false alarms.
3. **Isolation Forest** (scikit-learn): trained on the baseline `(latency,
   error rate)` pairs, it checks whether the current pair is unusual together.
4. **Decision**: a z-score above 4 raises a *warning*. If the Isolation Forest
   agrees, or the z-score is very large, it becomes *critical*. The forest
   alone never raises an alert, which keeps false alarms down.

Design choices worth knowing:

- Using the **median of the last 3 points** means one noisy sample is ignored,
  but a real fault lasting more than a few seconds is caught.
- Detection compares each service with **its own** history, so no fixed
  thresholds are needed per service.
- Prometheus returns *no series* when there are no 5xx errors, so the error
  query uses `or vector(0)` to mean "zero errors" rather than "no data".

## Adding another service

Add a block to `docker-compose.yml`, a scrape target in `prometheus/prometheus.yml`, then add its name to `SERVICES` (and `DEPENDENCIES`, e.g. `orders>newsvc`) on the detector. The dashboard picks it up automatically.

## Project layout

```
services/     Flask microservice (metrics + fault injection)
loadgen/      steady traffic generator
detector/     detection.py (algorithms) + app.py (Prometheus polling, REST API)
dashboard/    React (Vite) UI, served by nginx
prometheus/   scrape config
grafana/      datasource + dashboard provisioning
tests/        pytest tests for detection logic and the service
```

## Tests

```bash
pip install -r detector/requirements.txt -r services/requirements.txt pytest
python -m pytest tests -q
```

## Possible next steps

- Group related anomalies into one incident using the service dependency (orders -> payments).
- Add alert notifications (webhook / email) and automatic remediation hooks.
- Add a CI pipeline (GitHub Actions) that runs the tests and builds the images.
- Deploy on Kubernetes with Helm.

## Limitations

- Fault injection and the detector's `/api/chaos` proxy are demo features with no authentication.
- The baseline lives in Prometheus; the detector keeps its anomaly history in memory only.
