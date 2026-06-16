#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MODE="${MODE:-dry-run}"
GUARD_BACKEND="${GUARD_BACKEND:-go}"
RUN_DIR="${RUN_DIR:-runs}"

mkdir -p "$RUN_DIR"

kubectl port-forward \
  -n monitoring \
  service/prometheus \
  "${PROMETHEUS_PORT}:9090" \
  > /tmp/geonhae-prometheus-feedback.log 2>&1 &
PORT_FORWARD_PID=$!

cleanup() {
  kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 5

AUTOGEN_FLAGS=()
if [[ "${USE_AUTOGEN:-0}" == "1" ]]; then
  AUTOGEN_FLAGS+=(--autogen --show-transcript)
fi

aiops-k8s-agents feedback-loop \
  --mode "$MODE" \
  --guard-backend "$GUARD_BACKEND" \
  --prometheus-url "http://127.0.0.1:${PROMETHEUS_PORT}" \
  --query up \
  --metric cpu \
  --threshold 0.5 \
  --default-namespace online-boutique \
  --default-service paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice \
  --iterations "$ITERATIONS" \
  --interval-seconds "$INTERVAL_SECONDS" \
  --save-result-dir "$RUN_DIR" \
  "${AUTOGEN_FLAGS[@]}"
