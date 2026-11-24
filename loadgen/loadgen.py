"""Sends steady, slightly random traffic to the orders service."""
import os
import random
import time

import requests

TARGET = os.getenv("TARGET_URL", "http://orders:5000/checkout")
RPS = float(os.getenv("RPS", "8"))


def main():
    print(f"loadgen: sending ~{RPS} req/s to {TARGET}", flush=True)
    session = requests.Session()
    while True:
        try:
            session.post(TARGET, timeout=5)
        except requests.RequestException:
            pass  # service may still be starting up
        time.sleep(random.expovariate(RPS))


if __name__ == "__main__":
    main()
