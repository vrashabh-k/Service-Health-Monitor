# Service Health Monitor

Monitors three small microservices and flags unusual latency or error rates automatically, with a live dashboard anyone can read.

**Stack:** Python (Flask, scikit-learn) · Prometheus · Grafana · React · Docker Compose

```
loadgen -> orders -> payments
                 \-> inventory      Prometheus -> Detector (Python) -> React dashboard
                                          \-> Grafana
```

## Quick start

Requires Docker.

```bash
docker compose up --build
```

Wait about 3 minutes while the detector learns what "normal" looks like.

| Page | URL |
|---|---|
| Dashboard | http://localhost:8080 |
| Grafana (`admin` / `admin`) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

## Try it

Open the dashboard, pick a service, choose "Slow responses" or "Failing requests", and press **Start test**. The problem is detected in about 10-15 seconds and clears when the test ends.

## How it works

Each service publishes latency and error metrics. Every 5 seconds the detector compares the latest values with that service's own last 15 minutes, using a robust z-score and an Isolation Forest. More in [docs/DETAILS.md](docs/DETAILS.md).

## Tests

```bash
pip install -r detector/requirements.txt -r services/requirements.txt pytest
python -m pytest tests -q
```

## Author

Vrashabh Kambalyal · vvkam17@gmail.com · [LinkedIn](https://www.linkedin.com/in/vrashabh-k) · [GitHub](https://github.com/vrashabh-k)
