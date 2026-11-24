#!/bin/bash
# Usage: scripts/inject_fault.sh <latency|errors|clear> [service] [seconds]
KIND=${1:-latency}; SVC=${2:-payments}; SECS=${3:-60}
PORT=5002; [ "$SVC" = "orders" ] && PORT=5001
case "$KIND" in
  latency) curl -s -X POST localhost:$PORT/chaos -H 'Content-Type: application/json' -d "{\"latency_ms\":400,\"duration_s\":$SECS}" ;;
  errors)  curl -s -X POST localhost:$PORT/chaos -H 'Content-Type: application/json' -d "{\"error_rate\":0.4,\"duration_s\":$SECS}" ;;
  clear)   curl -s -X DELETE localhost:$PORT/chaos ;;
  *) echo "usage: $0 <latency|errors|clear> [orders|payments] [seconds]"; exit 1 ;;
esac
echo
