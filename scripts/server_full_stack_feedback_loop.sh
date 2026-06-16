#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/geonhae/aiops_research"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"

MONITORING_NS="${MONITORING_NS:-monitoring-full}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-kube-prometheus-stack-prometheus}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9091}"
APP_NS="${APP_NS:-online-boutique}"
SCENARIO="${SCENARIO:-cpu-stress}"
ITERATIONS="${ITERATIONS:-3}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MODE="${MODE:-dry-run}"
GUARD_BACKEND="${GUARD_BACKEND:-go}"
RUN_DIR="${RUN_DIR:-runs/full-stack}"

set_default() {
  local name="$1"
  local default_value="$2"

  if [[ -z "${!name:-}" ]]; then
    printf -v "$name" '%s' "$default_value"
  fi
}

case "$SCENARIO" in
  cpu-stress)
    set_default SERVICE "paymentservice"
    set_default METRIC "cpu"
    set_default THRESHOLD "0.5"
    set_default QUERY 'sum(rate(container_cpu_usage_seconds_total{namespace="online-boutique",pod=~"paymentservice-.*",container!="",image!=""}[2m])) * 100'
    ;;
  memory-stress)
    set_default SERVICE "checkoutservice"
    set_default METRIC "restart_count"
    set_default THRESHOLD "0.5"
    set_default QUERY 'max(increase(kube_pod_container_status_restarts_total{namespace="online-boutique",pod=~"checkoutservice-.*",container!="POD"}[5m]))'
    ;;
  pod-kill)
    set_default SERVICE "paymentservice"
    set_default METRIC "availability"
    set_default THRESHOLD "2"
    set_default QUERY 'max(kube_deployment_status_replicas_available{namespace="online-boutique",deployment="paymentservice"})'
    ;;
  network-delay)
    set_default SERVICE "paymentservice"
    set_default METRIC "latency"
    set_default THRESHOLD "0.5"
    set_default QUERY "max(up)"
    ;;
  *)
    echo "Unsupported scenario: ${SCENARIO}" >&2
    exit 2
    ;;
esac

mkdir -p "$RUN_DIR"

kubectl port-forward \
  -n "$MONITORING_NS" \
  "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_PORT}:9090" \
  > "/tmp/geonhae-full-prometheus-${PROMETHEUS_PORT}.log" 2>&1 &
PORT_FORWARD_PID=$!

cleanup() {
  kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_prometheus() {
  local url="http://127.0.0.1:${PROMETHEUS_PORT}/-/ready"
  local log_file="/tmp/geonhae-full-prometheus-${PROMETHEUS_PORT}.log"

  for _ in {1..30}; do
    if ! kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
      echo "Prometheus port-forward stopped unexpectedly." >&2
      cat "$log_file" >&2 || true
      exit 1
    fi

    if curl -sf "$url" >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done

  echo "Prometheus did not become ready at ${url}." >&2
  cat "$log_file" >&2 || true
  exit 1
}

wait_for_prometheus

ALLOWED_DEPLOYMENTS=(
  adservice
  cartservice
  checkoutservice
  currencyservice
  emailservice
  frontend
  loadgenerator
  paymentservice
  productcatalogservice
  recommendationservice
  redis-cart
  shippingservice
)

ALLOWED_ARGS=()
for deployment in "${ALLOWED_DEPLOYMENTS[@]}"; do
  ALLOWED_ARGS+=(--allowed-deployment "$deployment")
done

AUTOGEN_FLAGS=()
if [[ "${USE_AUTOGEN:-0}" == "1" ]]; then
  AUTOGEN_FLAGS+=(--autogen --show-transcript)
fi

echo "== Full-stack feedback loop =="
echo "scenario=${SCENARIO}"
echo "metric=${METRIC}"
echo "service=${SERVICE}"
echo "guard_backend=${GUARD_BACKEND}"
echo "query=${QUERY}"
echo "threshold=${THRESHOLD}"

aiops-k8s-agents feedback-loop \
  --mode "$MODE" \
  --guard-backend "$GUARD_BACKEND" \
  --prometheus-url "http://127.0.0.1:${PROMETHEUS_PORT}" \
  --query "$QUERY" \
  --metric "$METRIC" \
  --threshold "$THRESHOLD" \
  --default-namespace "$APP_NS" \
  --default-service "$SERVICE" \
  --allowed-namespace "$APP_NS" \
  "${ALLOWED_ARGS[@]}" \
  --iterations "$ITERATIONS" \
  --interval-seconds "$INTERVAL_SECONDS" \
  --save-result-dir "$RUN_DIR" \
  "${AUTOGEN_FLAGS[@]}"
